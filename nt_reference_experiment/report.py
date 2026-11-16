"""Report a completed NT two-fold experiment without altering any decision."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd


def _json(path: Path) -> dict:
    return json.loads(path.read_text())


def _csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path)


def _number(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame:
        return pd.Series(np.nan, index=frame.index, dtype=float)
    return pd.to_numeric(frame[column], errors="coerce")


def _flag(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame:
        return pd.Series(False, index=frame.index, dtype=bool)
    values = frame[column]
    if values.dtype == bool:
        return values
    return values.astype(str).str.lower().isin(["true", "1"])


def _safe(value):
    if isinstance(value, dict):
        return {str(k): _safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(v) for v in value]
    if isinstance(value, np.generic):
        return _safe(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _show(value) -> str:
    if value is None or (isinstance(value, (float, np.floating)) and not math.isfinite(value)):
        return "NA"
    if isinstance(value, (float, np.floating)):
        return f"{value:.4g}"
    return str(value).replace("|", "\\|").replace("\n", " ")


def _md(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "无记录。"
    return "\n".join(
        ["| " + " | ".join(map(_show, frame.columns)) + " |",
         "| " + " | ".join(["---"] * len(frame.columns)) + " |"]
        + ["| " + " | ".join(map(_show, row)) + " |"
           for row in frame.itertuples(index=False, name=None)]
    )


def _genes(value):
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            parsed = value
    else:
        parsed = value
    return tuple(sorted(parsed)) if isinstance(parsed, (tuple, list)) else str(parsed)


def _gene_count(frame):
    return len(set(frame.genes.map(_genes))) if "genes" in frame else 0


def _median(values):
    values = pd.to_numeric(values, errors="coerce").dropna()
    return float(values.median()) if len(values) else None


def _support_bins(values):
    return pd.cut(values, bins=[-1, 0, 4, 9, 19, np.inf],
                  labels=["0", "1–4", "5–9", "10–19", "≥20"])


def _plot(run, counts, agreement, discovery_tables, title):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import MaxNLocator

    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                         "axes.spines.top": False, "axes.spines.right": False,
                         "figure.facecolor": "white", "savefig.facecolor": "white",
                         "pdf.fonttype": 42})
    fig, axes = plt.subplots(2, 2, figsize=(14, 10), constrained_layout=True)
    blue, green, orange = "#3269A8", "#14806B", "#CA7436"

    def empty(ax, message):
        ax.text(.5, .5, message, transform=ax.transAxes, ha="center", va="center",
                color="#59616B", wrap=True)
        ax.set(xticks=[], yticks=[], xlim=(0, 1), ylim=(0, 1))

    ax = axes[0, 0]
    ax.set_title("A  Locked-state reproducibility", loc="left", weight="bold")
    if counts.empty:
        empty(ax, "No patterns evaluated")
    else:
        x = np.arange(len(counts))
        for offset, column, color, label in [
            (-.25, "within_fold_stable_patterns", blue, "Within-fold stable"),
            (0, "cross_fold_replicated_patterns", green, "Cross-fold replicated"),
            (.25, "bidirectionally_rediscovered_patterns", orange, "Bidirectionally rediscovered")]:
            bars = ax.bar(x + offset, counts[column], .24, color=color, label=label)
            ax.bar_label(bars, padding=2, fontsize=7)
        ax.set_xticks(x, [f"{r.direction}\nk={int(r.order)}" for r in counts.itertuples()])
        ax.set_ylabel("Specific binary-state patterns")
        high = max(float(counts[c].max()) for c in ["within_fold_stable_patterns",
                    "cross_fold_replicated_patterns", "bidirectionally_rediscovered_patterns"])
        ax.set_ylim(0, max(1, high * 1.3))
        ax.yaxis.set_major_locator(MaxNLocator(integer=True))
        ax.grid(axis="y", alpha=.15)
        ax.set_axisbelow(True)
        ax.legend(frameon=False, fontsize=8)

    ax = axes[0, 1]
    ax.set_title("B  Higher-order MFI in locked validation", loc="left", weight="bold")
    higher = agreement.loc[_number(agreement, "order") >= 3]
    if higher.empty:
        empty(ax, "No locked order ≥ 3 gene sets")
    else:
        for order, color in [(3, blue), (4, orange)]:
            part = higher.loc[higher.order == order]
            if not part.empty:
                ax.scatter(part.mfi_discovery, part.mfi_validation, color=color,
                           s=29, alpha=.7, label=f"Order {order}")
        lim = max(float(np.nanmax(np.abs(higher[["mfi_discovery", "mfi_validation"]]))), .1) * 1.1
        ax.plot([-lim, lim], [-lim, lim], ls="--", lw=.8, color="#999999")
        ax.axhline(0, lw=.7, color="#999999")
        ax.axvline(0, lw=.7, color="#999999")
        ax.set(xlim=(-lim, lim), ylim=(-lim, lim), xlabel="Discovery MFI", ylabel="Validation MFI")
        ax.legend(frameon=False, fontsize=9)
        ax.text(.02, .98, "One point per direction × gene set", transform=ax.transAxes,
                va="top", fontsize=8, color="#59616B")

    ax = axes[1, 0]
    ax.set_title("C  Full-table rare states and MFI precision", loc="left", weight="bold")
    eligible = discovery_tables.loc[_number(discovery_tables, "order") >= 3].copy()
    eligible["ci_width"] = (_number(eligible, "mfi_bootstrap_ci_high")
                            - _number(eligible, "mfi_bootstrap_ci_low"))
    eligible = eligible.loc[eligible.ci_width.notna()]
    if eligible.empty:
        empty(ax, "No bootstrapped order ≥ 3 discovery gene sets")
    else:
        for order, color in [(3, blue), (4, orange)]:
            part = eligible.loc[eligible.order == order]
            if not part.empty:
                ax.scatter(part.min_state_count, part.ci_width, s=23, color=color,
                           alpha=.65, label=f"Order {order}")
        ax.set_xscale("symlog", linthresh=1)
        ax.set(xlabel="Minimum count across all 2^k states (symlog)",
               ylabel="Bootstrap MFI CI width")
        ax.legend(frameon=False, fontsize=9)
        ax.grid(alpha=.15)

    ax = axes[1, 1]
    ax.set_title("D  Complete discovery state-table support", loc="left", weight="bold")
    if discovery_tables.empty:
        empty(ax, "No discovery gene-set tables")
    else:
        buckets = ["0", "1–4", "5–9", "10–19", "≥20"]
        colors = ["#963B4B", "#CA7436", "#DCA96C", "#9CA9B7", "#14806B"]
        orders = sorted(discovery_tables.order.unique())
        x = np.arange(len(orders))
        base = np.zeros(len(orders))
        bins = _support_bins(_number(discovery_tables, "min_state_count"))
        for label, color in zip(buckets, colors):
            values = np.array([int(((discovery_tables.order == order) & (bins == label)).sum())
                               for order in orders])
            ax.bar(x, values, bottom=base, width=.55, color=color, label=label)
            base += values
        ax.set_xticks(x, [f"Order {int(order)}" for order in orders])
        ax.set_ylabel("Discovery-fold × gene-set tables")
        ax.set_ylim(0, max(1, float(max(base, default=0)) * 1.15))
        ax.yaxis.set_major_locator(MaxNLocator(integer=True))
        ax.legend(title="Minimum state count", frameon=False, fontsize=8, ncol=2)
    fig.suptitle(title + "\nNT-only two-fold reference experiment; marginal MFI", fontsize=15)
    fig.savefig(run / "overview.png", dpi=180)
    fig.savefig(run / "overview.pdf")
    plt.close(fig)


def _audit(metadata, tables):
    """Check recorded invariants, without recomputing statistical decisions."""
    if metadata.get("cell_ids_overlap") != 0:
        raise ValueError("metadata must confirm zero overlap between NT folds")
    if metadata.get("both_discoveries_frozen_before_validation") is not True:
        raise ValueError("both discovery catalogues must be frozen before validation")
    if metadata.get("validation_search_performed") is not False:
        raise ValueError("locked validation must not perform a new search")
    families = metadata["bh_families"]
    for role, frame in tables.items():
        ids = frame.reference_id.astype(str).tolist()
        if len(ids) != len(set(ids)):
            raise ValueError(f"duplicate pattern identities in {role}")
        family = families[role]
        if family["n_tests"] != len(ids) or set(family["reference_ids"]) != set(ids):
            raise ValueError(f"BH family does not match evaluated patterns in {role}")
    for source, validation in [("A_discovery", "B_validation_from_A"),
                               ("B_discovery", "A_validation_from_B")]:
        expected = set(tables[source].loc[_flag(tables[source], "stable_in_discovery"), "reference_id"])
        observed = set(tables[validation].reference_id)
        if expected != observed:
            raise ValueError(f"locked validation differs from discovery shortlist: {source}")
    return dict(cell_ids_overlap=0, both_discoveries_frozen_before_validation=True,
                validation_search_performed=False, locked_candidate_id_sets_match=True,
                all_four_bh_families_match_recorded_rows=True)


def _direction_tables(tables, estimates, cross, orders):
    counts, mfi_counts, agreement = [], [], []
    for direction, source, validation, flag in [
        ("A→B", "A_discovery", "B_validation_from_A", "A_to_B_replicated"),
        ("B→A", "B_discovery", "A_validation_from_B", "B_to_A_replicated")]:
        discovery = tables[source]
        checks = tables[validation]
        for order in orders:
            d = discovery.loc[_number(discovery, "order") == order]
            v = checks.loc[_number(checks, "order") == order]
            c = cross.loc[_number(cross, "order") == order]
            stable = d.loc[_flag(d, "stable_in_discovery")]
            passed = v.loc[_flag(v, "replicated_in_reference_validation")]
            bidir = c.loc[_flag(c, "bidirectionally_rediscovered")]
            counts.append(dict(direction=direction, order=order, evaluated_patterns=len(d),
                within_fold_stable_patterns=len(stable), within_fold_stable_gene_sets=_gene_count(stable),
                cross_fold_replicated_patterns=len(passed), cross_fold_replicated_gene_sets=_gene_count(passed),
                bidirectionally_rediscovered_patterns=len(bidir),
                bidirectionally_rediscovered_gene_sets=_gene_count(bidir)))
            e = estimates.loc[(estimates.evaluation_role == source) & (estimates.order == order)]
            mfi_pass = v.loc[_flag(v, "mfi_only_cross_fold_replicated")]
            mfi_counts.append(dict(direction=direction, order=order, evaluated_gene_sets=len(e),
                bootstrapped_gene_sets=int(_flag(e, "bootstrap_performed").sum()),
                within_fold_mfi_stable_gene_sets=int(_flag(e, "mfi_only_stable").sum()),
                locked_validation_gene_sets=_gene_count(v),
                locked_cross_fold_mfi_replicated_gene_sets=_gene_count(mfi_pass)))
        left = estimates.loc[estimates.evaluation_role == source, ["gene_set_id", "genes", "order", "mfi"]]
        right = estimates.loc[estimates.evaluation_role == validation,
                              ["gene_set_id", "mfi", "mfi_only_stable"]]
        joined = left.merge(right, on="gene_set_id", suffixes=("_discovery", "_validation"),
                            validate="one_to_one")
        joined["direction"] = direction
        agreement.append(joined)
    return pd.DataFrame(counts), pd.DataFrame(mfi_counts), pd.concat(agreement, ignore_index=True)


def _estimability_summaries(discovery):
    bucket_rows, association_rows, order_rows = [], [], []
    discovery = discovery.copy()
    discovery["ci_width"] = (_number(discovery, "mfi_bootstrap_ci_high")
                              - _number(discovery, "mfi_bootstrap_ci_low"))
    discovery["support_bin"] = _support_bins(_number(discovery, "min_state_count"))
    for (role, order), group in discovery.groupby(["evaluation_role", "order"], sort=True):
        n = len(group)
        boot = group.loc[_flag(group, "bootstrap_performed")]
        order_rows.append(dict(fold=role.split("_")[0], order=int(order), gene_sets=n,
            bootstrapped=len(boot), mfi_only_stable=int(_flag(group, "mfi_only_stable").sum()),
            with_zero_state=int((_number(group, "zero_state_count") > 0).sum()),
            min_state_below_5=int((_number(group, "min_state_count") < 5).sum()),
            min_state_below_20=int((_number(group, "min_state_count") < 20).sum()),
            median_min_state_count=_median(group.min_state_count), median_mfi_ci_width=_median(group.ci_width)))
        if int(order) >= 3:
            for bucket, part in group.groupby("support_bin", observed=True, sort=False):
                b = part.loc[_flag(part, "bootstrap_performed")]
                bucket_rows.append(dict(fold=role.split("_")[0], order=int(order), min_state_count_bin=str(bucket),
                    gene_sets=len(part), bootstrapped=len(b), mfi_only_stable=int(_flag(part, "mfi_only_stable").sum()),
                    median_ci_width=_median(b.ci_width),
                    median_sign_stability=_median(_number(b, "mfi_bootstrap_sign_stability"))))
            row = dict(fold=role.split("_")[0], order=int(order), bootstrapped_gene_sets=len(boot))
            for metric, column in [("rho_min_count_vs_ci_width", "ci_width"),
                                   ("rho_min_count_vs_sign_stability", "mfi_bootstrap_sign_stability")]:
                pair = boot[["min_state_count", column]].dropna()
                row[metric] = (float(pair.min_state_count.corr(pair[column], method="spearman"))
                    if len(pair) >= 3 and pair.min_state_count.nunique() > 1 and pair[column].nunique() > 1 else None)
            association_rows.append(row)
    return (pd.DataFrame(order_rows), pd.DataFrame(bucket_rows), pd.DataFrame(association_rows))


def summarize(run_dir):
    run = Path(run_dir)
    manifest = _json(run / "nt_fold_manifest.json")
    execution = _json(run / "execution_status.json")
    if execution.get("complete") is not True:
        raise ValueError("cannot report an incomplete or failed experiment")
    if execution.get("run_role") != manifest.get("run_role"):
        raise ValueError("execution status run_role must match the fold manifest")
    metadata = _json(run / "nt_reference_metadata.json")
    synthetic = manifest.get("run_role") == "synthetic_validation"
    if manifest.get("run_role") not in {"synthetic_validation", "development_nt_twofold"}:
        raise ValueError("unknown run_role; report must distinguish synthetic and real data")
    filenames = dict(A_discovery="fold_A_discovery.csv", B_discovery="fold_B_discovery.csv",
                     B_validation_from_A="fold_B_validation.csv", A_validation_from_B="fold_A_validation.csv")
    tables = {role: _csv(run / filename) for role, filename in filenames.items()}
    cross = _csv(run / "cross_fold_summary.csv")
    estimates = _csv(run / "state_table_estimability.csv")
    provided_orders = _csv(run / "order_reproducibility_summary.csv")
    checks = _audit(metadata, tables)
    if cross.reference_id.duplicated().any():
        raise ValueError("cross_fold_summary must have one row per unique pattern")
    if estimates.duplicated(["evaluation_role", "gene_set_id"]).any():
        raise ValueError("estimability must have one row per role and gene set")
    max_order = int(metadata["config"]["max_order"])
    orders = list(range(2, max_order + 1))
    counts, mfi_counts, agreement = _direction_tables(tables, estimates, cross, orders)
    discovery = estimates.loc[estimates.evaluation_role.isin(["A_discovery", "B_discovery"])].copy()
    estimability, bins, associations = _estimability_summaries(discovery)
    union_rows = []
    for order in orders:
        c = cross.loc[_number(cross, "order") == order]
        row = dict(order=order)
        for level in ["within_fold_stable", "cross_fold_replicated", "bidirectionally_rediscovered"]:
            passed = c.loc[_flag(c, level)]
            row[level + "_patterns"] = len(passed)
            row[level + "_gene_sets"] = _gene_count(passed)
            supplied = provided_orders.loc[provided_orders.order == order]
            if len(supplied) != 1 or int(supplied.iloc[0][level]) != len(passed):
                raise ValueError("order summary does not agree with cross-fold pattern counts")
        union_rows.append(row)
    union = pd.DataFrame(union_rows)
    q_results = {}
    for order, name in [(3, "Q1_three_way"), (4, "Q2_four_way")]:
        part = union.loc[union.order == order]
        record = part.iloc[0].to_dict() if len(part) else dict(order=order, evaluated=False)
        direction = mfi_counts.loc[mfi_counts.order == order]
        record["directions"] = direction.to_dict(orient="records")
        record["interpretation_scope"] = "synthetic_code_validation_only" if synthetic else "internal_development_nt_cells_only"
        q_results[name] = record
    family_rows = []
    for role, family in metadata["bh_families"].items():
        family_rows.append(dict(evaluation_role=role, n_tests=family["n_tests"],
                                statistic=family["statistic"], scope=family["scope"]))
    families = pd.DataFrame(family_rows)
    summary = dict(run_role=manifest["run_role"], synthetic=synthetic,
        dataset=manifest.get("dataset"), n_cells=metadata["n_cells"], module_genes=metadata["candidate_genes"],
        config=metadata["config"], checks=checks, questions=q_results,
        direction_pattern_counts=counts.to_dict(orient="records"),
        union_pattern_counts=union.to_dict(orient="records"),
        mfi_gene_set_counts=mfi_counts.to_dict(orient="records"),
        discovery_estimability=estimability.to_dict(orient="records"),
        rare_state_support_bins=bins.to_dict(orient="records"),
        descriptive_rank_associations=associations.to_dict(orient="records"),
        bh_families=families.to_dict(orient="records"), mfi_fdr_controlled=metadata["mfi_fdr_controlled"],
        union_fdr_controlled=metadata["union_fdr_controlled"],
        conclusion_scope="synthetic validation is not biological evidence" if synthetic else metadata["validation_scope"])
    (run / "summary.json").write_text(json.dumps(_safe(summary), ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    title = ("SYNTHETIC VALIDATION — not a real-data result" if synthetic
             else "NT higher-order reference — development experiment")
    _plot(run, counts, agreement, discovery, title)
    _write_report(run, manifest, metadata, summary, counts, union, mfi_counts,
                  estimability, bins, associations, families, cross)
    return summary


def _write_report(run, manifest, metadata, summary, counts, union, mfi_counts,
                  estimability, bins, associations, families, cross):
    synthetic = summary["synthetic"]
    config = metadata["config"]
    title = "NT two-fold 合成数据验证报告" if synthetic else "NT two-fold 开发实验报告"
    scope = ("**这是合成数据上的代码验证，不是 Replogle K562 的真实结果。以下计数仅用于检查搜索、锁定验证、报告及空结果路径，不能回答真实 NT 是否存在可复现高阶结构。**"
             if synthetic else
             "本轮只使用 NT cells，检验同一数据集内互斥细胞的高阶结构复现；结果属于开发实验，不能称为两个独立生物学重复或从未查看过的最终 benchmark。")
    answers = []
    for order, label in [(3, "Q1 · 三阶"), (4, "Q2 · 四阶")]:
        part = union.loc[union.order == order]
        if part.empty:
            answers.append(f"**{label}：**本次配置未评估该阶数。")
            continue
        r = part.iloc[0]
        m = mfi_counts.loc[mfi_counts.order == order]
        total_evaluated = int(m.evaluated_gene_sets.sum())
        detail = "；".join(f"{x.direction} 的 MFI-only locked 复现 {int(x.locked_cross_fold_mfi_replicated_gene_sets)}/{int(x.locked_validation_gene_sets)} 组"
                          for x in m.itertuples())
        prefix = "合成演示中，" if synthetic else "本轮中，"
        if total_evaluated == 0:
            statement = f"{prefix}没有候选进入该阶评估，不能据此判断该阶 MFI 是否可估。"
        else:
            statement = (f"{prefix}跨方向合并去重后，完整 pattern 跨 fold 通过 "
                f"{int(r.cross_fold_replicated_patterns)} 个状态 / {int(r.cross_fold_replicated_gene_sets)} 个 gene sets，"
                f"双向独立重发现 {int(r.bidirectionally_rediscovered_patterns)} 个状态 / "
                f"{int(r.bidirectionally_rediscovered_gene_sets)} 个 gene sets。{detail}。")
        if not synthetic and int(r.cross_fold_replicated_patterns) == 0 and total_evaluated:
            statement += "因此当前固定模块及门槛下没有得到可进入后续调查的该阶 reference pattern；这不等于总体不存在该阶结构。"
        answers.append(f"**{label}：**{statement}")
    q3 = ("**Q3 · rare-state support：**按每个 discovery fold 的独立 gene set 汇总完整状态表，"
          "报告最小格数、低支持状态比例、MFI CI 宽度与符号稳定性。下表和相关系数只作描述，"
          "未设定新的 min_state_count≥20 准入门槛，也不证明稀有状态是唯一原因。")
    if synthetic:
        q3 += "合成样本中的关系不能外推至真实 NT。"
    module_rows = [dict(fold=fold, cells=metadata["n_cells"][fold],
                       module_genes=", ".join(metadata["candidate_genes"][fold])) for fold in ["A", "B"]]
    union_display = union.rename(columns={"order": "阶数", "within_fold_stable_patterns": "任一fold稳定状态",
        "within_fold_stable_gene_sets": "任一fold稳定基因组", "cross_fold_replicated_patterns": "跨fold状态",
        "cross_fold_replicated_gene_sets": "跨fold基因组", "bidirectionally_rediscovered_patterns": "双向重发现状态",
        "bidirectionally_rediscovered_gene_sets": "双向重发现基因组"})
    direction_display = counts[["direction", "order", "evaluated_patterns", "within_fold_stable_patterns",
        "within_fold_stable_gene_sets", "cross_fold_replicated_patterns", "cross_fold_replicated_gene_sets"]].rename(columns={
        "direction": "方向", "order": "阶数", "evaluated_patterns": "搜索评估状态",
        "within_fold_stable_patterns": "发现稳定状态", "within_fold_stable_gene_sets": "发现稳定基因组",
        "cross_fold_replicated_patterns": "locked通过状态", "cross_fold_replicated_gene_sets": "locked通过基因组"})
    mfi_display = mfi_counts.rename(columns={"direction": "方向", "order": "阶数",
        "evaluated_gene_sets": "发现评估基因组", "bootstrapped_gene_sets": "完成bootstrap",
        "within_fold_mfi_stable_gene_sets": "fold内MFI稳定",
        "locked_validation_gene_sets": "进入locked验证",
        "locked_cross_fold_mfi_replicated_gene_sets": "locked MFI复现"})
    sparse_display = estimability.rename(columns={"fold": "fold", "order": "阶数", "gene_sets": "基因组数",
        "bootstrapped": "完成bootstrap", "mfi_only_stable": "MFI稳定", "with_zero_state": "含零格",
        "min_state_below_5": "最小格<5", "min_state_below_20": "最小格<20",
        "median_min_state_count": "最小格中位数", "median_mfi_ci_width": "CI宽度中位数"})
    bin_display = bins.rename(columns={"fold": "fold", "order": "阶数", "min_state_count_bin": "最小格分箱",
        "gene_sets": "基因组数", "bootstrapped": "完成bootstrap", "mfi_only_stable": "MFI稳定",
        "median_ci_width": "CI宽度中位数", "median_sign_stability": "符号稳定性中位数"})
    association_display = associations.rename(columns={"order": "阶数", "bootstrapped_gene_sets": "完成bootstrap",
        "rho_min_count_vs_ci_width": "ρ(最小格,CI宽度)",
        "rho_min_count_vs_sign_stability": "ρ(最小格,符号稳定性)"})
    family_display = families[["evaluation_role", "n_tests"]].rename(columns={"evaluation_role": "角色", "n_tests": "BH family大小"})
    higher = cross.loc[(_number(cross, "order") >= 3) & _flag(cross, "cross_fold_replicated")]
    examples = higher.sort_values(["order", "reference_id"]).head(12)
    examples = examples[[c for c in ["reference_id", "order", "pattern_string", "A_to_B_replicated",
                                     "B_to_A_replicated", "bidirectionally_rediscovered"] if c in examples]]
    dataset = manifest.get("dataset", "未提供")
    n_boot = config["n_bootstrap"]
    prose = [f"# {title}", scope, f"数据标识：`{dataset}`。实验角色：`{manifest['run_role']}`。",
        *answers, q3, "## 预先固定的实验设计", _md(pd.DataFrame(module_rows)),
        f"按 GEM batch 分层划分（合成演示若使用模拟分层，则以 manifest 为准）。A/B cell IDs 零重叠；"
        "两个方向均在本 fold 内选择模块及搜索，两个候选目录先冻结，再分别读取对侧 fold 做 locked validation。"
        "验证不重新挑基因、状态或门槛。两个方向共享这两批细胞，不能当成两次独立复制。",
        f"本次 max_order={config['max_order']}，每次 bootstrap={n_boot}，marginal MFI，"
        f"smoothing α={config['smoothing_alpha']}。bootstrap 不增加新细胞。"
        "当前 Fano baseline、搜索和完整 pattern gate 保持固定；代码及软件版本、seed、冻结目录摘要见两个 metadata JSON。",
        "## 三种复现强度", 
        "`within_fold_stable` 是沿用 v0.2 的完整 pattern gate：包含 MFI、状态支持数、富集及 BH q 值等条件，"
        "不等同于仅 MFI bootstrap 稳定。`cross_fold_replicated` 表示至少一个方向的同一 locked 状态在对侧通过完整 gate，"
        "且 MFI 同号。`bidirectionally_rediscovered` 要求完全相同 genes+states 在两 fold 独立发现，并在两方向均通过。",
        _md(union_display), "上表跨方向按相同 canonical genes+states 去重；基因组数再按 genes 去重。双向重发现是更强标签，未作为所有 reference 的必需条件。",
        _md(direction_display),
        "## MFI-only 结果", _md(mfi_display),
        f"MFI-only 保持已有 table-quality gate、|MFI|≥{config['min_abs_mfi']}、"
        f"bootstrap sign stability≥{config['min_sign_stability']} 与 CI 排除 0；不含状态富集、状态支持数和 BH q gate。"
        "locked MFI 复现列只统计完整 pattern discovery shortlist 所涉及的 gene sets；没有对所有 MFI-only 稳定组合另做验证搜索。",
        "另外保存 λ=1−sign stability 以及严格 λ<0.05 的诊断标志。后者不替换当前≥0.95的门槛；边界 λ=0.05 时两种表述并不等价。",
        "## 完整状态表的可估计性", _md(sparse_display),
        "这些计数以 discovery fold × gene set 为单位，每个组合只计一次，不因多个 d-tuples 重复，也不叠加 locked-validation 行。"
        "未通过已有 table-quality gate 的组合仍保存完整状态表，但不强行补算 bootstrap；对应 CI 和符号稳定性缺失，不能当作 0 或稳定。",
        "### 三、四阶的 rare-state 分箱", _md(bin_display),
        "### 分 fold、分阶数的描述性 Spearman 相关", _md(association_display),
        "相关仅使用有 bootstrap 的 gene sets，且是经过搜索与质量门槛选择后的描述统计；不报告显著性或因果结论。"
        "样本不足或变量无变化时记为 NA。两个 fold 可能选择不同模块，相关系数之间不构成独立重复证据。",
        "## 搜索范围与误差控制", _md(family_display),
        "四个 BH family 分别记录，discovery 包含该方向所有实际评估的状态及阶数；validation 包含来自对侧的所有 locked 状态，包括失败项。"
        "BH 校正的是 plug-in independence null 下的状态富集，**不是 MFI 的搜索后总体 FDR**。"
        "MFI bootstrap 区间为逐组合区间；跨方向取并集亦没有新的统一 FDR 保证。",
        f"停止原因：A=`{metadata['stop_reason']['A']}`，B=`{metadata['stop_reason']['B']}`。未根据验证结果改变扩展规则或追求更高阶。",
        "## 高阶 locked 复现状态示例", _md(examples),
        "仅按 order、reference_id 确定展示顺序，最多 12 行；完整结果保留在 cross_fold_summary.csv，没有因展示规则删除或重新校正结果。",
        "## 审计与结果文件",
        "报告已检查：A/B ID 零重叠的运行记录、两侧目录均先冻结、validation 无搜索、locked IDs 与对侧 discovery shortlist 一致、四个 BH family 与实际行一致。"
        "这些检查验证产物的一致性；模块只使用本 fold 的保证还依赖 runner、代码测试及 provenance，不能仅凭 CSV 推断。",
        "- `nt_fold_manifest.json`：数据/模块/运行角色与 provenance。\n"
        "- `nt_reference_metadata.json`：阈值、seed、BH families、冻结目录、代码 hash。\n"
        "- `fold_A_discovery.csv` / `fold_B_discovery.csv`：各自的完整搜索记录。\n"
        "- `fold_B_validation.csv` / `fold_A_validation.csv`：对侧锁定候选的验证。\n"
        "- `cross_fold_summary.csv` / `order_reproducibility_summary.csv`：状态与阶数汇总。\n"
        "- `state_table_estimability.csv` / `mfi_bootstrap_distributions.npz`：完整状态表与可追溯 bootstrap 分布。\n"
        "- `summary.json` / `overview.png` / `overview.pdf`：机器可读汇总与科学图。",
        "本轮没有 perturbation 分析，也没有机制、TN、Agent 或 CPA 推断。" ]
    (run / "REPORT.md").write_text("\n\n".join(prose) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args()
    summary = summarize(args.run_dir)
    print(json.dumps({"report": str((args.run_dir / "REPORT.md").resolve()),
                      "run_role": summary["run_role"], "questions": summary["questions"]},
                     ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
