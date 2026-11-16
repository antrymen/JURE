"""Dynamic queue choice, faithful operations and closed reasoning boundaries."""
from copy import deepcopy
import json

import pytest
from pydantic import ValidationError

from jure.agents.explorer import MechanismExplorer, MockExplorerBackend
from jure.agents.explorer.demo import initial_output, synthetic_clue
from jure.agents.investigator.backend import (
    JSONInvestigatorBackend, MockInvestigatorBackend, ToolInterpretation, ToolSelection,
    investigator_output_json_schema,
)
from jure.agents.investigator.context import build_investigator_context
from jure.agents.investigator.prioritization import PrioritizationResult, reprioritize_pending_questions
from jure.agents.investigator.query_plan import QueryPlan
from jure.casefile import CaseStore, EvidenceQuestion, EvidenceRecord, HistoryEvent, Provenance
from jure.casefile.models import FrozenJSON


def test_source_planning_can_override_family_hint_without_rewriting_question(case):
    from jure.agents.investigator.query_plan import PlannedOperation
    from jure.agents.investigator.validation import validate_investigator_action
    q = case.evidence_questions[0].model_copy(update={'suggested_evidence_type': 'dataset',
        'query_spec': FrozenJSON(), 'question_text': 'What experimental evidence tests the proposed connection?'})
    detached = case.model_copy(update={'evidence_questions': (q,)})
    plan = QueryPlan(plan_id='PLAN_SOURCE', question_id=q.question_id, objective=q.question_text,
        evidence_type='literature', candidate_tool_types=('literature',),
        planned_operations=(PlannedOperation(operation='search', inputs={'keywords': ['fixture']},
            evidence_planning={'claim': q.question_text, 'gap': 'Mechanistic bridge',
                'evidence_need': 'Experimental mechanism evidence',
                'source_choice_reason': 'A dataset hint does not answer the experimental question.',
                'expected_information_gain': 'Connection support only; applicability remains unknown.'}),),
        expected_output='Traceable source for later audit')
    assert validate_investigator_action(detached, question_id=q.question_id, plan=plan)
    captured=[]
    backend=JSONInvestigatorBackend(lambda request: captured.append(request) or '{}')
    context=build_investigator_context(detached, source_aware_planning=True)
    backend.operationalize_question(context, q.question_id)
    assert 'experimental mechanism connection' in captured[0]['system_instructions']
    assert 'required_evidence_types' in captured[0]['system_instructions']
    assert detached.evidence_questions[0] == q


class Registry:
    """Metadata-only registry: reasoning may inspect, but never execute tools."""
    def __init__(self, unavailable=()):
        self.unavailable = unavailable

    def metadata_snapshot(self):
        return [
            {"tool_id": "network", "tool_type": "network", "version": "mock-1",
             "capabilities": ["query_shared_regulators", "query_edge"],
             "required_inputs": {"query_shared_regulators": ["target_genes"],
                                 "query_edge": ["source_gene", "target_gene"]},
             "cost_class": "low", "availability": "unavailable" if "network" in self.unavailable else "available"},
            {"tool_id": "dataset", "tool_type": "dataset", "version": "mock-1",
             "capabilities": ["compare_conditional_frequency", "conditional_frequency"],
             "required_inputs": {"compare_conditional_frequency": ["target_gene", "conditioning_gene"],
                                 "conditional_frequency": ["target_gene"]},
             "cost_class": "low", "availability": "unavailable" if "dataset" in self.unavailable else "available"},
            {"tool_id": "literature", "tool_type": "literature", "version": "mock-1",
             "capabilities": ["search_claim", "search_regulatory_relation", "search_perturbation_evidence"],
             "required_inputs": {"search_claim": ["claim"],
                                 "search_regulatory_relation": ["source_gene", "target_gene"],
                                 "search_perturbation_evidence": ["perturbed_entity", "measured_entity"]},
             "cost_class": "medium", "availability": "unavailable" if "literature" in self.unavailable else "available"},
        ]


@pytest.fixture
def case(tmp_path):
    with CaseStore(tmp_path / "reasoning.sqlite") as store:
        case = store.create_case_from_clue(synthetic_clue(), cell_context="K562")
        result = MechanismExplorer(MockExplorerBackend([initial_output(case)])).run(store, case.metadata.case_id)
        assert result.success, result.validation_errors
        case = store.load_case(case.metadata.case_id)
    return case.model_copy(update={"evidence_questions": (
        EvidenceQuestion(question_id="Q1", question_text="Is there a shared regulator of A/B/C?",
                         discriminates_between=("H1", "H2"), suggested_evidence_type="network"),
        EvidenceQuestion(question_id="Q2", question_text="Is perturbation gene X associated with cancer?"),
        EvidenceQuestion(question_id="Q3", question_text="Does B state alter C response?",
                         discriminates_between=("H2", "H3"), suggested_evidence_type="dataset"),
    )})


def evidence(question_id="Q1", evidence_id="E1"):
    return EvidenceRecord(evidence_id=evidence_id, question_id=question_id,
        claim_tested="Shared regulator candidate", result_summary="X connects to A, B and C in a mock network",
        source_type="grn", support_quality="sufficient", provenance=Provenance(source_id="mock_network"))


def test_discriminative_questions_beat_generic_information(case):
    result = reprioritize_pending_questions(case, Registry())
    assessments = {a.question_id: a for a in result.assessments}
    assert assessments["Q2"].discriminative_value == "low"
    assert assessments["Q2"].priority_class == "low"
    assert assessments["Q1"].priority_class == assessments["Q3"].priority_class == "high"
    assert result.selected_question_id in {"Q1", "Q3"}
    assert result.assessments[0].priority_reason


def test_unavailable_tool_changes_selection(case):
    result = reprioritize_pending_questions(case, Registry(unavailable={"dataset"}))
    assert result.selected_question_id == "Q1"
    assert next(a for a in result.assessments if a.question_id == "Q3").answerability == "low"


def test_new_verification_overtakes_old_queue_after_evidence(case):
    question = EvidenceQuestion(question_id="Q4", question_text="Is X regulation of A/B/C experimentally supported?",
        discriminates_between=("H1", "H2"), suggested_evidence_type="literature",
        investigation_depth="verification", derived_from_question_ids=("Q1",), derived_from_evidence_ids=("E1",),
        query_spec={"operation": "search_claim", "evidence_type": "literature",
                    "inputs": {"claim": "X regulates A, B and C", "context": "K562"}})
    questions = (case.evidence_questions[0].model_copy(update={"status": "answered"}),
                 *case.evidence_questions[1:], question)
    after = case.model_copy(update={"evidence_questions": questions, "evidence_records": (evidence(),)})
    result = reprioritize_pending_questions(after, Registry())
    assert result.selected_question_id == "Q4"
    assert "newly acquired" in result.assessments[0].priority_reason


def test_evidence_redundancy_is_recomputed(case):
    after = case.model_copy(update={"evidence_records": (evidence("Q3"),)})
    # Network evidence on a dataset question is partial, not complete, redundancy.
    item = next(a for a in reprioritize_pending_questions(after, Registry()).assessments if a.question_id == "Q3")
    assert item.redundancy == "partial"
    network_after = case.model_copy(update={"evidence_records": (evidence(),)})
    item = next(a for a in reprioritize_pending_questions(network_after, Registry()).assessments if a.question_id == "Q1")
    assert item.redundancy == "high"
    assert item.priority_class == "medium"


def test_focused_context_retains_all_competitors_but_not_unrelated_evidence(case):
    case = case.model_copy(update={"evidence_records": (evidence(), evidence("Q2", "E2"))})
    context = build_investigator_context(case, registry=Registry(), question_id="Q1")
    assert {h["hypothesis_id"] for h in context["active_hypotheses"]} == {"H1", "H2", "H3"}
    assert all(h["weakening_conditions"] for h in context["active_hypotheses"])
    assert [e["evidence_id"] for e in context["existing_evidence"]] == ["E1"]
    assert "investigation_history" not in context and "source_payload" not in context
    context["active_hypotheses"][0]["mechanism_statement"] = "tampered"
    assert case.hypotheses[0].current_revision.mechanism_statement != "tampered"


def test_human_priority_is_visible_without_history_payload(case):
    event = HistoryEvent(event_id="HUMAN_1", sequence=100, case_revision=case.metadata.case_revision,
        actor="human", action="QUESTION_MANUALLY_PRIORITIZED", object_type="evidence_question",
        object_id="Q1", summary="Select Q1 next")
    case = case.model_copy(update={"investigation_history": (*case.investigation_history, event)})
    result = reprioritize_pending_questions(case, Registry())
    assert result.selected_question_id == "Q1"
    assert "human priority" in result.assessments[0].priority_reason


def test_explicit_query_filters_are_preserved_and_inputs_not_inferred(case):
    spec = {"operation": "conditional_frequency", "evidence_type": "dataset", "inputs": {
        "target_gene": "C", "target_state": 1, "conditions": {"A": 1, "B": 0, "D": 1},
        "condition": "perturbation", "min_conditional_support": 20}}
    q = case.evidence_questions[2].model_copy(update={"query_spec": FrozenJSON(spec)})
    case = case.model_copy(update={"evidence_questions": (q,)})
    backend = MockInvestigatorBackend()
    context = build_investigator_context(case, registry=Registry())
    plan = QueryPlan.model_validate(backend.operationalize_question(context, "Q3"))
    assert plan.planned_operations[0].inputs.to_dict() == spec["inputs"]
    assert plan.required_inputs.to_dict() == spec["inputs"]
    assert ToolSelection.model_validate(backend.select_tool(context, plan)).tool_id == "dataset"


def test_conceptual_composition_question_does_not_become_b_c_comparison(case):
    q = case.evidence_questions[2].model_copy(update={
        "question_text": "Does the pattern persist after matching broader cell-state composition?"})
    case = case.model_copy(update={"evidence_questions": (q,)})
    backend = MockInvestigatorBackend()
    context = build_investigator_context(case, registry=Registry())
    plan = QueryPlan.model_validate(backend.operationalize_question(context, "Q3"))
    assert plan.planned_operations == ()
    assert ToolSelection.model_validate(backend.select_tool(context, plan)).tool_id is None


def test_cascade_query_does_not_silently_drop_second_relation(case):
    q = case.evidence_questions[0].model_copy(update={
        "question_text": "Is A→B→C experimentally supported?", "suggested_evidence_type": "literature"})
    case = case.model_copy(update={"evidence_questions": (q,)})
    backend = MockInvestigatorBackend()
    context = build_investigator_context(case, registry=Registry())
    plan = QueryPlan.model_validate(backend.operationalize_question(context, "Q1"))
    assert [(o.inputs["source_gene"], o.inputs["target_gene"]) for o in plan.planned_operations] == [
        ("A", "B"), ("B", "C")]


def test_missing_required_input_prevents_available_tool_selection(case):
    q = case.evidence_questions[0].model_copy(update={"query_spec": FrozenJSON({
        "operation": "query_edge", "evidence_type": "network", "inputs": {"source_gene": "A"}})})
    case = case.model_copy(update={"evidence_questions": (q,)})
    backend = MockInvestigatorBackend()
    context = build_investigator_context(case, registry=Registry())
    plan = QueryPlan.model_validate(backend.operationalize_question(context, "Q1"))
    assert ToolSelection.model_validate(backend.select_tool(context, plan)).tool_id is None


@pytest.mark.parametrize("mutation", ["hypotheses", "create_hypothesis", "clue", "hypothesis_verdict", "evidence_records"])
def test_interpretation_schema_rejects_case_mutations(mutation):
    with pytest.raises(ValidationError, match="Extra inputs"):
        ToolInterpretation.model_validate({"warnings": [], "possible_gap": None, mutation: {}})


def test_priority_schema_rejects_fake_numeric_score(case):
    payload = reprioritize_pending_questions(case, Registry()).model_dump(mode="json")
    payload["assessments"][0]["priority_score"] = .8734
    with pytest.raises(ValidationError, match="Extra inputs"):
        PrioritizationResult.model_validate(payload)


def test_json_wrapper_detaches_context_and_supplies_strict_schema(case):
    requests = []
    def transport(request):
        requests.append(deepcopy(request))
        request["context"]["active_hypotheses"].clear()
        return json.dumps({"assessments": [], "selected_question_id": None})
    backend = JSONInvestigatorBackend(transport)
    context = build_investigator_context(case, registry=Registry())
    PrioritizationResult.model_validate_json(backend.prioritize_questions(context))
    assert context["active_hypotheses"]
    assert requests[0]["strict_json"]
    assert requests[0]["response_schema"]["additionalProperties"] is False
    schema = investigator_output_json_schema("interpret_tool_result")
    assert set(schema["required"]) == {"warnings", "possible_gap", "information_update"}


def test_mock_injected_failures_remain_visible_to_validation(case):
    backend = MockInvestigatorBackend(responses={"interpret_tool_result": {"hypotheses": []}})
    context = build_investigator_context(case, registry=Registry())
    plan = QueryPlan.model_validate(backend.operationalize_question(context, "Q1"))
    with pytest.raises(ValidationError):
        ToolInterpretation.model_validate(backend.interpret_tool_result(context, plan, {"status": "success"}))


def test_no_result_interpretation_never_claims_negative_evidence(case):
    backend = MockInvestigatorBackend()
    context = build_investigator_context(case, registry=Registry())
    plan = QueryPlan.model_validate(backend.operationalize_question(context, "Q1"))
    result = ToolInterpretation.model_validate(backend.interpret_tool_result(context, plan, {"status": "no_result"}))
    assert "remains unresolved" in result.possible_gap
    assert set(result.model_dump()) == {"warnings", "possible_gap", "information_update"}
    assert result.information_update is None
