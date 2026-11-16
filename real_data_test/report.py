"""Summarize the frozen real-data runs and create a standalone audit figure."""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


def recovery_metrics(baseline, sample):
    baseline = baseline.query("order == 3 and status == 'candidate_clue'").copy()
    sample_all = sample.query("order == 3").set_index("pattern_string")
    selected = sample_all.query("status == 'candidate_clue'")
    full = set(baseline.pattern_string)
    recovered = full & set(selected.index)
    top = baseline.assign(abs_delta=baseline.delta_frequency.abs()).sort_values(
        ["abs_delta", "pattern_string"], ascending=[False, True]).head(20)
    top_set = set(top.pattern_string)
    shared = baseline.set_index("pattern_string").join(sample_all[["delta_frequency"]], rsuffix="_down", how="inner")
    return {"baseline_clues": len(full), "downsample_clues": len(selected),
            "recovered_clues": len(recovered), "exact_pattern_recall": len(recovered) / len(full) if full else None,
            "jaccard": len(recovered) / len(full | set(selected.index)) if full | set(selected.index) else None,
            "baseline_patterns_still_searched": len(full & set(sample_all.index)),
            "direction_consistent_fraction": float((shared.delta_frequency * shared.delta_frequency_down > 0).mean()) if len(shared) else None,
            "top_effect_n": len(top_set), "top_effect_recovered": len(top_set & set(selected.index)),
            "top_effect_recall": len(top_set & set(selected.index)) / len(top_set) if top_set else None}


def report(results):
    results = Path(results)
    manifest = json.loads((results / "input_manifest.json").read_text())
    summaries = [json.loads(p.read_text()) for p in sorted(results.glob("*/summary.json"))]
    if len(summaries) != manifest["n_comparisons"]:
        raise ValueError("audit incomplete; all pre-specified runs must finish before final report")
    summary = pd.DataFrame(summaries)
    tables = {s["run_id"]: pd.read_csv(results / s["run_id"] / "audit_patterns.csv") for s in summaries}
    candidates = []
    for s in summaries:
        frame = tables[s["run_id"]].query("order == 3 and status == 'candidate_clue'").copy()
        for col in ("run_id", "kind", "perturbation", "fraction", "sampling_seed"):
            frame.insert(0, col, s[col])
        candidates.append(frame)
    all_candidates = pd.concat(candidates, ignore_index=True)
    all_candidates.to_csv(results / "third_order_candidates.csv", index=False)
    recovery = []
    for s in summaries:
        if s["kind"] != "downsample":
            continue
        full_name = f"real_{s['perturbation']}_100"
        recovery.append({k: s[k] for k in ("run_id", "perturbation", "fraction", "sampling_seed")} |
                        recovery_metrics(tables[full_name], tables[s["run_id"]]))
    recovery = pd.DataFrame(recovery)
    recovery.to_csv(results / "downsample_recovery.csv", index=False)
    baseline = summary.query("kind == 'real'").sort_values("n_perturb")
    null = summary.loc[summary.kind.str.startswith("null")].copy()
    null.to_csv(results / "negative_control_summary.csv", index=False)
    from .prepare import write_json
    audit = {"baseline_three_way_clues": dict(zip(baseline.perturbation, baseline.n_candidates_3.astype(int))),
             "null_run_count": len(null), "null_runs_with_any_three_way_clue": int((null.n_candidates_3 > 0).sum()),
             "null_total_three_way_clues": int(null.n_candidates_3.sum()),
             "all_runs_complete": True, "algorithm_changed": False,
             "median_triple_search_fraction": float(summary.triple_search_fraction.median()),
             "downsample_median_recall": {str(f): float(g.exact_pattern_recall.median()) if g.exact_pattern_recall.notna().any() else None
                                            for f, g in recovery.groupby("fraction")}}
    write_json(results / "audit_summary.json", audit)
    lines = ["# Real-data Test v0.1：Replogle K562 Essential day 6", "",
             f"已完成 {len(summaries)} 次预注册比较，算法代码和默认阈值保持冻结，bootstrap=200。CPA 未参与。",
             "", "## 数据与选择", "",
             f"源数据：{manifest['source_shape'][0]:,} cells × {manifest['source_shape'][1]:,} genes。官方 MD5 已匹配：`{manifest['source_md5']}`。",
             f"NT 共 {manifest['n_source_controls']:,} cells；其中 1,000 cells 只作 calibration，{manifest['n_test_controls']:,} cells 用于检验。",
             f"Calibration detection filtering 后 {manifest['n_genes_after_calibration_filter']:,} genes；固定 module 为 12 genes：`{', '.join(manifest['module_genes'])}`。",
             "目标仅按细胞数量分层随机选取，不按响应或 clue 选择。真实比较的 control 依 GEM group 匹配，随机拆分/下采样均不称为独立实验重复。",
             "", "## 基线结果", "", "| Perturbation | Pert cells | Ctrl cells | Genes | 2-point tested | 3-point tested | 3-way clues | Bootstrap shortlist | Seconds |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for r in baseline.itertuples():
        lines.append(f"| {r.perturbation} | {r.n_perturb} | {r.n_control} | {r.n_genes} | {r.n_pairs} | {r.n_triples} | {r.n_candidates_3} | {r.n_bootstrapped} | {r.elapsed_seconds:.1f} |")
    lines += ["", f"所有比较的三阶搜索比例中位数为 {audit['median_triple_search_fraction']:.1%}（相对于过滤后基因的全部三阶 binary patterns）。",
              "小 module 的完整搜索上界是 264 二阶 + 1,760 三阶；module 限制与 bottom-up 剪枝分开报告。", "",
              "## Control split 负对照", "", "| Run | Ctrl cells | Pseudo-pert cells | 3-way clues | UMI median ratio | Batch TV |",
              "|---|---:|---:|---:|---:|---:|"]
    for r in null.itertuples():
        lines.append(f"| {r.run_id} | {r.n_control} | {r.n_perturb} | {r.n_candidates_3} | {r.median_umi_ratio:.3f} | {r.batch_total_variation:.3f} |")
    lines += ["", f"{audit['null_run_count']} 次负对照中，{audit['null_runs_with_any_three_way_clue']} 次出现至少一个三阶候选，总计 {audit['null_total_three_way_clues']} 个候选。",
              "这些随机 split 有细胞复用，不能视为独立生物学重复，也不足以估计精确全局 FDR。", "",
              "## 下采样找回率", "", "| Perturbation | Fraction | Median exact recall | Range | Median top-20 recall |",
              "|---|---:|---:|---|---:|"]
    def pct(value):
        return "NA" if pd.isna(value) else f"{value:.1%}"
    for (target, fraction), group in recovery.groupby(["perturbation", "fraction"]):
        values = group.exact_pattern_recall
        lines.append(f"| {target} | {fraction:.0%} | {pct(values.median())} | {pct(values.min())}–{pct(values.max())} | {pct(group.top_effect_recall.median())} |")
    lines += ["", "找回必须是相同 genes/states 再次通过 candidate_clue 判定；方向保持、是否进入搜索、Jaccard 单独见 downsample_recovery.csv。基线无候选时 recall=NA。", "",
              "## 证据分布与限制", "",
              "run_summary.csv 包含三阶候选 support、Delta、MFI、bootstrap stability 的 min/q25/median/q75/max；third_order_candidates.csv 保留逐模式证据；每个 run 仍保留全量 clues 和搜索日志。",
              "额外列出零 joint-state 个数、最小 joint-state support、UMI/检测基因数中位数和 batch 构成差异，以识别平滑或测序深度驱动的风险。support 在 v0.1 中是两组计数的最大值，不能解读为每组都有 20 cells。",
              "本轮不将统计候选升级为机制解释。Independence-null 不严格排除 pairwise 解释，marginal MFI 不是条件因果交互；cell-level Fisher / bootstrap 也不处理全部混合细胞状态和生物学重复变异。",
              "", "## 复现文件", "",
              "prepared/ 中有 counts.npz、cells.csv、genes.csv、comparisons.json、comparison_cell_membership.csv.gz、frozen_manifest.json。manifest 固定来源、基因/细胞选择、config 和脚本 SHA256。",
              "[官方数据版本](https://zenodo.org/records/13350497)；[作者原始发布](https://doi.org/10.25452/figshare.plus.20029387)。", ""]
    (results / "audit_report.md").write_text("\n".join(lines))
    make_plot(results, summary, recovery, all_candidates)
    print(json.dumps(audit, indent=2))


def make_plot(results, summary, recovery, candidates):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                         "axes.spines.top": False, "axes.spines.right": False})
    fig, axes = plt.subplots(2, 2, figsize=(13, 8.2), layout="constrained")
    base = summary.query("kind == 'real'").sort_values("n_perturb")
    axes[0, 0].bar(base.perturbation, base.n_candidates_3, color="#257e92")
    axes[0, 0].set(title="Three-way candidates at 100% cells", ylabel="Candidate patterns")
    axes[0, 0].tick_params(axis="x", rotation=30)
    n = summary.loc[summary.kind.str.startswith("null")]
    axes[0, 1].bar(range(len(n)), n.n_candidates_3, color="#b97744")
    axes[0, 1].set(title="NT vs NT sanity checks", xlabel="Pre-specified control split", ylabel="Three-way candidates")
    axes[0, 1].set_xticks(range(len(n)), [str(i+1) for i in range(len(n))])
    for target, group in recovery.groupby("perturbation"):
        agg = group.groupby("fraction").exact_pattern_recall.agg(["median", "min", "max"])
        if agg["median"].notna().any():
            x = np.array([.25, .5, 1.])
            y = np.r_[agg.reindex([.25, .5])["median"], 1.]
            axes[1, 0].plot(x*100, y, "o-", label=target)
    axes[1, 0].set(title="Exact-pattern recovery (median of 3 draws)", xlabel="Cells retained (%)", ylabel="Recall of baseline candidates", ylim=(-.02, 1.03))
    axes[1, 0].legend(fontsize=8, frameon=False, ncol=2)
    real = candidates.query("kind == 'real'")
    if len(real):
        scatter = axes[1, 1].scatter(real.perturb_count, real.delta_frequency.abs(),
                                    c=real.mfi_perturb.abs(), s=14, alpha=.65, cmap="viridis")
        fig.colorbar(scatter, ax=axes[1, 1], label="|MFI perturbation|")
    else:
        axes[1, 1].text(.5, .5, "No baseline three-way candidates", ha="center", transform=axes[1, 1].transAxes)
    axes[1, 1].set(title="Baseline evidence distribution", xlabel="Perturbation pattern-support cells", ylabel="|Delta frequency|")
    fig.suptitle("Clue Discovery v0.1 · Replogle K562 Essential day 6", fontsize=16)
    fig.savefig(results / "audit_overview.png", dpi=180)
    fig.savefig(results / "audit_overview.pdf")
    plt.close(fig)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", default="outputs/real_data_test_v01")
    report(parser.parse_args().results)
