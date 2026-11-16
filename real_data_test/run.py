"""Run the frozen audit without changing the discovery algorithm or thresholds."""
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import json
import math
from pathlib import Path
import time

import numpy as np
import pandas as pd
from scipy import sparse

from clue_discovery import DiscoveryConfig, discover_clues
from .prepare import file_hash, write_json

_STATE = {}


def initialize(prepared, results):
    prepared = Path(prepared)
    manifest = json.loads((prepared / "frozen_manifest.json").read_text())
    genes = pd.read_csv(prepared / "genes.csv").feature_name.tolist()
    module = manifest["module_genes"]
    matrix = sparse.load_npz(prepared / "counts.npz")[:, [genes.index(g) for g in module]].toarray()
    cells = pd.read_csv(prepared / "cells.csv")
    _STATE.update(matrix=matrix, cells=cells, module=module, manifest=manifest, results=Path(results))


def summarize_metrics(table, columns, prefix=""):
    summary = {}
    for column in columns:
        for name, q in (("min", 0), ("q25", .25), ("median", .5), ("q75", .75), ("max", 1)):
            values = pd.to_numeric(table[column], errors="coerce").dropna()
            summary[f"{prefix}{column}_{name}"] = None if values.empty else float(values.quantile(q))
    return summary


def run_one(comparison):
    name = comparison["run_id"]
    folder = _STATE["results"] / name
    completion = folder / "summary.json"
    if completion.exists():
        return json.loads(completion.read_text())
    start = time.monotonic()
    ci, pi = comparison["control_rows"], comparison["perturb_rows"]
    control, perturb = _STATE["matrix"][ci], _STATE["matrix"][pi]
    config = DiscoveryConfig(**_STATE["manifest"]["algorithm_config"])
    result = discover_clues(control, perturb, _STATE["module"], config=config,
                            perturbation=comparison["perturbation"])
    elapsed = time.monotonic() - start
    result.write(folder)
    table = result.clues
    for condition in ("control", "perturb"):
        values = table[f"raw_state_counts_{condition}"]
        table[f"zero_states_{condition}"] = values.map(lambda x: sum(v == 0 for v in x.values()))
        table[f"min_state_count_{condition}"] = values.map(lambda x: min(x.values()))
    table["abs_delta"] = table.delta_frequency.abs()
    table["abs_mfi_control"] = table.mfi_control.abs()
    table["abs_mfi_perturb"] = table.mfi_perturb.abs()
    metrics = ["support", "control_count", "perturb_count", "abs_delta", "mfi_control", "mfi_perturb",
               "delta_sign_stability", "mfi_control_sign_stability", "mfi_perturb_sign_stability",
               "zero_states_control", "zero_states_perturb", "min_state_count_control", "min_state_count_perturb"]
    third = table.query("order == 3")
    candidates = third.query("status == 'candidate_clue'").copy()
    compact = ["pattern_string", "order", "status", "status_reason", "genes", "states", "control_frequency",
               "perturb_frequency", "delta_frequency", "q_value_shift", "q_value_null_control",
               "q_value_null_perturb", "bootstrap_delta_ci_low", "bootstrap_delta_ci_high",
               "higher_order_evidence", "bootstrap_performed", *metrics]
    table[list(dict.fromkeys(compact))].to_csv(folder / "audit_patterns.csv", index=False)
    n_genes = len(result.metadata["retained_genes"])
    theoretical_pairs = 4 * math.comb(n_genes, 2) if n_genes >= 2 else 0
    theoretical_triples = 8 * math.comb(n_genes, 3) if n_genes >= 3 else 0
    summary = {k: comparison[k] for k in ("run_id", "kind", "perturbation", "fraction", "sampling_seed")}
    summary.update(n_control=len(control), n_perturb=len(perturb), n_genes=n_genes,
                   n_pairs=int((table.order == 2).sum()), n_triples=len(third),
                   theoretical_pairs=theoretical_pairs, theoretical_triples=theoretical_triples,
                   triple_search_fraction=len(third) / theoretical_triples if theoretical_triples else None,
                   n_candidates=int((table.status == "candidate_clue").sum()), n_candidates_3=len(candidates),
                   n_bootstrapped=int(table.bootstrap_performed.sum()), elapsed_seconds=elapsed,
                   statuses=table.status.value_counts().to_dict(),
                   triple_statuses=third.status.value_counts().to_dict(),
                   expansion_reasons=result.search_log.query("order == 2").reason.value_counts().to_dict())
    summary.update(summarize_metrics(candidates, metrics, "clue3_"))
    summary["fraction_tested_triples_with_zero_state_perturb"] = float((third.zero_states_perturb > 0).mean()) if len(third) else None
    summary["fraction_clue3_with_zero_state_perturb"] = float((candidates.zero_states_perturb > 0).mean()) if len(candidates) else None
    cells = _STATE["cells"]
    for condition, ix in (("control", ci), ("perturb", pi)):
        selected = cells.iloc[ix]
        for metric in ("total_counts_measured", "detected_genes_measured"):
            summary[f"{condition}_{metric}_median"] = float(selected[metric].median())
        summary[f"{condition}_batch_counts"] = selected.batch.astype(str).value_counts().to_dict()
    cb = cells.iloc[ci].batch.astype(str).value_counts(normalize=True)
    pb = cells.iloc[pi].batch.astype(str).value_counts(normalize=True)
    keys = cb.index.union(pb.index)
    summary["batch_total_variation"] = float((cb.reindex(keys, fill_value=0) - pb.reindex(keys, fill_value=0)).abs().sum() / 2)
    summary["median_umi_ratio"] = summary["perturb_total_counts_measured_median"] / summary["control_total_counts_measured_median"]
    write_json(completion, summary)
    return summary


def run(prepared, results, workers=2, only=None):
    prepared, results = Path(prepared), Path(results)
    manifest = json.loads((prepared / "frozen_manifest.json").read_text())
    root = Path(__file__).resolve().parents[1]
    for relative, expected in manifest["code_sha256"].items():
        if file_hash(root / relative) != expected:
            raise ValueError(f"frozen code changed: {relative}")
    if file_hash(prepared / "comparisons.json") != manifest["comparisons_sha256"]:
        raise ValueError("frozen cell comparisons changed")
    if file_hash(prepared / "counts.npz") != manifest["counts_npz_sha256"]:
        raise ValueError("frozen counts changed")
    results.mkdir(parents=True, exist_ok=True)
    source_manifest = results / "input_manifest.json"
    if source_manifest.exists() and json.loads(source_manifest.read_text()) != manifest:
        raise ValueError("output contains a different frozen run")
    write_json(source_manifest, manifest)
    comparisons = json.loads((prepared / "comparisons.json").read_text())
    if only:
        comparisons = [c for c in comparisons if c["run_id"] in only or c["kind"] in only]
        if not comparisons:
            raise ValueError("no comparisons matched --only")
    with ProcessPoolExecutor(max_workers=workers, initializer=initialize,
                             initargs=(str(prepared), str(results))) as pool:
        futures = {pool.submit(run_one, c): c["run_id"] for c in comparisons}
        for completed in as_completed(futures):
            row = completed.result()
            print(json.dumps({k: row[k] for k in ("run_id", "n_pairs", "n_triples", "n_candidates_3",
                                                   "n_bootstrapped", "elapsed_seconds")}), flush=True)
    summaries = [json.loads(p.read_text()) for p in sorted(results.glob("*/summary.json"))]
    pd.DataFrame([{k: json.dumps(v) if isinstance(v, dict) else v for k, v in s.items()}
                  for s in summaries]).to_csv(results / "run_summary.csv", index=False)
    write_json(results / "execution_status.json", {"completed": len(summaries),
                                                   "expected": manifest["n_comparisons"],
                                                   "complete": len(summaries) == manifest["n_comparisons"]})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared", default="data/replogle_k562_essential_day6/prepared")
    parser.add_argument("--output", default="outputs/real_data_test_v01")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--only", nargs="*")
    args = parser.parse_args()
    run(args.prepared, args.output, args.workers, args.only)
