"""Evaluate frozen patterns from aggregated target-by-batch integer counts."""
from dataclasses import asdict,dataclass
import csv
import gzip
import json
from pathlib import Path

import numpy as np

from clue_discovery.v03.artifacts import digest,write_json,canonical
from .statistics import exact_stratified_test,implicit_holm,simultaneous_delta_radius


@dataclass(frozen=True)
class ScanConfig:
    version:str='perturbation_scan_v01'
    min_pert_cells:int=100
    min_nt_per_batch:int=20
    min_effective_nt:int=100
    min_directional_support:int=10
    min_abs_delta:float=.10
    alpha:float=.05


@dataclass
class Counts:
    targets:tuple
    batches:tuple
    group_target:np.ndarray # 0 is NT; target i has index i+1
    group_batch:np.ndarray
    n_cells:np.ndarray
    hits:np.ndarray
    patterns:list
    n_universe_genes:int

    def validate(self):
        n=len(self.group_target);p=len(self.patterns)
        if (self.hits.shape!=(n,p) or self.n_cells.shape!=(n,) or self.group_batch.shape!=(n,)
            or len(set(self.targets))!=len(self.targets) or len(set(self.batches))!=len(self.batches)):
            raise ValueError('invalid count dimensions or identities')
        for values in (self.group_target,self.group_batch,self.n_cells,self.hits):
            if not np.issubdtype(values.dtype,np.integer) or (values<0).any():raise ValueError('invalid integer counts')
        if ((self.group_target>len(self.targets)).any() or (self.group_batch>=len(self.batches)).any()
            or (self.n_cells<=0).any() or (self.hits>self.n_cells[:,None]).any()
            or len(set(zip(self.group_target,self.group_batch)))!=n):raise ValueError('invalid or duplicate groups')
        ids=[r['reference_id'] for r in self.patterns]
        if len(set(ids))!=len(ids) or any(len(set(r['genes']))!=3 or len(r['states'])!=3
            or any(v not in (0,1) for v in r['states']) for r in self.patterns):
            raise ValueError('invalid frozen patterns')

    def save(self,path):
        self.validate();path=Path(path);path.mkdir(parents=True,exist_ok=True)
        np.savez_compressed(path/'counts.npz',group_target=self.group_target,group_batch=self.group_batch,
                            n_cells=self.n_cells,hits=self.hits)
        write_json(path/'identities.json',dict(targets=self.targets,batches=self.batches,patterns=self.patterns,
                                              n_universe_genes=self.n_universe_genes))

    @classmethod
    def load(cls,path):
        path=Path(path);identity=json.loads((path/'identities.json').read_text())
        with np.load(path/'counts.npz',allow_pickle=False) as data:
            result=cls(**identity,**{k:data[k] for k in data.files})
        result.validate();return result


def scan(counts,output,config=ScanConfig()):
    counts.validate();out=Path(output)
    if out.exists() and any(out.iterdir()):raise FileExistsError('refuse overwrite of scan')
    out.mkdir(parents=True,exist_ok=True)
    T,P,B=len(counts.targets),len(counts.patterns),len(counts.batches)
    M=T*P
    if not M:raise ValueError('empty target or pattern family')
    write_json(out/'testing_family_frozen.json',dict(config=asdict(config),catalogue_digest=digest(counts.patterns),
        targets=counts.targets,family_size=M,uncomputed_hypotheses_p1=True,
        method='selected_family_Holm_exploratory',nt_selection_adjusted=False,
        confirmatory=False,frozen_before_any_test=True))
    nt_n=np.zeros(B,dtype=np.int64);nt_x=np.zeros((B,P),dtype=np.int64)
    controls=np.flatnonzero(counts.group_target==0)
    nt_n[counts.group_batch[controls]]=counts.n_cells[controls]
    nt_x[counts.group_batch[controls]]=counts.hits[controls]
    if not nt_n.sum():raise ValueError('missing all NT cells')
    pooled_nt=nt_x.sum(0)/nt_n.sum()
    p=np.ones((T,P));tested=np.zeros((T,P),dtype=bool)
    xp=np.zeros((T,P),dtype=np.int64);matched=np.full((T,P),np.nan)
    deltas=np.full((T,P),np.nan);nt_support=np.zeros((T,P),dtype=np.int64)
    reasons=np.full((T,P),'',dtype='<U40')
    npert=np.zeros(T,dtype=np.int64);matched_n=np.zeros(T,dtype=np.int64)
    effective=np.zeros(T);radii=np.full(T,np.nan);nbatch=np.zeros(T,dtype=np.int64)
    for i,target in enumerate(counts.targets):
        rows=np.flatnonzero(counts.group_target==i+1)
        batches=counts.group_batch[rows];n=counts.n_cells[rows].astype(np.int64)
        x=counts.hits[rows].astype(np.int64);N=int(n.sum());npert[i]=N;nbatch[i]=len(rows)
        xp[i]=x.sum(0);matched_n[i]=nt_n[batches].sum();nt_support[i]=nt_x[batches].sum(0)
        if not N:reasons[i]='no_target_cells';continue
        if (nt_n[batches]==0).any():reasons[i]='missing_matched_NT';continue
        w=n/N;matched[i]=w@(nt_x[batches]/nt_n[batches,None])
        deltas[i]=xp[i]/N-matched[i]
        effective[i]=1/np.sum(w*w/nt_n[batches])
        radii[i]=simultaneous_delta_radius(n,nt_n[batches],1,config.alpha)
        if N<config.min_pert_cells:reasons[i]='insufficient_perturbation_cells';continue
        if (nt_n[batches]<config.min_nt_per_batch).any() or effective[i]<config.min_effective_nt:
            reasons[i]='insufficient_matched_NT';continue
        for j in range(P):
            delta=deltas[i,j]
            if abs(delta)<config.min_abs_delta:reasons[i,j]='effect_below_prespecified_minimum';continue
            shifted_support=xp[i,j] if delta>0 else N-xp[i,j]
            reference_opportunities=N*(1-matched[i,j]) if delta>0 else N*matched[i,j]
            if min(shifted_support,reference_opportunities)<config.min_directional_support:
                reasons[i,j]='insufficient_directional_support';continue
            result=exact_stratified_test(x[:,j],n,nt_x[batches,j],nt_n[batches])
            p[i,j]=result['p_value'];tested[i,j]=True
        if i%100==0:print(json.dumps(dict(targets_completed=i+1,total_targets=T)),flush=True)
    exploratory=implicit_holm(p.ravel(),T*P).reshape(T,P)
    explored=tested&(exploratory<=config.alpha)
    np.savez_compressed(out/'statistics.npz',p_accounting=p,tested=tested,selected_holm_exploratory=exploratory,candidate=explored,target_hits=xp,target_n=npert,
        matched_nt_frequency=matched,delta=deltas,nominal_pointwise_ci_radius=radii,reason=reasons)
    fields=['clue_id','target','reference_id','pattern','order','perturbation_hits','perturbation_n',
        'perturbation_frequency','pooled_nt_hits','pooled_nt_n','pooled_nt_frequency',
        'matched_nt_hits_pooled','matched_nt_cells_pooled','matched_nt_effective_n','matched_nt_frequency',
        'delta','delta_percentage_points','delta_vs_pooled_nt_descriptive','nominal_pointwise_delta_ci_low',
        'nominal_pointwise_delta_ci_high','matched_batches','tested','p_value','p_accounting',
        'selected_family_holm_exploratory','status','reason','biological_replicate_validated']
    first_case=None
    candidate_count=int(explored.sum())
    with gzip.open(out/'all_comparisons.csv.gz','wt',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader()
        for i,target in enumerate(counts.targets):
            for j,pattern in enumerate(counts.patterns):
                delta=deltas[i,j]
                status=('exploratory_perturbation_candidate' if explored[i,j] else
                        'tested_not_qualified' if tested[i,j] else 'not_tested')
                row=dict(clue_id='C'+digest([target,pattern['reference_id']])[:20],target=target,
                    reference_id=pattern['reference_id'],pattern=pattern['pattern'],order=3,
                    perturbation_hits=int(xp[i,j]),perturbation_n=int(npert[i]),
                    perturbation_frequency=xp[i,j]/npert[i] if npert[i] else None,
                    pooled_nt_hits=int(nt_x[:,j].sum()),pooled_nt_n=int(nt_n.sum()),pooled_nt_frequency=pooled_nt[j],
                    matched_nt_hits_pooled=int(nt_support[i,j]),matched_nt_cells_pooled=int(matched_n[i]),
                    matched_nt_effective_n=effective[i],matched_nt_frequency=matched[i,j],delta=delta,
                    delta_percentage_points=100*delta,
                    delta_vs_pooled_nt_descriptive=xp[i,j]/npert[i]-pooled_nt[j] if npert[i] else None,
                    nominal_pointwise_delta_ci_low=max(-1.,delta-radii[i]) if np.isfinite(delta) else None,
                    nominal_pointwise_delta_ci_high=min(1.,delta+radii[i]) if np.isfinite(delta) else None,
                    matched_batches=int(nbatch[i]),tested=bool(tested[i,j]),p_value=p[i,j] if tested[i,j] else None,
                    p_accounting=p[i,j],
                    selected_family_holm_exploratory=exploratory[i,j],status=status,reason=reasons[i,j],
                    biological_replicate_validated=False)
                writer.writerow(row)
    catalogue_digest=digest(counts.patterns)
    selected=list(zip(*np.nonzero(explored)))
    selected.sort(key=lambda ij:(exploratory[ij],-abs(deltas[ij]),counts.targets[ij[0]],counts.patterns[ij[1]]['reference_id']))
    # Stream full candidate evidence; retain just one case instead of all nested batch records.
    with (out/'candidates.jsonl').open('w') as stream:
        for i,j in selected:
            pattern=counts.patterns[j];group=np.flatnonzero(counts.group_target==i+1)
            bybatch=[dict(batch=counts.batches[counts.group_batch[k]],perturbation_hits=int(counts.hits[k,j]),
                perturbation_n=int(counts.n_cells[k]),nt_hits=int(nt_x[counts.group_batch[k],j]),
                nt_n=int(nt_n[counts.group_batch[k]])) for k in group]
            evidence={k:pattern[k] for k in ('reference_id','candidate_id','nt_support','nt_n_cells',
                'successful_directions','bidirectionally_qualified','holm_qualified',
                'discovery_bootstrap_stable','validation_bootstrap_stable') if k in pattern}
            case=dict(clue_id='C'+digest([counts.targets[i],pattern['reference_id']])[:20],
                target=counts.targets[i],reference_id=pattern['reference_id'],pattern=pattern['pattern'],
                genes=pattern['genes'],states=pattern['states'],order=3,
                perturbation_hits=int(xp[i,j]),perturbation_n=int(npert[i]),
                perturbation_frequency=xp[i,j]/npert[i],
                pooled_nt_hits=int(nt_x[:,j].sum()),pooled_nt_n=int(nt_n.sum()),
                pooled_nt_frequency=pooled_nt[j],matched_nt_frequency=matched[i,j],
                delta=deltas[i,j],delta_percentage_points=100*deltas[i,j],
                nominal_pointwise_delta_ci_low=max(-1.,deltas[i,j]-radii[i]),
                nominal_pointwise_delta_ci_high=min(1.,deltas[i,j]+radii[i]),
                p_value=p[i,j],selected_family_holm_exploratory=exploratory[i,j],
                status='exploratory_perturbation_candidate',batch_support=bybatch,reference_evidence=evidence,
                eligible_for_explorer_development=True,eligible_as_confirmed_clue=False,
                nt_selection_adjusted=False,external_validation_status='not_performed',mechanistic_claim=False,
                biological_replicate_validated=False,support_and_effect_gates_passed=True,
                catalogue_digest=catalogue_digest,family_size=M,
                inference_scope='exploratory_only_reused_NT_no_confirmatory_error_rate_claim',
                effect_is_not_change_in_higher_order_interaction_strength=True,
                statistical_method='exact_batch_conditional_plus_selected_family_Holm',
                ci_method='nominal_pointwise_Hoeffding_not_selection_adjusted_not_simultaneous')
            stream.write(canonical(case)+'\n')
            if first_case is None:first_case=case
    write_json(out/'first_case.json',dict(status='exploratory_case_available' if first_case else 'no_exploratory_candidate',
                                        case=first_case))
    summary=dict(targets=T,patterns=P,comparisons=T*P,family_size=M,exact_tests=int(tested.sum()),
        confirmed_clues=0,exploratory_candidates=candidate_count,candidate_targets=int(explored.any(axis=1).sum()),
        exploratory_selected_family_pairs=int(explored.sum()),
        catalogue_digest=digest(counts.patterns),config=asdict(config),not_tested_remain_in_family=True,
        nt_selection_adjusted=False,confirmatory=False,biological_replication=False,agent_calls=False)
    write_json(out/'summary.json',summary)
    return summary
