"""Compatible bottom-up joins. Support-only exploration retains parity interactions."""
from collections import defaultdict
from itertools import combinations, product
from .patterns import JointPattern, merge_patterns
from .statistics import pattern_shift, benjamini_hochberg
from .mfi import calculate_mfi
from .dtuple import dtuple_deviation


def evaluate_pattern(control, perturb, pattern, config, mfi_cache=None):
    cache = {} if mfi_cache is None else mfi_cache
    row = {"genes": pattern.genes, "states": pattern.states, "order": pattern.order,
           "pattern_string": pattern.to_string(), "smoothing_alpha": config.smoothing_alpha,
           "mfi_mode": config.mfi_mode, "null_model": config.null_model}
    row.update(pattern_shift(control, perturb, pattern, config.frequency_epsilon))
    row["support"] = max(row["control_count"], row["perturb_count"])
    for name, matrix in (("control", control), ("perturb", perturb)):
        key = name, pattern.genes
        if key not in cache:
            cache[key] = calculate_mfi(matrix, pattern.genes, config.smoothing_alpha, config.mfi_mode)
        result = cache[key]
        row[f"mfi_{name}"] = result.value
        row[f"raw_state_counts_{name}"] = result.raw_state_counts
        row.update({f"{k}_{name}": v for k, v in dtuple_deviation(
            matrix, pattern, config.epsilon, config.null_model).items()})
    row["mfi_difference"] = row["mfi_perturb"] - row["mfi_control"]
    return row


def should_expand(candidate, thresholds):
    if candidate["support"] < thresholds.min_support:
        return False, "insufficient_support"
    if max(candidate["expected_count_control"], candidate["expected_count_perturb"]) < thresholds.expansion_min_expected:
        return False, "insufficient_expected_count"
    if candidate["p_value_shift"] <= thresholds.expansion_p:
        return True, "shift_signal"
    if min(candidate["p_value_null_control"], candidate["p_value_null_perturb"]) <= thresholds.expansion_p:
        return True, "null_deviation"
    if thresholds.allow_support_only:
        return True, "support_only"
    return False, "no_expansion_signal"


def merge_candidates(patterns, max_candidates=100_000):
    buckets = defaultdict(list)
    for pattern in sorted(set(patterns)):
        for subset in pattern.subpatterns():
            buckets[subset].append(pattern)
    merged = defaultdict(set)
    for bucket in buckets.values():
        for left, right in combinations(bucket, 2):
            child = merge_patterns(left, right)
            if child is not None:
                merged[child].add((left.to_string(), right.to_string()))
                if len(merged) > max_candidates:
                    raise ValueError("candidate budget exceeded; reduce candidate_genes or expansion scope")
    return {p: sorted(parents) for p, parents in sorted(merged.items())}


def adjust_fdr(rows):
    # One family across ALL evaluated orders for each endpoint/condition.
    for suffix in ("shift", "null_control", "null_perturb"):
        q = benjamini_hochberg([r[f"p_value_{suffix}"] for r in rows])
        for row, value in zip(rows, q):
            row[f"q_value_{suffix}"] = float(value)


def search_candidates(control, perturb, config):
    genes = sorted(control.columns)
    if 4 * len(genes) * (len(genes) - 1) // 2 > config.max_candidates:
        raise ValueError("pair candidate budget exceeded; supply a smaller candidate_genes module")
    generation = {JointPattern(g, s): [] for g in combinations(genes, 2)
                  for s in product((0, 1), repeat=2)}
    rows, logs, cache = [], [], {}
    for order in range(2, config.max_order + 1):
        expandable = []
        for pattern, parents in generation.items():
            row = evaluate_pattern(control, perturb, pattern, config, cache)
            rows.append(row)
            expand, reason = should_expand(row, config)
            if order == config.max_order and expand:
                expand, reason = False, "max_order"
            if expand:
                expandable.append(pattern)
            logs.append({"pattern": pattern.to_string(), "genes": pattern.genes,
                         "states": pattern.states, "order": order, "generated_from": parents,
                         "support": row["support"], "expanded": expand,
                         "expanded_or_pruned": "expanded" if expand else "pruned",
                         "reason": reason})
        if order < config.max_order:
            generation = merge_candidates(expandable, config.max_candidates - len(rows))
    adjust_fdr(rows)
    lookup = {JointPattern(r["genes"], r["states"]): r for r in rows}
    subset_keys = ("control_frequency", "perturb_frequency", "control_count", "perturb_count",
                   "delta_frequency", "q_value_shift", "log2_enrichment_control",
                   "log2_enrichment_perturb", "q_value_null_control", "q_value_null_perturb",
                   "mfi_control", "mfi_perturb", "support")
    for pattern, row in lookup.items():
        subsets = [lookup[s] for s in pattern.subpatterns()] if pattern.order > 2 else []
        row["subset_summary"] = [{"pattern": s["pattern_string"], **{k: s[k] for k in subset_keys}}
                                 for s in subsets]
        row["min_subset_support"] = min((s["support"] for s in subsets), default=None)
        row["max_subset_shift"] = max((abs(s["delta_frequency"]) for s in subsets), default=None)
    return rows, logs
