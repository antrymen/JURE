"""New, fully pregenerated benchmark for validation-family correction only."""
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import replace
from datetime import datetime, timezone
import gzip
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import shutil
import time

import numpy as np
from scipy.optimize import brentq
from scipy.special import xlogy
from scipy.stats import beta

from ..v02.populations import Population
from ..v03.artifacts import code_hashes, digest, software_versions, write_csv, write_json
from ..v04.benchmark import populations_for_case
from ..v04.config import ScalableConfig
from ..v04.pipeline import peak_rss_mib
from .experiment import run_experiment
from .policy import ARMS


NAMESPACE = 'JURE_validation_family_v1_new_holdout_20260927'
REPO = Path(__file__).resolve().parents[2]
V04_FREEZE = REPO/'outputs/clue_hunting_v04_benchmark/SOURCE_FREEZE.json'


def cases():
    result = []
    for kind in ('independent', 'biased_independent', 'pairwise_only'):
        for index in range(60):
            result.append(dict(case_id=f'null_{kind}_{index:03}', kind=kind,
                size=100, strength=0., index=index, group=kind, positive=False))
    for size, count in ((100, 20), (1000, 6)):
        for label, strength in [('medium', .50), ('strong', .65)]:
            for index in range(count):
                result.append(dict(case_id=f'positive_{label}_{size}_{index:03}', kind='parity',
                    size=size, strength=strength, index=index, group=f'{label}_{size}', positive=True))
    for row in result:
        row['seed'] = int.from_bytes(hashlib.sha256(f'{NAMESPACE}:{row["case_id"]}'.encode()).digest()[:8], 'big')
    assert len({c['seed'] for c in result}) == len(result)
    assert not {11, 29, 47, 20260927}.intersection(c['seed'] for c in result)
    return result


def verify_v04():
    frozen = json.loads(V04_FREEZE.read_text())
    changed = [name for name, expected in frozen['code_hashes'].items()
               if hashlib.sha256((REPO/name).read_bytes()).hexdigest() != expected]
    if changed:
        raise RuntimeError(f'frozen v0.4 sources changed: {changed}')
    return frozen


def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''):
            h.update(chunk)
    return h.hexdigest()


def pregenerate(root, specs):
    """Complete and hash every new dataset before any discovery/validation runs."""
    index = []
    for case in specs:
        path = root/'datasets'/case['case_id']
        path.mkdir(parents=True, exist_ok=False)
        populations, target, metadata = populations_for_case(
            size=case['size'], seed=case['seed'], strength=case['strength'], kind=case['kind'])
        np.savez_compressed(path/'counts.npz', **{fold: p.matrix for fold, p in populations.items()})
        metadata.pop('target_genes_posthoc_only')
        metadata.update(genes=populations['A'].gene_names, generation_namespace=NAMESPACE)
        write_json(path/'data.json', metadata)
        write_json(path/'truth.json', dict(true_triplets=[target] if target else [],
            use='read_after_all_discovery_validation_and_corrections_for_this_case'))
        index.append(dict(case_id=case['case_id'],
            files={name: file_hash(path/name) for name in ('counts.npz', 'data.json', 'truth.json')},
            dataset_hashes=metadata['dataset_hashes']))
    write_json(root/'DATASETS_FROZEN.json', dict(datasets=index, index_sha256=digest(index),
        all_datasets_generated_before_any_evaluation=True, created_at=datetime.now(timezone.utc).isoformat()))
    return index


def load_case(path, entry):
    for name, expected in entry['files'].items():
        if name == 'truth.json':
            continue
        if file_hash(path/name) != expected:
            raise ValueError('pregenerated dataset artifact changed')
    data = json.loads((path/'data.json').read_text())
    genes = tuple(data['genes'])
    populations = {}
    with np.load(path/'counts.npz', allow_pickle=False) as archive:
        for fold in ('A', 'B'):
            matrix = archive[fold]
            cells = tuple(f'{data["kind"]}_{data["seed"]}_{data["size"]}_{fold}_{i}'
                          for i in range(data['n_per_fold']))
            hashes = dict(matrix_sha256=hashlib.sha256(matrix.tobytes()).hexdigest(),
                          genes_sha256=digest(genes), cell_ids_sha256=digest(cells))
            if hashes != entry['dataset_hashes'][fold]:
                raise ValueError('matrix/cell/gene identity hash mismatch')
            populations[fold] = Population(matrix, genes, cells)
    return populations, data


def _metric(case, result, truth, arm):
    gain = {tuple(r['genes']) for r in result.corrected_sets if r['arm'] == arm and r['family_gain_rejected']}
    states = [r for r in result.corrected_states if r['arm'] == arm and r['qualified']]
    qualified = {tuple(r['genes']) for r in states}
    directions = {}
    for row in states:
        directions.setdefault(row['reference_id'], set()).add(row['family_id'].split(':')[0])
    bidirectional = {tuple(r['genes']) for r in states if len(directions[r['reference_id']]) == 2}
    proposed = {tuple(r['genes']) for d in result.discoveries.values() for r in d.proposals if r['order'] == 3}
    dlocked = {tuple(r['genes']) for d in result.discoveries.values() for r in d.locked if r['order'] == 3}
    return dict(case_id=case['case_id'], group=case['group'], positive=case['positive'],
        size=case['size'], strength=case['strength'], seed=case['seed'], arm=arm,
        true_triplets=sorted(truth), target_proposed=bool(proposed & truth),
        target_discovery_locked=bool(dlocked & truth),
        target_gain_rejected=bool(gain & truth), target_qualified=bool(qualified & truth),
        target_bidirectional=bool(bidirectional & truth),
        family_size_A=len(result.families['A'].members), family_size_B=len(result.families['B'].members),
        gain_rejected_triplets=len(gain), gain_false_triplets=len(gain-truth),
        gain_fdp=len(gain-truth)/max(1, len(gain)),
        qualified_triplets=len(qualified), false_triplets=len(qualified-truth),
        qualified_fdp=len(qualified-truth)/max(1, len(qualified)),
        any_false_clue=bool(qualified-truth), false_triplet_identities=sorted(qualified-truth),
        qualified_states=len({r['reference_id'] for r in states}),
        qualified_state_direction_events=len(states), bidirectional_false_triplets=len(bidirectional-truth),
        discovery_budget_exhausted=any(d.status != 'complete' for d in result.discoveries.values()),
        state_level_error_rate_controlled=False)


def run_case(root_string, case, entry, expected_hashes):
    root = Path(root_string)
    if code_hashes() != expected_hashes:
        raise RuntimeError('source does not match preregistration')
    data_path = root/'datasets'/case['case_id']
    populations, data = load_case(data_path, entry)
    config = replace(ScalableConfig(), hvg_pool_size=case['size'])
    path = root/'runs'/case['case_id']
    result = run_experiment(populations['A'], populations['B'], config, path,
                            compact=True, dataset_manifest=data)
    # Truth is opened only after corrected decisions have been written and locked.
    if file_hash(data_path/'truth.json') != entry['files']['truth.json']:
        raise ValueError('frozen truth changed')
    truth = {tuple(t) for t in json.loads((data_path/'truth.json').read_text())['true_triplets']}
    rows = [_metric(case, result, truth, arm) for arm, _, _ in ARMS]
    raw_case = next(r for r in rows if r['arm'] == 'raw_05')
    for row in rows:
        row['raw_target_qualified'] = raw_case['target_qualified']
        row['runtime_seconds'] = result.manifest['runtime_seconds']
        row['worker_peak_rss_mib'] = peak_rss_mib()
        row['memory_scope'] = 'worker_lifetime_peak_local_CPU_not_AutoDL_cgroup'
    write_json(path/'case_summary.json', rows)
    # Lossless compression of this new run's large text artifacts only.
    compressed = {}
    for csv in path.rglob('*.csv'):
        before = file_hash(csv)
        zipped = csv.with_suffix(csv.suffix+'.gz')
        with csv.open('rb') as src, gzip.open(zipped, 'wb', compresslevel=1) as dst:
            shutil.copyfileobj(src, dst, length=1024*1024)
        compressed[str(csv.relative_to(path))] = dict(path=str(zipped.relative_to(path)),
            uncompressed_sha256=before, compressed_sha256=file_hash(zipped))
        csv.unlink()
    write_json(path/'compressed_csv_manifest.json', compressed)
    return rows


def binomial_interval(successes, total, *, one_sided=False):
    if not total:
        return [None, None]
    alpha = .05 if one_sided else .025
    lo = 0. if successes == 0 or one_sided else float(beta.ppf(alpha, successes, total-successes+1))
    hi = 1. if successes == total else float(beta.ppf(1-alpha, successes+1, total-successes))
    return [lo, hi]


def pooled_error_upper(successes, total, alpha=.05):
    """KL-Chernoff upper bound for independent, possibly unequal Bernoulli p.

    The pooled regimes need not share an error probability. Their sum MGF is
    bounded by that of Binomial(n, mean(p)), by concavity of log(1-p+p*exp(t)).
    Invert n*KL(observed_rate || upper)=log(1/alpha) on the upper branch.
    """
    if not total:
        return None
    if successes == total:
        return 1.
    if successes == 0:
        return float(-np.expm1(np.log(alpha)/total))
    p = successes/total
    def equation(q):
        return total*(xlogy(p, p/q)+xlogy(1-p, (1-p)/(1-q)))+np.log(alpha)
    hi = np.nextafter(1., 0.)
    return float(brentq(equation, p, hi)) if equation(hi) > 0 else 1.


def summarize(rows):
    output = []
    for group in sorted({r['group'] for r in rows}):
        for arm, _, _ in ARMS:
            values = [r for r in rows if r['group'] == group and r['arm'] == arm]
            n = len(values); events = sum(r['any_false_clue'] for r in values)
            successes = sum(r['target_qualified'] for r in values)
            raw_successes = sum(r['raw_target_qualified'] for r in values)
            output.append(dict(group=group, arm=arm, n_datasets=n,
                null=not values[0]['positive'], datasets_with_any_false_clue=events,
                any_false_clue_rate=events/n, any_false_clue_CI95=binomial_interval(events, n),
                false_triplets=sum(r['false_triplets'] for r in values),
                mean_qualified_fdp=float(np.mean([r['qualified_fdp'] for r in values])),
                mean_gain_fdp=float(np.mean([r['gain_fdp'] for r in values])),
                nonempty_family_datasets=sum(bool(r['family_size_A']+r['family_size_B']) for r in values),
                target_proposed=sum(r['target_proposed'] for r in values),
                target_discovery_locked=sum(r['target_discovery_locked'] for r in values),
                target_qualified=successes, end_to_end_power=successes/n if values[0]['positive'] else None,
                power_CI95=binomial_interval(successes, n) if values[0]['positive'] else [None, None],
                raw_target_qualified=raw_successes,
                retention_given_raw=successes/raw_successes if raw_successes else None,
                target_bidirectional=sum(r['target_bidirectional'] for r in values)))
    return output


def acceptance(rows, summary):
    """Fixed engineering screen, not a proof of FDR or biological validity."""
    results = {}
    for arm, _, _ in ARMS:
        null = [r for r in rows if not r['positive'] and r['arm'] == arm]
        events = sum(r['any_false_clue'] for r in null)
        pooled_upper = pooled_error_upper(events, len(null))
        groups = [r for r in summary if r['arm'] == arm]
        null_rates_pass = all(r['any_false_clue_rate'] <= .05 for r in groups if r['null'])
        positive_groups = [r for r in groups if not r['null']]
        retention_pass = all(r['raw_target_qualified'] >= 3 and r['retention_given_raw'] is not None
            and r['retention_given_raw'] >= (.9 if r['group'].startswith('strong') else .8)
            for r in positive_groups)
        strong_power_pass = all(r['end_to_end_power'] >= .8 for r in positive_groups if r['group'].startswith('strong'))
        results[arm] = dict(pooled_null_any_false_events=events, pooled_null_datasets=len(null),
            pooled_null_one_sided95_upper=pooled_upper,
            pooled_interval_method='KL_Chernoff_independent_nonidentical_Bernoulli_upper',
            per_null_regime_point_rate_le_05=null_rates_pass,
            positive_retention_pass=retention_pass, strong_end_to_end_power_ge_08=strong_power_pass,
            engineering_screen_pass=bool(null_rates_pass and pooled_upper is not None
                and pooled_upper <= .05 and retention_pass and strong_power_pass),
            chosen_after_results=False)
    return dict(predeclared_conservative_arm='holm_025', arms=results,
        automatic_agent_or_real_data_promotion=False,
        formal_BH_guarantee_established=False, state_level_error_control_established=False)


def render_report(root, summary, review, runtime):
    lines = ['# v0.4 冻结搜索器：Validation Family 新数据验收', '',
        '搜索器、MFI/Gain、bootstrap 与弱信号阈值未改。所有新数据在任何 discovery/validation 开始前生成并冻结。', '',
        '每方向的全部 locked 三阶 gene sets 构成 family；不按状态重复计数，也不剔除验证侧不可估计的成员。', '',
        'raw_05 为逐候选 p≤0.05；bh_05 为每方向 BH q≤0.05；bh_025 将方向预算减半；holm_025 为每方向 Holm 调整 p≤0.025。', '',
        '## 阴性数据（按完整双向运行计数）', '',
        '| 数据类型 | 方法 | 出现假 clue 的数据集 | 假 clue 数据集比例的 95% CI | 假阳性三元组总数 |',
        '|---|---|---:|---|---:|']
    for r in summary:
        if r['null']:
            lo, hi = r['any_false_clue_CI95']
            lines.append(f'| {r["group"]} | {r["arm"]} | {r["datasets_with_any_false_clue"]}/{r["n_datasets"]} | [{lo:.3f}, {hi:.3f}] | {r["false_triplets"]} |')
    lines += ['', '## 阳性数据（正常搜索，不注入真值）', '',
        'medium θ=0.50，strong θ=0.65；每 fold 6000 cells。end-to-end 分母包括搜索漏检；保留率分母仅为同批 raw 已确认目标，分开报告。', '',
        '| 分组 | 方法 | 提出目标 | Discovery 锁定 | 最终跨折目标 | 相对 raw 保留率 | 双向目标 |',
        '|---|---|---:|---:|---:|---:|---:|']
    for r in summary:
        if not r['null']:
            retention = 'NA' if r['retention_given_raw'] is None else f'{r["retention_given_raw"]:.1%}'
            lines.append(f'| {r["group"]} | {r["arm"]} | {r["target_proposed"]}/{r["n_datasets"]} | {r["target_discovery_locked"]}/{r["n_datasets"]} | {r["target_qualified"]}/{r["n_datasets"]} | {retention} | {r["target_bidirectional"]}/{r["n_datasets"]} |')
    lines += ['', '## 预定验收检查', '',
        '| 方法 | 全部 null 出现假 clue 的次数 | pooled 单侧 95% Chernoff 上界 | 工程检查通过 |',
        '|---|---:|---:|---|']
    for arm, r in review['arms'].items():
        lines.append(f'| {arm} | {r["pooled_null_any_false_events"]}/{r["pooled_null_datasets"]} | {r["pooled_null_one_sided95_upper"]:.3f} | {r["engineering_screen_pass"]} |')
    lines += ['', f'总运行时间：{runtime:.1f} 秒。各 case 的本地 worker 累计 RSS 在 metrics.csv 中；不是 AutoDL 2 GiB 实测。', '',
        '## 推断边界', '',
        '- BH 的独立性/PRDS 条件未在共享基因的 families 中证明；BH 比较是经验评估，不能直接写成全局 FDR 保证。',
        '- BH 后再套 bootstrap、方向与具体状态过滤，最终子集不自动继承 BH 的 FDR 保证；gene-set 拒绝与最终 qualified 结果分开保存。',
        '- Holm 每方向 0.025 的 gene-set FWER 推理以有效的独立留出 p 值为前提，两方向通过 union bound 合并；不要求两方向独立。进一步过滤不会增加任何假拒绝事件。',
        '- 不把 gene-set-level 校正说成具体 d-tuple 的 state-level FDR，也不等同于机制正确或生物学重复。',
        '- 各 null 类型单列 Clopper–Pearson 区间；三类 pooled 上界用允许独立但不同分布 Bernoulli 的 KL-Chernoff bound，不假定三类错误率相同。',
        '- 旧的 6/4/1 null 只用于提出问题，没有用于本次验收；未根据本次结果调参或选择更好看的 seed。',
        '- 所有 arms 用完全相同的候选、点估计和 bootstrap。原始 primary 规则和下游 Agent 开关未改。',
        '- 工程检查通过不是对所有数据分布的定理；不自动上线真实数据或 Agent。', '',
        '依据：[SciPy BH 文档](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.false_discovery_control.html)、[R p.adjust 文档](https://stat.ethz.ch/R-manual/R-devel/library/stats/html/p.adjust.html)。', '']
    (root/'BENCHMARK_REPORT.md').write_text('\n'.join(lines))


def run(output_dir, workers=2):
    root = Path(output_dir).resolve()
    if root.exists() and any(root.iterdir()):
        raise FileExistsError('new benchmark requires an empty output directory')
    if workers not in (1, 2):
        raise ValueError('local suite allows one or two independent workers')
    baseline = verify_v04()
    config, specs = ScalableConfig(), cases()
    root.mkdir(parents=True, exist_ok=True)
    hashes = code_hashes()
    protocol = dict(version='validation_family_v1', namespace=NAMESPACE,
        registered_at=datetime.now(timezone.utc).isoformat(), config=config.to_dict(),
        config_hash=config.sha256, source_hashes=hashes, v04_source_hash=baseline['code_hash'],
        cases=specs, n_per_fold=6000, arms=ARMS, workers=workers,
        null_cases_per_regime=60, primary_conservative_arm='holm_025',
        no_search_kernel_threshold_changes=True, old_datasets_used_for_acceptance=False,
        family_definition='direction x all unique locked triplets, frozen before validation; missing/poor p1 accounting',
        outcomes=['gene_set_rejections', 'qualified_concrete_states', 'false_clue_event_per_dataset',
                  'mean_FDP', 'end_to_end_power', 'retention_given_raw_power', 'binomial_CI'],
        acceptance=dict(per_null_regime_observed_any_false_clue_rate_max=.05,
            pooled_null_one_sided95_upper_max=.05, strong_end_to_end_power_min=.8,
            strong_retention_given_raw_min=.9, medium_retention_given_raw_min=.8,
            minimum_raw_positive_datasets_per_group=3,
            weak_recall_not_optimized=True, medium_absolute_power_reported_without_search_retuning=True),
        software_versions=software_versions(), real_data_used=False)
    write_json(root/'PROTOCOL_FROZEN.json', protocol)
    started = time.monotonic()
    status = dict(status='pregenerating', completed_cases=0, expected_cases=len(specs))
    write_json(root/'execution_status.json', status)
    try:
        entries = pregenerate(root, specs)
        # One namespace and all files fixed before launching the first evaluator.
        status.update(status='evaluating', all_datasets_frozen_before_evaluation=True)
        write_json(root/'execution_status.json', status)
        print(json.dumps(dict(phase='all_datasets_frozen', datasets=len(entries))), flush=True)
        for name in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS'):
            os.environ[name] = '1'
        rows = []
        with ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context('spawn')) as pool:
            pending = {pool.submit(run_case, str(root), case, entry, hashes): case
                       for case, entry in zip(specs, entries)}
            for future in as_completed(pending):
                try:
                    result = future.result()
                except BaseException:
                    for queued in pending:
                        queued.cancel()
                    raise
                rows.extend(result)
                status['completed_cases'] += 1
                ordered = sorted(rows, key=lambda r: (r['case_id'], r['arm']))
                write_csv(root/'metrics.csv', ordered)
                write_json(root/'execution_status.json', status)
                print(json.dumps(dict(case=pending[future]['case_id'], completed=status['completed_cases'],
                    false_triplets={r['arm']: r['false_triplets'] for r in result},
                    target_qualified={r['arm']: r['target_qualified'] for r in result})), flush=True)
        if hashes != code_hashes():
            raise RuntimeError('source changed after preregistration')
        verify_v04()
        summary = summarize(rows)
        review = acceptance(rows, summary)
        write_csv(root/'summary.csv', summary)
        write_json(root/'acceptance.json', review)
        runtime = time.monotonic()-started
        render_report(root, summary, review, runtime)
        status.update(status='complete', runtime_seconds=runtime, source_unchanged=True,
                      v04_unchanged=True, all_prespecified_cases_completed=True)
        write_json(root/'execution_status.json', status)
    except BaseException as error:
        status.update(status='failed', error_type=type(error).__name__, error=str(error))
        write_json(root/'execution_status.json', status)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--workers', type=int, default=2)
    args = parser.parse_args()
    run(args.output_dir, args.workers)


if __name__ == '__main__':
    main()
