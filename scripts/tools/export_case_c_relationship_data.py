"""Export measured Case C states and matched controls; no hypothesis fitting."""
import itertools,json,shutil,sys,zipfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import numpy as np
import pandas as pd
from jure.tools.real.experiment import CellStateStore
from jure.tools.real.registry import file_sha

OUT=Path('outputs/case_c_relationship_data_20260930')
SOURCE=Path('outputs/case_c_claim_source_revision_test_20260930/recovery_002/C/case_file/case_file.json')
GENES=['PCK2','PHGDH','TRIB3']

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    store=CellStateStore('data/day6_tool_store')
    case=json.loads(SOURCE.read_text());clue=case['clue']
    assert clue['perturbation']=='EIF2B5' and clue['pattern']['genes']==GENES and clue['pattern']['states']==[1,1,1]
    meta=store.meta
    batches=sorted(meta.loc[meta.scan_target.eq('EIF2B5'),'batch'].unique())
    keep=meta.scan_target.isin(['EIF2B5','non-targeting']) & meta.batch.isin(batches)
    rows=np.flatnonzero(keep.to_numpy())
    cells=meta.iloc[rows].copy()
    for gene in GENES:
        pos=store.index[gene]
        cells[gene]=((store.packed[rows,pos//8]>>(7-pos%8))&1).astype('uint8')
    cells['group']=np.where(cells.scan_target.eq('EIF2B5'),'EIF2B5','matched_NT')
    cells['signed_state']=cells[GENES].astype(str).agg(''.join,axis=1)
    cells['is_case_c_state']=(cells.signed_state=='111').astype('uint8')
    n=int((cells.group=='EIF2B5').sum())
    nt=int((cells.group=='matched_NT').sum())
    batch_rows=[]
    for batch in batches:
        part=cells[cells.batch==batch]
        pn=int((part.group=='EIF2B5').sum());nn=int((part.group=='matched_NT').sum())
        assert pn>0 and nn>0
        batch_rows.append(dict(batch=batch,perturbation_n=pn,nt_n=nn,batch_weight=pn/n,
            perturbation_cell_weight=1/n,nt_cell_weight=(pn/n)/nn))
    weights=pd.DataFrame(batch_rows)
    by_batch=weights.set_index('batch').nt_cell_weight
    cells['analysis_weight']=np.where(cells.group=='EIF2B5',1/n,cells.batch.map(by_batch))
    cells.to_csv(OUT/'case_c_cells_binary.csv',index=False)
    weights.to_csv(OUT/'matched_nt_batch_weights.csv',index=False)
    tables=[]
    for batch in batches:
        for group in ('EIF2B5','matched_NT'):
            part=cells[(cells.batch==batch)&(cells.group==group)]
            for signs in itertools.product((0,1),repeat=3):
                state=''.join(map(str,signs));subset=part[part.signed_state==state]
                tables.append(dict(batch=batch,group=group,**dict(zip(GENES,signs)),
                    signed_state=state,n=int(len(subset)),group_batch_n=int(len(part)),
                    weighted_probability_contribution=float(subset.analysis_weight.sum())))
    pd.DataFrame(tables).to_csv(OUT/'eight_states_by_batch.csv',index=False)
    summary=[]
    for group in ('EIF2B5','matched_NT'):
        part=cells[cells.group==group]
        for signs in itertools.product((0,1),repeat=3):
            state=''.join(map(str,signs));subset=part[part.signed_state==state]
            summary.append(dict(group=group,**dict(zip(GENES,signs)),signed_state=state,
                pooled_count=int(len(subset)),pooled_n=len(part),
                pooled_frequency=len(subset)/len(part),weighted_probability=float(subset.analysis_weight.sum())))
    pd.DataFrame(summary).to_csv(OUT/'eight_states_summary.csv',index=False)
    target=cells[cells.is_case_c_state==1]
    observed=float(target.loc[target.group=='EIF2B5','analysis_weight'].sum())
    matched=float(target.loc[target.group=='matched_NT','analysis_weight'].sum())
    ref=clue['perturbation_shift']
    assert n==ref['perturbation_n']==461 and nt==ref['pooled_nt_n']==10691
    assert int((target.group=='EIF2B5').sum())==ref['perturb_count']==194
    assert abs(observed-ref['perturb_frequency'])<1e-12
    assert abs(matched-ref['control_frequency'])<1e-12
    assert np.allclose(cells.groupby('group').analysis_weight.sum(),1)
    for filename in ('case_c_cells_binary.csv','matched_nt_batch_weights.csv','eight_states_by_batch.csv','eight_states_summary.csv'):
        assert (OUT/filename).is_file()
    (OUT/'case_c_clue.json').write_text(json.dumps(clue,ensure_ascii=False,indent=2)+'\n')
    shutil.copyfile(store.root/'manifest.json',OUT/'source_store_manifest.json')
    provenance=dict(dataset_id=store.manifest['dataset_id'],encoding=store.manifest['encoding'],
        source_store=str(store.root.resolve()),store_version=store.version,verified_store_files=store.manifest['files'],
        source_case_file=str(SOURCE.resolve()),source_case_sha256=file_sha(SOURCE),
        export_script_sha256=file_sha(Path(__file__)),genes=GENES,perturbation='EIF2B5',
        selection='All allowed EIF2B5 cells and non-targeting cells in EIF2B5-covered batches; no filtering on response state.',
        perturbation_n=n,matched_nt_pooled_n=nt,batches=len(batches),
        reproduced_condition_frequency=observed,reproduced_matched_nt_frequency=matched,
        original_h5ad_hash_verification='Original h5ad hash copied from store manifest, not independently rehashed in this export.',
        day8_status='NOT_PERFORMED',models_called=0,agent_scientific_records_modified=False)
    (OUT/'export_provenance.json').write_text(json.dumps(provenance,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(provenance,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
