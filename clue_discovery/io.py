import json
import math
from pathlib import Path
import numpy as np


CLUE_COLUMNS = """perturbation order genes states pattern_string control_frequency perturb_frequency
control_count perturb_count delta_frequency risk_ratio odds_ratio p_value_shift q_value_shift
mfi_control mfi_perturb mfi_difference observed_count_control expected_count_control
log2_enrichment_control q_value_null_control observed_count_perturb expected_count_perturb
log2_enrichment_perturb q_value_null_perturb min_subset_support max_subset_shift subset_summary
bootstrap_delta_median bootstrap_delta_ci_low bootstrap_delta_ci_high delta_sign_stability
mfi_control_sign_stability mfi_perturb_sign_stability replicate_delta_values replicate_mfi_values
replicate_direction_consistent status status_reason smoothing_alpha raw_state_counts_control
raw_state_counts_perturb replication_status bootstrap_performed""".split()
SEARCH_COLUMNS = "pattern genes states order generated_from support expanded expanded_or_pruned reason".split()


def json_safe(value):
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, np.ndarray)):
        return [json_safe(v) for v in value]
    if isinstance(value, np.generic):
        return json_safe(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None if math.isnan(value) else ("Infinity" if value > 0 else "-Infinity")
    return value


def write_results(result, output_dir):
    folder = Path(output_dir)
    folder.mkdir(parents=True, exist_ok=True)
    for filename, table in (("clues.csv", result.clues), ("candidate_search_log.csv", result.search_log),
                             ("gene_qc.csv", result.gene_qc)):
        table = table.copy()
        for col in table:
            table[col] = table[col].map(lambda value: json.dumps(json_safe(value), ensure_ascii=False, allow_nan=False)
                                        if isinstance(value, (dict, list, tuple)) else value)
        table.to_csv(folder / filename, index=False)
    (folder / "run_metadata.json").write_text(json.dumps(json_safe(result.metadata), indent=2,
                                                        ensure_ascii=False, allow_nan=False) + "\n")
    return folder
