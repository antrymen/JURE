"""Read measured detection states; no scan, ranking or mechanism inference."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
from .contracts import Outcome, Status, ToolFailure
from .registry import digest,file_sha
from perturbation_scan.scan import Counts
from perturbation_scan.statistics import simultaneous_delta_radius

DATASET='replogle_k562_essential_day6'

class CellStateStore:
    """Bit-packed observed raw_count > 0, preserving row and gene identities."""
    def __init__(self,root):
        self.root=Path(root);self.manifest=json.loads((self.root/'manifest.json').read_text())
        if self.manifest['dataset_id']!=DATASET or self.manifest['encoding']!='raw_count_gt_0': raise ValueError('incompatible dataset/encoding')
        for name,sha in self.manifest['files'].items():
            if file_sha(self.root/name)!=sha: raise ValueError('cell store hash mismatch')
        self.meta=pd.read_csv(self.root/'cells.csv.gz',dtype={'cell_id':str,'scan_target':str,'batch':str})
        self.genes=json.loads((self.root/'genes.json').read_text()); self.index={g:i for i,g in enumerate(self.genes)}
        self.packed=np.load(self.root/'states.npy',mmap_mode='r',allow_pickle=False)
        if len(self.genes)!=len(self.index) or self.packed.shape!=(len(self.meta),(len(self.genes)+7)//8): raise ValueError('invalid cell state dimensions')
        if self.meta.cell_id.duplicated().any() or self.meta.source_row.duplicated().any(): raise ValueError('duplicate cells')
        self.version=digest(self.manifest)
    def mask(self,state):
        missing=set(state)-self.index.keys()
        if missing: raise ToolFailure(Status.NOT_EVALUABLE,'GENE_NOT_MEASURED','Genes absent from measured store',{'genes':sorted(missing)})
        mask=np.ones(len(self.meta),dtype=bool)
        for gene,sign in sorted(state.items()):
            pos=self.index[gene]; values=(self.packed[:,pos//8]>>(7-pos%8))&1
            mask &= values==sign
        return mask
    def counts(self,condition,state,given=None):
        if condition not in set(self.meta.scan_target):
            raise ToolFailure(Status.NOT_EVALUABLE,'CONDITION_NOT_AVAILABLE','Condition excluded or absent from allowed Day6 cells')
        eligible=self.meta.scan_target.eq(condition).to_numpy(copy=True)
        if given: eligible &= self.mask(given)
        hit=self.mask(state)&eligible
        all_batches=sorted(self.meta.loc[self.meta.scan_target.eq(condition),'batch'].unique())
        result=[]
        for batch in all_batches:
            batchmask=self.meta.batch.eq(batch).to_numpy();rows=np.flatnonzero(eligible&batchmask)
            result.append(dict(batch=batch,n=int(len(rows)),hits=int(np.count_nonzero(hit&batchmask)),
                cell_set_id=digest(self.meta.iloc[rows].cell_id.tolist())))
        return result

class FrozenCountsStore:
    """Verified sufficient statistics, limited to exactly stored signed states.

    Never infer missing marginals or conditionals from an incomplete catalogue.
    """
    def __init__(self,root,expected_files):
        self.root=Path(root)
        for name,sha in expected_files.items():
            if file_sha(self.root/name)!=sha: raise ValueError('frozen counts checksum mismatch')
        self.counts_data=Counts.load(root); self.manifest={'dataset_id':DATASET,'encoding':'raw_count_gt_0',
            'files':expected_files,'scope':'341 frozen joint states only','source':'verified Day6 cell aggregation'}
        self.version=digest(self.manifest)
    def counts(self,condition,state,given=None):
        c=self.counts_data
        if given: raise ToolFailure(Status.NOT_EVALUABLE,'CELL_STORE_REQUIRED','Conditional queries require the measured cell state store')
        matches=[i for i,p in enumerate(c.patterns) if dict(zip(p['genes'],p['states']))==state]
        if len(matches)!=1: raise ToolFailure(Status.NOT_EVALUABLE,'STATE_NOT_STORED','Signed state absent from frozen sufficient statistics; cell store required')
        if condition=='non-targeting': target=0
        elif condition in c.targets: target=c.targets.index(condition)+1
        else: raise ToolFailure(Status.NOT_EVALUABLE,'CONDITION_NOT_AVAILABLE','Condition absent from allowed Day6 counts')
        rows=np.flatnonzero(c.group_target==target);j=matches[0]
        return [dict(batch=c.batches[c.group_batch[r]],n=int(c.n_cells[r]),hits=int(c.hits[r,j]),
            cell_set_id=f'{self.version}:group:{r}') for r in rows]


def matched_comparison(pert,control,q,*,conditional=False):
    """Exact accepted Day6 estimand, written out because original kernel is inline.

    Original: perturbation_scan.scan.scan, w=n/N, w @ (nt_x / nt_n),
    effective_n=1/sum(w*w/nt_n). Its interval function is imported unchanged.
    Conditional queries redefine n to the conditioning subset and label it.
    """
    bybatch={r['batch']:r for r in control};rows=[r for r in pert if r['n']>0]
    if not rows: raise ToolFailure(Status.NOT_EVALUABLE,'ZERO_DENOMINATOR','No cells satisfy the conditioning/query population')
    missing=[r['batch'] for r in rows if bybatch.get(r['batch'],{}).get('n',0)==0]
    if missing: raise ToolFailure(Status.NOT_EVALUABLE,'MISSING_MATCHED_NT','A perturbation batch lacks an evaluable control denominator',{'batches':missing})
    n=np.array([r['n'] for r in rows]);x=np.array([r['hits'] for r in rows])
    nn=np.array([bybatch[r['batch']]['n'] for r in rows]);nx=np.array([bybatch[r['batch']]['hits'] for r in rows])
    N=int(n.sum()); X=int(x.sum()); w=n/N; matched=float(w@(nx/nn)); effective=float(1/np.sum(w*w/nn)); delta=X/N-matched
    support_reasons=[]
    if N<q.min_condition_cells:support_reasons.append('condition_denominator_below_threshold')
    if (nn<q.min_nt_per_batch).any(): support_reasons.append('NT_batch_denominator_below_threshold')
    if effective<q.min_effective_nt:support_reasons.append('effective_NT_below_threshold')
    directional_events=X if delta>0 else N-X
    opportunities=N*(1-matched) if delta>0 else N*matched
    if min(directional_events,opportunities)<q.min_events:support_reasons.append('directional_support_below_threshold')
    radius=float(simultaneous_delta_radius(n,nn,1,.05))
    result=dict(condition_n=N,condition_hits=X,condition_frequency=X/N,matched_nt_frequency=matched,
        delta=delta,delta_percentage_points=100*delta,matched_nt_effective_n=effective,
        matched_nt_pooled_n=int(nn.sum()),matched_nt_pooled_hits=int(nx.sum()),
        pooled_nt_frequency_descriptive=float(nx.sum()/nn.sum()),
        matched_control_rule='perturbation_batch_weighted_NT',
        nominal_pointwise_delta_interval=[max(-1.,delta-radius),min(1.,delta+radius)],
        interval_method='Hoeffding; nominal 95%; not selection adjusted; not simultaneous',
        conditional=conditional,support_reasons=support_reasons,
        batch_support=[dict(batch=r['batch'],perturbation_n=int(n[i]),perturbation_hits=int(x[i]),nt_n=int(nn[i]),
            nt_hits=int(nx[i]),weight=float(w[i]),condition_cell_set_id=r['cell_set_id'],nt_cell_set_id=bybatch[r['batch']]['cell_set_id']) for i,r in enumerate(rows)],
        empty_conditioning_batches=[r['batch'] for r in pert if r['n']==0])
    return result

class DataExperimentTool:
    def __init__(self,store=None,resolver=None):
        self.store=store;self.resolver=resolver
        self.source_mode=store.manifest.get('source_mode','REAL') if store else 'REAL'
    def normalize(self,q):
        if not self.resolver or not isinstance(self.store,CellStateStore):return q
        def resolve(state):
            pairs=[]
            for gene,sign in state.items():
                mapped=gene if gene in self.store.index else self.resolver.resolve(gene)['symbol']
                pairs.append((mapped,sign))
            if len({g for g,_ in pairs})!=len(pairs):raise ValueError('Aliases collapse to duplicate genes')
            return dict(sorted(pairs))
        payload=q.model_dump(mode='json');payload['state']=resolve(q.state)
        payload['conditioning_states']=resolve(q.conditioning_states)
        payload['contrast_state']=resolve(q.contrast_state) if q.contrast_state else None
        return type(q).model_validate(payload)
    def compare(self,q,state,condition=None):
        given=q.conditioning_states or None
        return matched_comparison(self.store.counts(condition or q.condition,state,given),self.store.counts('non-targeting',state,given),q,conditional=bool(given))
    def execute(self,q,ctx):
        if not self.store: raise ToolFailure(Status.UNAVAILABLE,'DAY6_DATA_UNAVAILABLE','No verified Day6 store configured')
        if q.dataset_id!=DATASET: raise ToolFailure(Status.NOT_EVALUABLE,'DATASET_MISMATCH','Only canonical Day6 is available')
        if q.condition=='non-targeting': raise ToolFailure(Status.INVALID_QUERY,'CONTROL_AS_PERTURBATION','Specify a perturbation condition')
        result=self.compare(q,q.state);all_results=[result]
        if q.mode=='PAIRWISE':
            genes=sorted(q.state);cells=[]
            for a,b in ((0,0),(0,1),(1,0),(1,1)):
                item=self.compare(q,dict(zip(genes,(a,b))));cells.append(item)
            freq=np.array([c['condition_frequency'] for c in cells]).reshape(2,2)
            nt=np.array([c['matched_nt_frequency'] for c in cells]).reshape(2,2)
            result.update(genes=genes,table_order=['00','01','10','11'],contingency_counts=[c['condition_hits'] for c in cells],
                matched_nt_cell_probabilities=nt.tolist(),condition_cell_probabilities=freq.tolist(),
                marginals={'condition':[float(freq[1,:].sum()),float(freq[:,1].sum())],
                    'matched_nt':[float(nt[1,:].sum()),float(nt[:,1].sum())]},
                association={'condition_p11_minus_p1_p1':float(freq[1,1]-freq[1,:].sum()*freq[:,1].sum()),
                    'matched_nt_p11_minus_p1_p1':float(nt[1,1]-nt[1,:].sum()*nt[:,1].sum()),'interpretation':'association only; no regulatory direction'})
        elif q.mode=='STATE_CONTRAST':
            second=self.compare(q,q.contrast_state);all_results.append(second)
            result={'state_a':result,'state_b':second,'delta_difference_descriptive':result['delta']-second['delta'],
                'test_of_delta_difference':None}
        elif q.mode=='CONDITION_COMPARISON' and q.condition_b and q.condition_b!='non-targeting':
            second=self.compare(q,q.state,q.condition_b);all_results.append(second)
            batches_a=[b['batch'] for b in result['batch_support']];batches_b=[b['batch'] for b in second['batch_support']]
            compatible=batches_a==batches_b
            if compatible:
                wa=np.array([b['perturbation_n'] for b in result['batch_support']],dtype=float)
                wb=np.array([b['perturbation_n'] for b in second['batch_support']],dtype=float)
                weights=(wa+wb)/(wa.sum()+wb.sum())
                fa=np.array([b['perturbation_hits']/b['perturbation_n'] for b in result['batch_support']]);fb=np.array([b['perturbation_hits']/b['perturbation_n'] for b in second['batch_support']])
                contrast=float(weights@(fa-fb))
            else: contrast=None
            result={'condition_a':result,'condition_b':second,'comparable_batches':compatible,
                'common_population_delta':contrast,'comparison_rule':'pooled A+B batch weights; requires identical batch coverage'}
            if not compatible:
                return Outcome(Status.NOT_EVALUABLE,result=result,provenance=self.provenance(q),limitations=['A and B batch coverage differs; no cross-condition effect returned.'])
        support=any(r['support_reasons'] for r in all_results)
        return Outcome(Status.INSUFFICIENT_SUPPORT if support else Status.OK,
            result={'mode':q.mode,'state':q.state,'conditioning_states':q.conditioning_states,'statistics':result,
                'evidence_level':'DAY6_EXPLORATORY','day8_status':'NOT_PERFORMED'},
            record_ids=[f'dataset:{DATASET}'],provenance=self.provenance(q),
            limitations=['Detection (raw count > 0) is not high/low expression. No confirmation, regulatory claim, or higher-order interaction-strength claim.',
                'Repeated queries reuse the Day6 dataset and are not independent confirmation.'])
    def provenance(self,q):
        return dict(dataset_id=DATASET,store_version=self.store.version,store_manifest=self.store.manifest,
            source_path=str(self.store.root.resolve()),encoding='raw_count_gt_0',
            cell_selection_rule='frozen allowed_cell_metadata: NT or allowed single perturbation; protected targets excluded',
            upstream_source_ids=[f'dataset:{DATASET}'],statistical_kernel='Day6 exact batch-weighted estimand; imported simultaneous_delta_radius',
            kernel_source_sha256=file_sha(Path('perturbation_scan/scan.py')),parameters=q.model_dump(mode='json'))
