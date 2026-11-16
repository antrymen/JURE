"""Adversarial acquisition tests: an executable query is not yet a valid answer."""
from copy import deepcopy

import pytest

from jure.agents.investigator.agent import EvidenceInvestigator
from jure.agents.investigator.backend import MockInvestigatorBackend
from jure.agents.investigator.demo import create_explored_case
from jure.casefile import CaseStore, EvidenceQuestion
from jure.tools.evidence import EvidenceToolRegistry, MockDatasetTool, MockLiteratureTool, MockNetworkTool


@pytest.fixture
def explored(tmp_path):
    with CaseStore(tmp_path / "adversarial.sqlite") as store:
        yield store, create_explored_case(store)


def targeted_case(store, case, family, operation, inputs, text):
    for original in case.evidence_questions:
        case = store.manually_cancel_question(case.metadata.case_id, original.question_id,
                                              expected_revision=case.metadata.case_revision)
    question = EvidenceQuestion(question_id="Q_ADVERSARIAL", question_text=text,
        derived_from_prediction_ids=("P1",), relevant_hypothesis_ids=("H1", "H2"),
        discriminates_between=("H1", "H2"), suggested_evidence_type=family,
        query_spec={"evidence_type": family, "operation": operation, "inputs": inputs})
    return store.manually_add_evidence_question(case.metadata.case_id, question,
                                               expected_revision=case.metadata.case_revision)


def acquire(store, case, tmp_path, tool, backend=None):
    result = EvidenceInvestigator(backend=backend, registry=EvidenceToolRegistry([tool])).run(
        store, case.metadata.case_id, artifact_dir=tmp_path / "run")
    updated = store.load_case(case.metadata.case_id)
    assert updated.clue == case.clue
    assert updated.hypotheses == case.hypotheses
    assert updated.mechanistic_question == case.mechanistic_question
    return result, updated


def candidate(target="A", *, paper=None, null=False, directness="direct",
              source_quality="primary_experiment", support_quality="sufficient"):
    paper = paper or f"SYNTHETIC_{target}"
    return {"paper_id": paper, "title": f"Synthetic X perturbation and {target} measurement", "year": 2026,
        "claim_tested": f"X regulates {target}", "experiment_identifier": f"exp_{paper}",
        "experiment_type": "CRISPR knockout", "perturbed_entity": "X", "measured_entity": target,
        "observed_effect": f"{target} unchanged" if null else f"{target} decreased",
        "biological_context": "K562", "cell_type_or_model": "K562", "directness": directness,
        "source_excerpt_or_summary": f"Synthetic experiment observes {target} after X knockout.",
        "source_reference": f"mock://tests/{paper}", "source_quality": source_quality,
        "support_quality": support_quality, "negative_evidence_type": "explicit_null_result" if null else "not_applicable",
        "sufficient_power": null, "relation_effect": "challenges" if null else "supports"}


@pytest.mark.parametrize("change", ["wrong_target", "drop_conditioning_filter", "drop_population_filter"])
def test_explicit_scientific_query_cannot_be_silently_changed(explored, tmp_path, change):
    store, case = explored
    if change == "wrong_target":
        family, operation = "network", "query_edge"
        inputs = {"source_gene": "X", "target_gene": "A", "context": "K562"}
        tool = MockNetworkTool()
    else:
        family, operation = "dataset", "conditional_frequency"
        inputs = {"target_gene": "C", "target_state": 1, "conditions": {"A": 1, "B": 0},
                  "condition": "perturbation"}
        tool = MockDatasetTool()
    case = targeted_case(store, case, family, operation, inputs, "Acquire the explicitly specified comparison.")

    def changed_plan(context, question_id):
        plan = deepcopy(MockInvestigatorBackend().operationalize_question(context, question_id))
        query = plan["planned_operations"][0]["inputs"]
        if change == "wrong_target":
            query["target_gene"] = "B"
        elif change == "drop_conditioning_filter":
            query["conditions"] = {}
        else:
            query.pop("condition")
        return plan

    result, updated = acquire(store, case, tmp_path, tool,
                              MockInvestigatorBackend(operationalize_question=changed_plan))
    assert not result.success
    assert result.validation_errors
    assert not result.tool_calls
    assert updated.evidence_questions == case.evidence_questions
    assert not updated.evidence_records


def test_wrong_network_relation_returned_by_tool_does_not_answer_question(explored, tmp_path):
    class WrongRelation(MockNetworkTool):
        def query_edge(self, source_gene, target_gene, context=None):
            return super().query_edge("X", "B", context)

    store, case = explored
    case = targeted_case(store, case, "network", "query_edge",
                         {"source_gene": "X", "target_gene": "A"}, "Is there a candidate edge X→A?")
    result, updated = acquire(store, case, tmp_path, WrongRelation())
    assert result.success, result.validation_errors
    assert result.question_final_status == "unresolved"
    assert not updated.evidence_records
    assert not updated.evidence_assessments
    assert result.created_gap_ids


def test_wrong_experimental_relation_returned_by_tool_does_not_answer_question(explored, tmp_path):
    class WrongRelation(MockLiteratureTool):
        def search_regulatory_relation(self, source_gene, target_gene, context=None):
            return super().search_regulatory_relation("X", "B", context)

    store, case = explored
    case = targeted_case(store, case, "literature", "search_regulatory_relation",
        {"source_gene": "X", "target_gene": "A", "context": "K562"}, "Does an experiment support X→A in K562?")
    result, updated = acquire(store, case, tmp_path, WrongRelation(verified_candidates=[candidate("B")]))
    assert result.success, result.validation_errors
    assert result.question_final_status == "unresolved"
    assert not updated.evidence_records
    assert not updated.evidence_assessments


def test_wrong_dataset_target_returned_by_tool_is_not_recorded_as_requested_query(explored, tmp_path):
    class WrongTarget(MockDatasetTool):
        def conditional_frequency(self, target_gene=None, target_state=1, conditions=None,
                                  condition=None, min_conditional_support=None):
            return super().conditional_frequency("A", target_state, conditions, condition,
                                                 min_conditional_support)

    store, case = explored
    case = targeted_case(store, case, "dataset", "conditional_frequency",
        {"target_gene": "C", "target_state": 1, "conditions": {"B": 1}}, "What is P(C+ | B+)?")
    result, updated = acquire(store, case, tmp_path, WrongTarget())
    assert result.question_final_status != "answered"
    assert not updated.evidence_records
    assert not updated.evidence_assessments


def test_partial_shared_regulator_architecture_cannot_answer_all_targets(explored, tmp_path):
    class PartialArchitecture(MockNetworkTool):
        def query_shared_regulators(self, target_genes, context=None):
            return super().query_shared_regulators(target_genes[:2], context)

    store, case = explored
    case = targeted_case(store, case, "network", "query_shared_regulators",
                         {"target_genes": ["A", "B", "C"]}, "Does X connect to all of A, B and C?")
    result, updated = acquire(store, case, tmp_path, PartialArchitecture())
    assert result.success, result.validation_errors
    assert result.question_final_status == "partially_answered"
    assert len(updated.evidence_records) == 2
    assert not result.created_followup_question_ids
    assert result.created_gap_ids
    assert {assessment.relation for assessment in updated.evidence_assessments} == {"neutral"}


def test_single_experiment_cannot_answer_complete_fanout_claim(explored, tmp_path):
    store, case = explored
    case = targeted_case(store, case, "literature", "search_claim",
        {"claim": "X regulates A, B, C", "context": "K562"}, "Is X regulation of A, B and C experimentally supported?")
    result, updated = acquire(store, case, tmp_path, MockLiteratureTool(verified_candidates=[candidate("A")]))
    assert result.success, result.validation_errors
    assert result.question_final_status == "partially_answered"
    assert len(updated.evidence_records) == 1
    assert updated.evidence_records[0].directness == "direct"
    assert result.created_gap_ids
    assert not updated.contradictions


def test_effect_and_null_on_different_targets_are_not_a_conflict(explored, tmp_path):
    store, case = explored
    case = targeted_case(store, case, "literature", "search_claim",
        {"claim": "X regulates A, B", "context": "K562"}, "What experimental evidence tests X regulation of A and B?")
    result, updated = acquire(store, case, tmp_path,
        MockLiteratureTool(verified_candidates=[candidate("A"), candidate("B", null=True)]))
    assert result.success, result.validation_errors
    assert len(updated.evidence_records) == 2
    assert not updated.contradictions
    assert all(not record.potential_conflict for record in updated.evidence_records)


@pytest.mark.parametrize("source_quality", ["secondary_source", "unknown"])
def test_experiment_described_by_secondary_source_is_not_upgraded_to_primary(explored, tmp_path, source_quality):
    store, case = explored
    case = targeted_case(store, case, "literature", "search_regulatory_relation",
        {"source_gene": "X", "target_gene": "A", "context": "K562"}, "Does experimental evidence support X→A?")
    result, updated = acquire(store, case, tmp_path, MockLiteratureTool(verified_candidates=[candidate(
        "A", directness="indirect", source_quality=source_quality)]))
    assert result.success, result.validation_errors
    assert updated.evidence_records[0].source_quality == source_quality
    assert updated.evidence_records[0].directness == "indirect"
    assert result.question_final_status == "partially_answered"
