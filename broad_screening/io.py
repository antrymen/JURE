"""Identity-checked reuse of completed Day 6 analyses; no scan execution."""
from pathlib import Path
import hashlib
import json
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LEGACY = ROOT / 'outputs/broad_screening_v01_landscape_20260927'
DEFAULT_SCAN = ROOT / 'outputs/perturbation_scan_day6_v01_20260927'
DEFAULT_OUTPUT = ROOT / 'outputs/broad_screening_v01'


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def clean_json(x):
    if isinstance(x, dict): return {str(k): clean_json(v) for k, v in x.items()}
    if isinstance(x, (list, tuple, np.ndarray)): return [clean_json(v) for v in x]
    if isinstance(x, (np.bool_,)): return bool(x)
    if isinstance(x, (np.integer,)): return int(x)
    if isinstance(x, (float, np.floating)): return float(x) if np.isfinite(x) else None
    if isinstance(x, Path): return str(x)
    return x


def dump(path, obj):
    Path(path).write_text(json.dumps(clean_json(obj), ensure_ascii=False, indent=2, allow_nan=False)+'\n')


def jsonl(path, rows):
    with Path(path).open('w') as f:
        for row in rows:
            f.write(json.dumps(clean_json(row), ensure_ascii=False, allow_nan=False)+'\n')


def csv(path, data, **kwargs):
    data.to_csv(path, index=False, na_rep='NA', **kwargs)


def load(legacy, scan):
    lm = json.loads((legacy/'RUN_MANIFEST.json').read_text())
    frozen = json.loads((legacy/'ANALYSIS_FROZEN.json').read_text())
    if json.loads((legacy/'VERIFICATION.json').read_text())['status'] != 'passed':
        raise ValueError('Legacy analysis has not passed verification')
    if json.loads((scan/'FINAL_AUDIT.json').read_text())['status'] != 'passed':
        raise ValueError('Day 6 scan has not passed audit')
    hashes = {}
    for rel, expected in lm['artifacts_sha256'].items():
        p = legacy/rel
        if sha(p) != expected: raise ValueError(f'Legacy artifact hash mismatch: {rel}')
        hashes[str(p)] = expected
    # Bind source files to the original analysis, not to a newly accepted hash.
    for rel, expected in frozen['source_inputs_sha256'].items():
        p = ROOT/rel
        if sha(p) != expected: raise ValueError(f'Scan source hash mismatch: {rel}')
        hashes[str(p)] = expected
    run = scan/'remote/outputs/day6_scan'
    identity = json.loads((run/'counts/identities.json').read_text())
    scan_summary = json.loads((run/'scan/summary.json').read_text())
    if json.loads((run/'run_status.json').read_text())['status'] != 'complete':
        raise ValueError('Scan is incomplete')
    observed = pd.read_csv(legacy/'matrices/observed.csv.gz', index_col=0)
    mask_df = pd.read_csv(legacy/'matrices/candidate_mask.csv.gz', index_col=0).astype(bool)
    if not observed.index.equals(mask_df.index) or not observed.columns.equals(mask_df.columns):
        raise ValueError('Matrix/mask identities differ')
    with np.load(run/'scan/statistics.npz', allow_pickle=False) as z:
        stats = {k:z[k].copy() for k in z.files}
    ti = {v:i for i,v in enumerate(identity['targets'])}
    pi = {v['reference_id']:i for i,v in enumerate(identity['patterns'])}
    rows = np.array([ti[t] for t in observed.index]); cols = np.array([pi[r] for r in observed.columns])
    raw = stats['delta'][np.ix_(rows, cols)]
    mask = stats['candidate'][np.ix_(rows, cols)]
    if not np.allclose(observed.values, raw, atol=1e-14, rtol=1e-12, equal_nan=True):
        raise ValueError('Legacy effect differs from scan')
    if not np.array_equal(mask, mask_df.values): raise ValueError('Legacy mask differs from scan')
    if not np.isfinite(raw).all(): raise ValueError('Main cohort needs explicit missing-profile handling')
    patterns = [identity['patterns'][i] for i in cols]
    targets = np.asarray(observed.index)
    refs = np.asarray(observed.columns)
    candidates = []
    seen = set()
    with (run/'scan/candidates.jsonl').open() as f:
        for line_number,line in enumerate(f,1):
            c=json.loads(line); key=(c['target'],c['reference_id'])
            i,j=ti[key[0]],pi[key[1]]; p=identity['patterns'][j]
            if key in seen or not stats['candidate'][i,j]: raise ValueError('Duplicate or altered candidate')
            if c['genes'] != p['genes'] or c['states'] != p['states']: raise ValueError('Signed state mismatch')
            for name, matrix in [('delta','delta'),('selected_family_holm_exploratory','selected_holm_exploratory'),('matched_nt_frequency','matched_nt_frequency')]:
                if not np.isclose(c[name],stats[matrix][i,j],rtol=1e-12,atol=0): raise ValueError(name)
            if c['eligible_as_confirmed_clue'] or c['nt_selection_adjusted'] or c['external_validation_status']!='not_performed':
                raise ValueError('Unexpected confirmatory/validation status')
            c['_source_line']=line_number; candidates.append(c); seen.add(key)
    if len(seen) != int(mask.sum()) or int(mask.sum()) != scan_summary['exploratory_candidates']:
        raise ValueError('Candidate membership is incomplete')
    with np.load(legacy/'matrices/linkage_and_order.npz',allow_pickle=False) as z:
        trees={k:z[k].copy() for k in z.files}
    with np.load(legacy/'matrices/resampling_coassignment.npz',allow_pickle=False) as z:
        co={k:z[k].copy() for k in z.files}
    ptable=pd.read_csv(legacy/'tables/pattern_summary.csv').set_index('reference_id').loc[refs]
    ttable=pd.read_csv(legacy/'tables/target_summary.csv').set_index('target').loc[targets]
    return dict(legacy=legacy,scan=scan,scan_run=run,hashes=hashes,frozen=frozen,
        scan_summary=scan_summary,identity=identity,stats=stats,rows=rows,cols=cols,
        x=raw*100,mask=mask,patterns=patterns,targets=targets,refs=refs,candidates=candidates,
        trees=trees,co=co,pattern_table=ptable,target_table=ttable,
        legacy_summary=json.loads((legacy/'SUMMARY.json').read_text()))
