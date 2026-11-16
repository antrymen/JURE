"""Schema and cross-reference tests independent of the authoritative store."""

import copy
import json

import pytest
from pydantic import ValidationError

from jure.casefile.models import (
    ActionState, CaseFile, CaseMetadata, ClueRecord, EvidenceAssessment,
    EvidenceQuestion, EvidenceRecord, FrozenJSON, HistoryEvent, HypothesisRecord,
    HypothesisRevision, MechanisticQuestion, PatternRecord, PredictionRecord,
    Provenance, ShiftEvidence, StatisticalEvidence, new_id,
)
from jure.casefile.schema import case_json_schema
from jure.casefile.validation import validate_case


@pytest.fixture
def clue():
    return ClueRecord(
        clue_id="CLUE_1", perturbation="KO", discovery_mode="reference_guided",
        source_schema_version="0.2.0", source_run_id="run_1", source_artifact="clues.csv",
        pattern=PatternRecord(genes=("B", "A"), states=(1, 0), order=2, pattern_string="B+A-"),
        perturbation_shift=ShiftEvidence(control_frequency=.2, perturb_frequency=.35,
                                        delta_frequency=.15, control_count=20, perturb_count=35,
                                        support=35),
        source_payload={"nested": {"genes": ["B", "A"]}},
    )


def case_with(clue, **fields):
    return CaseFile(
        metadata=CaseMetadata(case_id="CASE_1", perturbation="KO"), clue=clue,
        investigation_history=(HistoryEvent(event_id="EV_1", sequence=1, case_revision=1,
                                           actor="controller", action="case.created", object_type="case",
                                           object_id="CASE_1", summary="Synthetic initial state"),),
        **fields,
    )


def graph_case(clue):
    revision = HypothesisRevision(revision_id="HR_1", title="Common regulator",
                                  mechanism_statement="R may explain the pattern", mechanism_type="common upstream")
    prediction = PredictionRecord(prediction_id="P_1", hypothesis_id="H_1", hypothesis_revision_id="HR_1",
                                  statement="R regulates both genes", expected_if_true="Both regulatory links exist",
                                  weakened_if_observed="No links exist")
    hypothesis = HypothesisRecord(hypothesis_id="H_1", current_revision_id="HR_1",
                                  revisions=(revision,), predictions=(prediction,))
    question = EvidenceQuestion(question_id="Q_1", question_text="Does R regulate both?",
                                derived_from_prediction_ids=("P_1",), relevant_hypothesis_ids=("H_1",))
    evidence = EvidenceRecord(evidence_id="E_1", question_id="Q_1", claim_tested="Regulatory links",
                              result_summary="One link is reported", source_type="grn",
                              provenance=Provenance(source_id="network_1", parameters={"genes": ["A", "B"]}))
    assessment = EvidenceAssessment(assessment_id="EA_1", evidence_id="E_1", hypothesis_id="H_1",
                                    hypothesis_revision_id="HR_1", prediction_id="P_1", relation="inconclusive",
                                    rationale="A partial network cannot exclude the missing edge")
    return case_with(clue, hypotheses=(hypothesis,), evidence_questions=(question,),
                     evidence_records=(evidence,), evidence_assessments=(assessment,))


def test_clue_is_frozen_and_preserves_pattern_order(clue):
    assert clue.pattern.genes == ("B", "A")
    with pytest.raises(ValidationError, match="frozen"):
        clue.perturbation = "OTHER"
    with pytest.raises(ValidationError, match="frozen"):
        clue.perturbation_shift.delta_frequency = -.1
    detached = clue.source_payload["nested"]
    detached["genes"].append("C")
    assert clue.source_payload["nested"]["genes"] == ["B", "A"]
    assert "does not by itself establish a causal" in clue.interpretation_boundary


def test_frozen_json_detaches_inputs_outputs_and_provenance():
    original = {"nested": {"values": [1, 2]}, "unicode": "证据"}
    frozen = FrozenJSON(original)
    original["nested"]["values"].append(3)
    assert frozen.to_dict()["nested"]["values"] == [1, 2]
    detached = frozen.to_dict()
    detached["nested"]["values"].append(4)
    assert frozen["nested"]["values"] == [1, 2]
    with pytest.raises(TypeError, match="immutable"):
        frozen._json = "{}"
    provenance = Provenance(source_id="s", parameters=frozen)
    assert provenance.model_dump(mode="json")["parameters"] == frozen.to_dict()
    assert copy.deepcopy(provenance) == provenance


@pytest.mark.parametrize("value", [{"x": float("nan")}, {"x": float("inf")}, {1: "x"}, {"x": object()}, []])
def test_metadata_accepts_json_objects_only(value):
    with pytest.raises(ValueError):
        FrozenJSON(value)


@pytest.mark.parametrize("identifier", ["", "has space", "1starts_numeric", "H/1", "H\n1"])
def test_invalid_ids_rejected(identifier):
    with pytest.raises(ValidationError):
        CaseMetadata(case_id=identifier)


def test_generated_ids_and_schema_version(clue):
    identifiers = {new_id("H") for _ in range(20)}
    assert len(identifiers) == 20
    with pytest.raises(ValueError):
        new_id("bad prefix")
    case = validate_case(case_with(clue))
    assert case.metadata.schema_version == "0.1.1"
    assert case.metadata.created_at.utcoffset().total_seconds() == 0
    with pytest.raises(ValidationError):
        CaseMetadata(schema_version="0.2.0")
    with pytest.raises(ValidationError):
        CaseMetadata(created_at="2026-01-01T00:00:00")


@pytest.mark.parametrize("changes", [
    {"states": (True, 0)}, {"states": (1.0, 0)}, {"states": (2, 0)},
    {"order": 3}, {"genes": ("A", "A")}, {"pattern_string": "A+B-"},
])
def test_invalid_pattern_rejected(clue, changes):
    with pytest.raises(ValidationError):
        PatternRecord.model_validate(dict(clue.pattern.model_dump(), **changes))


@pytest.mark.parametrize("changes", [{"delta_frequency": .9}, {"support": 99}, {"control_count": True},
                                      {"q_value_shift": 1.5}, {"control_frequency": float("nan")}])
def test_invalid_statistical_fields_rejected(clue, changes):
    with pytest.raises(ValidationError):
        ShiftEvidence.model_validate(dict(clue.perturbation_shift.model_dump(), **changes))


def test_reference_and_legacy_populations_cannot_be_mixed(clue):
    data = clue.model_dump(mode="json")
    data["legacy_control"] = {"mfi": 2.0}
    with pytest.raises(ValidationError, match="legacy"):
        ClueRecord.model_validate(data)
    assert StatisticalEvidence().mfi is None


def test_json_round_trip_and_schema_object_metadata(clue):
    case = validate_case(graph_case(clue))
    payload = json.loads(case.model_dump_json())
    assert isinstance(payload["clue"]["source_payload"], dict)
    assert validate_case(payload) == case
    schema = case_json_schema()
    assert schema["$defs"]["CaseMetadata"]["properties"]["schema_version"]["enum"] == ["0.1.0", "0.1.1"]
    assert schema["$defs"]["Provenance"]["properties"]["parameters"]["type"] == "object"
    assert schema["additionalProperties"] is False


def test_old_prediction_and_evidence_keep_original_hypothesis_revision(clue):
    case = graph_case(clue)
    original = case.hypotheses[0]
    second = HypothesisRevision(revision_id="HR_2", title="Indirect regulator",
                                 mechanism_statement="R acts through C", mechanism_type="indirect",
                                 supersedes_revision_id="HR_1", reason="Original network was incomplete")
    revised = original.model_copy(update={"current_revision_id": "HR_2", "revisions": original.revisions + (second,)})
    updated = validate_case(case.model_copy(update={"hypotheses": (revised,)}))
    assert updated.hypotheses[0].current_revision.revision_id == "HR_2"
    assert updated.hypotheses[0].predictions[0].hypothesis_revision_id == "HR_1"
    assert updated.evidence_assessments[0].hypothesis_revision_id == "HR_1"


@pytest.mark.parametrize("path,value,match", [
    (("evidence_questions", 0, "derived_from_prediction_ids"), ["P_missing"], "reference"),
    (("evidence_records", 0, "question_id"), "Q_missing", "reference"),
    (("evidence_assessments", 0, "evidence_id"), "E_missing", "reference"),
    (("evidence_assessments", 0, "hypothesis_revision_id"), "HR_missing", "revision"),
    (("hypotheses", 0, "current_revision_id"), "HR_missing", "latest"),
    (("hypotheses", 0, "predictions", 0, "hypothesis_id"), "H_missing", "containing"),
    (("hypotheses", 0, "revisions", 0, "supersedes_revision_id"), "HR_1", "chain"),
    (("evidence_questions", 0, "question_id"), "H_1", "duplicate"),
    (("investigation_history", 0, "sequence"), 2, "contiguous"),
    (("metadata", "case_revision"), 2, "length"),
])
def test_invalid_graphs_rejected(clue, path, value, match):
    data = graph_case(clue).model_dump(mode="json")
    target = data
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValueError, match=match):
        validate_case(data)


def test_typed_derived_from_and_assessment_prediction_coherence(clue):
    data = graph_case(clue).model_dump(mode="json")
    data["hypotheses"][0]["revisions"][0]["derived_from"] = [
        {"object_type": "evidence_question", "object_id": "CLUE_1"}]
    with pytest.raises(ValueError, match="wrong-type"):
        validate_case(data)
    data = graph_case(clue).model_dump(mode="json")
    second = dict(data["hypotheses"][0]["revisions"][0], revision_id="HR_2", supersedes_revision_id="HR_1")
    data["hypotheses"][0]["revisions"].append(second)
    data["hypotheses"][0]["current_revision_id"] = "HR_2"
    data["evidence_assessments"][0]["hypothesis_revision_id"] = "HR_2"
    with pytest.raises(ValueError, match="prediction and hypothesis revision"):
        validate_case(data)


def test_selected_question_pointer_requires_active_existing_question(clue):
    case = graph_case(clue)
    state = ActionState(selected_question_id="Q_1", current_phase="evidence_in_progress", next_actor="investigator")
    with pytest.raises(ValueError, match="active"):
        validate_case(case.model_copy(update={"action_state": state}))
    active_question = case.evidence_questions[0].model_copy(update={"status": "selected"})
    selected = case.model_copy(update={"evidence_questions": (active_question,)})
    assert validate_case(selected).action_state.selected_question_id is None
    assert validate_case(selected.model_copy(update={"action_state": state})).action_state == state


def test_unchecked_model_copy_is_revalidated_at_boundary(clue):
    corrupted = clue.model_copy(update={"clue_id": "contains space"})
    with pytest.raises(ValidationError):
        validate_case(case_with(corrupted))


def test_question_revision_text_must_match_current_text(clue):
    question = MechanisticQuestion(question_id="MQ_1", question_text="Original?", derived_from_clue_id="CLUE_1",
                                   revisions=[dict(previous_text="Original?", new_text="Reframed?", reason="New observation")])
    with pytest.raises(ValueError, match="latest revision"):
        validate_case(case_with(clue, mechanistic_question=question))


def test_schema_rejects_explorer_tool_assignment():
    with pytest.raises(ValidationError, match="preferred_tool"):
        EvidenceQuestion(question_text="Any relevant network?", preferred_tool="grn_query")


@pytest.mark.parametrize("state", [
    {"current_phase": "stopped"},
    {"current_phase": "stopped", "stop_reason": "Finished", "next_actor": "critic"},
    {"current_phase": "stopped", "stop_reason": "Finished", "selected_question_id": "Q_1"},
    {"current_phase": "clue_ready", "stop_reason": "Stale reason"},
])
def test_stopped_state_rejects_incomplete_or_stale_routing(state):
    with pytest.raises(ValidationError):
        ActionState(**state)
    assert ActionState(current_phase="stopped", stop_reason="Investigation complete").next_actor == "none"


def test_history_events_require_known_types_and_existing_objects(clue):
    data = case_with(clue).model_dump(mode="json")
    data["investigation_history"][0]["object_type"] = "typo"
    with pytest.raises(ValidationError):
        validate_case(data)
    data["investigation_history"][0]["object_type"] = "hypothesis"
    data["investigation_history"][0]["object_id"] = "H_missing"
    with pytest.raises(ValueError, match="reference"):
        validate_case(data)
