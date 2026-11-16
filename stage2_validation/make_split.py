"""Create a deterministic, mutually exclusive Day 6 A/B cell split.

This step uses metadata only. It does not read expression values, discover
states, test shifts, or inspect validation outcomes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd


SPLIT_VERSION = "stage2_day6_ab_v1"
DEFAULT_SEED = "jure-stage2-day6-heldout-v1"
STRATA = ["scan_target", "batch", "guide_id"]


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def keyed_hash(seed: str, *values: object) -> str:
    payload = "\x1f".join([seed, *(str(value) for value in values)])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def assign_folds(frame: pd.DataFrame, seed: str) -> pd.DataFrame:
    required = {"cell_id", "source_row", *STRATA}
    if not required.issubset(frame.columns):
        raise ValueError(f"missing columns: {sorted(required - set(frame.columns))}")
    if frame.cell_id.duplicated().any() or frame.source_row.duplicated().any():
        raise ValueError("cell_id and source_row must be unique")
    if frame[list(required)].isna().any().any():
        raise ValueError("split fields cannot contain missing values")

    parts: list[pd.DataFrame] = []
    for key, group in frame.groupby(STRATA, sort=True, observed=True):
        group = group.copy()
        group["_rank"] = [keyed_hash(seed, "cell", cell_id) for cell_id in group.cell_id]
        group = group.sort_values(["_rank", "cell_id"], kind="mergesort")
        start = int(keyed_hash(seed, "stratum", *key), 16) % 2
        group["fold"] = ["A" if (position + start) % 2 == 0 else "B"
                         for position in range(len(group))]
        parts.append(group.drop(columns="_rank"))

    result = pd.concat(parts, ignore_index=True).sort_values("source_row", kind="mergesort")
    result.insert(0, "split_version", SPLIT_VERSION)
    result.insert(1, "split_seed", seed)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--seed", default=DEFAULT_SEED)
    args = parser.parse_args()

    source = Path(args.metadata).resolve()
    output = Path(args.output_dir).resolve()
    output.mkdir(parents=True, exist_ok=False)
    frame = pd.read_csv(source)
    assigned = assign_folds(frame, args.seed)

    assignment_path = output / "cell_fold_assignment.csv.gz"
    assigned.to_csv(assignment_path, index=False, compression="gzip")

    by_fold = assigned.groupby("fold", observed=True).size().to_dict()
    by_type = (assigned.assign(cell_type=assigned.scan_target.eq("non-targeting")
                               .map({True: "NT", False: "perturbation"}))
               .groupby(["cell_type", "fold"], observed=True).size()
               .unstack(fill_value=0))
    strata_counts = assigned.groupby(STRATA + ["fold"], observed=True).size().unstack(fill_value=0)
    target_counts = assigned.groupby(["scan_target", "fold"], observed=True).size().unstack(fill_value=0)
    target_counts.to_csv(output / "target_fold_counts.csv")
    strata_counts.to_csv(output / "stratum_fold_counts.csv.gz", compression="gzip")

    imbalance = (strata_counts.get("A", 0) - strata_counts.get("B", 0)).abs()
    manifest = {
        "split_version": SPLIT_VERSION,
        "purpose": "Frozen metadata-only split for future Stage 2 held-out validation",
        "seed": args.seed,
        "method": "Within each scan_target x batch x guide_id stratum, rank cells by seeded SHA-256 and alternate A/B; seeded stratum hash chooses the odd-cell remainder fold.",
        "stratification": STRATA,
        "source_metadata": str(source),
        "source_metadata_sha256": sha256_file(source),
        "assignment_sha256": sha256_file(assignment_path),
        "n_cells": int(len(assigned)),
        "fold_counts": {key: int(value) for key, value in by_fold.items()},
        "cell_type_fold_counts": {
            row: {column: int(by_type.loc[row, column]) for column in by_type.columns}
            for row in by_type.index
        },
        "n_targets_including_nt": int(assigned.scan_target.nunique()),
        "n_perturbation_targets": int(assigned.scan_target.nunique() - 1),
        "n_batches": int(assigned.batch.nunique()),
        "n_guides": int(assigned.guide_id.nunique()),
        "n_strata": int(len(strata_counts)),
        "max_absolute_stratum_imbalance": int(imbalance.max()),
        "mutually_exclusive": bool(not assigned.cell_id.duplicated().any()),
        "expression_accessed": False,
        "candidate_results_accessed_for_assignment": False,
        "validation_performed": False,
    }
    (output / "SPLIT_MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    )


if __name__ == "__main__":
    main()
