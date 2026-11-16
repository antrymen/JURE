"""Shared-state contracts across independently acting clients and restarts."""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from pydantic import ValidationError

from jure.casefile.models import (
    ActionState, ClueRecord, ContradictionRecord, EvidenceAssessment, EvidenceGap,
    EvidenceQuestion, EvidenceRecord, MechanisticQuestion, ObjectReference,
    PatternRecord, PredictionRecord, Provenance, ShiftEvidence,
)
from jure.casefile.store import (
    CaseStore, IntegrityError, RevisionConflict, load_case, save_case,
)


@pytest.fixture
def clue():
    return ClueRecord(
        clue_id="CLUE_SYNTHETIC", perturbation="KO", discovery_mode="reference_guided",
        source_schema_version="0.2.0", source_run_id="run_synthetic",
        source_artifact="synthetic_shifts.csv", reference_id="REF_1",
        catalogue_sha256="a" * 64,
        pattern=PatternRecord(genes=("A", "B", "C"), states=(1, 0, 1), order=3,
                              pattern_string="A+B-C+"),
        perturbation_shift=ShiftEvidence(control_frequency=.1, perturb_frequency=.2,
                                         delta_frequency=.1, control_count=10,
                                         perturb_count=20),
        source_payload={"cohort": {"cell_ids": ["nt_1", "nt_2"]}},
    )


@pytest.fixture
def store(tmp_path):
    with CaseStore(tmp_path / "cases.sqlite") as current:
        yield current


def command(store, case, method, *args, actor="explorer", **kwargs):
    return getattr(store, method)(case.metadata.case_id, *args, actor=actor,
                                  expected_revision=case.metadata.case_revision, **kwargs)


def hypothesis(case, hypothesis_id="H1"):
    return next(item for item in case.hypotheses if item.hypothesis_id == hypothesis_id)


def question_case(store, clue):
    """Three competing explanations, each with its own falsifiable prediction."""
    case = store.create_case_from_clue(clue, case_id="CASE_TEST")
    case = command(store, case, "add_mechanistic_question", MechanisticQuestion(
        question_id="MQ1", question_text="What accounts for the observed A/B/C shift?",
        derived_from_clue_id=clue.clue_id,
    ))
    for index, mechanism in enumerate(("common regulator", "indirect cascade", "state composition"), 1):
        case = command(store, case, "add_hypothesis", hypothesis_id=f"H{index}",
                       title=mechanism, mechanism_statement=f"The shift may reflect {mechanism}.",
                       mechanism_type=mechanism,
                       derived_from=(ObjectReference(object_type="mechanistic_question", object_id="MQ1"),))
    for index in range(1, 4):
        current = hypothesis(case, f"H{index}")
        case = command(store, case, "add_prediction", PredictionRecord(
            prediction_id=f"P{index}", hypothesis_id=current.hypothesis_id,
            hypothesis_revision_id=current.current_revision_id,
            statement=f"Observable consequence of H{index}", expected_if_true="A discriminating result",
            weakened_if_observed="The opposite result",
            discriminates_from_hypotheses=tuple(f"H{i}" for i in range(1, 4) if i != index),
        ))
    return command(store, case, "add_evidence_question", EvidenceQuestion(
        question_id="Q1", question_text="Which explanation matches the available network evidence?",
        derived_from_prediction_ids=("P1", "P2", "P3"),
        relevant_hypothesis_ids=("H1", "H2", "H3"), discriminates_between=("H1", "H2", "H3"),
        priority="high", suggested_evidence_type="network", created_by="critic",
    ))


def evidence(evidence_id="E1", **changes):
    values = dict(
        evidence_id=evidence_id, question_id="Q1", source_type="grn",
        claim_tested="A common regulator is connected to A/B/C",
        result_summary="The saved synthetic network contains the expected edges",
        directness="indirect", context_match="partial",
        limitations=("Network edges alone do not establish causality",),
        provenance=Provenance(source_id="network_fixture", source_uri="fixture://network",
                              tool="fixture_reader", parameters={"filters": {"genes": ["A", "B", "C"]}}),
        raw_result_reference="fixture://network/result.json", created_by="critic",
    )
    values.update(changes)
    return EvidenceRecord(**values)


def count_events(path, case_id):
    with sqlite3.connect(path) as connection:
        return connection.execute("SELECT count(*) FROM events WHERE case_id=?", (case_id,)).fetchone()[0]


def test_full_investigation_chain_records_facts_without_automatic_verdict_or_routing(store, clue):
    case = question_case(store, clue)
    initial = case
    assert [item.hypothesis_id for item in case.hypotheses] == ["H1", "H2", "H3"]
    assert case.evidence_questions[0].created_by == "explorer"
    assert case.evidence_questions[0].derived_from_prediction_ids == ("P1", "P2", "P3")

    case = command(store, case, "mark_selected", "Q1", actor="investigator")
    state = ActionState(current_phase="evidence_in_progress", next_actor="investigator", selected_question_id="Q1")
    case = command(store, case, "set_action_state", state, actor="controller")
    case = command(store, case, "update_evidence_question_status", "Q1", "in_progress", actor="investigator")
    case = command(store, case, "add_evidence_record", evidence(), actor="investigator")
    revision = hypothesis(case).current_revision_id
    case = command(store, case, "add_evidence_assessment", EvidenceAssessment(
        assessment_id="EA1", evidence_id="E1", hypothesis_id="H1", hypothesis_revision_id=revision,
        prediction_id="P1", relation="supports", rationale="The network contains the predicted connections",
        assessed_by="critic",
    ), actor="investigator")
    case = command(store, case, "update_prediction_status", "P1", "tested", actor="investigator")
    case = command(store, case, "mark_answered", "Q1", actor="investigator")
    case = command(store, case, "add_evidence_gap", EvidenceGap(
        gap_id="GAP1", description="Direct perturbational validation is still missing",
        related_hypotheses=("H1",), related_predictions=("P1",),
    ), actor="investigator")
    case = command(store, case, "add_contradiction", ContradictionRecord(
        contradiction_id="C1", description="The result conflicts with the exclusive H2 prediction",
        evidence_ids=("E1",), hypothesis_ids=("H2",),
    ), actor="critic")

    assert case.evidence_records[0].created_by == "investigator"
    assert case.evidence_assessments[0].assessed_by == "investigator"
    assert all(item.current_revision.status == "proposed" for item in case.hypotheses)
    assert case.evidence_questions[0].status == "answered"
    assert hypothesis(case).predictions[0].status == "tested"
    assert case.action_state.selected_question_id is None
    assert case.action_state.current_phase == "evidence_in_progress"
    assert case.action_state.next_actor == "investigator"
    assert case.investigation_history[:len(initial.investigation_history)] == initial.investigation_history
    assert case.metadata.case_revision == len(case.investigation_history)
    assert [event.sequence for event in case.investigation_history] == list(range(1, case.metadata.case_revision + 1))
    assert all(event.case_revision == event.sequence for event in case.investigation_history)
    assert all(event.changes["after"] for event in case.investigation_history)

    case = command(store, case, "update_hypothesis", "H2", reason="Recorded critic decision",
                   status="challenged", actor="critic")
    assert hypothesis(case, "H2").current_revision.status == "challenged"
    assert hypothesis(case).current_revision.status == "proposed"
    assert store.load_case(case.metadata.case_id) == case


def test_hypothesis_revision_preserves_the_claim_tested_by_old_prediction_and_assessment(store, clue):
    case = question_case(store, clue)
    case = command(store, case, "add_evidence_record", evidence(), actor="investigator")
    original = hypothesis(case).current_revision
    assessment = EvidenceAssessment(
        evidence_id="E1", hypothesis_id="H1", hypothesis_revision_id=original.revision_id,
        prediction_id="P1", relation="inconclusive", rationale="The result does not distinguish directness",
    )
    case = command(store, case, "add_evidence_assessment", assessment, actor="investigator")
    case = command(store, case, "update_hypothesis", "H1", reason="Separate direct from mediated effects",
                   mechanism_statement="A regulates B through mediator C.")
    revised = hypothesis(case)
    assert len(revised.revisions) == 2
    assert revised.revisions[0] == original
    assert revised.current_revision.supersedes_revision_id == original.revision_id
    assert revised.current_revision.status == "proposed"
    assert revised.predictions[0].hypothesis_revision_id == original.revision_id
    assert case.evidence_assessments[0].hypothesis_revision_id == original.revision_id
    with pytest.raises(ValueError):
        command(store, case, "add_evidence_assessment", EvidenceAssessment(
            evidence_id="E1", hypothesis_id="H1", hypothesis_revision_id=revised.current_revision_id,
            prediction_id="P1", relation="supports", rationale="This combines two different claims",
        ), actor="investigator")
    assert store.load_case(case.metadata.case_id) == case
    case = command(store, case, "update_hypothesis", "H1", revision_id=original.revision_id,
                   status="rejected", reason="Critique of the original claim", actor="critic")
    assert hypothesis(case).revisions[0].status == "rejected"
    assert hypothesis(case).current_revision.status == "proposed"


def test_mechanistic_question_revisions_and_unresolved_question_are_audited(store, clue):
    case = question_case(store, clue)
    old_text = case.mechanistic_question.question_text
    case = command(store, case, "revise_mechanistic_question", new_text="Does cell composition explain the shift?",
                   reason="Make the alternative explanation explicit")
    revision = case.mechanistic_question.revisions[0]
    assert revision.previous_text == old_text
    assert revision.new_text == case.mechanistic_question.question_text
    assert revision.actor == "explorer"
    assert case.mechanistic_question.status == "reframed"
    before = case.investigation_history
    case = command(store, case, "mark_unresolved", "Q1", actor="investigator")
    assert case.evidence_questions[0].status == "unresolved"
    assert case.investigation_history[:-1] == before
    assert case.investigation_history[-1].object_id == "Q1"


@pytest.mark.parametrize("actor,status,changes", [
    ("investigator", "rejected", {}),
    ("investigator", None, {"mechanism_statement": "An altered interpretation"}),
    ("explorer", "retained", {}),
    ("controller", "active", {}),
    ("critic", None, {"mechanism_statement": "An altered interpretation"}),
])
def test_hypothesis_ownership_rejects_unauthorized_mutation_without_audit_change(store, clue, actor, status, changes):
    case = question_case(store, clue)
    with pytest.raises(PermissionError):
        command(store, case, "update_hypothesis", "H1", reason="Unauthorized change", actor=actor,
                status=status, **changes)
    assert store.load_case(case.metadata.case_id) == case
    assert count_events(store.path, case.metadata.case_id) == len(case.investigation_history)


def test_agents_cannot_write_external_routing_decisions(store, clue):
    case = question_case(store, clue)
    for actor in ("explorer", "investigator", "critic"):
        with pytest.raises(PermissionError):
            command(store, case, "set_action_state", ActionState(next_actor="critic"), actor=actor)
    assert store.load_case(case.metadata.case_id) == case


def test_explorer_cannot_create_a_prediction_with_investigator_status(store, clue):
    case = question_case(store, clue)
    prediction = PredictionRecord(
        prediction_id="P_ALREADY_TESTED", hypothesis_id="H1",
        hypothesis_revision_id=hypothesis(case).current_revision_id,
        statement="A proposed consequence", expected_if_true="A predicted outcome",
        weakened_if_observed="A conflicting outcome", status="tested",
    )
    with pytest.raises(ValueError, match="new prediction must be untested"):
        command(store, case, "add_prediction", prediction)
    assert store.load_case(case.metadata.case_id) == case
    assert count_events(store.path, case.metadata.case_id) == len(case.investigation_history)


def test_explorer_cannot_create_an_already_addressed_evidence_gap(store, clue):
    case = question_case(store, clue)
    gap = EvidenceGap(gap_id="GAP_ADDRESSED", description="Direct validation is missing",
                      related_hypotheses=("H1",), status="addressed")
    with pytest.raises(ValueError, match="new evidence gap must be open"):
        command(store, case, "add_evidence_gap", gap)
    assert store.load_case(case.metadata.case_id) == case
    assert count_events(store.path, case.metadata.case_id) == len(case.investigation_history)


@pytest.mark.parametrize("object_type,object_id", [
    ("unknown_object_type", "CASE_TEST"),
    ("hypothesis", "H_MISSING"),
])
def test_public_history_annotations_reject_invalid_object_references(store, clue, object_type, object_id):
    case = question_case(store, clue)
    with pytest.raises(ValueError):
        command(store, case, "append_history_event", summary="An annotation needs a valid target",
                object_type=object_type, object_id=object_id)
    assert store.load_case(case.metadata.case_id) == case
    assert count_events(store.path, case.metadata.case_id) == len(case.investigation_history)


@pytest.mark.parametrize("kind", ["prediction", "question", "evidence", "assessment", "action"])
def test_dangling_references_are_rejected_atomically(store, clue, kind):
    case = question_case(store, clue)
    revision = hypothesis(case).current_revision_id
    with pytest.raises(ValueError):
        if kind == "prediction":
            command(store, case, "add_prediction", PredictionRecord(
                prediction_id="P_BAD", hypothesis_id="H1", hypothesis_revision_id="HR_MISSING",
                statement="A prediction", expected_if_true="An outcome", weakened_if_observed="Another outcome",
            ))
        elif kind == "question":
            command(store, case, "add_evidence_question", EvidenceQuestion(
                question_id="Q_BAD", question_text="An unresolved question", derived_from_prediction_ids=("P_MISSING",),
            ))
        elif kind == "evidence":
            command(store, case, "add_evidence_record", evidence(question_id="Q_MISSING"), actor="investigator")
        elif kind == "assessment":
            command(store, case, "add_evidence_assessment", EvidenceAssessment(
                evidence_id="E_MISSING", hypothesis_id="H1", hypothesis_revision_id=revision,
                relation="supports", rationale="An unavailable record cannot support a claim",
            ), actor="investigator")
        else:
            command(store, case, "set_action_state", ActionState(selected_question_id="Q_MISSING"), actor="controller")
    assert store.load_case(case.metadata.case_id) == case
    assert count_events(store.path, case.metadata.case_id) == len(case.investigation_history)


def test_duplicate_ids_and_inactive_selected_question_do_not_commit(store, clue):
    case = question_case(store, clue)
    with pytest.raises(ValueError):
        command(store, case, "add_evidence_question", case.evidence_questions[0])
    with pytest.raises(ValueError):
        command(store, case, "set_action_state", ActionState(
            selected_question_id="Q1", current_phase="evidence_in_progress", next_actor="investigator",
        ), actor="controller")
    assert store.load_case(case.metadata.case_id) == case


def test_independent_clients_reject_stale_writes_then_allow_explicit_retry(store, clue):
    case = store.create_case_from_clue(clue)
    with CaseStore(store.path) as second:
        stale = second.load_case(case.metadata.case_id)
        updated = command(store, case, "append_history_event", summary="First client's annotation")
        with pytest.raises(RevisionConflict):
            command(second, stale, "append_history_event", summary="Second client's annotation")
        assert second.load_case(case.metadata.case_id) == updated
        latest = command(second, updated, "append_history_event", summary="Second client's annotation")
    assert latest.metadata.case_revision == case.metadata.case_revision + 2
    assert [event.summary for event in latest.investigation_history[-2:]] == [
        "First client's annotation", "Second client's annotation",
    ]
    assert store.load_case(case.metadata.case_id) == latest


def test_simultaneous_writers_commit_exactly_one_revision(store, clue):
    case = store.create_case_from_clue(clue)
    ready = Barrier(2)

    def write_as_independent_client(label):
        with CaseStore(store.path) as client:
            same_revision = client.load_case(case.metadata.case_id)
            ready.wait(timeout=5)
            try:
                return command(client, same_revision, "append_history_event", summary=label)
            except RevisionConflict as error:
                return error

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(write_as_independent_client, label) for label in ("writer_1", "writer_2")]
        results = [future.result(timeout=15) for future in futures]
    assert sum(isinstance(result, RevisionConflict) for result in results) == 1
    winner = next(result for result in results if not isinstance(result, RevisionConflict))
    assert winner.metadata.case_revision == case.metadata.case_revision + 1
    assert store.load_case(case.metadata.case_id) == winner
    assert count_events(store.path, case.metadata.case_id) == 2


def test_snapshot_write_failure_rolls_back_preceding_audit_insert_and_survives_reopen(store, clue, monkeypatch):
    case = question_case(store, clue)

    def fail_after_event_insert(_case):
        raise OSError("simulated storage failure before snapshot update")

    with monkeypatch.context() as patch:
        patch.setattr(store, "_write_snapshot", fail_after_event_insert)
        with pytest.raises(OSError, match="simulated storage failure"):
            command(store, case, "mark_selected", "Q1", actor="investigator")
    with CaseStore(store.path) as reopened:
        assert reopened.load_case(case.metadata.case_id) == case
        assert count_events(store.path, case.metadata.case_id) == len(case.investigation_history)
        retried = command(reopened, case, "mark_selected", "Q1", actor="investigator")
        assert retried.metadata.case_revision == case.metadata.case_revision + 1
        assert retried.evidence_questions[0].status == "selected"


@pytest.mark.parametrize("statement", [
    "UPDATE events SET payload_json='{}'",
    "DELETE FROM events",
    "INSERT OR REPLACE INTO events SELECT case_id, sequence, event_id, payload_json FROM events",
])
def test_persisted_history_cannot_be_overwritten_deleted_or_replaced(store, clue, statement):
    case = store.create_case_from_clue(clue)
    with sqlite3.connect(store.path) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(statement)
    assert store.load_case(case.metadata.case_id) == case


def test_reopening_detects_snapshot_audit_disagreement(store, clue):
    case = store.create_case_from_clue(clue)
    payload = case.model_dump(mode="json")
    payload["clue"]["perturbation"] = "tampered"
    with sqlite3.connect(store.path) as connection:
        connection.execute("UPDATE cases SET snapshot_json=? WHERE case_id=?",
                           (json.dumps(payload), case.metadata.case_id))
    with CaseStore(store.path) as reopened:
        with pytest.raises(ValueError):
            reopened.load_case(case.metadata.case_id)


@pytest.mark.parametrize("extension", ["json", "yaml"])
def test_serialization_round_trip_preserves_revisions_provenance_and_history(store, clue, tmp_path, extension):
    case = question_case(store, clue)
    case = command(store, case, "add_evidence_record", evidence(), actor="investigator")
    case = command(store, case, "update_hypothesis", "H1", reason="Clarify the causal path",
                   mechanism_statement="The common regulator acts through an intermediate.")
    path = tmp_path / f"roundtrip.{extension}"
    assert save_case(case, path) == path
    loaded = load_case(path)
    assert loaded == case
    assert loaded.metadata.schema_version == "0.1.1"
    assert loaded.evidence_records[0].provenance.parameters["filters"]["genes"] == ["A", "B", "C"]
    assert len(hypothesis(loaded).revisions) == 2


def test_import_rejects_an_altered_clue_even_when_its_schema_is_valid(store, clue, tmp_path):
    case = store.create_case_from_clue(clue)
    path = save_case(case, tmp_path / "tampered.json")
    payload = json.loads(path.read_text())
    # Change a valid observational field without changing its original audit record.
    payload["clue"]["source_run_id"] = "different_run"
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="audit"):
        load_case(path)
    assert store.load_case(case.metadata.case_id) == case


def test_clue_and_provenance_are_frozen_across_retained_snapshots(store, clue):
    case = question_case(store, clue)
    saved_evidence = evidence()
    updated = command(store, case, "add_evidence_record", saved_evidence, actor="investigator")
    with pytest.raises(ValidationError):
        updated.clue.perturbation_shift.delta_frequency = .9
    with pytest.raises(ValidationError):
        updated.evidence_records[0].provenance.source_id = "different-source"
    detached_cells = updated.clue.source_payload["cohort"]["cell_ids"]
    detached_cells.append("invented-cell")
    detached_filters = updated.evidence_records[0].provenance.parameters["filters"]
    detached_filters["genes"].clear()
    assert updated.clue.source_payload["cohort"]["cell_ids"] == ["nt_1", "nt_2"]
    assert updated.evidence_records[0].provenance.parameters["filters"]["genes"] == ["A", "B", "C"]
    assert case.evidence_records == ()
    assert store.load_case(case.metadata.case_id) == updated


def test_corrected_evidence_retains_original_provenance_and_its_audit_event(store, clue):
    case = question_case(store, clue)
    case = command(store, case, "add_evidence_record", evidence(), actor="investigator")
    original = case.evidence_records[0]
    original_history = case.investigation_history
    correction = evidence(
        "E2", supersedes_evidence_id="E1", result_summary="One of the saved edges was mislabelled",
        provenance=Provenance(source_id="network_fixture_corrected", source_uri="fixture://corrected-network"),
    )
    case = command(store, case, "add_evidence_record", correction, actor="investigator")
    assert case.evidence_records[0] == original
    assert case.evidence_records[1].supersedes_evidence_id == "E1"
    assert case.evidence_records[1].provenance.source_id == "network_fixture_corrected"
    assert case.investigation_history[:-1] == original_history
    assert case.investigation_history[-1].object_id == "E2"


def test_exports_append_only_missing_events_and_refuse_corrupted_prefix(store, clue, tmp_path):
    case = question_case(store, clue)
    directory = tmp_path / "export"
    paths = store.export_case(case.metadata.case_id, directory)
    original = paths["history"].read_bytes()
    store.export_case(case.metadata.case_id, directory)
    assert paths["history"].read_bytes() == original
    case = command(store, case, "append_history_event", summary="Human-readable observation",
                   metadata={"review": {"labels": ["manual"]}})
    store.export_case(case.metadata.case_id, directory)
    current = paths["history"].read_bytes()
    assert current.startswith(original)
    assert len(current.splitlines()) == len(original.splitlines()) + 1
    assert [json.loads(line) for line in current.splitlines()] == [
        event.model_dump(mode="json") for event in case.investigation_history
    ]
    assert load_case(paths["json"]) == case
    assert load_case(paths["yaml"]) == case

    lines = current.decode().splitlines()
    tampered = json.loads(lines[0])
    tampered["summary"] = "Rewritten history"
    lines[0] = json.dumps(tampered)
    paths["history"].write_text("\n".join(lines) + "\n")
    damaged = paths["history"].read_bytes()
    with pytest.raises(IntegrityError, match="prefix"):
        store.export_case(case.metadata.case_id, directory)
    assert paths["history"].read_bytes() == damaged
    assert store.load_case(case.metadata.case_id) == case


def test_export_rejects_a_partial_audit_line_without_overwriting_it(store, clue, tmp_path):
    case = store.create_case_from_clue(clue)
    directory = tmp_path / "interrupted_export"
    paths = store.export_case(case.metadata.case_id, directory)
    paths["history"].write_text(paths["history"].read_text() + '{"event_id":')
    before = paths["history"].read_bytes()
    with pytest.raises(IntegrityError, match="incomplete"):
        store.export_case(case.metadata.case_id, directory)
    assert paths["history"].read_bytes() == before
    recovered = store.export_case(case.metadata.case_id, tmp_path / "recovered_export")
    assert load_case(recovered["json"]) == case


def test_interrupted_export_leaves_authority_intact_and_can_be_regenerated(store, clue, tmp_path, monkeypatch):
    case = store.create_case_from_clue(clue)
    directory = tmp_path / "export"
    paths = store.export_case(case.metadata.case_id, directory)
    original_history = paths["history"].read_bytes()
    case = command(store, case, "append_history_event", summary="A committed change after the initial export")

    def fail_second_snapshot(snapshot, path):
        if path.suffix == ".yaml":
            raise OSError("simulated export interruption")
        return save_case(snapshot, path)

    with monkeypatch.context() as patch:
        patch.setattr("jure.casefile.store.save_case", fail_second_snapshot)
        with pytest.raises(OSError, match="simulated export interruption"):
            store.export_case(case.metadata.case_id, directory)
    with CaseStore(store.path) as reopened:
        assert reopened.load_case(case.metadata.case_id) == case
        assert paths["history"].read_bytes() == original_history
        reopened.export_case(case.metadata.case_id, directory)
    assert load_case(paths["json"]) == case
    assert load_case(paths["yaml"]) == case
    assert len(paths["history"].read_bytes().splitlines()) == len(case.investigation_history)
