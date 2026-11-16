"""Provider and prompt boundaries independent of reasoning/commit behavior."""

import json

import pytest
from pydantic import ValidationError

from jure.agents.explorer.backend import JSONExplorerBackend, MockExplorerBackend
from jure.agents.explorer.context import ContextLimitError, build_explorer_context
from jure.agents.explorer.demo import synthetic_clue
from jure.agents.explorer.models import ExplorerConfig
from jure.casefile.models import (
    CaseFile, CaseMetadata, EvidenceAssessment, EvidenceRecord, FrozenJSON,
    HistoryEvent, HypothesisRecord, HypothesisRevision, MechanisticQuestion,
    PredictionRecord, Provenance,
)


@pytest.fixture
def case():
    return CaseFile(metadata=CaseMetadata(case_id="CASE_CONTRACT", cell_context="K562"),
                    clue=synthetic_clue())


@pytest.mark.parametrize("config", [
    {"min_hypotheses": 4, "max_hypotheses": 2}, {"min_hypotheses": True},
    {"max_retries": -1}, {"max_retries": 6}, {"max_context_chars": 0},
    {"max_response_chars": 1_000_001}, {"max_hypotheses": 1},
])
def test_configuration_rejects_unbounded_or_incoherent_limits(config):
    with pytest.raises(ValidationError):
        ExplorerConfig(**config)


def test_json_backend_delivers_strict_schema_and_separates_context_feedback():
    received = []

    def transport(request):
        received.append(request)
        request["context"]["clue"]["genes"].append("MUTATED")
        return '{"malformed_proposal":true}'

    context = {"clue": {"genes": ["A", "B"]}}
    backend = JSONExplorerBackend(transport)
    assert backend.generate_reframe(context, feedback=("Invalid prediction lineage",)) == '{"malformed_proposal":true}'
    assert context == {"clue": {"genes": ["A", "B"]}}
    request = received[0]
    assert request["mode"] == "reframe"
    assert request["strict_json"] is True
    assert request["feedback"] == ["Invalid prediction lineage"]
    schema = request["response_schema"]
    for model_schema in [schema, *schema["$defs"].values()]:
        if "properties" in model_schema:
            assert model_schema["additionalProperties"] is False
            assert set(model_schema["required"]) == set(model_schema["properties"])
    assert "Do not call tools" in request["system_instructions"]
    assert "retained/rejected" in request["system_instructions"]


def test_mock_retry_sequence_and_call_records_are_detached():
    responses = ["not json", {"hypotheses": ["ORIGINAL"]}]
    backend = MockExplorerBackend(responses)
    responses[1]["hypotheses"].append("CALLER_MUTATION")
    context = {"facts": [1]}
    assert backend.generate_initial(context) == "not json"
    context["facts"].append(2)
    second = backend.generate_initial(context, feedback=("Malformed JSON",))
    second["hypotheses"].append("RESULT_MUTATION")
    assert backend.calls[0]["context"] == {"facts": [1]}
    assert backend.calls[1]["feedback"] == ("Malformed JSON",)
    with pytest.raises(RuntimeError, match="exhausted"):
        backend.generate_initial(context)


def test_mock_callable_receives_mode_and_detached_context():
    def generate(mode, context, feedback):
        context["facts"].clear()
        return {"mode": mode, "feedback": feedback}

    backend = MockExplorerBackend(generate)
    context = {"facts": [1]}
    assert backend.generate_reframe(context, feedback=("retry",)) == {"mode": "reframe", "feedback": ("retry",)}
    assert context == {"facts": [1]}
    assert backend.calls[0]["context"] == context


def test_initial_context_omits_raw_payload_and_history_preserves_stage_statistics(case):
    raw = case.clue.model_copy(update={"source_payload": FrozenJSON({"huge": "x" * 100_000})})
    history = HistoryEvent(sequence=1, case_revision=1, actor="explorer", action="annotation.added",
                           object_type="case", object_id=case.metadata.case_id,
                           summary="PRIVATE_HISTORY", metadata={"huge": "x" * 100_000})
    snapshot = case.model_copy(update={"clue": raw, "investigation_history": (history,)})
    context = build_explorer_context(snapshot, "initial")
    assert "source_payload" not in context["clue"]
    assert "investigation_history" not in context
    assert "PRIVATE_HISTORY" not in json.dumps(context)
    assert context["clue"]["reference_evidence"] == raw.reference_evidence.model_dump(mode="json")
    assert context["clue"]["perturbation_shift"] == raw.perturbation_shift.model_dump(mode="json")
    assert context["clue"]["pattern"]["encoding"] == raw.pattern.encoding
    assert "existing_evidence" not in context
    assert context["biological_context"]["cell_context"] == "K562"


def test_context_limit_fails_without_truncating(case):
    context = build_explorer_context(case, "initial")
    size = len(json.dumps(context, ensure_ascii=False, allow_nan=False))
    assert build_explorer_context(case, "initial", max_chars=size) == context
    with pytest.raises(ContextLimitError, match="no evidence was silently omitted"):
        build_explorer_context(case, "initial", max_chars=size - 1)


def test_reframe_retains_evidence_referenced_old_revision_and_current_structure(case):
    revisions = tuple(
        HypothesisRevision(revision_id=f"HR_{n}", title=f"Mechanism {n}",
                           mechanism_statement="An unspecified mediator may connect the clue genes.",
                           mechanism_type="shared upstream",
                           supersedes_revision_id=f"HR_{n-1}" if n > 1 else None)
        for n in range(1, 4)
    )
    prediction = PredictionRecord(prediction_id="P_OLD", hypothesis_id="H1", hypothesis_revision_id="HR_1",
                                  statement="Shared connectivity is expected", expected_if_true="Shared links",
                                  weakened_if_observed="Matched tests exclude shared links")
    hypothesis = HypothesisRecord(hypothesis_id="H1", current_revision_id="HR_3", revisions=revisions,
                                  predictions=(prediction,))
    evidence = EvidenceRecord(evidence_id="E1", question_id="Q1", claim_tested="Shared connectivity",
                              result_summary="Counterevidence remains relevant", source_type="grn",
                              provenance=Provenance(source_id="SYNTHETIC_NETWORK"))
    assessment = EvidenceAssessment(evidence_id="E1", hypothesis_id="H1", hypothesis_revision_id="HR_1",
                                    prediction_id="P_OLD", relation="challenges", rationale="No shared links")
    structure = {"causal_structure": "unspecified mediator", "directness": "indirect",
                 "cell_state_explanation": False, "conditional_dependence": False,
                 "directed_edges": [], "distinguishing_features": []}
    history = tuple(
        HistoryEvent(sequence=n, case_revision=n, actor="explorer", action="annotation.added",
                     object_type="hypothesis", object_id="H1", summary="HYPOTHESIS_REVISED",
                     metadata={"hypothesis_revision_id": revision, "structure": structure})
        for n, revision in enumerate(("HR_3", "HR_2"), 1)
    )
    snapshot = case.model_copy(update={
        "mechanistic_question": MechanisticQuestion(question_text="Why the joint-state shift?",
                                                     derived_from_clue_id=case.clue.clue_id),
        "hypotheses": (hypothesis,), "evidence_records": (evidence,),
        "evidence_assessments": (assessment,), "investigation_history": history,
    })
    context = build_explorer_context(snapshot, "reframe", reframe_reason="New counterevidence")
    current = context["existing_hypotheses"][0]
    assert current["structure"] == structure
    assert current["current_revision"]["revision_id"] == "HR_3"
    assert [r["revision_id"] for r in current["referenced_revisions"]] == ["HR_1"]
    assert context["existing_evidence"][0]["result_summary"] == "Counterevidence remains relevant"
    assert context["existing_evidence_assessments"][0]["hypothesis_revision_id"] == "HR_1"
    assert "investigation_history" not in context
    with pytest.raises(ContextLimitError):
        build_explorer_context(snapshot, "reframe", reframe_reason="New counterevidence", max_chars=100)


@pytest.mark.parametrize("reason", [None, "", "  "])
def test_reframe_requires_reason(case, reason):
    with pytest.raises(ValueError, match="reframe_reason"):
        build_explorer_context(case, "reframe", reframe_reason=reason)
