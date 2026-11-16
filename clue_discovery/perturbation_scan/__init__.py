"""Stage II: aggregate canonical cells, then call the unchanged scan backend."""
from dataclasses import dataclass
from pathlib import Path
import json
import numpy as np
import pandas as pd
from clue_discovery.schemas import ConditionAssociation
from clue_discovery.integration.io import artifact, clean, identity, read_jsonl, write_json, write_jsonl
from landscape_analysis.core import matrix_views

@dataclass
class AssociationBundle:
    dataset_id: str
    catalogue: object
    conditions: list[str]
    delta: np.ndarray
    candidate: np.ndarray
    tested: np.ndarray
    reason: np.ndarray
    support: np.ndarray
    condition_n: np.ndarray
    associations: list[ConditionAssociation]
    provenance: dict

    def validate(self):
        shape=(len(self.conditions),len(self.catalogue.records))
        if any(a.shape!=shape for a in (self.delta,self.candidate,self.tested,self.reason,self.support)):
            raise ValueError('condition × reference dimensions inconsistent')
        if len(set(self.conditions))!=len(self.conditions) or len(self.condition_n)!=shape[0]:
            raise ValueError('condition identities/counts inconsistent')
        matrix_views(self.delta,self.candidate,self.tested,self.reason)
        refs={r.reference_id:r for r in self.catalogue.records}; indices={r:i for i,r in enumerate(refs)}
        cells=set()
        for a in self.associations:
            if a.dataset_id!=self.dataset_id or a.condition_id not in self.conditions or a.reference_id not in refs:
                raise ValueError('association identity outside frozen family')
            r=refs[a.reference_id]
            if a.genes!=r.genes or a.states!=r.states: raise ValueError('association changed signed reference identity')
            i,j=self.conditions.index(a.condition_id),indices[a.reference_id]
            if (i,j) in cells or not self.candidate[i,j] or not np.isclose(a.matched_effect,self.delta[i,j],rtol=0,atol=1e-14):
                raise ValueError('association/matrix conflict')
            cells.add((i,j))
        if len(cells)!=int(self.candidate.sum()): raise ValueError('candidate records/mask differ')
        return self


def convert_candidate(r,config,source,line):
    return ConditionAssociation(candidate_id=r['clue_id'],dataset_id=config.dataset_id,
        condition_id=r['target'],condition_type=config.condition_type,
        perturbation_target=r['target'] if config.condition_type=='gene_perturbation' else None,
        reference_id=r['reference_id'],genes=r['genes'],states=r['states'],order=r['order'],matched_effect=r['delta'],
        direction='enrichment' if r['delta']>0 else 'depletion',
        condition_support={k:r[k] for k in ('perturbation_hits','perturbation_n','perturbation_frequency','batch_support') if k in r},
        control_support={k:r[k] for k in ('matched_nt_frequency','pooled_nt_n','matched_nt_cells_pooled','matched_nt_effective_n') if k in r},
        association_evidence={k:r[k] for k in ('p_value','selected_family_holm_exploratory','family_size',
            'nominal_pointwise_delta_ci_low','nominal_pointwise_delta_ci_high','nt_selection_adjusted','status',
            'statistical_method','inference_scope','ci_method','effect_is_not_change_in_higher_order_interaction_strength') if k in r},
        quality_flags=['EXPLORATORY_NOT_SELECTION_ADJUSTED','BURDEN_DEPENDS_ON_SAMPLE_SIZE'],
        provenance={**source,'line':line,'source_clue_id':r['clue_id']})


def scan_conditions(dataset,catalogue,output):
    from perturbation_scan.scan import Counts, ScanConfig, scan
    out=Path(output);out.mkdir(parents=True,exist_ok=True)
    cfg=dataset.config;meta=dataset.cell_metadata;refs=catalogue.records
    if any(r.order!=3 for r in refs): raise ValueError('accepted shift backend supports order 3 only')
    conditions=list(dataset.conditions);shape=(len(conditions),len(refs))
    missing={r.reference_id:sorted(set(r.genes)-set(dataset.genes)) for r in refs if not set(r.genes)<=set(dataset.genes)}
    n=np.array([sum(meta.condition_id==c) for c in conditions],dtype=int)
    if not refs or not conditions or not dataset.reference_available:
        reason='reference_population_unavailable' if not dataset.reference_available else 'empty_reference_or_condition_family'
        bundle=AssociationBundle(dataset.dataset_id,catalogue,conditions,np.full(shape,np.nan),np.zeros(shape,bool),
            np.zeros(shape,bool),np.full(shape,reason,dtype='<U64'),np.zeros(shape,int),n,[],
            {'status':reason,'family_size':shape[0]*shape[1],'dataset':dataset.provenance})
    else:
        if dataset.detection_matrix is None: raise ValueError('Stage II needs detection data')
        batches=sorted(meta.batch_id.unique());gene_index={g:i for i,g in enumerate(dataset.genes)}
        hits=np.zeros((len(meta),len(refs)),int)
        for j,r in enumerate(refs):
            if r.reference_id not in missing:
                hits[:,j]=(dataset.detection_matrix[:,[gene_index[g] for g in r.genes]]==r.states).all(1)
        group_target=[];group_batch=[];group_n=[];group_hits=[];membership=[]
        groups=np.where(meta.is_control,0,[conditions.index(c)+1 if c in conditions else 0 for c in meta.condition_id])
        for t in range(len(conditions)+1):
            for b,batch in enumerate(batches):
                ix=np.flatnonzero((groups==t)&(meta.batch_id.to_numpy()==batch))
                if not len(ix):continue
                group_target.append(t);group_batch.append(b);group_n.append(len(ix));group_hits.append(hits[ix].sum(0))
                membership.append({'condition_id':conditions[t-1] if t else 'CONTROL_POOL','batch_id':batch,
                                   'cell_ids':meta.iloc[ix].cell_id.tolist()})
        patterns=[dict(reference_id=r.reference_id,genes=r.genes,states=r.states,order=r.order,pattern=r.signed_pattern,
            candidate_id=r.provenance.get('gene_set_id',identity(sorted(r.genes))),
            reference_evidence=r.model_dump(mode='json')) for r in refs]
        counts=Counts(tuple(conditions),tuple(batches),np.array(group_target),np.array(group_batch),
            np.array(group_n),np.array(group_hits),patterns,len(dataset.genes))
        counts.save(out/'counts');write_json(out/'cell_provenance.json',{'dataset':dataset.provenance,'groups':membership})
        scan_cfg=ScanConfig(min_pert_cells=cfg.min_cells['condition'],min_nt_per_batch=cfg.min_cells['control_per_batch'],
            min_effective_nt=cfg.min_cells['effective_control'],min_directional_support=cfg.min_cells['directional_support'],
            min_abs_delta=cfg.multiple_testing_config['min_abs_delta'],alpha=cfg.multiple_testing_config['alpha'])
        scan(counts,out/'backend',scan_cfg)
        with np.load(out/'backend/statistics.npz') as z:
            vals={k:z[k].copy() for k in z.files}
        # Missing genes stay in the backend multiplicity denominator with p=1.
        # Only the canonical evaluability view is marked NA; backend artifacts are untouched.
        reason=vals['reason'].astype('<U64');delta=vals['delta'].copy()
        for j,r in enumerate(refs):
            if r.reference_id in missing:
                if vals['tested'][:,j].any(): raise AssertionError('missing-gene reference was tested')
                reason[:,j]='NOT_EVALUABLE:missing_reference_genes';delta[:,j]=np.nan
        src=artifact(out/'backend/candidates.jsonl')
        associations=[convert_candidate(r,cfg,src,i) for i,r in enumerate(read_jsonl(src['path']),1)]
        bundle=AssociationBundle(dataset.dataset_id,catalogue,conditions,delta,vals['candidate'],vals['tested'],reason,
            vals['target_hits'],vals['target_n'],associations,{'backend':artifact(out/'backend/testing_family_frozen.json'),
            'cell_provenance':artifact(out/'cell_provenance.json'),'dataset':dataset.provenance,
            'family_size':shape[0]*shape[1],'missing_reference_genes':missing})
    bundle.validate()
    write_jsonl(out/'condition_associations.jsonl',bundle.associations)
    np.savez_compressed(out/'condition_reference_matrix.npz',delta=bundle.delta,candidate=bundle.candidate,
        tested=bundle.tested,reason=bundle.reason,support=bundle.support,condition_n=bundle.condition_n)
    views=matrix_views(bundle.delta,bundle.candidate,bundle.tested,bundle.reason)
    evaluability=np.where(views['enough_support'],'EVALUABLE','NOT_EVALUABLE')
    pd.DataFrame(evaluability,index=pd.Index(conditions,name='condition_id'),
        columns=[r.reference_id for r in refs]).to_csv(out/'evaluability_status.csv')
    write_json(out/'matrix_axes.json',{'conditions':conditions,'reference_ids':[r.reference_id for r in refs],
        'effect_units':'prevalence_difference','provenance':bundle.provenance,
        'NOT_EVALUABLE_count':int((~matrix_views(bundle.delta,bundle.candidate,bundle.tested,bundle.reason)['enough_support']).sum()),
        'family_denominator':shape[0]*shape[1]})
    return bundle
