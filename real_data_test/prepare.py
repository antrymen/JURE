"""Verify the fixed source, freeze selection, and export sparse cells x genes inputs."""
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path

import anndata as ad
import numpy as np
import pandas as pd
from scipy import sparse

from clue_discovery import DiscoveryConfig

SOURCE_MD5 = "d8cba17576d1a8afc0f7d71b79cad0f7"
SEED = 20260927


def file_hash(path, algorithm="sha256"):
    digest = hashlib.new(algorithm)
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def checked_counts(matrix):
    matrix = sparse.csr_matrix(matrix)
    data = matrix.data
    if not np.isfinite(data).all() or (data < 0).any() or not (data == np.floor(data)).all():
        raise ValueError("X is not finite nonnegative raw integer counts")
    matrix.eliminate_zeros()
    return matrix


def choose_targets(counts, excluded, seed=SEED):
    rng = np.random.default_rng(seed)
    selected = []
    for lo, hi in ((100, 150), (150, 300), (300, float("inf"))):
        pool = sorted(g for g, n in counts.items() if lo <= n < hi and g not in excluded)
        if len(pool) < 2:
            raise ValueError(f"too few non-heldout targets in count band {lo}–{hi}")
        selected.extend(sorted(rng.choice(pool, 2, replace=False).tolist()))
    return selected


def sample_matched(pool, batches, demand, rng, multiplier=1):
    chosen = []
    for batch, n in sorted(demand.items()):
        candidates = pool[batches[pool] == batch]
        size = int(n) * multiplier
        if len(candidates) < size:
            raise ValueError(f"batch {batch}: need {size} controls, only {len(candidates)} available")
        chosen.extend(rng.choice(candidates, size, replace=False).tolist())
    return np.array(sorted(chosen), dtype=int)


def prepare(source, output, project_root):
    source, output, root = Path(source), Path(output), Path(project_root)
    output.mkdir(parents=True, exist_ok=True)
    if (output / "frozen_manifest.json").exists():
        raise FileExistsError("frozen_manifest.json exists; use the existing frozen inputs")
    actual_md5 = file_hash(source, "md5")
    if actual_md5 != SOURCE_MD5:
        raise ValueError(f"source MD5 mismatch: {actual_md5}")
    expected = json.loads((root / "dataset_audit/replogle_counts.json").read_text())["TabB_K562_day6_library"]
    isolation = json.loads((root / "dataset_audit/combined_audit.json").read_text())
    excluded = sorted({r["canonical"] for r in isolation["rows"]} | set(isolation["aliases"]))
    aliases = isolation["aliases"]
    data = ad.read_h5ad(source, backed="r")
    if not data.obs_names.is_unique or not data.var_names.is_unique:
        raise ValueError("cell IDs and feature names must be unique")
    obs = data.obs.copy()
    if "gene" not in obs or "batch" not in obs or "guide_id" not in obs:
        raise ValueError(f"required source metadata missing; observed columns={list(obs)}")
    if obs[["gene", "batch", "guide_id"]].isna().any().any():
        raise ValueError("missing gene/batch/guide labels")
    labels = obs.gene.astype(str).replace(aliases).to_numpy()
    batches = obs.batch.astype(str).to_numpy()
    control_indices = np.flatnonzero(labels == "non-targeting")
    if len(obs) != expected["total"] or len(control_indices) != expected["control"]:
        raise ValueError("source cell counts do not match Essential day 6 Table S2")
    observed = pd.Series(labels).value_counts().to_dict()
    comparisons = []
    for gene, count in expected["counts"].items():
        canonical = aliases.get(gene, gene)
        comparisons.append({"gene": gene, "canonical": canonical,
                            "expected_cells": count, "observed_cells": observed.get(canonical, 0)})
    reconciliation = pd.DataFrame(comparisons)
    reconciliation.to_csv(output / "target_count_reconciliation.csv", index=False)
    if not (reconciliation.expected_cells == reconciliation.observed_cells).all():
        raise ValueError("target cell-count mismatch against Table S2; inspect reconciliation")
    if "nperts" in obs and not (obs.iloc[control_indices].nperts.to_numpy() == 0).all():
        raise ValueError("control nperts label conflicts with gene label")
    targets = choose_targets({k: v for k, v in observed.items() if k != "non-targeting"}, excluded)
    rng = np.random.default_rng(SEED)
    calibration = np.sort(rng.choice(control_indices, 1000, replace=False))
    test_controls = np.setdiff1d(control_indices, calibration)
    # No perturbation expression is loaded before target and module selection.
    calibration_X = checked_counts(data[calibration, :].X)
    mean = np.asarray(calibration_X.mean(axis=0)).ravel()
    variance = (np.asarray(calibration_X.power(2).mean(axis=0)).ravel() - mean ** 2) * 1000 / 999
    detection = np.asarray((calibration_X > 0).mean(axis=0)).ravel()
    fano = np.divide(variance, mean, out=np.zeros_like(mean), where=mean > 0)
    config = DiscoveryConfig()
    qc = pd.DataFrame({"gene": data.var_names, "detection_rate": detection,
                       "mean_counts": mean, "variance_counts": variance, "fano": fano})
    qc["detection_pass"] = qc.detection_rate.between(config.min_detection_rate, config.max_detection_rate)
    ranking = qc.loc[qc.detection_pass].sort_values(["fano", "gene"], ascending=[False, True])
    if len(ranking) < 12:
        raise ValueError("fewer than 12 calibration-eligible genes")
    module = ranking.head(12).gene.tolist()
    qc["module_selected"] = qc.gene.isin(module)
    qc.to_csv(output / "calibration_gene_qc.csv", index=False)
    # Keep ALL genes in a reusable sparse subset, but discover_clues uses the frozen module.
    selected_rows = np.flatnonzero(np.isin(labels, targets) | (labels == "non-targeting"))
    X = checked_counts(data[selected_rows, :].X)
    selection = obs.iloc[selected_rows].copy()
    selection["perturbation"] = labels[selected_rows]
    selection["source_row"] = selected_rows
    selection["cell_id"] = selection.index.astype(str)
    selection["calibration"] = np.isin(selected_rows, calibration)
    selection["total_counts_measured"] = np.asarray(X.sum(axis=1)).ravel()
    selection["detected_genes_measured"] = X.getnnz(axis=1)
    selection.to_csv(output / "cells.csv", index=False)
    genes = data.var.copy()
    genes.insert(0, "feature_name", genes.index)
    genes.to_csv(output / "genes.csv", index=False)
    sparse.save_npz(output / "counts.npz", X)
    local_row = {int(source_i): i for i, source_i in enumerate(selected_rows)}
    comparisons, memberships = [], []

    def register(name, kind, target, c, p, fraction=1.0, sampling_seed=SEED):
        c, p = np.asarray(c), np.asarray(p)
        if set(c) & set(p) or set(c) & set(calibration) or set(p) & set(calibration):
            raise ValueError("comparison cells overlap or leak calibration cells")
        record = {"run_id": name, "kind": kind, "perturbation": target,
                  "fraction": fraction, "sampling_seed": sampling_seed,
                  "control_rows": [local_row[int(i)] for i in c],
                  "perturb_rows": [local_row[int(i)] for i in p]}
        comparisons.append(record)
        for condition, indices in (("control", c), ("perturb", p)):
            memberships.extend({"run_id": name, "condition": condition, "cell_id": str(obs.index[i])}
                               for i in indices)

    for target in targets:
        pert = np.flatnonzero(labels == target)
        demand = pd.Series(batches[pert]).value_counts().to_dict()
        ctrl = sample_matched(test_controls, batches, demand, rng, multiplier=3)
        register(f"real_{target}_100", "real", target, ctrl, pert)
        for seed in (101, 202, 303):
            # Same seed's 25% sample is nested in its 50% sample.
            sample_rng = np.random.default_rng(seed)
            cp, pp = sample_rng.permutation(ctrl), sample_rng.permutation(pert)
            for fraction in (.5, .25):
                register(f"real_{target}_{int(fraction*100)}_s{seed}", "downsample", target,
                         cp[:int(len(cp)*fraction)], pp[:int(len(pp)*fraction)], fraction, seed)
        pseudo_pert = sample_matched(test_controls, batches, demand, rng)
        pseudo_ctrl = sample_matched(np.setdiff1d(test_controls, pseudo_pert), batches, demand, rng, 3)
        register(f"null_matched_{target}", "null_matched", target, pseudo_ctrl, pseudo_pert)
    for seed in (101, 202, 303):
        permutation = np.random.default_rng(seed).permutation(test_controls)
        split = len(permutation) // 2
        register(f"null_halfsplit_s{seed}", "null_halfsplit", "NT_split",
                 permutation[:split], permutation[split:], sampling_seed=seed)
    pd.DataFrame(memberships).to_csv(output / "comparison_cell_membership.csv.gz", index=False)
    write_json(output / "comparisons.json", comparisons)
    hashes = {str(p.relative_to(root)): file_hash(p) for directory in ("clue_discovery", "real_data_test")
              for p in sorted((root / directory).glob("*.py"))}
    hashes["real_data_test/PROTOCOL.md"] = file_hash(root / "real_data_test/PROTOCOL.md")
    manifest = {"protocol": "Real-data Test v0.1", "source": str(source), "source_md5": actual_md5,
                "source_sha256": file_hash(source), "source_shape": list(data.shape),
                "counts_integer_verified": True, "matrix_used": "X",
                "source_url": "https://zenodo.org/records/13350497/files/ReplogleWeissman2022_K562_essential.h5ad",
                "excluded_perturbations": excluded, "selected_targets": targets,
                "target_cell_counts": {t: int(observed[t]) for t in targets},
                "n_source_controls": len(control_indices), "n_calibration_controls": len(calibration),
                "n_test_controls": len(test_controls), "module_genes": module,
                "n_genes_before_filter": int(data.n_vars), "n_genes_after_calibration_filter": int(qc.detection_pass.sum()),
                "feature_selection": "control calibration only: raw count Fano factor, top 12",
                "n_comparisons": len(comparisons), "algorithm_config": asdict(config), "code_sha256": hashes,
                "cpa_expression_accessed": False, "replication_status": "not_available",
                "counts_npz_sha256": file_hash(output / "counts.npz"),
                "comparisons_sha256": file_hash(output / "comparisons.json")}
    write_json(output / "frozen_manifest.json", manifest)
    data.file.close()
    print(json.dumps({k: manifest[k] for k in ("source_shape", "selected_targets", "target_cell_counts",
                                               "module_genes", "n_comparisons")}, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", default="data/replogle_k562_essential_day6/prepared")
    parser.add_argument("--project-root", default=".")
    args = parser.parse_args()
    prepare(args.source, args.output, args.project_root)
