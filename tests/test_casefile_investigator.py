"""Compatibility and authority boundaries for staged evidence investigation."""

import copy
import json
import sqlite3

import pytest

from jure.casefile import (
    ActionState, CaseStore, ClueRecord, ContradictionRecord, EvidenceGap,
    EvidenceQuestion, EvidenceRecord, IntegrityError, PatternRecord, Provenance,
    RevisionConflict, ShiftEvidence, load_case, save_case, validate_case,
)
from jure.casefile.history import verify_history


@pytest.fixture
def store_case(tmp_path):
    clue = ClueRecord(
        clue_id="CLUE_I", perturbation="X", discovery_mode="reference_guided",
        source_schema_version="0.2.0", source_run_id="synthetic", source_artifact="fixture.csv",
        pattern=PatternRecord(genes=("A", "B"), states=(1, 0), order=2, pattern_string="A+B-"),
        perturbation_shift=ShiftEvidence(control_frequency=.1, perturb_frequency=.2,
                                         delta_frequency=.1, control_count=10, perturb_count=20),
    )
    with CaseStore(tmp_path / "authoritative.sqlite") as store:
        case = store.create_case_from_clue(clue, case_id="CASE_I")
        for index in (1, 2):
            case = call(store, case, "add_evidence_question", EvidenceQuestion(
                question_id=f"Q{index}", question_text=f"Does X regulate gene {index}?",
            ), actor="explorer")
        yield store, case


def call(store, case, operation, *args, actor="evidence_investigator", **kwargs):
    return getattr(store, operation)(case.metadata.case_id, *args, actor=actor,
                                    expected_revision=case.metadata.case_revision, **kwargs)


def add_evidence(store, case):
    return call(store, case, "add_evidence_record", EvidenceRecord(
        evidence_id="E1", question_id="Q1", claim_tested="X has a curated edge to A",
        result_summary="Synthetic network contains an edge", source_type="grn",
        source_quality="curated_database", support_quality="limited", fingerprint="network:X:A",
        provenance=Provenance(source_id="synthetic", source_uri="fixture://network"),
    ))


def followup(**changes):
    values = dict(question_id="Q3", question_text="Is the edge experimentally supported?",
                  derived_from_question_ids=("Q1",), derived_from_evidence_ids=("E1",),
                  investigation_depth="verification", query_spec={"source": "X", "target": "A"})
    values.update(changes)
    return EvidenceQuestion(**values)


def legacy_snapshot(case):
    """Reproduce genuine 0.1.0 shape, including original audit section shapes."""
    payload = case.model_dump(mode="json")
    additive = {
        "derived_from_question_ids", "derived_from_evidence_ids", "investigation_depth", "query_spec",
        "related_question_ids", "source_quality", "support_quality", "negative_evidence_type",
        "potential_conflict", "fingerprint",
    }

    def strip(value):
        if isinstance(value, dict):
            for key in list(value):
                if key in additive:
                    del value[key]
                elif key == "schema_version" and value[key] == "0.1.1":
                    value[key] = "0.1.0"
                else:
                    strip(value[key])
        elif isinstance(value, list):
            for item in value:
                strip(item)
    strip(payload)
    return payload


def test_legacy_import_keeps_original_events_and_audits_version_upgrade(store_case, tmp_path):
    store, case = store_case
    # Include evidence and gap shapes, not only empty legacy sections.
    case = call(store, case, "add_evidence_record", EvidenceRecord(
        question_id="Q1", claim_tested="A network edge", result_summary="One edge",
        source_type="grn", provenance=Provenance(source_id="legacy")), actor="investigator")
    case = call(store, case, "add_evidence_gap", EvidenceGap(description="Validation missing"), actor="explorer")
    payload = legacy_snapshot(case)
    original_events = copy.deepcopy(payload["investigation_history"])
    path = tmp_path / "legacy.json"
    path.write_text(json.dumps(payload))
    legacy = load_case(path)
    assert legacy.metadata.schema_version == "0.1.0"
    assert legacy.evidence_records[0].question_ids == ("Q1",)
    with CaseStore() as imported:
        imported.import_case(legacy)
        assert imported.load_case(legacy.metadata.case_id) == legacy
        upgraded = call(imported, legacy, "append_history_event", summary="Started", action="INVESTIGATOR_STARTED")
        assert upgraded.metadata.schema_version == "0.1.1"
        assert [event.model_dump(mode="json") for event in upgraded.investigation_history[:-1]] == original_events
        assert upgraded.investigation_history[-1].changes["before"]["metadata"]["schema_version"] == "0.1.0"
        verify_history(upgraded)
        assert load_case(save_case(upgraded, tmp_path / "upgraded.json")) == upgraded
        with pytest.raises(sqlite3.IntegrityError):
            imported.import_case(legacy)


def test_import_rejects_snapshot_without_matching_audit(store_case):
    _, case = store_case
    payload = case.model_dump(mode="json")
    payload["evidence_questions"][0]["question_text"] = "Invented change"
    with CaseStore() as staged, pytest.raises(ValueError, match="audit"):
        staged.import_case(payload)


def test_followup_links_and_reference_integrity_roundtrip(store_case, tmp_path):
    store, case = store_case
    case = add_evidence(store, case)
    original = case.evidence_records[0]
    case = call(store, case, "add_evidence_question", followup())
    case = call(store, case, "link_evidence_to_question", "E1", "Q2")
    assert len(case.evidence_records) == 1
    assert case.evidence_records[0].question_ids == ("Q1", "Q2")
    assert case.evidence_records[0].primary_question_id == "Q1"
    assert case.evidence_records[0].provenance == original.provenance
    assert case.evidence_questions[-1].created_by == "evidence_investigator"
    case = call(store, case, "add_evidence_gap", EvidenceGap(
        description="Direct experiment missing", related_question_ids=("Q3",)))
    assert load_case(save_case(case, tmp_path / "roundtrip.yaml")) == case
    with pytest.raises(ValueError, match="already linked"):
        call(store, case, "link_evidence_to_question", "E1", "Q2")


@pytest.mark.parametrize("changes", [
    {"derived_from_question_ids": ()}, {"derived_from_evidence_ids": ()},
    {"derived_from_question_ids": ("Q_MISSING",)}, {"derived_from_evidence_ids": ("E_MISSING",)},
    {"derived_from_question_ids": ("Q3",)},
])
def test_invalid_followup_rolls_back(store_case, changes):
    store, case = store_case
    case = add_evidence(store, case)
    with pytest.raises(ValueError):
        call(store, case, "add_evidence_question", followup(**changes))
    assert store.load_case(case.metadata.case_id) == case


def test_question_transitions_routing_and_human_interventions(store_case):
    store, case = store_case
    with pytest.raises(ValueError, match="transition"):
        call(store, case, "mark_answered", "Q1")
    for status in ("selected", "in_progress", "partially_answered", "selected", "in_progress", "answered"):
        case = call(store, case, "update_evidence_question_status", "Q1", status)
    case = call(store, case, "set_action_state", ActionState(current_phase="critique_needed", next_actor="critic"))
    with pytest.raises(PermissionError):
        call(store, case, "set_action_state", ActionState(current_phase="stopped", stop_reason="Done"))
    case = store.manually_prioritize_question(case.metadata.case_id, "Q2", expected_revision=case.metadata.case_revision)
    assert case.evidence_questions[1].priority == "high"
    case = store.manually_cancel_question(case.metadata.case_id, "Q2", expected_revision=case.metadata.case_revision)
    case = store.manually_add_evidence_question(case.metadata.case_id, EvidenceQuestion(
        question_id="Q_HUMAN", question_text="Check an alternative experiment?"), expected_revision=case.metadata.case_revision)
    assert [event.actor for event in case.investigation_history[-3:]] == ["human"] * 3
    assert case.evidence_questions[-1].created_by == "human"


def test_investigator_cannot_modify_hypotheses_predictions_or_resolve_conflicts(store_case):
    store, case = store_case
    with pytest.raises(PermissionError):
        call(store, case, "add_hypothesis", title="No", mechanism_statement="No", mechanism_type="No")
    with pytest.raises(PermissionError):
        call(store, case, "update_prediction_status", "P1", "tested")
    with pytest.raises(PermissionError):
        call(store, case, "add_contradiction", ContradictionRecord(description="No", status="resolved"))
    case = call(store, case, "add_contradiction", ContradictionRecord(contradiction_id="C1", description="Potential conflict"))
    with pytest.raises(PermissionError):
        call(store, case, "update_contradiction_status", "C1", "resolved")
    with pytest.raises(ValueError, match="uppercase"):
        call(store, case, "append_history_event", summary="No spoofed mutation", action="hypothesis.created")


def test_staged_commit_is_atomic_and_preserves_complete_history(store_case):
    store, case = store_case
    with CaseStore() as staged:
        staged.import_case(case)
        result = call(staged, case, "mark_selected", "Q1")
        result = call(staged, result, "update_evidence_question_status", "Q1", "in_progress")
        result = add_evidence(staged, result)
        result = call(staged, result, "add_evidence_question", followup())
        result = call(staged, result, "mark_answered", "Q1")
        result = call(staged, result, "set_action_state", ActionState(current_phase="critique_needed", next_actor="critic"))
        assert store.load_case(case.metadata.case_id) == case
        committed = store.commit_investigator_case(case.metadata.case_id, result, expected_revision=case.metadata.case_revision)
    assert committed == result == store.load_case(case.metadata.case_id)
    assert committed.investigation_history[:len(case.investigation_history)] == case.investigation_history
    verify_history(committed)


def test_staged_commit_rejects_stale_run_without_partial_writes(store_case):
    store, case = store_case
    with CaseStore() as staged:
        staged.import_case(case)
        result = add_evidence(staged, case)
        latest = store.manually_prioritize_question(case.metadata.case_id, "Q1", expected_revision=case.metadata.case_revision)
        with pytest.raises(RevisionConflict):
            store.commit_investigator_case(case.metadata.case_id, result, expected_revision=case.metadata.case_revision)
    assert store.load_case(case.metadata.case_id) == latest
    assert not latest.evidence_records


@pytest.mark.parametrize("kind", ["clue", "question", "actor", "stopped", "prefix"])
def test_staged_commit_rejects_unauthorized_changes(store_case, kind):
    store, case = store_case
    with CaseStore() as staged:
        staged.import_case(case)
        if kind == "actor":
            result = call(staged, case, "append_history_event", actor="explorer", summary="Unauthorized actor")
        elif kind == "stopped":
            result = call(staged, case, "set_action_state", actor="controller", state=ActionState(
                current_phase="stopped", stop_reason="Unauthorized stop"))
        elif kind == "prefix":
            result = call(staged, case, "append_history_event", summary="New event")
            payload = result.model_dump(mode="json")
            payload["investigation_history"][0]["summary"] = "Rewritten prefix"
            result = validate_case(payload)
        else:
            def change(data):
                if kind == "clue":
                    data["clue"]["source_run_id"] = "forged"
                else:
                    data["evidence_questions"][0]["question_text"] = "Silently rewritten question"
            result = staged._mutate(case.metadata.case_id, expected_revision=case.metadata.case_revision,
                                    actor="evidence_investigator", action="evidence_question.status_changed",
                                    object_type="case", object_id=case.metadata.case_id,
                                    summary="Forged mutation", change=change)
        with pytest.raises((PermissionError, IntegrityError)):
            store.commit_investigator_case(case.metadata.case_id, result, expected_revision=case.metadata.case_revision)
    assert store.load_case(case.metadata.case_id) == case


def test_staged_snapshot_failure_rolls_back_all_events(store_case, monkeypatch):
    store, case = store_case
    with CaseStore() as staged:
        staged.import_case(case)
        result = add_evidence(staged, case)
        result = call(staged, result, "add_evidence_question", followup())
        with monkeypatch.context() as patch:
            def fail(_case):
                raise OSError("simulated write failure")
            patch.setattr(store, "_write_snapshot", fail)
            with pytest.raises(OSError):
                store.commit_investigator_case(case.metadata.case_id, result, expected_revision=case.metadata.case_revision)
    assert store.load_case(case.metadata.case_id) == case


def test_staged_investigator_can_update_gap_status_preserving_content(store_case):
    store, case = store_case
    case = call(store, case, "add_evidence_gap", EvidenceGap(
        gap_id="GAP1", description="Direct experimental verification is needed", related_question_ids=("Q1",)))
    original = case.evidence_gaps[0]
    with CaseStore() as staged:
        staged.import_case(case)
        result = call(staged, case, "update_evidence_gap_status", "GAP1", "unresolved")
        result = call(staged, result, "update_evidence_gap_status", "GAP1", "addressed")
        committed = store.commit_investigator_case(case.metadata.case_id, result,
                                                    expected_revision=case.metadata.case_revision)
    assert committed.evidence_gaps[0].status == "addressed"
    assert committed.evidence_gaps[0].model_copy(update={"status": "open"}) == original
    assert [event.action for event in committed.investigation_history[-2:]] == ["evidence_gap.status_changed"] * 2
    verify_history(committed)


@pytest.mark.parametrize("field,value", [("description", "Rewritten gap"), ("related_question_ids", ["Q2"])])
def test_staged_gap_status_event_cannot_rewrite_gap_content(store_case, field, value):
    store, case = store_case
    case = call(store, case, "add_evidence_gap", EvidenceGap(
        gap_id="GAP1", description="Direct experimental verification is needed", related_question_ids=("Q1",)))
    with CaseStore() as staged:
        staged.import_case(case)

        def change(data):
            data["evidence_gaps"][0].update(status="addressed", **{field: value})

        result = staged._mutate(case.metadata.case_id, expected_revision=case.metadata.case_revision,
                                actor="evidence_investigator", action="evidence_gap.status_changed",
                                object_type="evidence_gap", object_id="GAP1",
                                summary="Forged gap rewrite", change=change)
        with pytest.raises(PermissionError, match="gap content or references"):
            store.commit_investigator_case(case.metadata.case_id, result,
                                           expected_revision=case.metadata.case_revision)
    assert store.load_case(case.metadata.case_id) == case
