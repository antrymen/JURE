"""Offline verification of archived JURE results, not a rerun from raw cells/LLMs."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import linkage, fcluster
from scipy.spatial.distance import squareform


def check(condition, message):
    if not condition:
        raise ValueError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', type=Path, default=Path(__file__).resolve().parents[1] / 'evidence')
    parser.add_argument('--output', type=Path, help='Optional JSON report; refuses overwrite')
    args = parser.parse_args()
    if args.output and args.output.exists():
        parser.error('Output exists; use a fresh path.')
    root = args.evidence.resolve()
    inventory = json.loads((root / 'inventory.json').read_text())
    for relative, digest in inventory.items():
        path = root / relative
        check(path.is_file(), 'Missing archived artifact: ' + relative)
        check(hashlib.sha256(path.read_bytes()).hexdigest() == digest, 'Hash mismatch: ' + relative)
    catalogue = json.loads((root / 'discovery/reference_catalogue.json').read_text())['payload']['records']
    triplets = {tuple(row['genes']) for row in catalogue}
    check(len(catalogue) == 341 and len(triplets) == 86, 'Reference catalogue count mismatch')
    specs = [
        ('Day6 A → B', 'day6_A_to_B.csv', 'discovery_delta', 'validation_delta', 'p_accounting', 'evaluable', 'holm', 'validated', .025),
        ('Day6 B → A', 'day6_B_to_A.csv', 'discovery_delta', 'validation_delta', 'p_accounting', 'evaluable', 'holm', 'validated', .025),
        ('Day6 → Day8', 'day6_to_day8.csv', 'delta_percentage_points', 'day8_delta_pp', 'day8_p_value', 'day8_status', 'day8_holm', 'validation_supported', .05),
        ('Day8 → Day6', 'day8_to_day6.csv', 'day8_delta_pp', 'day6_delta_pp', 'p_value', 'status', 'holm', 'supported', .05),
    ]
    results = []
    for name, filename, x, y, pcol, ecol, hcol, flag, alpha in specs:
        d = pd.read_csv(root / 'validation' / filename)
        ev = d[ecol].eq('OK') if ecol.endswith('status') else d[ecol].eq(True)
        p = d[pcol].to_numpy(float)
        check(np.isfinite(p).all() and ((p >= 0) & (p <= 1)).all(), name + ': invalid P values')
        order = np.argsort(p, kind='stable')
        adjusted = np.empty(len(p))
        adjusted[order] = np.minimum(1, np.maximum.accumulate(p[order] * (len(p) - np.arange(len(p)))))
        check(np.allclose(adjusted, d[hcol], atol=1e-15, rtol=1e-12), name + ': Holm mismatch')
        check(d.loc[~ev, pcol].eq(1).all(), name + ': non-evaluable P is not 1')
        check(d.loc[ev, [x, y]].notna().all().all(), name + ': missing evaluable effect')
        same = ev & (np.sign(d[x]) == np.sign(d[y]))
        passed = same & (adjusted <= alpha)
        check(np.array_equal(same, d.same_direction), name + ': direction flag mismatch')
        check(np.array_equal(passed, d[flag]), name + ': validation flag mismatch')
        results.append(dict(direction=name, locked=len(d), evaluable=int(ev.sum()), pearson_r=float(d.loc[ev, x].corr(d.loc[ev, y])), directional_concordance_percent=100*int(same.sum())/int(ev.sum()), alpha=alpha, validated=int(passed.sum()), rate_evaluable=100*int(passed.sum())/int(ev.sum()), rate_locked=100*int(passed.sum())/len(d)))
    modules = pd.read_csv(root / 'modules/module_summary.csv')
    effect = pd.read_csv(root / 'modules/effect_matrix.csv.gz', index_col=0)
    co = pd.read_csv(root / 'modules/co_clustering_matrix.csv.gz', index_col=0)
    check(effect.shape == (419, 341), 'Effect matrix shape mismatch')
    cores = []
    for module in ['M01', 'M02', 'M03', 'M04', 'M05']:
        row = modules.set_index('module_id').loc[module]
        saved = json.loads(row.stable_core_patterns)
        members = saved + json.loads(row.boundary_patterns)
        # Preserve original matrix order for linkage tie behavior.
        members = [key for key in co.index if key in set(members)]
        sub = co.loc[members, members].to_numpy(float)
        dist = np.clip(1-sub, 0, 1)
        np.fill_diagonal(dist, 0)
        labels = fcluster(linkage(squareform(dist, checks=False), method='complete'), np.nextafter(.2, np.inf), criterion='distance')
        groups = [np.flatnonzero(labels == lab) for lab in np.unique(labels) if (labels == lab).sum() >= 2]
        def key(ids):
            pairs = sub[np.ix_(ids, ids)][np.triu_indices(len(ids), 1)]
            return (-len(ids), -float(pairs.mean()), tuple(sorted(members[i] for i in ids)))
        chosen = sorted(groups, key=key)[0] if groups else []
        check(set(saved) == {members[i] for i in chosen}, module + ': reconstructed core mismatch')
        cores.append(dict(module=module, core_size=len(chosen)))
    cases = json.loads((root / 'cases/index.json').read_text())
    check(len(cases) == 18 and len({x['case_id'] for x in cases}) == 18, 'Case inventory mismatch')
    for case in cases:
        for path in case['records'].values():
            check((root / path).is_file(), 'Missing role record: ' + path)
        if case['complete_evidence_feedback']:
            check(all(k in case['records'] for k in ['request_source', 'executed_source', 'reviewed_source']), 'Incomplete feedback: ' + case['slot'])
    check(sum(x['complete_evidence_feedback'] for x in cases) == 11, 'Feedback count mismatch')
    candidates = pd.read_csv(root / 'discovery/day6_candidates.csv')
    phb2 = candidates[(candidates.target == 'PHB2') & (candidates.pattern == 'DDIT4+ PHGDH+ TRIB3+')]
    check(len(phb2) == 1, 'PHB2 association identity mismatch')
    phb2 = phb2.iloc[0]
    report = dict(status='PASS', scope='Archived results verified; raw-cell experiments and model calls were not rerun.', checked_artifacts=len(inventory), reference_states=len(catalogue), triplets=len(triplets), validation=results, total_clusters=len(modules), selected_cores=cores, cases=len(cases), feedback_cases=11, phb2=dict(nt_percent=100*phb2.matched_nt_frequency, perturbation_percent=100*phb2.perturbation_frequency, delta_pp=phb2.delta_percentage_points))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
