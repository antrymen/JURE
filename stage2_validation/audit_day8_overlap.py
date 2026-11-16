"""Metadata-only Day8 feasibility audit; never interpret aggregate support as evaluability."""
import csv
import hashlib
import json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'outputs/result2_day8_feasibility_20261013'
CAND = ROOT / 'outputs/perturbation_scan_day6_v01_20260927/remote/outputs/day6_scan/scan/candidates.jsonl'
META = ROOT / 'dataset_audit/replogle_counts.json'

def main():
    OUT.mkdir(exist_ok=True)
    rows = [json.loads(x) for x in CAND.read_text().splitlines()]
    meta = json.loads(META.read_text())['TabA_K562_day8_library']
    counts = meta['counts']
    assert len(rows) == 6129 and len({r['clue_id'] for r in rows}) == 6129
    thresholds = {}
    for n in (0, 50, 100, 200, 300):
        keep = [r for r in rows if r['target'] in counts and counts[r['target']] >= n]
        thresholds[n] = dict(candidate_rows=len(keep), targets=len({r['target'] for r in keep}), fraction=len(keep)/len(rows))
    summary = dict(status='METADATA_ONLY_NOT_VALIDATION', candidates=len(rows), targets=len({r['target'] for r in rows}),
        state_genes=sorted({g for r in rows for g in r['genes']}),triplets=len({tuple(r['genes']) for r in rows}),
        missing_targets=sorted({r['target'] for r in rows}-counts.keys()), aggregate_support_thresholds=thresholds,
        day8_aggregate_nt=meta['control'], day8_aggregate_total=meta['total'],
        evaluable_candidates=None, validation_performed=False,
        source_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (CAND,META,Path(__file__))})
    (OUT/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    with (OUT/'candidate_overlap.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=['clue_id','target','reference_id','genes','states','day6_delta','day8_aggregate_n','aggregate_status','validation_status'])
        w.writeheader()
        for r in rows:
            n=counts.get(r['target'])
            w.writerow(dict(clue_id=r['clue_id'],target=r['target'],reference_id=r['reference_id'],genes=';'.join(r['genes']),states=''.join(map(str,r['states'])),day6_delta=r['delta'],day8_aggregate_n=n,aggregate_status='target_absent' if n is None else ('n_ge_100' if n>=100 else 'n_lt_100'),validation_status='not_performed'))
    print(json.dumps(thresholds))
if __name__ == '__main__':main()
