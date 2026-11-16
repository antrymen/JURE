"""Contract tests against real baseline and reference-guided pipeline outputs."""
from copy import deepcopy
from itertools import product
import json

import numpy as np
import pandas as pd
import pytest

from clue_discovery import DiscoveryConfig, discover_clues
from clue_discovery.v02 import (
    FrozenCatalogue, Population, ReferenceConfig, fit_reference, test_perturbations,
)
from jure.casefile.adapters import clue_from_v01, clue_from_v02
from jure.casefile.models import ClueRecord


def _population(prefix, *, uniform=False):
    states = np.array(list(product((0, 1), repeat=3)), dtype=np.uint8)
    counts = np.full(8, 250) if uniform else np.where(states.sum(axis=1) % 2 == 0, 400, 100)
    matrix = np.repeat(states, counts, axis=0)
    return Population(matrix, tuple("ABC"), tuple(f"{prefix}:{i}" for i in range(len(matrix))))


@pytest.fixture(scope="module")
def v02_result():
    discovery, validation, control = [_population(name) for name in ("d", "v", "t")]
    reference = fit_reference(discovery, validation, control, candidate_genes=tuple("ABC"),
                              config=ReferenceConfig(max_order=3, n_bootstrap=40))
    shifts = test_perturbations(reference.catalogue, control, {"KO": _population("p", uniform=True)})
    return reference, shifts


@pytest.fixture(scope="module")
def v01_result():
    return discover_clues(_population("c", uniform=True).matrix, _population("p").matrix,
                          list("ABC"), config=DiscoveryConfig(max_order=3, n_bootstrap=40),
                          perturbation="KO")


def _v02(row, **kwargs):
    return clue_from_v02(row, source_run_id="reference-run", source_artifact="shifts.csv", **kwargs)


def _v01(row, **kwargs):
    return clue_from_v01(row, source_run_id="baseline-run", source_artifact="clues.csv", **kwargs)


def test_actual_v02_shift_preserves_distinct_statistical_populations(v02_result):
    reference, shifts = v02_result
    row = shifts.shifts.iloc[0]
    clue = _v02(row, catalogue=reference.catalogue, source_metadata=shifts.metadata)
    record = next(item for item in reference.catalogue.payload["records"]
                  if item["reference_id"] == row.reference_id)
    assert clue.discovery_mode == "reference_guided"
    assert clue.source_schema_version == "0.2.0"
    assert clue.catalogue_sha256 == reference.catalogue.sha256
    assert clue.legacy_control is None and clue.legacy_perturbation is None
    assert clue.reference_evidence.discovery.mfi == row.reference_mfi
    assert clue.reference_evidence.validation.mfi == row.validation_mfi
    assert clue.reference_evidence.discovery.q_value_null == record["q_value_null"]
    assert clue.reference_evidence.discovery.expected_count == record["expected_support"]
    assert clue.reference_evidence.discovery.bootstrap.ci_low == record["mfi_bootstrap_ci_low"]
    assert clue.reference_evidence.validation.enrichment_bootstrap.sign_stability == (
        record["reference_validation"]["enrichment_bootstrap_sign_stability"]
    )
    assert clue.perturbation_shift.control_count == row.control_count
    assert clue.perturbation_shift.control_frequency == row.control_frequency
    assert clue.perturbation_shift.delta_frequency == row.delta_frequency
    assert clue.perturbation_shift.q_value_shift == row.q_value_shift
    assert clue.perturbation_shift.bootstrap.sign_stability == row.delta_sign_stability
    assert clue.replication_status == "not_available"
    assert "does not by itself establish a causal" in clue.interpretation_boundary


def test_v02_missing_catalogue_does_not_invent_reference_null_or_bootstrap(v02_result):
    _, shifts = v02_result
    clue = _v02(shifts.shifts.iloc[0])
    assert clue.reference_evidence.discovery.mfi == shifts.shifts.iloc[0].reference_mfi
    assert clue.reference_evidence.discovery.p_value_null is None
    assert clue.reference_evidence.discovery.q_value_null is None
    assert clue.reference_evidence.discovery.bootstrap is None
    assert clue.legacy_control is None and clue.legacy_perturbation is None


def test_actual_v01_maps_null_deviation_and_bootstrap(v01_result):
    row = v01_result.clues.query("order == 3 and bootstrap_performed").iloc[0]
    clue = _v01(row, source_metadata=v01_result.metadata)
    assert clue.discovery_mode == "perturbation_emergent"
    assert clue.source_schema_version == "0.1.0"
    assert clue.reference_id is None and clue.catalogue_sha256 is None
    assert clue.reference_evidence.discovery is None
    assert clue.reference_evidence.validation is None
    assert clue.legacy_control.mfi == row.mfi_control
    assert clue.legacy_perturbation.mfi == row.mfi_perturb
    assert clue.legacy_control.log2_enrichment == row.log2_enrichment_control
    assert clue.legacy_perturbation.q_value_null == row.q_value_null_perturb
    assert clue.legacy_control.bootstrap.ci_low == row.bootstrap_mfi_control_ci_low
    assert clue.legacy_perturbation.enrichment_bootstrap.ci_high == row.bootstrap_log2_enrichment_perturb_ci_high
    assert clue.perturbation_shift.delta_frequency == row.delta_frequency
    assert clue.perturbation_shift.bootstrap.sign_stability == row.delta_sign_stability


def test_both_csv_writers_are_supported_without_changing_clue_identity(tmp_path, v01_result, v02_result):
    reference, shifts = v02_result
    shifts.write(tmp_path / "v02")
    reference.catalogue.save(tmp_path / "catalogue.json")
    saved = json.loads((tmp_path / "catalogue.json").read_text())
    row = pd.read_csv(tmp_path / "v02" / "perturbation_state_shifts.csv").iloc[0]
    imported = _v02(row, catalogue=saved, source_metadata=shifts.metadata)
    original = _v02(shifts.shifts.iloc[0], catalogue=reference.catalogue)
    assert imported.clue_id == original.clue_id
    assert imported.pattern == original.pattern
    assert imported.reference_evidence == original.reference_evidence
    assert imported.perturbation_shift.delta_frequency == pytest.approx(original.perturbation_shift.delta_frequency)
    v01_result.write(tmp_path / "v01")
    baseline_row = pd.read_csv(tmp_path / "v01" / "clues.csv").iloc[0]
    baseline = _v01(baseline_row, source_metadata=v01_result.metadata)
    assert baseline.clue_id == _v01(v01_result.clues.iloc[0]).clue_id
    assert baseline.pattern == _v01(v01_result.clues.iloc[0]).pattern


def test_source_is_json_safe_detached_and_deeply_frozen(v02_result):
    _, shifts = v02_result
    row = shifts.shifts.iloc[0].to_dict()
    row["extra_diagnostics"] = {"missing": np.nan, "odds": np.inf, "opposite": -np.inf}
    metadata = {"cohorts": {"counts": [2000, 2000]}, "threshold": np.int64(0)}
    clue = _v02(row, source_metadata=metadata)
    metadata["cohorts"]["counts"].append(999)
    row["extra_diagnostics"]["missing"] = 42
    encoded = json.loads(clue.model_dump_json())
    assert encoded["source_payload"]["metadata"]["cohorts"]["counts"] == [2000, 2000]
    assert encoded["source_payload"]["row"]["extra_diagnostics"] == {
        "missing": None, "odds": "Infinity", "opposite": "-Infinity",
    }
    assert ClueRecord.model_validate_json(clue.model_dump_json()) == clue
    clue.source_payload["metadata"]["cohorts"]["counts"].append(999)
    assert clue.source_payload["metadata"]["cohorts"]["counts"] == [2000, 2000]
    with pytest.raises(TypeError):
        clue.source_payload["metadata"] = {}
    with pytest.raises((ValueError, TypeError, AttributeError)):
        clue.pattern.genes += ("D",)


@pytest.mark.parametrize("key", ["reference_mfi", "validation_mfi", "delta_frequency", "q_value_shift"])
def test_nonfinite_structured_metrics_rejected(v02_result, key):
    _, shifts = v02_result
    row = shifts.shifts.iloc[0].to_dict()
    row[key] = np.inf
    with pytest.raises(ValueError, match="finite"):
        _v02(row)


def test_missing_statistics_stay_null(v01_result, v02_result):
    row = v01_result.clues.iloc[0].to_dict()
    row["mfi_control"] = np.nan
    row["bootstrap_delta_ci_low"] = row["bootstrap_delta_ci_high"] = row["delta_sign_stability"] = np.nan
    clue = _v01(row)
    assert clue.legacy_control.mfi is None
    assert clue.perturbation_shift.bootstrap is None
    _, shifts = v02_result
    row = shifts.shifts.iloc[0].to_dict()
    row.pop("reference_mfi")
    row.pop("validation_mfi")
    clue = _v02(row)
    assert clue.reference_evidence.discovery is None
    assert clue.reference_evidence.validation is None


def test_catalogue_checksum_and_row_catalogue_link_are_verified(v02_result):
    reference, shifts = v02_result
    row = shifts.shifts.iloc[0].to_dict()
    saved = {"payload": reference.catalogue.payload, "sha256": reference.catalogue.sha256}
    saved["payload"]["records"][0]["mfi"] = 123
    with pytest.raises(ValueError, match="checksum"):
        _v02(row, catalogue=saved)
    row["catalogue_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="catalogue_sha256"):
        _v02(row, catalogue=reference.catalogue)


@pytest.mark.parametrize("change", [
    {"reference_id": "R0000000000000000"},
    {"genes": ("D", "E", "F"), "pattern_string": "D-E-F-"},
    {"pattern_string": "different"},
    {"order": 2},
])
def test_inconsistent_pattern_identity_is_rejected(v02_result, change):
    reference, shifts = v02_result
    row = shifts.shifts.iloc[0].to_dict()
    row.update(change)
    with pytest.raises(ValueError):
        _v02(row, catalogue=reference.catalogue)


def test_catalogue_record_and_duplicate_statistics_must_match(v02_result):
    reference, shifts = v02_result
    row = shifts.shifts.iloc[0].to_dict()
    row["reference_mfi"] += 1
    with pytest.raises(ValueError, match="MFI"):
        _v02(row, catalogue=reference.catalogue)
    row = shifts.shifts.iloc[0].to_dict()
    payload = reference.catalogue.payload
    record = next(item for item in payload["records"] if item["reference_id"] == row["reference_id"])
    record["reference_validation"]["reference_id"] = "R0000000000000000"
    changed = FrozenCatalogue.create(payload)
    row["catalogue_sha256"] = changed.sha256
    with pytest.raises(ValueError, match="pattern/reference_id"):
        _v02(row, catalogue=changed)


def test_discovery_modes_cannot_be_conflated(v01_result, v02_result):
    _, shifts = v02_result
    with pytest.raises(ValueError, match="different discovery mode"):
        _v01(shifts.shifts.iloc[0])
    with pytest.raises(ValueError, match="different discovery mode"):
        _v02(v01_result.clues.iloc[0])
    with pytest.raises(ValueError, match="mode"):
        _v02(shifts.shifts.iloc[0], source_metadata={"mode": "perturbation_emergent"})
    with pytest.raises(ValueError, match="schema"):
        _v01(v01_result.clues.iloc[0], source_metadata={"version": "0.2.0"})
    with pytest.raises(ValueError, match="catalogue_sha256 mismatch"):
        _v02(shifts.shifts.iloc[0], source_metadata={"catalogue_sha256": "0" * 64})


def test_stable_id_changes_with_run_or_perturbation(v01_result):
    row = v01_result.clues.iloc[0].to_dict()
    first = _v01(row)
    assert _v01(deepcopy(row)).clue_id == first.clue_id
    other_run = clue_from_v01(row, source_run_id="other-run", source_artifact="clues.csv")
    assert other_run.clue_id != first.clue_id
    row["perturbation"] = "OTHER_KO"
    assert _v01(row).clue_id != first.clue_id
