"""Independently aggregate every frozen pattern from measured cell states."""
import argparse,json
from pathlib import Path
import numpy as np
from perturbation_scan.scan import Counts
from jure.tools.real.experiment import CellStateStore
from jure.tools.real.registry import file_sha

def check(store_path,output):
    store=CellStateStore(store_path)
    counts=Counts.load('outputs/perturbation_scan_day6_v01_20260927/remote/outputs/day6_scan/counts')
    groups=store.meta.group_index.to_numpy(dtype=np.int64)
    denominators=np.bincount(groups,minlength=len(counts.n_cells))
    if not np.array_equal(denominators,counts.n_cells):raise AssertionError('cell-group denominators differ')
    mismatches=[]
    for index,p in enumerate(counts.patterns):
        hit=store.mask(dict(zip(p['genes'],p['states'])))
        # Independent empirical aggregation; frozen counts used only as oracle.
        actual=np.bincount(groups[hit],minlength=len(counts.n_cells))
        if not np.array_equal(actual,counts.hits[:,index]):mismatches.append(p['reference_id'])
    result={'dataset_id':store.manifest['dataset_id'],'store_version':store.version,
        'source_sha256':store.manifest['source_sha256'],'n_cells':len(store.meta),'n_genes':len(store.genes),
        'n_groups':len(counts.n_cells),'n_patterns':len(counts.patterns),'denominators_match':True,
        'pattern_mismatches':mismatches,'all_counts_match':not mismatches,'agent_calls':0,
        'verification_method':'Independent per-cell Boolean masks + group bincount compared with frozen raw count arrays',
        'script_sha256':file_sha(__file__)}
    Path(output).write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result),flush=True)
    if mismatches:raise AssertionError('frozen count mismatch')
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--store',default='data/day6_tool_store');p.add_argument('--output',default='outputs/tool_validation/day6_all_counts_check.json');a=p.parse_args();check(a.store,a.output)
