import numpy as np
from .patterns import JointPattern
from .candidate_search import evaluate_pattern, adjust_fdr


def split_replicates(control, perturb, labels_control, labels_perturb, discovery_replicate):
    if labels_control is None and labels_perturb is None:
        if discovery_replicate is not None:
            raise ValueError("discovery_replicate requires replicate labels")
        return control, perturb, {}, None
    if labels_control is None or labels_perturb is None:
        raise ValueError("both conditions require independent replicate labels")
    for labels, matrix in ((labels_control, control), (labels_perturb, perturb)):
        if len(labels) != len(matrix) or any(not isinstance(x, str) or not x for x in labels):
            raise ValueError("replicate labels must be nonempty strings matching cell rows")
    c, p = np.asarray(labels_control), np.asarray(labels_perturb)
    if set(c) != set(p) or len(set(c)) < 2:
        raise ValueError("at least two matching control/perturb replicate IDs are required")
    if discovery_replicate not in set(c):
        raise ValueError("explicitly choose discovery_replicate from the replicate IDs")
    validation = {str(rep): (control.loc[c == rep], perturb.loc[p == rep])
                  for rep in sorted(set(c)) if rep != discovery_replicate}
    return control.loc[c == discovery_replicate], perturb.loc[p == discovery_replicate], validation, discovery_replicate


def locked_validation(rows, validation, discovery_replicate, config):
    """Only evaluate already accepted discovery clues; never search validation data."""
    locked = [r for r in rows if r["status"] == "candidate_clue"]
    for row in rows:
        row.update({"replication_status": "not_tested" if validation else "not_available",
                    "replicate_direction_consistent": None, "delta_direction_consistent": None,
                    "mfi_direction_consistent": None, "replicate_delta_values": {},
                    "replicate_mfi_values": {}, "replicate_frequency_values": {},
                    "absolute_delta_difference": {}, "replicate_validation": {}})
    if not validation:
        return
    for row in locked:
        rep = discovery_replicate
        row["replicate_delta_values"][rep] = row["delta_frequency"]
        row["replicate_mfi_values"][rep] = {k: row[f"mfi_{k}"] for k in ("control", "perturb")}
        row["replicate_frequency_values"][rep] = {k: row[f"{k}_frequency"] for k in ("control", "perturb")}
    for rep, (control, perturb) in validation.items():
        cache = {}
        checks = [evaluate_pattern(control, perturb, JointPattern(r["genes"], r["states"]), config, cache)
                  for r in locked]
        adjust_fdr(checks)  # separate locked family within each held-out replicate
        for row, check in zip(locked, checks):
            direction = bool(row["delta_frequency"] * check["delta_frequency"] > 0)
            mfi_direction = bool(row["mfi_perturb"] * check["mfi_perturb"] > 0)
            supported = check["support"] >= config.min_support
            row["replicate_delta_values"][rep] = check["delta_frequency"]
            row["replicate_mfi_values"][rep] = {k: check[f"mfi_{k}"] for k in ("control", "perturb")}
            row["replicate_frequency_values"][rep] = {k: check[f"{k}_frequency"] for k in ("control", "perturb")}
            difference = abs(row["delta_frequency"] - check["delta_frequency"])
            row["absolute_delta_difference"][rep] = difference
            row["replicate_validation"][rep] = {**check, "delta_direction_consistent": direction,
                                                 "mfi_direction_consistent": mfi_direction,
                                                 "support_sufficient": supported,
                                                 "absolute_delta_difference": difference}
    for row in locked:
        checks = list(row["replicate_validation"].values())
        same = all(r["delta_direction_consistent"] for r in checks)
        row["replicate_direction_consistent"] = row["delta_direction_consistent"] = same
        row["mfi_direction_consistent"] = all(r["mfi_direction_consistent"] for r in checks)
        passed = same and all(r["support_sufficient"] for r in checks)
        row["replication_status"] = "replicated" if passed else "not_replicated"
        row["status"] = "reproducible_clue" if passed else "not_replicated"
