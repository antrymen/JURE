"""Aggregation preserves frozen sources and keeps dry/missing evidence unknown."""
import hashlib
import json

import pandas as pd

from clue_discovery.v03.artifacts import digest, write_json
from clue_discovery.v03.report import generate_report


def _file_hashes(paths):
    return {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


def _family():
    ids = ["C1", "C2"]
    return {"family_id": "A_discovery:order3:gain", "statistic": "gain",
            "unique_member_ids": ids, "n_members": 2, "member_ids_sha256": digest(ids),
            "global_search_fdr_controlled": False}


def _scale_stage(root, size, dry, *, resource=False):
    directory = root / "scale_real"
    stage = directory / f"genes_{size}_{'dry' if dry else 'full'}"
    stage.mkdir(parents=True)
    manifest = {"crossfold_counts": {"2": 8, "3": 5, "4": 1}, "bidirectional_counts": {"3": 2}}
    write_json(stage / "run_manifest.json", manifest)
    write_json(stage / "multiple_testing_manifest.json", {"families": [_family()],
               "generation_accounting_complete": True, "global_search_fdr_controlled": False})
    pd.DataFrame([{"fold": "A", "genes": '["A","B","C"]', "failure_stage": "not_evaluated" if dry else "replicated",
                   "mfi": 2., "set_level_gain": .1, "p_gain": .01,
                   "min_state_count": 20, "kept_states": 4, "validated_states": 4}]).to_csv(stage / "sentinel_recovery.csv", index=False)
    if resource:
        write_json(directory / f"resources_{size}.json", {"status": "completed", "exit_code": 0,
            "wall_seconds": 12., "resource_guard_triggered": False,
            "peak_process_memory_bytes": 400 * 1024 ** 2, "peak_cgroup_current_bytes": 900 * 1024 ** 2,
            "cgroup_initial": {"memory_max_bytes": 2048 * 1024 ** 2, "cpu_limit_cores": 1.},
            "cgroup_events_delta": {"oom": 0, "oom_kill": 0}})
    return {"hvg_pool_size": size, "dry_run": dry, "status": "complete", "runtime_seconds": 10.,
            "peak_process_rss_mib": 400., "disk_usage_mib": 20., "primary_patterns": 3,
            "exploratory_patterns": 10, "crossfold_triplet_patterns": 5, "bidirectional_triplet_patterns": 2,
            "order2_proposed": 10, "order2_evaluated": 0 if dry else 10,
            "order3_proposed": 20, "order3_evaluated": 0 if dry else 20,
            "order4_proposed": 10, "order4_evaluated": 0 if dry else 10,
            "bootstrap_total_gene_set_calls_including_validation": 0 if dry else 10,
            "estimated_bootstrap_gene_set_calls_upper_bound_including_validation": 512,
            "estimated_bootstrap_array_bytes_upper_bound": 1024 ** 2,
            "path": f"/remote/autodl/task/genes_{size}_{'dry' if dry else 'full'}", "limitations": []}


def test_missing_runs_report_unknown_instead_of_zero_or_success(tmp_path):
    result = generate_report(tmp_path)
    text = (tmp_path / "BENCHMARK_REPORT.md").read_text()
    assert result["scale_rows"] == 0
    assert "real_scale_benchmark_not_run_or_not_completed" in result["limitations"]
    assert "未运行或未完成；不计为零候选/零复现" in text
    assert "不能据此宣称 2GB 容器无 OOM" in text
    assert "global_search_fdr_controlled=false" in text
    assert result["no_additional_experiments_started"]


def test_downloaded_paths_dry_fields_resources_and_source_immutability(tmp_path):
    full = _scale_stage(tmp_path, 50, False, resource=True)
    dry = _scale_stage(tmp_path, 1000, True, resource=True)
    directory = tmp_path / "scale_real"
    write_json(directory / "scale_summary.json", {"completed_stages": 2, "stages": [full, dry]})
    write_json(directory / "execution_status.json", {"complete": True, "no_real_result_retuning": True})
    write_json(directory / "scale_plan_frozen.json", {"no_real_result_retuning": True})
    # Missing event deltas are unknown, never fabricated as no OOM.
    write_json(directory / "preparation_resources.json", {"status": "completed", "exit_code": 0,
        "peak_process_memory_bytes": 500 * 1024 ** 2, "cgroup_events_delta": None})
    source_files = list(directory.rglob("*"))
    source_files = [path for path in source_files if path.is_file()]
    hashes = _file_hashes(source_files)
    result = generate_report(tmp_path)
    assert result["scale_rows"] == 2
    assert result["resource_records"] == 3
    frame = pd.read_csv(tmp_path / "scale_benchmark.csv")
    assert frame.loc[frame.hvg_pool_size == 50, "order3_crossfold_patterns"].iloc[0] == 5
    assert pd.isna(frame.loc[frame.hvg_pool_size == 1000, "order3_crossfold_patterns"].iloc[0])
    assert pd.isna(frame.loc[frame.hvg_pool_size == 1000, "primary_patterns"].iloc[0])
    sentinel = pd.read_csv(tmp_path / "sentinel_recovery.csv")
    assert sentinel.loc[sentinel.hvg_pool_size == 50, "validated_states"].iloc[0] == 4
    assert pd.isna(sentinel.loc[sentinel.hvg_pool_size == 1000, "validated_states"].iloc[0])
    resources = pd.read_csv(tmp_path / "resource_audit.csv")
    assert resources.loc[resources.stage == "50", "peak_cgroup_current_mib"].iloc[0] == 900
    assert pd.isna(resources.loc[resources.stage == "preparation", "no_oom_events_observed"].iloc[0])
    before_report = (tmp_path / "BENCHMARK_REPORT.md").read_bytes()
    generate_report(tmp_path)
    assert before_report == (tmp_path / "BENCHMARK_REPORT.md").read_bytes()
    assert hashes == _file_hashes(source_files)
    assert "cgroup_oom_event_observed" not in result["limitations"]


def test_search_failure_and_testing_hash_inconsistency_are_explicit(tmp_path):
    case = "hybrid"
    directory = tmp_path / "search_recovery" / case
    directory.mkdir(parents=True)
    write_json(tmp_path / "search_recovery" / "summary.json", {"cases": [{"case": case,
        "gene_universe_size": 100, "unique_candidates_proposed": 1500,
        "candidate_recall": .333, "true_higher_order_candidate_recall": 0.,
        "true_higher_order_recovery": 0., "false_candidate_proposal_count": 1000,
        "failure_stage_counts": {"search_failure": 4, "statistical_failure": 1},
        "exploration_target_inclusion_probability_any_fold": .0037}]})
    family = _family()
    family["member_ids_sha256"] = "tampered"
    write_json(directory / "multiple_testing_manifest.json", {"families": [family],
        "global_search_fdr_controlled": False, "generation_accounting_complete": False})
    result = generate_report(tmp_path)
    text = (tmp_path / "BENCHMARK_REPORT.md").read_text()
    assert "pure_higher_order_search_coverage_incomplete" in result["limitations"]
    assert "multiple_testing_audit_missing_or_inconsistent" in result["limitations"]
    assert "search_failure" in text
    assert "小基因池阳性流程不能替代 100 基因搜索覆盖验收" in text
    audit = json.loads((tmp_path / "multiple_testing_audit_summary.json").read_text())
    assert "family_hash_mismatch:A_discovery:order3:gain" in audit["runs"][0]["problems"]
