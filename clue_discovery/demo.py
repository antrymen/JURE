"""Run: python -m clue_discovery.demo --output outputs/clue_discovery_demo"""
import argparse
import json
from pathlib import Path
import numpy as np
import pandas as pd
from . import DiscoveryConfig, discover_clues
from .synthetic import GENES, independent, parity, pairwise_only, rare_pattern


def run_demo(output, n_bootstrap=200):
    output = Path(output)
    config = DiscoveryConfig(n_bootstrap=n_bootstrap)
    scenarios = {
        "scenario1_independent": (independent(seed=1), independent(seed=2)),
        "scenario2_pairwise_only": (independent(seed=1), pairwise_only()),
        "scenario3_true_three_way": (independent(seed=1), parity()),
        "scenario4_perturbation_clue": (independent(seed=11), parity(seed=12)),
        "scenario5_rare_pattern": rare_pattern(),
    }
    summaries = []
    for name, (control, perturb) in scenarios.items():
        result = discover_clues(control, perturb, GENES, config=config, perturbation=name)
        result.write(output / name)
        target = result.clues.set_index("pattern_string").loc["A+B-C+"]
        summaries.append({"scenario": name, **target[["status", "control_frequency", "perturb_frequency",
                           "delta_frequency", "q_value_shift", "mfi_control", "mfi_perturb",
                           "q_value_null_perturb", "delta_sign_stability", "mfi_perturb_sign_stability"]].to_dict()})
    for name, strength in (("scenario6_replicated", .6), ("scenario6_opposite_replicate", -.6)):
        c1, c2 = independent(seed=21), independent(seed=23)
        p1, p2 = parity(seed=22), parity(seed=24, strength=strength)
        labels = np.repeat(["Rep1", "Rep2"], [len(c1), len(c2)])
        result = discover_clues(pd.concat([c1, c2]), pd.concat([p1, p2]), GENES, config=config,
                                 replicate_control=labels, replicate_perturb=labels,
                                 discovery_replicate="Rep1", perturbation=name)
        result.write(output / name)
        target = result.clues.set_index("pattern_string").loc["A+B-C+"]
        summaries.append({"scenario": name, **target[["status", "replicate_direction_consistent",
                           "replicate_delta_values", "replicate_mfi_values"]].to_dict()})
    from .io import json_safe
    (output / "scenario_summary.json").write_text(json.dumps(json_safe(summaries), indent=2) + "\n")
    for row in summaries:
        print(f"{row['scenario']}: A+B-C+ -> {row['status']}")
    return summaries


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="outputs/clue_discovery_demo")
    parser.add_argument("--n-bootstrap", type=int, default=200)
    args = parser.parse_args()
    run_demo(args.output, args.n_bootstrap)
