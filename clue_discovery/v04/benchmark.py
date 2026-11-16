"""Predeclared synthetic-only search coverage and end-to-end regression suite."""
import argparse
from dataclasses import replace
import hashlib
import itertools
import json
from pathlib import Path
import time

import numpy as np

from ..v02.populations import Population
from ..v03.artifacts import code_hashes, digest, write_csv, write_json
from ..v03.exploration import sample_exploration
from ..v03.recovery import generate_search_recovery_populations
from .config import ScalableConfig
from .fingerprint import screen_triplets
from .pipeline import fit_twofold, peak_rss_mib


def populations_for_case(*, size, seed, strength, kind='parity', n_per_fold=6000):
    """Random anonymous target placement; truth is never an argument to search."""
    if kind not in ('parity', 'independent', 'biased_independent', 'pairwise_only'):
        raise ValueError('unknown synthetic kind')
    if size < 3 or not -1 < strength < 1:
        raise ValueError('invalid synthetic dimensions/strength')
    placement = np.random.default_rng(np.random.SeedSequence([seed, size, 97])).choice(size, 3, replace=False)
    genes = tuple(f'G{i:04}' for i in range(size))
    target = tuple(sorted(genes[i] for i in placement)) if kind == 'parity' and strength != 0 else ()
    folds, hashes = {}, {}
    for number, fold in enumerate(('A', 'B')):
        rng = np.random.default_rng(np.random.SeedSequence([seed, size, number]))
        frequency = np.linspace(.05, .95, size) if kind == 'biased_independent' else .5
        matrix = rng.binomial(1, frequency, (n_per_fold, size)).astype(np.uint8)
        if kind == 'parity':
            flip = rng.random(n_per_fold) < (1-strength)/2
            matrix[:, placement[2]] = matrix[:, placement[0]] ^ matrix[:, placement[1]] ^ flip
        elif kind == 'pairwise_only':
            states = np.array(list(itertools.product((0, 1), repeat=3)), dtype=np.uint8)
            spins = states.astype(float)*2-1
            # Nonzero main effects avoid testing only symmetric zero third moments.
            logits = spins @ np.array([.25, -.4, .15]) + .55*(spins[:, 0]*spins[:, 1]
                + spins[:, 0]*spins[:, 2] + spins[:, 1]*spins[:, 2])
            probs = np.exp(logits-logits.max()); probs /= probs.sum()
            matrix[:, placement] = states[rng.choice(8, n_per_fold, p=probs)]
        cells = tuple(f'{kind}_{seed}_{size}_{fold}_{i}' for i in range(n_per_fold))
        folds[fold] = Population(matrix, genes, cells)
        hashes[fold] = dict(matrix_sha256=hashlib.sha256(matrix.tobytes()).hexdigest(),
                            cell_ids_sha256=digest(cells), genes_sha256=digest(genes))
    metadata = dict(kind=kind, strength=strength, seed=seed, size=size,
        n_per_fold=n_per_fold, placement_rule='random_anonymous_positions_independent_of_search',
        dataset_hashes=hashes, target_genes_posthoc_only=target, real_data_used=False)
    return folds, target, metadata


def _full_summary(name, result, true_triples):
    proposed = {tuple(row['genes']) for d in result.discoveries.values() for row in d.proposals if row['order'] == 3}
    replicated = {tuple(row['genes']) for row in result.cross_summary if row['order'] == 3 and row['cross_fold_replicated']}
    bidirectional = {tuple(row['genes']) for row in result.cross_summary if row['order'] == 3 and row['bidirectionally_rediscovered']}
    return dict(case=name, hvg_pool_size=result.manifest['config']['hvg_pool_size'],
        genuine_triplets=sorted(true_triples), target_proposed=bool(proposed & true_triples),
        target_crossfold_recovered=bool(replicated & true_triples),
        target_bidirectionally_recovered=bool(bidirectional & true_triples),
        crossfold_false_positive_triplets=sorted(replicated-true_triples),
        crossfold_false_positive_triplet_count=len(replicated-true_triples),
        bidirectional_false_positive_triplet_count=len(bidirectional-true_triples),
        crossfold_triplet_states=sum(r['order'] == 3 and r['cross_fold_replicated'] for r in result.cross_summary),
        n_bootstrap=result.manifest['config']['n_bootstrap'],
        n_null_simulations=result.manifest['config']['n_null_simulations'],
        runtime_seconds=result.manifest['runtime_seconds'],
        peak_process_rss_mib=result.manifest['peak_process_rss_mib'],
        resource_scope='local_process_cumulative_peak_not_AutoDL_2GiB_test',
        status=result.manifest['status'], primary_count=result.manifest['catalogue_counts'].get('primary', 0),
        formal_global_fdr_control=False)


def run(output_dir):
    root = Path(output_dir)
    if root.exists() and any(root.iterdir()):
        raise FileExistsError('benchmark already exists; never overwrite a frozen suite')
    root.mkdir(parents=True, exist_ok=True)
    config = ScalableConfig()
    coverage_specs = [dict(size=size, seed=seed, strength=strength, kind='parity')
        for size in (100, 500, 1000) for strength in (.35, .65) for seed in (11, 29, 47)]
    full_specs = [dict(size=1000, seed=11, strength=.65, kind='parity')]
    full_specs += [dict(size=100, seed=seed, strength=0., kind=kind)
        for kind in ('independent', 'biased_independent', 'pairwise_only') for seed in (11, 29, 47)]
    protocol = dict(version=config.run_version, config=config.to_dict(), config_hash=config.sha256,
        code_hashes=code_hashes(), coverage_cases=coverage_specs, full_cases=full_specs,
        original_100_gene_case=True, n_per_fold=6000,
        selection_or_seed_changes_after_results=False, real_data_used=False,
        coverage_only_is_not_full_pipeline=True, truth_passed_to_search=False,
        intended_checks=['strong_and_weak_parity_coverage', 'pairwise_and_independent_negative_controls',
                         'same_original_100_gene_dataset', 'one_1000_gene_full_pipeline'],
        acceptance_claim='report measured recovery and misses; no universal coverage or FDR claim')
    write_json(root/'protocol_frozen.json', protocol)
    rows, full = [], []
    status = dict(status='running', completed_coverage_folds=0, completed_full_runs=0)
    write_json(root/'execution_status.json', status)
    started = time.monotonic()
    try:
        for case in coverage_specs:
            case_name = f'{case["kind"]}_{case["size"]}_theta{case["strength"]}_seed{case["seed"]}'
            populations, target, data = populations_for_case(**case)
            local = replace(config, hvg_pool_size=case['size'])
            path = root/'coverage'/case_name
            write_json(path/'data.json', data)
            for fold, population in populations.items():
                candidates, audit = screen_triplets(population.matrix, population.gene_names, local, fold=fold)
                write_csv(path/f'screen_{fold}.csv', audit['screened_records'])
                write_json(path/f'audit_{fold}.json', {k: v for k, v in audit.items() if k != 'screened_records'})
                # Reference probability/realization for the old 300-tuple random budget.
                random_candidates, random_audit = sample_exploration(population.gene_names, 3,
                    n_candidates=300, random_seed=case['seed'], fold=fold)
                included = target in {c.genes for c in candidates}
                target_screen = next((r for r in audit['screened_records'] if tuple(r['genes']) == target), None)
                rows.append(dict(case=case_name, fold=fold, **case, target=target,
                    target_proposed=included,
                    target_collision_bands=target_screen['fingerprint_collision_bands'] if target_screen else None,
                    target_screened=target_screen is not None,
                    target_failure_stage='proposed' if included else 'score_quota' if target_screen else 'fingerprint_or_screen_coverage',
                    proposed=len(candidates), scored=audit['candidates_scored'],
                    observed_unique_collisions=audit['observed_unique_collisions'],
                    bucket_entries_dropped=sum(b['bucket_entries_dropped'] for b in audit['bands']),
                    collision_bands_truncated=sum(b['collision_budget_truncated'] for b in audit['bands']),
                    random_300_target_proposed=target in {c.genes for c in random_candidates},
                    random_300_probability=random_audit['inclusion_probability'],
                    runtime_seconds=audit['runtime_seconds'], peak_process_rss_mib=peak_rss_mib()))
                status['completed_coverage_folds'] += 1
            write_csv(root/'coverage.csv', rows)
            write_json(root/'execution_status.json', status)
            print(json.dumps(dict(completed=case_name, target_proposed=[r['target_proposed'] for r in rows[-2:]])), flush=True)
        # Original published run generator/data, not the oracle bypass.
        populations, truth, data = generate_search_recovery_populations()
        original = Path('outputs/clue_hunting_v03_benchmark/search_recovery/benchmark_protocol.json')
        if original.exists():
            expected = json.loads(original.read_text())['data']['dataset_hashes']
            if data['dataset_hashes'] != expected:
                raise RuntimeError('original synthetic dataset hashes do not match')
            data['original_frozen_dataset_hashes_matched'] = True
        result = fit_twofold(populations['A'], populations['B'], replace(config, hvg_pool_size=100),
            root/'full'/'original_100', dataset_manifest=data)
        full.append(_full_summary('original_100', result,
            {tuple(t['genes']) for t in truth if t['genuine_highest_order'] and t['order'] == 3}))
        status['completed_full_runs'] += 1
        write_csv(root/'full_summary.csv', full)
        print(json.dumps(full[-1]), flush=True)
        for case in full_specs:
            name = f'{case["kind"]}_{case["size"]}_theta{case["strength"]}_seed{case["seed"]}'
            populations, target, data = populations_for_case(**case)
            result = fit_twofold(populations['A'], populations['B'], replace(config, hvg_pool_size=case['size']),
                root/'full'/name, dataset_manifest=data)
            full.append(_full_summary(name, result, {target} if target else set()))
            status['completed_full_runs'] += 1
            write_csv(root/'full_summary.csv', full)
            write_json(root/'execution_status.json', status)
            print(json.dumps(full[-1]), flush=True)
        if protocol['code_hashes'] != code_hashes():
            raise RuntimeError('source changed during benchmark')
        status.update(status='complete', runtime_seconds=time.monotonic()-started,
                      source_unchanged=True, real_data_used=False)
        write_json(root/'execution_status.json', status)
        report(root, rows, full)
    except BaseException as error:
        status.update(status='failed', error_type=type(error).__name__, error=str(error))
        write_json(root/'execution_status.json', status)
        raise
    return rows, full


def report(root, rows, full):
    lines = ['# Clue Hunting v0.4 Synthetic 验证', '',
        '所有 seed、强度、规模及配置在运行前冻结。未使用真实 NT；未向搜索器提供 planted tuple。', '',
        '## 独立指纹通道的覆盖', '',
        '每个规模/强度包含 3 个数据 seed × 2 folds。这里只测候选覆盖，不替代完整统计。', '',
        '| Genes | θ | 命中 folds | 两 fold 均命中的数据集 | 300 随机候选命中 folds |',
        '|---:|---:|---:|---:|---:|']
    for size in (100, 500, 1000):
        for strength in (.35, .65):
            group = [r for r in rows if r['size'] == size and r['strength'] == strength]
            both = sum(all(r['target_proposed'] for r in group if r['seed'] == seed) for seed in (11, 29, 47))
            lines.append(f'| {size} | {strength} | {sum(r["target_proposed"] for r in group)}/6 | {both}/3 | {sum(r["random_300_target_proposed"] for r in group)}/6 |')
    lines += ['', '## 完整流程', '',
        '以下运行保留 1999 次 null 模拟与 1000 次 bootstrap。假阳性按三阶 gene set 去重；不把候选本身算成发现。', '',
        '| Case | 目标提出 | 目标跨折通过 | 目标双向通过 | 非真值跨折三元组 | 秒 |',
        '|---|---|---|---|---:|---:|']
    for r in full:
        lines.append(f'| {r["case"]} | {r["target_proposed"] if r["genuine_triplets"] else "无目标"} | {r["target_crossfold_recovered"] if r["genuine_triplets"] else "不适用"} | {r["target_bidirectionally_recovered"] if r["genuine_triplets"] else "不适用"} | {r["crossfold_false_positive_triplet_count"]} | {r["runtime_seconds"]:.2f} |')
    lines += ['', '## 边界', '',
        '- 指纹是偏好强 binary parity 模式的候选启发式；弱信号、偏置或稀疏状态可能漏检。',
        '- 单次 1000-gene 完整 synthetic run 不代表真实 NT 千基因流程或 2 GiB AutoDL 验收。',
        '- RSS 是本地进程累计高水位；未施加 2 GiB cgroup / 0.5 CPU 限制，未使用 GPU。',
        '- 少量 null 运行不能证明全局 FDR；排序与候选筛选均是 data-adaptive。',
        '- 搜索预算未覆盖完整 universe 时仍为 budget_exhausted，primary 的全局预算限制保留。',
        '- 四阶搜索未升级；本报告三阶恢复不能替代 pure-four-way 验收。', '']
    (Path(root)/'BENCHMARK_REPORT.md').write_text('\n'.join(lines))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', required=True)
    args = parser.parse_args()
    run(args.output_dir)


if __name__ == '__main__':
    main()
