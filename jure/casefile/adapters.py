"""Copy Clue Discovery results into immutable case records without recomputation.

The adapters accept a row mapping or pandas Series (including rows read back from
the CSV writers). ``source_metadata`` is the corresponding run/shift metadata.
The optional v0.2 catalogue is either a ``FrozenCatalogue`` or the saved JSON
envelope ``{"payload": ..., "sha256": ...}``; its checksum and matching record
are verified before discovery/validation statistics are copied.
"""
from collections.abc import Mapping
import hashlib
import json
import math
from pathlib import Path
import re

import numpy as np
import pandas as pd

from clue_discovery.v02.reference import FrozenCatalogue, canonical_json

from .models import (
    BootstrapSummary,
    ClueRecord,
    PatternRecord,
    ReferenceEvidence,
    ShiftEvidence,
    StatisticalEvidence,
)


def _mapping(value, name):
    if isinstance(value, pd.Series):
        value = value.to_dict()
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be a mapping or pandas Series")
    return dict(value)


def _missing(value):
    return value is None or value is pd.NA or (
        isinstance(value, (float, np.floating)) and math.isnan(float(value))
    )


def _json_value(value):
    """Retain the upstream JSON convention for NaN and infinite raw diagnostics."""
    if _missing(value):
        return None
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("source payload object keys must be strings")
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, np.ndarray)):
        return [_json_value(item) for item in value]
    if isinstance(value, np.generic):
        return _json_value(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return "Infinity" if value > 0 else "-Infinity"
    if isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"unsupported source payload value: {type(value).__name__}")


def _number(row, key, *, integer=False):
    value = row.get(key)
    if _missing(value):
        return None
    if isinstance(value, (bool, np.bool_)):
        raise ValueError(f"{key} must be a finite number, not boolean")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{key} must be a finite number") from exc
    if not math.isfinite(number):
        raise ValueError(f"{key} must be finite; unavailable metrics must be null")
    if integer:
        if number != int(number):
            raise ValueError(f"{key} must be an integer")
        return int(number)
    return number


def _text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a nonempty string")
    return value


def _array(value, name):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{name} must be a JSON array in CSV input") from exc
    if not isinstance(value, (list, tuple, np.ndarray)):
        raise ValueError(f"{name} must be an array")
    return tuple(item.item() if isinstance(item, np.generic) else item for item in value)


def _pattern(row):
    genes, states = _array(row.get("genes"), "genes"), _array(row.get("states"), "states")
    if any(isinstance(state, bool) or not isinstance(state, int) for state in states):
        raise ValueError("states must contain integer binary values")
    pattern = PatternRecord(
        genes=genes, states=states, order=_number(row, "order", integer=True),
        pattern_string=_text(row.get("pattern_string"), "pattern_string"),
    )
    expected = "".join(gene + ("+" if state else "-") for gene, state in zip(genes, states))
    if pattern.pattern_string != expected:
        raise ValueError("pattern_string does not match genes/states")
    return pattern


def _bootstrap(row, prefix, stability_key):
    values = dict(ci_low=_number(row, prefix + "ci_low"), ci_high=_number(row, prefix + "ci_high"),
                  sign_stability=_number(row, stability_key))
    return BootstrapSummary(**values) if any(value is not None for value in values.values()) else None


def _shift(row):
    values = {key: _number(row, key) for key in (
        "control_frequency", "perturb_frequency", "delta_frequency", "p_value_shift", "q_value_shift"
    )}
    values.update({key: _number(row, key, integer=True) for key in ("control_count", "perturb_count", "support")})
    values.update(status=_text(row.get("status", "unknown"), "status"),
                  bootstrap=_bootstrap(row, "bootstrap_delta_", "delta_sign_stability"))
    return ShiftEvidence(**values)


def _legacy_statistics(row, condition):
    values = {key: _number(row, f"{key}_{condition}") for key in (
        "mfi", "log2_enrichment", "p_value_null", "q_value_null", "expected_count"
    )}
    values.update(
        bootstrap=_bootstrap(row, f"bootstrap_mfi_{condition}_", f"mfi_{condition}_sign_stability"),
        enrichment_bootstrap=_bootstrap(row, f"bootstrap_log2_enrichment_{condition}_",
                                        f"log2_enrichment_{condition}_sign_stability"),
    )
    return StatisticalEvidence(**values) if any(value is not None for value in values.values()) else None


def _reference_statistics(record, fallback_mfi):
    if record is None:
        return StatisticalEvidence(mfi=fallback_mfi) if fallback_mfi is not None else None
    mfi = _number(record, "mfi")
    if fallback_mfi is not None and (mfi is None or not math.isclose(mfi, fallback_mfi, rel_tol=1e-12, abs_tol=1e-12)):
        raise ValueError("row MFI does not match catalogue evidence")
    return StatisticalEvidence(
        mfi=mfi, log2_enrichment=_number(record, "log2_enrichment"),
        p_value_null=_number(record, "p_value_null"), q_value_null=_number(record, "q_value_null"),
        expected_count=_number(record, "expected_support"),
        bootstrap=_bootstrap(record, "mfi_bootstrap_", "mfi_bootstrap_sign_stability"),
        enrichment_bootstrap=_bootstrap(record, "enrichment_bootstrap_", "enrichment_bootstrap_sign_stability"),
    )


def _verify_source(row, metadata, mode, version):
    for source in (row, metadata):
        for key in ("mode", "discovery_mode"):
            if not _missing(source.get(key)) and source[key] != mode:
                raise ValueError(f"{key} does not match {mode} adapter")
        for key in ("version", "source_schema_version"):
            if not _missing(source.get(key)) and source[key] != version:
                raise ValueError(f"{key} does not match source schema {version}")


def _reject_values(row, keys, mode):
    for key in keys:
        if not _missing(row.get(key)):
            raise ValueError(f"{key} belongs to a different discovery mode than {mode}")


def _hash_value(value, name):
    if _missing(value):
        return None
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _same_optional(row, metadata, key):
    first, second = row.get(key), metadata.get(key)
    if not _missing(first) and not _missing(second) and first != second:
        raise ValueError(f"row and source metadata {key} mismatch")
    return second if _missing(first) else first


def _base(row, metadata, pattern, source_run_id, source_artifact, mode, version, catalogue_sha256=None):
    perturbation = _text(row.get("perturbation"), "perturbation")
    if not _missing(metadata.get("perturbation")) and metadata["perturbation"] != perturbation:
        raise ValueError("row and source metadata perturbation mismatch")
    source_run_id = _text(source_run_id, "source_run_id")
    if isinstance(source_artifact, Path):
        source_artifact = str(source_artifact)
    source_artifact = _text(source_artifact, "source_artifact")
    identity = [mode, source_run_id, perturbation, pattern.genes, pattern.states, catalogue_sha256]
    clue_id = "CLUE_" + hashlib.sha256(canonical_json(identity).encode()).hexdigest()
    return dict(
        clue_id=clue_id, perturbation=perturbation, pattern=pattern,
        discovery_mode=mode, source_schema_version=version,
        source_run_id=source_run_id, source_artifact=source_artifact,
        source_artifact_sha256=_hash_value(_same_optional(row, metadata, "source_artifact_sha256"),
                                          "source_artifact_sha256"),
        perturbation_shift=_shift(row),
        replication_status=_text(row.get("replication_status", "not_available"), "replication_status"),
    )


def clue_from_v01(row, *, source_run_id, source_artifact, source_metadata=None) -> ClueRecord:
    """Adapt preserved v0.1 output, retaining separate control/perturbation MFI."""
    row = _mapping(row, "row")
    metadata = {} if source_metadata is None else _mapping(source_metadata, "source_metadata")
    _verify_source(row, metadata, "perturbation_emergent", "0.1.0")
    for source in (row, metadata):
        _reject_values(source, ("reference_mfi", "validation_mfi", "reference_id", "catalogue_sha256"),
                       "perturbation_emergent")
    values = _base(row, metadata, _pattern(row), source_run_id, source_artifact,
                   "perturbation_emergent", "0.1.0")
    return ClueRecord(
        **values, reference_evidence=ReferenceEvidence(),
        legacy_control=_legacy_statistics(row, "control"),
        legacy_perturbation=_legacy_statistics(row, "perturb"),
        source_payload=_json_value({"row": row, "metadata": metadata}),
    )


def _catalogue_record(catalogue, pattern, reference_id, expected_sha256):
    if isinstance(catalogue, FrozenCatalogue):
        # Recheck even an existing instance: the digest is part of this boundary.
        catalogue = FrozenCatalogue(catalogue.payload_json, catalogue.sha256)
    else:
        saved = _mapping(catalogue, "catalogue")
        if set(saved) != {"payload", "sha256"}:
            raise ValueError("catalogue must be the saved payload/sha256 envelope")
        catalogue = FrozenCatalogue(canonical_json(saved["payload"]), saved["sha256"])
    _hash_value(catalogue.sha256, "catalogue_sha256")
    if expected_sha256 is not None and catalogue.sha256 != expected_sha256:
        raise ValueError("row/metadata catalogue_sha256 does not match supplied catalogue")
    payload = catalogue.payload
    if payload.get("version") != "0.2.0":
        raise ValueError("catalogue version must be 0.2.0")
    records = payload.get("records")
    if not isinstance(records, list) or any(not isinstance(record, dict) for record in records):
        raise ValueError("catalogue records must be a list of objects")
    matches = [record for record in records if record.get("reference_id") == reference_id]
    if len(matches) != 1:
        raise ValueError("reference_id must occur exactly once in supplied catalogue")
    record = matches[0]
    validation = record.get("reference_validation")
    if not isinstance(validation, dict):
        raise ValueError("catalogue reference_validation must be an object")
    for evidence in (record, validation):
        if _pattern(evidence) != pattern or evidence.get("reference_id") != reference_id:
            raise ValueError("catalogue evidence pattern/reference_id mismatch")
    return catalogue.sha256, record


def clue_from_v02(row, *, source_run_id, source_artifact, catalogue=None, source_metadata=None) -> ClueRecord:
    """Adapt v0.2 shifts; reference MFI is never assigned to either shift cohort.

    Without ``catalogue``, only the reference/validation MFI present on the shift
    row is available. Null statistics and reference bootstrap remain ``None``.
    A supplied catalogue adds its verified evidence without recomputing metrics.
    """
    row = _mapping(row, "row")
    metadata = {} if source_metadata is None else _mapping(source_metadata, "source_metadata")
    _verify_source(row, metadata, "reference_guided", "0.2.0")
    _reject_values(row, tuple(f"{name}_{condition}" for condition in ("control", "perturb")
                             for name in ("mfi", "log2_enrichment", "p_value_null", "q_value_null", "expected_count")),
                   "reference_guided")
    pattern = _pattern(row)
    reference_id = _text(row.get("reference_id"), "reference_id")
    expected_id = "R" + hashlib.sha256(canonical_json([pattern.genes, pattern.states]).encode()).hexdigest()[:16]
    if reference_id != expected_id:
        raise ValueError("reference_id does not match genes/states")
    catalogue_sha256 = _hash_value(_same_optional(row, metadata, "catalogue_sha256"), "catalogue_sha256")
    record = None
    if catalogue is not None:
        catalogue_sha256, record = _catalogue_record(catalogue, pattern, reference_id, catalogue_sha256)
    payload = {"row": row, "metadata": metadata}
    if record is not None:
        payload["catalogue_record"] = record
    values = _base(row, metadata, pattern, source_run_id, source_artifact,
                   "reference_guided", "0.2.0", catalogue_sha256)
    return ClueRecord(
        **values, reference_id=reference_id, catalogue_sha256=catalogue_sha256,
        reference_evidence=ReferenceEvidence(
            discovery=_reference_statistics(record, _number(row, "reference_mfi")),
            validation=_reference_statistics(None if record is None else record["reference_validation"],
                                             _number(row, "validation_mfi")),
        ),
        source_payload=_json_value(payload),
    )
