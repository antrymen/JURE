"""Summarize an already completed v0.2 run without changing calls or FDR families."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd


OLD_TARGETS = ["CDAN1", "NDUFB3", "ELP2", "MCM10", "SRSF11", "TRRAP"]


def read_json(path):
    return json.loads(path.read_text()) if path.exists() else {}


def read_csv(path):
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def numeric(frame, column):
    if column not in frame:
        return pd.Series(np.nan, index=frame.index, dtype=float)
    return pd.to_numeric(frame[column], errors="coerce")


def clean_json(value):
    if isinstance(value, dict):
        return {str(k): clean_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean_json(v) for v in value]
    if isinstance(value, np.generic):
        return clean_json(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def show(value):
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return "NA"
    if isinstance(value, (float, np.floating)):
        if value == 0:
            return "0"
        return f"{value:.3g}"
    return str(value).replace("|", "\\|").replace("\n", " ")


def markdown_table(frame):
    if frame.empty:
        return "无记录。"
    rows = [[show(v) for v in row] for row in frame.itertuples(index=False, name=None)]
    header = [show(c) for c in frame.columns]
    return "\n".join(["| " + " | ".join(header) + " |",
                      "| " + " | ".join(["---"] * len(header)) + " |"]
                     + ["| " + " | ".join(row) + " |" for row in rows])


def gene_set(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return value
    return tuple(sorted(value)) if isinstance(value, (list, tuple)) else str(value)


def unique_gene_sets(frame):
    return len(set(frame.genes.map(gene_set))) if "genes" in frame else 0


def n_targets(frame):
    return int(frame.perturbation.nunique()) if "perturbation" in frame else 0


def quantiles(series):
    series = pd.to_numeric(series, errors="coerce").dropna()
    if series.empty:
        return {key: None for key in ("min", "q25", "median", "q75", "q90", "max")}
    return dict(zip(("min", "q25", "median", "q75", "q90", "max"),
                    map(float, series.quantile([0, .25, .5, .75, .9, 1]).values)))


def nt_test_umi(manifest):
    for name in ("nt_test_median_total_counts", "reference_test_median_total_counts"):
        value = manifest.get(name)
        if isinstance(value, (float, int)) and value > 0:
            return float(value)
    qc = manifest.get("nt_qc", {}).get("test", {})
    value = qc.get("median_total_counts") if isinstance(qc, dict) else None
    return float(value) if isinstance(value, (float, int)) and value > 0 else None


def add_target_qc(shifts, qc):
    frame = shifts.copy()
    target_col = "perturbation" if "perturbation" in qc else "target"
    if target_col in qc:
        fields = [c for c in (target_col, "n_cells", "median_total_counts", "median_detected_genes",
                              "batch_total_variation", "missing_control_batch_cells") if c in qc]
        table = qc[fields].rename(columns={target_col: "perturbation"})
        if table.perturbation.duplicated().any():
            raise ValueError("target_qc must contain one row per perturbation")
        if "perturbation" in frame:
            frame = frame.merge(table, on="perturbation", how="left", validate="many_to_one")
    if "n_cells" not in frame:
        frame["n_cells"] = numeric(frame, "perturb_total_cells")
    else:
        frame["n_cells"] = numeric(frame, "n_cells").fillna(numeric(frame, "perturb_total_cells"))
    return frame


def plot_overview(run, orders, shifts_by_order, top, nulls):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import MaxNLocator

    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                         "axes.spines.top": False, "axes.spines.right": False,
                         "figure.facecolor": "white", "savefig.facecolor": "white",
                         "pdf.fonttype": 42})
    fig, axes = plt.subplots(2, 2, figsize=(15, 10), constrained_layout=True)
    blue, green, orange = "#3269A8", "#14806B", "#CA7436"

    def empty(ax, message):
        ax.text(.5, .5, message, ha="center", va="center", transform=ax.transAxes,
                color="#5D6570", wrap=True)
        ax.set_xticks([])
        ax.set_yticks([])
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)

    def count_axis(ax, values):
        high = max([float(x) for x in values if pd.notna(x)] + [0])
        ax.set_ylim(0, max(1, high * 1.2))
        ax.yaxis.set_major_locator(MaxNLocator(integer=True))
        ax.grid(axis="y", alpha=.18)
        ax.set_axisbelow(True)

    ax = axes[0, 0]
    ax.set_title("A  Reference patterns: discovery and held-out NT", loc="left", weight="bold")
    if orders.empty:
        empty(ax, "No reference candidates evaluated")
    else:
        x = np.arange(len(orders))
        first = numeric(orders, "stable_in_discovery").fillna(0)
        second = numeric(orders, "replicated_in_reference_validation").fillna(0)
        a = ax.bar(x - .18, first, .36, color=blue, label="Stable in discovery")
        b = ax.bar(x + .18, second, .36, color=green, label="Frozen after NT validation")
        ax.bar_label(a, padding=3, fontsize=8)
        ax.bar_label(b, padding=3, fontsize=8)
        ax.set_xticks(x, [str(int(v)) for v in orders.order])
        ax.set_xlabel("Pattern order")
        ax.set_ylabel("Specific binary-state patterns")
        count_axis(ax, list(first) + list(second))
        ax.legend(frameon=False, fontsize=9)

    ax = axes[0, 1]
    ax.set_title("B  Main scan: globally adjusted candidate shifts", loc="left", weight="bold")
    if shifts_by_order.empty:
        empty(ax, "No pattern tests; frozen catalogue is empty")
    else:
        x = np.arange(len(shifts_by_order))
        a = ax.bar(x - .18, shifts_by_order.candidate_shifts, .36, color=blue, label="Target × pattern calls")
        b = ax.bar(x + .18, shifts_by_order.targets_with_candidates, .36, color=orange, label="Distinct targets")
        ax.bar_label(a, padding=3, fontsize=8)
        ax.bar_label(b, padding=3, fontsize=8)
        ax.set_xticks(x, [str(int(v)) for v in shifts_by_order.order])
        ax.set_xlabel("Pattern order")
        ax.set_ylabel("Count (targets may recur across orders)")
        count_axis(ax, list(shifts_by_order.candidate_shifts) + list(shifts_by_order.targets_with_candidates))
        ax.legend(frameon=False, fontsize=9)

    ax = axes[1, 0]
    ax.set_title("C  Largest shifts with adequate observed support", loc="left", weight="bold")
    if top.empty:
        empty(ax, "No candidate passes the display rule:\nperturbation n ≥ 200; each state count ≥ 20")
    else:
        y = np.arange(len(top))
        effect = numeric(top, "delta_frequency").to_numpy() * 100
        lo = numeric(top, "bootstrap_delta_ci_low").to_numpy() * 100
        hi = numeric(top, "bootstrap_delta_ci_high").to_numpy() * 100
        labels = [f"{r.perturbation} | {r.pattern_string}" for r in top.itertuples()]
        for i, (m, low, high, order) in enumerate(zip(effect, lo, hi, top.order)):
            color = green if order >= 3 else blue
            ax.plot([low, high], [i, i], color=color, lw=1.5)
            ax.scatter([m], [i], color=color, s=25, zorder=3)
        ax.axvline(0, color="#91979F", lw=.8)
        ax.set_yticks(y, labels, fontsize=8)
        ax.invert_yaxis()
        ax.set_xlabel("Prevalence difference (percentage points), bootstrap CI")
        ax.grid(axis="x", alpha=.18)

    ax = axes[1, 1]
    ax.set_title("D  Reserved-NT pseudo-perturbation diagnostics", loc="left", weight="bold")
    if nulls.empty:
        empty(ax, "No completed NT diagnostic records")
    else:
        x = np.arange(len(nulls))
        all_calls = numeric(nulls, "n_candidates").fillna(0)
        higher = numeric(nulls, "n_candidates_higher").fillna(0)
        a = ax.bar(x - .18, all_calls, .36, color=blue, label="All orders")
        b = ax.bar(x + .18, higher, .36, color=green, label="Order ≥ 3")
        ax.bar_label(a, padding=3, fontsize=8)
        ax.bar_label(b, padding=3, fontsize=8)
        labels = nulls.run_id.astype(str).tolist() if "run_id" in nulls else list(map(str, x + 1))
        ax.set_xticks(x, labels, rotation=35, ha="right", fontsize=8)
        ax.set_ylabel("Candidate calls per diagnostic family")
        count_axis(ax, list(all_calls) + list(higher))
        ax.legend(frameon=False, fontsize=9)
    fig.suptitle("Replogle K562 Essential — Clue Discovery v0.2\nFrozen reference-state prevalence shifts; exploratory cell-level evidence", fontsize=16)
    fig.savefig(run / "overview.png", dpi=180)
    fig.savefig(run / "overview.pdf")
    plt.close(fig)


def summarize(run_dir):
    run = Path(run_dir)
    manifest = read_json(run / "manifest.json")
    if not manifest:
        raise ValueError("manifest.json is required")
    reference_meta = read_json(run / "reference/reference_metadata.json")
    shift_meta = read_json(run / "testing/shift_metadata.json")
    for relative in ("reference/order_summary.csv", "reference/frozen_reference_catalogue.csv",
                     "testing/perturbation_state_shifts.csv"):
        if not (run / relative).exists():
            raise FileNotFoundError(run / relative)
    orders = read_csv(run / "reference/order_summary.csv")
    catalogue = read_csv(run / "reference/frozen_reference_catalogue.csv")
    shifts = read_csv(run / "testing/perturbation_state_shifts.csv")
    qc = read_csv(run / "target_qc.csv")
    nulls = read_csv(run / "null_diagnostics/summary.csv")
    downsampling = read_csv(run / "downsampling/summary.csv")
    if shift_meta.get("fdr_scope") != "all_perturbations":
        raise ValueError("This report expects the pre-specified all_perturbations FDR family")
    shifts = add_target_qc(shifts, qc)
    shifts["order"] = numeric(shifts, "order")
    catalogue["order"] = numeric(catalogue, "order")
    status = shifts["status"] if "status" in shifts else pd.Series(index=shifts.index, dtype=object)
    candidates = shifts.loc[status.eq("candidate_shift")].copy()
    higher = candidates.loc[candidates.order.ge(3)]
    pairs = candidates.loc[candidates.order.eq(2)]
    cat_higher = catalogue.loc[catalogue.order.ge(3)]
    cat_pairs = catalogue.loc[catalogue.order.eq(2)]
    alpha = manifest.get("config", {}).get("alpha_shift", .05)
    # Calls are read verbatim. The display restriction never alters p/q values or the testing family.
    q_pass = shifts.loc[numeric(shifts, "q_value_shift").le(alpha)]
    eligible = candidates.loc[numeric(candidates, "n_cells").ge(200)
                              & numeric(candidates, "control_count").ge(20)
                              & numeric(candidates, "perturb_count").ge(20)].copy()
    eligible["abs_delta"] = numeric(eligible, "delta_frequency").abs()
    top = eligible.sort_values(["abs_delta", "perturbation", "pattern_string"],
                               ascending=[False, True, True]).head(10) if not eligible.empty else eligible
    order_rows = []
    all_orders = sorted(set(numeric(shifts, "order").dropna().astype(int))
                        | set(numeric(catalogue, "order").dropna().astype(int)))
    for order in all_orders:
        tests = shifts.loc[shifts.order.eq(order)]
        calls = candidates.loc[candidates.order.eq(order)]
        cats = catalogue.loc[catalogue.order.eq(order)]
        order_rows.append(dict(order=order, catalogue_patterns=len(cats),
                               catalogue_gene_sets=unique_gene_sets(cats), tests=len(tests),
                               candidate_shifts=len(calls), targets_with_candidates=n_targets(calls)))
    shifts_by_order = pd.DataFrame(order_rows)
    target_col = "perturbation" if "perturbation" in qc else "target"
    qc_index = qc.set_index(target_col) if target_col in qc else pd.DataFrame()
    old = []
    for target in OLD_TARGETS:
        subset = shifts.loc[shifts.perturbation.eq(target)] if "perturbation" in shifts else shifts.iloc[:0]
        calls = candidates.loc[candidates.perturbation.eq(target)] if "perturbation" in candidates else candidates
        n_cells = qc_index.loc[target, "n_cells"] if target in qc_index.index and "n_cells" in qc_index else (
            numeric(subset, "n_cells").iloc[0] if len(subset) else None)
        old.append(dict(target=target, n_cells=n_cells, n_tests=len(subset),
                        pair_candidates=int(calls.order.eq(2).sum()),
                        higher_candidates=int(calls.order.ge(3).sum()),
                        min_global_q=float(numeric(subset, "q_value_shift").min()) if len(subset) else None,
                        max_abs_delta=float(numeric(calls, "delta_frequency").abs().max()) if len(calls) else None))
    old_frame = pd.DataFrame(old)
    umi = nt_test_umi(manifest)
    risk = dict(candidate_rows_n_perturb_lt_200=int(numeric(candidates, "n_cells").lt(200).sum()),
                candidate_rows_either_state_count_lt_20=int((numeric(candidates, "control_count").lt(20)
                                                           | numeric(candidates, "perturb_count").lt(20)).sum()),
                candidate_rows_missing_n_cells=int(numeric(candidates, "n_cells").isna().sum()),
                target_median_umi=quantiles(numeric(qc, "median_total_counts")),
                candidate_target_median_umi=quantiles(candidates.drop_duplicates("perturbation")["median_total_counts"])
                    if "median_total_counts" in candidates and "perturbation" in candidates else quantiles(pd.Series(dtype=float)),
                nt_test_median_total_counts=umi,
                target_batch_total_variation=quantiles(numeric(qc, "batch_total_variation")),
                candidate_target_batch_total_variation=quantiles(numeric(candidates.drop_duplicates("perturbation"), "batch_total_variation"))
                    if "perturbation" in candidates else quantiles(pd.Series(dtype=float)))
    target_candidates = candidates.drop_duplicates("perturbation") if "perturbation" in candidates else candidates
    risk["candidate_targets_median_umi_below_half_nt"] = (
        int(numeric(target_candidates, "median_total_counts").lt(umi / 2).sum()) if umi is not None else None)
    risk["candidate_targets_with_cells_in_batches_absent_from_control"] = (
        int(numeric(target_candidates, "missing_control_batch_cells").gt(0).sum())
        if "missing_control_batch_cells" in target_candidates else None)
    result = dict(version="0.2.0", source_shape=manifest.get("source_shape"),
                  module_genes=manifest.get("module_genes", []), nt_split_counts=manifest.get("nt_split_counts", {}),
                  n_targets=manifest.get("n_targets", shift_meta.get("n_perturbations")),
                  excluded_perturbations=manifest.get("excluded_perturbations", []),
                  reference_stop_reason=reference_meta.get("stop_reason"),
                  highest_evaluated_order=reference_meta.get("highest_evaluated_order"),
                  n_catalogue_patterns=len(catalogue), n_catalogue_gene_sets=unique_gene_sets(catalogue),
                  n_pair_catalogue_patterns=len(cat_pairs), n_pair_catalogue_gene_sets=unique_gene_sets(cat_pairs),
                  n_higher_catalogue_patterns=len(cat_higher), n_higher_catalogue_gene_sets=unique_gene_sets(cat_higher),
                  n_tests=len(shifts), fdr_scope=shift_meta.get("fdr_scope"), alpha_shift=alpha,
                  n_q_significant_tests=len(q_pass), n_candidate_shifts=len(candidates),
                  n_targets_with_candidates=n_targets(candidates), n_pair_candidate_shifts=len(pairs),
                  n_targets_with_pair_candidates=n_targets(pairs), n_higher_candidate_shifts=len(higher),
                  n_targets_with_higher_candidates=n_targets(higher),
                  n_display_eligible_candidates=len(eligible), order_summary=orders.to_dict("records"),
                  shift_summary_by_order=shifts_by_order.to_dict("records"), old_six_targets=old,
                  risk_audit=risk, top_display_candidates=top.drop(columns=["abs_delta"], errors="ignore").to_dict("records"),
                  null_diagnostics=nulls.to_dict("records"), downsampling=downsampling.to_dict("records"),
                  catalogue_sha256=reference_meta.get("catalogue_sha256"),
                  inference_scope="prevalence shifts of frozen reference states; not interaction-strength changes or biological replication")
    result = clean_json(result)
    (run / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    order_display = orders.rename(columns={"order": "阶数", "candidates_evaluated": "已评价",
                                           "stable_in_discovery": "发现通过", "replicated_in_reference_validation": "冻结模式",
                                           "median_state_table_occupancy": "occupancy中位数",
                                           "expandable_candidates": "可扩展"})
    order_display = order_display[[c for c in ("阶数", "已评价", "发现通过", "冻结模式", "occupancy中位数", "可扩展") if c in order_display]]
    top_display = top.reindex(columns=["perturbation", "pattern_string", "order", "n_cells", "control_count", "perturb_count",
                                      "control_frequency", "perturb_frequency", "delta_frequency", "q_value_shift",
                                      "bootstrap_delta_ci_low", "bootstrap_delta_ci_high", "median_total_counts", "batch_total_variation"])
    text = ["# Replogle K562 Essential：Clue Discovery v0.2 真实数据审计", "",
            f"冻结 reference catalogue 含 **{len(catalogue):,} 个具体状态模式 / {unique_gene_sets(catalogue):,} 个去重 gene sets**，"
            f"其中二阶 {len(cat_pairs):,} 个、≥3 阶 {len(cat_higher):,} 个。主扫描对 {result['n_targets']} 个扰动进行了 {len(shifts):,} 次 target × pattern 检验，"
            f"得到 **{len(candidates):,} 个 candidate shifts，涉及 {n_targets(candidates):,} 个 targets**；"
            f"其中 ≥3 阶 {len(higher):,} 个，涉及 {n_targets(higher):,} 个 targets。", "",
            "这里发现的是**在 NT 中定义并冻结的联合表达状态，在扰动后出现 prevalence shift**。"
            "这不等同于高阶相互作用强度改变、扰动新生 interaction、因果机制或独立生物学重复复现。"
            "`+ / −` 表示检测到 / 未检测到表达；不是相对对照上调 / 下调。", "",
            "## 数据和冻结设计", "",
            f"源矩阵形状：`{manifest.get('source_shape')}`；NT split counts：`{json.dumps(manifest.get('nt_split_counts', {}), ensure_ascii=False)}`。",
            f"发现模块：`{', '.join(manifest.get('module_genes', []))}`。完整协议见 `PROTOCOL.md`，完整参数和排除 targets 见 `manifest.json`。",
            "NT discovery 选择基因和模式，NT validation 原样检验，NT test 只用于最后的 prevalence 比较。"
            "按 GEM batch 分层可平衡技术组成，GEM batch 不构成独立 biological replicate。此次是开发性分析，不是此前从未查看过的 locked benchmark。",
            f"catalogue SHA256：`{reference_meta.get('catalogue_sha256')}`。", "",
            "## 每阶 reference 搜索", "", markdown_table(order_display), "",
            f"停止原因：`{reference_meta.get('stop_reason')}`；最高已评价阶数：`{reference_meta.get('highest_evaluated_order')}`。"
            "此结果仅描述当前 12-gene 模块、样本和阈值，不能解释为普遍的生物学阶数上限。", "",
            "具体状态模式与 gene sets 分开计数：同一 ABC 可以贡献多个二进制状态，这些模式不是独立的生物学机制。", "",
            "## 主扫描与旧六个扰动", "",
            f"BH family 为本次调用的**全部 targets × 全部冻结 patterns**，没有按报告筛选后重算 q。"
            f"全局 q ≤ {alpha} 的检验数为 {len(q_pass):,}；candidate_shift 还必须通过原算法的效应量、支持数和 bootstrap 门槛。",
            "原算法 support 门槛使用两组 count 的较大值，因此出现 candidate_shift 并不保证两组各有 20 个状态细胞。", "",
            markdown_table(shifts_by_order), "", markdown_table(old_frame), "",
            "二阶结果单列，不计入 ≥3 阶 clue 数。旧六个 target 的复查是历史目标上的描述，不能当新独立验证。", "",
            "## 容量、测序深度与技术组成", "",
            f"candidate rows 中扰动 n < 200：**{risk['candidate_rows_n_perturb_lt_200']:,}**；任一组状态支持数 < 20："
            f"**{risk['candidate_rows_either_state_count_lt_20']:,}**。这些数量可能重叠，均保留在全表。",
            f"全部 target 的 median total UMI 分布：`{json.dumps(clean_json(risk['target_median_umi']), ensure_ascii=False)}`。",
            f"有候选的去重 targets 的 median total UMI 分布：`{json.dumps(clean_json(risk['candidate_target_median_umi']), ensure_ascii=False)}`。",
            f"NT test median total UMI：**{show(umi)}**。" + ("未提供该统计，无法从本报告评价相对 NT 的深度变化。" if umi is None else ""),
            f"有候选的 targets 中，median UMI 低于 NT test 一半的数量：**{show(risk['candidate_targets_median_umi_below_half_nt'])}**。"
            "一半仅是描述性深度提示，不用于生成候选或重算 q。",
            f"全部 target 与 NT test 的 batch total variation 分布：`{json.dumps(clean_json(risk['target_batch_total_variation']), ensure_ascii=False)}`。",
            f"有候选的去重 targets 的 batch total variation 分布：`{json.dumps(clean_json(risk['candidate_target_batch_total_variation']), ensure_ascii=False)}`。",
            f"有候选且含 NT test 未覆盖 batch 细胞的 targets：**{show(risk['candidate_targets_with_cells_in_batches_absent_from_control'])}**。",
            "total variation 越接近 0，批次组成越相近；接近 1 表示组成分离。pooled NT test 不是 target-specific matched control。"
            "UMI 深度会改变基因检出概率，低细胞数会增加抽样不确定性；本轮没有在统计模型中校正这些风险，bootstrap 不能消除它们。", "",
            "## 前十条有较充分观察支持的候选", "",
            f"仅用于展示：在既有 candidate_shift 中要求 perturbation n ≥ 200 且两组状态 count 均 ≥ 20，"
            f"共 {len(eligible):,} 条；按 |Δ frequency| 排序取前十。该展示门槛不改变原始候选、q 值或全表。",
            markdown_table(top_display), "",
            "## NT 负对照诊断", "", markdown_table(nulls), "",
            "这些比较复用 reserved NT test cells，组内不重叠但不同诊断可共享细胞。每次 BH family 是该次 catalogue，"
            "与主扫描的完整 targets × patterns family 不同。即使零阳性，也只说明这些抽样下未检出 candidate，不能解释为 FDR = 0，不能证明生物学可复现。", "",
            "## 旧六个扰动的下采样", ""]
    if downsampling.empty:
        text.append("未提供完成的下采样记录；没有据此声称稳定性。")
    else:
        text.extend([f"共有 {len(downsampling)} 条记录，完整结果见 `downsampling/summary.csv`。下表为前 18 条，便于检查输出：", "",
                     markdown_table(downsampling.head(18)), "",
                     "每个 fraction / seed 只更新旧六个 target 的 p 值，其余主分析 p 值保持，再在原完整 family 上做 BH。"
                     "exact-pattern recall 以主分析候选为基线；基线无候选时应为 NA。"
                     "下采样结果属于容量敏感性检查，不能替代独立实验重复。"])
    text.extend(["", "## 文件", "", "- `reference/`：候选、搜索日志、验证、冻结 catalogue、每阶汇总及 metadata。",
                 "- `testing/perturbation_state_shifts.csv`：完整检验表，保留所有 targets、模式和原始 q / status。",
                 "- `target_qc.csv`：每个 target 的细胞数、深度及 batch 组成诊断。",
                 "- `summary.json`：可复用机器汇总；`overview.png` / `overview.pdf`：概览图。", "",
                 "![结果概览](overview.png)", ""])
    (run / "report.md").write_text("\n".join(text))
    plot_overview(run, orders, shifts_by_order, top, nulls)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    args = parser.parse_args()
    result = summarize(args.run_dir)
    print(json.dumps({k: result[k] for k in ("n_catalogue_patterns", "n_higher_catalogue_patterns",
                                           "n_tests", "n_candidate_shifts", "n_higher_candidate_shifts")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
