"""Regenerate a Chinese benchmark report without mutating any frozen source run."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

import pandas as pd

from .artifacts import digest, write_csv, write_json


def _read(path):
    path = Path(path)
    return json.loads(path.read_text()) if path.is_file() else None


def _fmt(value, digits=3):
    if value is None or isinstance(value, float) and pd.isna(value):
        return "未评估"
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, float):
        return f"{value:.{digits}g}"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value).replace("|", "\\|").replace("\n", " ")


def _table(headers, rows):
    return ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)] + [
        "| " + " | ".join(_fmt(value) for value in row) + " |" for row in rows]


def _memory(value):
    return value / 1024 ** 2 if isinstance(value, (int, float)) else None


def _resource(path, mode, stage):
    value = _read(path)
    if value is None:
        return None
    initial = value.get("cgroup_initial") or {}
    delta = value.get("cgroup_events_delta") or {}
    oom, oom_kill = delta.get("oom"), delta.get("oom_kill")
    no_oom = (oom == 0 and oom_kill == 0) if oom is not None and oom_kill is not None else None
    return dict(benchmark_mode=mode, stage=stage, path=str(path), status=value.get("status"),
        wall_seconds=value.get("wall_seconds"), exit_code=value.get("exit_code"),
        resource_guard_triggered=value.get("resource_guard_triggered"),
        peak_process_rss_mib=_memory(value.get("peak_process_memory_bytes")),
        peak_cgroup_current_mib=_memory(value.get("peak_cgroup_current_bytes")),
        peak_cgroup_anon_mib=_memory(value.get("peak_cgroup_anon_bytes")),
        peak_cgroup_file_mib=_memory(value.get("peak_cgroup_file_bytes")),
        cgroup_memory_limit_mib=_memory(initial.get("memory_max_bytes")),
        cpu_limit_cores=initial.get("cpu_limit_cores"), oom_event_delta=oom,
        oom_kill_event_delta=oom_kill, no_oom_events_observed=no_oom,
        measurement_scope="process single-child RSS/HWM; cgroup includes shared processes and page cache")


def _testing_audit(path, label):
    data = _read(path)
    if data is None:
        return dict(run=label, available=False, global_search_fdr_controlled=False, problems=["missing_testing_manifest"])
    problems, members = [], Counter()
    for family in data.get("families", []):
        ids = family.get("unique_member_ids", [])
        if len(ids) != len(set(ids)) or len(ids) != family.get("n_members"):
            problems.append(f"invalid_family_members:{family.get('family_id')}")
        if family.get("member_ids_sha256") != digest(ids):
            problems.append(f"family_hash_mismatch:{family.get('family_id')}")
        members[family.get("statistic", "unknown")] += len(ids)
        if family.get("global_search_fdr_controlled"):
            problems.append("unexpected_global_FDR_claim")
    if data.get("global_search_fdr_controlled"):
        problems.append("unexpected_global_FDR_claim")
    return dict(run=label, available=True, n_families=len(data.get("families", [])),
        member_counts_by_statistic=dict(members),
        generation_accounting_complete=data.get("generation_accounting_complete"),
        global_search_fdr_controlled=data.get("global_search_fdr_controlled", False),
        problems=sorted(set(problems)), source_path=str(path))


def generate_report(root):
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    statistical = _read(root / "statistical" / "summary.json")
    recovery = _read(root / "search_recovery" / "summary.json")
    scales, sentinels, resources, audits, source_manifests = [], [], [], [], []
    limitations = {"global_search_fdr_not_established", "random_cell_holdout_is_not_biological_replication"}
    mode_status = {}
    for mode in ("synthetic", "real"):
        directory = root / f"scale_{mode}"
        summary = _read(directory / "scale_summary.json")
        execution = _read(directory / "execution_status.json")
        plan = _read(directory / "scale_plan_frozen.json")
        mode_status[mode] = dict(summary_available=summary is not None, execution=execution,
                                 plan=plan, completed_stages=summary.get("completed_stages") if summary else None)
        if summary is None:
            limitations.add(f"{mode}_scale_benchmark_not_run_or_not_completed")
        if execution is not None and not execution.get("complete", False):
            limitations.add(f"{mode}_scale_execution_incomplete_or_failed")
        for row in (summary or {}).get("stages", []):
            result = dict(row, benchmark_mode=mode)
            size, dry = row.get("hvg_pool_size"), bool(row.get("dry_run"))
            stage = directory / f"genes_{size}_{'dry' if dry else 'full'}"
            # Resolve downloaded remote artifacts within this local report root.
            manifest = _read(stage / "run_manifest.json")
            source_manifests.append((stage, manifest))
            result["local_source_path"] = str(stage)
            for order in (2, 3, 4):
                for output_key, manifest_key in (("crossfold", "crossfold_counts"), ("bidirectional", "bidirectional_counts")):
                    values = (manifest or {}).get(manifest_key)
                    result[f"order{order}_{output_key}_patterns"] = (
                        None if dry or values is None else values.get(str(order), values.get(order, 0)))
            if dry:
                for key in ("primary_patterns", "exploratory_patterns", "crossfold_triplet_patterns", "bidirectional_triplet_patterns"):
                    result[key] = None
                result["statistical_qualification_status"] = "not_evaluated"
            scales.append(result)
            limitations.update(row.get("limitations", []))
            if row.get("status") != "complete":
                limitations.add("candidate_or_evaluation_budget_exhaustion")
            sentinel_path = stage / "sentinel_recovery.csv"
            if sentinel_path.is_file():
                frame = pd.read_csv(sentinel_path)
                frame["benchmark_mode"] = mode
                frame["hvg_pool_size"] = size
                frame["run_dry_run"] = dry
                frame["statistical_sentinel_evaluation_performed"] = not dry
                frame["source_run"] = str(stage)
                if dry:
                    for key in ("mfi", "set_level_gain", "p_gain", "min_state_count", "kept_states", "validated_states"):
                        if key in frame:
                            frame[key] = None
                sentinels.extend(frame.to_dict("records"))
            audits.append(_testing_audit(stage / "multiple_testing_manifest.json", f"{mode}_{size}"))
            resource = _resource(directory / f"resources_{size}.json", mode, str(size))
            if resource:
                resources.append(resource)
        for filename in ("preparation_resources.json", "prepare_resources.json"):
            resource = _resource(directory / filename, mode, "preparation")
            if resource:
                resources.append(resource)
                break
    for case in (recovery or {}).get("cases", []):
        audits.append(_testing_audit(root / "search_recovery" / case["case"] / "multiple_testing_manifest.json",
                                     f"search_recovery_{case['case']}"))
        if case.get("gene_universe_size", 0) >= 100 and case.get("true_higher_order_candidate_recall", 1) < 1:
            limitations.add("pure_higher_order_search_coverage_incomplete")
    if any(not audit.get("available") or audit.get("problems") for audit in audits):
        limitations.add("multiple_testing_audit_missing_or_inconsistent")
    if any(r.get("resource_guard_triggered") for r in resources):
        limitations.add("resource_guard_triggered")
    if any(r.get("no_oom_events_observed") is False for r in resources):
        limitations.add("cgroup_oom_event_observed")
    if not statistical:
        limitations.add("statistical_synthetic_benchmark_missing")
    if not recovery:
        limitations.add("search_recovery_benchmark_missing")

    write_csv(root / "scale_benchmark.csv", scales, ["benchmark_mode", "hvg_pool_size", "dry_run", "status"])
    write_csv(root / "sentinel_recovery.csv", sentinels, ["benchmark_mode", "hvg_pool_size", "run_dry_run", "fold", "genes", "failure_stage"])
    write_csv(root / "resource_audit.csv", resources, ["benchmark_mode", "stage", "peak_process_rss_mib", "peak_cgroup_current_mib"])
    write_json(root / "multiple_testing_audit_summary.json", {"runs": audits,
        "global_search_fdr_controlled": False, "scope": "exploratory_selected_universe"})

    lines = ["# Clue Hunting v0.3 Benchmark Report", "",
        "本报告聚合冻结实验记录，重复生成不会修改源配置、候选或结果。v0.3 当前输出是 NT reference pattern；未接入 perturbation scan、Agent 或 TN。", "",
        "500/1000 基因默认仅进行候选 dry-run。候选数可控、程序完成与统计恢复成功是不同的验收条件；dry-run 的未评估值不代表零阳性。", "",
        "## A. Statistical synthetic validation", ""]
    if statistical:
        lines += _table(["Case", "MFI", "KL gain", "Parametric p", "期望行为通过"], [
            [r.get("case"), r.get("mfi"), r.get("set_level_gain"), r.get("p_gain"), r.get("expectation_met")]
            for r in statistical.get("cases", [])])
        cfg = statistical.get("config", {})
        lines += ["", f"预先指定候选；null draws={_fmt(cfg.get('n_null_simulations'))}，bootstrap={_fmt(cfg.get('n_bootstrap'))}。", ""]
        fpr = statistical.get("false_positive_audit", {})
        for method in ("parametric", "conditional"):
            record = fpr.get(method)
            if record:
                lines.append(f"- {method}: {record['rejections']}/{record['repetitions']} 拒绝；FPR={record['rate']:.3f}，{record.get('ci_level', .95):.0%} Clopper–Pearson CI=[{record['ci_low']:.3f}, {record['ci_high']:.3f}]。")
        lines += ["", "有限重复产生的置信区间较宽，不能据此证明全局 FDR 受控。MFI 与 KL 是同一个 binary table 高阶偏离的不同摘要，不是独立证据；各状态 gain 共享该结构。", ""]
    else:
        lines += ["未运行或尚无 summary.json。", ""]
    lines += ["## B. Search recovery", ""]
    if recovery:
        lines += _table(["Mode/case", "Genes", "候选数", "全部模块 proposal recall", "真实高阶 proposal recall", "高阶跨折 recovery", "其他高阶 proposal 数", "秒"], [
            [r.get("case"), r.get("gene_universe_size"), r.get("unique_candidates_proposed"), r.get("candidate_recall"),
             r.get("true_higher_order_candidate_recall"), r.get("true_higher_order_recovery"), r.get("false_candidate_proposal_count"), r.get("runtime_seconds")]
            for r in recovery.get("cases", [])])
        lines += ["", "其他 candidate proposal 不是 false discovery。搜索没有提议植入组合（search_failure）与可估后统计检验失败不同；小基因池阳性流程不能替代 100 基因搜索覆盖验收。", ""]
        for case in recovery.get("cases", []):
            if case.get("gene_universe_size", 0) >= 100:
                lines.append(f"- {case['case']}: 预定 exploration 任一 fold 命中目标三元组概率={_fmt(case.get('exploration_target_inclusion_probability_any_fold'))}；failure stages={_fmt(case.get('failure_stage_counts'))}。")
        lines += ["", "均匀随机探索预算较小时，纯高阶目标仍可能完全未进入候选集；保留这一负结果，不通过重抽 seed 或阈值调整制造恢复。", ""]
    else:
        lines += ["未运行或尚无 summary.json。", ""]
    lines += ["## C. Scale-up 与候选增长", "", "预定顺序：50 → 100 → 250 完整流程，500 → 1000 dry-run。每个数字汇总 A、B 两方向；generated 标为下界时，不能推断未消费候选总量。", ""]
    for mode in ("synthetic", "real"):
        own = [row for row in scales if row["benchmark_mode"] == mode]
        lines += [f"### {mode}", ""]
        if not own:
            lines += ["未运行或未完成；不计为零候选/零复现。", ""]
            continue
        lines += _table(["Genes", "Dry", "状态", "二阶 proposed/evaluated", "三阶 proposed/evaluated", "四阶 proposed/evaluated", "generated是否下界", "图边数"], [
            [r.get("hvg_pool_size"), r.get("dry_run"), r.get("status"),
             *[f"{_fmt(r.get(f'order{k}_proposed'))}/{_fmt(r.get(f'order{k}_evaluated'))}" for k in (2, 3, 4)],
             any(r.get(f"order{k}_generated_count_is_lower_bound", False) for k in (2, 3, 4)), r.get("selected_graph_edges")]
            for r in own])
        lines += ["", "候选 generated、exploration 概率、图密度、配置 hash 和完整计数保存在 scale_benchmark.csv。", ""]
    lines += ["## D. Pruning 与 bootstrap 工作量", ""]
    if scales:
        lines += _table(["数据/Genes", "Estimability prune", "Gain prune", "Proposal预算 prune下界", "Bootstrap预算 prune", "Gain预算 prune", "实际bootstrap调用含V", "预估调用上界含V", "bootstrap数组上界MiB"], [
            [f"{r['benchmark_mode']}/{r['hvg_pool_size']}", r.get("estimability_pruned"), r.get("gain_pruned"), r.get("proposal_budget_pruned_lower_bound"),
             r.get("bootstrap_budget_pruned"), r.get("gain_calibration_budget_pruned"), r.get("bootstrap_total_gene_set_calls_including_validation"),
             r.get("estimated_bootstrap_gene_set_calls_upper_bound_including_validation"), _memory(r.get("estimated_bootstrap_array_bytes_upper_bound"))]
            for r in scales])
    lines += ["", "bootstrap 按 unique gene set 调用，多个 concrete states 共享。上界仅覆盖未压缩 bootstrap arrays，不是总磁盘预测，未包含未来 null calibration/state-table/CSV。dry-run 的实际调用为未执行工作量，不是稳定性证据。", "",
              "## E. Cross-fold reference qualification", ""]
    if scales:
        lines += _table(["数据/Genes", "2阶跨折", "3阶跨折", "4阶跨折", "3阶双向重发现", "Primary", "Exploratory"], [
            [f"{r['benchmark_mode']}/{r['hvg_pool_size']}", r.get("order2_crossfold_patterns"), r.get("order3_crossfold_patterns"), r.get("order4_crossfold_patterns"),
             r.get("order3_bidirectional_patterns"), r.get("primary_patterns"), r.get("exploratory_patterns")]
            for r in scales])
    lines += ["", "跨折 locked validation 与双向独立重发现分开；随机 cell fold 不是 independent biological replicate。四阶为 exploratory，primary catalogue 的选定候选资格也不等于全局搜索 FDR 保证。", "",
              "## F. Sentinel recovery", ""]
    if sentinels:
        counts = Counter((r["benchmark_mode"], r["hvg_pool_size"], r.get("failure_stage", "unknown")) for r in sentinels)
        lines += _table(["数据", "Genes", "去留阶段", "fold×sentinel 行数"], [list(key) + [value] for key, value in sorted(counts.items(), key=lambda item: str(item[0]))])
        lines += ["", "完整旧 sentinel 的 HVG eligibility、proposal、estimability、MFI/Gain、bootstrap、validation 路径见 sentinel_recovery.csv。Sentinel 仅事后审计，不强制注入候选。dry-run 的统计字段保持未评估。", ""]
    else:
        lines += ["暂无 scale sentinel 结果。", ""]
    lines += ["## G. Resource audit", ""]
    if scales:
        lines += _table(["数据/Genes", "分析秒数", "进程峰值MiB", "已有产物MiB"], [
            [f"{r['benchmark_mode']}/{r['hvg_pool_size']}", r.get("runtime_seconds"), r.get("peak_process_rss_mib"), r.get("disk_usage_mib")]
            for r in scales])
        lines += [""]
    if resources:
        lines += _table(["数据/阶段", "CPU限额核", "容器内存限额MiB", "进程峰值MiB", "cgroup峰值MiB", "wall秒", "exit", "OOM增量", "guard触发"], [
            [f"{r['benchmark_mode']}/{r['stage']}", r["cpu_limit_cores"], r["cgroup_memory_limit_mib"], r["peak_process_rss_mib"], r["peak_cgroup_current_mib"],
             r["wall_seconds"], r["exit_code"], f"oom={_fmt(r['oom_event_delta'])}; kill={_fmt(r['oom_kill_event_delta'])}", r["resource_guard_triggered"]]
            for r in resources])
        lines += ["", "进程 RSS/HWM 与容器 cgroup 内存是不同范围；cgroup 含共享进程及 page cache。OOM 计数缺失不等于没有 OOM；只有观测增量为零才支持本轮未观测到事件。", ""]
    else:
        lines += ["暂无 Linux cgroup 资源记录；不能据此宣称 2GB 容器无 OOM。", ""]
    lines += ["## H. Multiple-testing audit", ""]
    if audits:
        lines += _table(["Run", "Family数", "成员数(MFI/Gain/state)", "生成审计完整", "一致性问题"], [
            [a["run"], a.get("n_families"), a.get("member_counts_by_statistic"), a.get("generation_accounting_complete"), a.get("problems")]
            for a in audits])
    lines += ["", "family 按 role × order × statistic 记录唯一成员和 hash，不按 neighborhood 分别 BH 后合并。BH q 仅是记录的 selected universe 内探索性调整；global_search_fdr_controlled=false。未检验成员的 accounting 占位不构成观测证据。", "",
              "## I. Frozen versions 与运行边界", ""]
    for mode, state in mode_status.items():
        plan, execution = state["plan"], state["execution"]
        lines.append(f"- {mode}: 已汇总阶段={_fmt(state['completed_stages'])}；计划记录禁止真实结果调参={_fmt((plan or {}).get('no_real_result_retuning'))}；执行完整={_fmt((execution or {}).get('complete'))}。")
    for attempt in _read(root / 'prior_attempts.json') or []:
        lines.append(f"- 保留历史尝试 `{attempt.get('path')}`：{attempt.get('reason')}；变更={attempt.get('change')}。")
    lines += ["", "本聚合程序只读取源文件，不改 scientific threshold、exploration fraction、budget 或候选；未执行 perturbation scan、Agent investigation、TN training 或额外生物学解释。源实验若失败或缺失，会明确保留未完成状态。", "",
              "## J. Known limitations", ""]
    lines += [f"- `{flag}`" for flag in sorted(limitations)]
    lines += ["", "不能以阳性数量增加证明方法更好；需要同时审阅 search coverage、合成恢复、跨折复现、estimability、false-positive 行为和资源。500/1000 dry-run 完成不等于千基因完整统计能力已经验证。", ""]
    (root / "BENCHMARK_REPORT.md").write_text("\n".join(lines))
    summary_sources = [root / "statistical" / "summary.json", root / "search_recovery" / "summary.json",
                       root / "scale_synthetic" / "scale_summary.json", root / "scale_real" / "scale_summary.json"]
    summary = dict(report=str(root / "BENCHMARK_REPORT.md"), scale_rows=len(scales), sentinel_rows=len(sentinels),
                   testing_audit_runs=len(audits), resource_records=len(resources), limitations=sorted(limitations),
                   source_summary_hashes={str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
                                          for path in summary_sources if path.is_file()},
                   frozen_source_files_modified=False, global_search_fdr_controlled=False,
                   no_additional_experiments_started=True)
    write_json(root / "report_summary.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default="outputs/clue_hunting_v03_benchmark")
    args = parser.parse_args()
    print(json.dumps(generate_report(args.root), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
