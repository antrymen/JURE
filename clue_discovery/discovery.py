from dataclasses import dataclass, asdict
import platform
import numpy as np
import pandas as pd
import scipy
from scipy import sparse
from .config import DiscoveryConfig
from .preprocessing import encode_binary_states
from .patterns import JointPattern
from .candidate_search import search_candidates
from .bootstrap import bootstrap_pattern, higher_order_evidence
from .replication import split_replicates, locked_validation


BOOTSTRAP_COLUMNS = [f"bootstrap_{key}_{metric}"
                     for key in ("delta", "mfi_control", "mfi_perturb", "mfi_difference",
                                 "log2_enrichment_control", "log2_enrichment_perturb")
                     for metric in ("median", "ci_low", "ci_high")] + [
    f"{key}_sign_stability" for key in ("delta", "mfi_control", "mfi_perturb", "mfi_difference",
                                      "log2_enrichment_control", "log2_enrichment_perturb")]


@dataclass
class DiscoveryResult:
    clues: pd.DataFrame
    search_log: pd.DataFrame
    gene_qc: pd.DataFrame
    metadata: dict

    def write(self, output_dir):
        from .io import write_results
        return write_results(self, output_dir)


def _select_input(X, names, selected):
    if len(X.shape) != 2 or X.shape[1] != len(names):
        raise ValueError("matrix columns must match gene_names")
    if isinstance(X, pd.DataFrame):
        if list(X.columns) != names:
            raise ValueError("DataFrame column order must exactly match gene_names")
        return X.loc[:, selected]
    indices = [names.index(g) for g in selected]
    return X.tocsr()[:, indices] if sparse.issparse(X) else np.asarray(X)[:, indices]


def discover_clues(X_control, X_perturb, gene_names, *, config=None,
                   candidate_genes=None, replicate_control=None, replicate_perturb=None,
                   discovery_replicate=None, perturbation="perturbation"):
    config = DiscoveryConfig() if config is None else config
    names = list(gene_names)
    if not names or len(set(names)) != len(names) or any(not isinstance(g, str) or not g for g in names):
        raise ValueError("gene_names must be unique nonempty strings")
    selected = names if candidate_genes is None else list(candidate_genes)
    if not selected or len(set(selected)) != len(selected) or not set(selected) <= set(names):
        raise ValueError("candidate_genes must be a nonempty unique subset of gene_names")
    matrices = []
    for matrix in (X_control, X_perturb):
        matrix = _select_input(matrix, names, selected)
        encoded, _ = encode_binary_states(matrix, config.threshold, gene_names=selected,
                                           input_kind=config.input_kind)
        matrices.append(encoded)
    control, perturb, validation, discovery_id = split_replicates(
        *matrices, replicate_control, replicate_perturb, discovery_replicate)
    # Filtering is fitted ONLY on discovery cells, separately in each condition.
    qc_rows, keep = [], []
    for gene in sorted(selected):
        rates = [float(m[gene].mean()) for m in (control, perturb)]
        retained = any(config.min_detection_rate <= r <= config.max_detection_rate for r in rates)
        if retained:
            keep.append(gene)
        for condition, matrix, rate in zip(("control", "perturb"), (control, perturb), rates):
            count = int(matrix[gene].sum())
            qc_rows.append({"gene": gene, "condition": condition, "replicate": discovery_id,
                            "detection_rate": rate, "number_detected": count,
                            "number_undetected": len(matrix) - count, "retained": retained,
                            "reason": "retained" if retained else "detection_rate_filter"})
    control, perturb = control[keep], perturb[keep]
    validation = {rep: (c[keep], p[keep]) for rep, (c, p) in validation.items()}
    rows, logs = search_candidates(control, perturb, config)
    rng = np.random.default_rng(config.random_seed)
    for row in rows:
        row.update({k: None for k in BOOTSTRAP_COLUMNS})
        row.update({"perturbation": perturbation, "discovery_replicate": discovery_id,
                    "bootstrap_performed": False, "bootstrap_distributions": {},
                    "higher_order_evidence": False})
        if row["support"] < config.min_support:
            row["status"], row["status_reason"] = "insufficient_support", "insufficient_support"
            continue
        if abs(row["delta_frequency"]) < config.min_delta or row["q_value_shift"] > config.alpha_shift:
            row["status"], row["status_reason"] = "screened_out", "insufficient_shift"
            continue
        promising = any(abs(row[f"mfi_{name}"]) >= config.min_abs_mfi
                        and row[f"q_value_null_{name}"] <= config.alpha_null
                        for name in ("control", "perturb"))
        if not promising:
            row["status"], row["status_reason"] = "screened_out", "insufficient_interaction_evidence"
            continue
        row.update(bootstrap_pattern(control, perturb, JointPattern(row["genes"], row["states"]), config, rng))
        row["higher_order_evidence"] = higher_order_evidence(row, config)
        delta_stable = row["delta_sign_stability"] >= config.min_sign_stability
        row["status"] = "candidate_clue" if delta_stable and row["higher_order_evidence"] else "unstable"
        row["status_reason"] = "passed_discovery" if row["status"] == "candidate_clue" else "bootstrap_instability"
    locked_validation(rows, validation, discovery_id, config)
    for row in rows:
        if row["status"] == "not_replicated":
            row["status_reason"] = "validation_direction_or_support_failed"
        elif row["status"] == "reproducible_clue":
            row["status_reason"] = "passed_locked_validation"
    from .io import CLUE_COLUMNS, SEARCH_COLUMNS
    clues = pd.DataFrame(rows).reindex(columns=list(dict.fromkeys(CLUE_COLUMNS + [k for r in rows for k in r])))
    log = pd.DataFrame(logs, columns=SEARCH_COLUMNS)
    metadata = {"version": "0.1.0", "config": asdict(config), "perturbation": perturbation,
                "discovery_replicate": discovery_id, "validation_replicates": sorted(validation),
                "discovery_control_cells": len(control), "discovery_perturb_cells": len(perturb),
                "retained_genes": keep, "tested_patterns": len(rows),
                "bootstrap_patterns": sum(r["bootstrap_performed"] for r in rows),
                "fdr_families": "all evaluated orders; shift, null_control, null_perturb separately",
                "inference_scope": "exploratory adaptive search; plug-in independence null",
                "replication_rule": "all held-out replicates: nonzero same shift sign and sufficient support",
                "environment": {"python": platform.python_version(), "numpy": np.__version__,
                                "scipy": scipy.__version__, "pandas": pd.__version__}}
    return DiscoveryResult(clues, log, pd.DataFrame(qc_rows), metadata)
