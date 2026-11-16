"""Scientific and transactional Explorer → Investigator acceptance scenarios."""

from datetime import timedelta
import hashlib
import json
from pathlib import Path

import pytest

from jure.agents.explorer.agent import MechanismExplorer
from jure.agents.explorer.backend import MockExplorerBackend
from jure.agents.explorer.demo import initial_output, synthetic_clue
from jure.agents.investigator.agent import EvidenceInvestigator
from jure.agents.investigator.backend import MockInvestigatorBackend
from jure.agents.investigator.prioritization import reprioritize_pending_questions
from jure.agents.investigator.queue import recover_stale_in_progress_questions
from jure.agents.investigator.result import InvestigatorConfig
from jure.casefile import CaseStore, EvidenceQuestion, load_case, save_case, utc_now, validate_case
from jure.casefile.history import verify_history
from jure.tools.evidence.mock import MockDatasetTool, MockLiteratureTool, MockNetworkTool
from jure.tools.evidence.registry import EvidenceToolRegistry


@pytest.fixture
def explored(tmp_path):
    with CaseStore(tmp_path / "case.sqlite") as store:
        initial = store.create_case_from_clue(synthetic_clue(), cell_context="K562")
        output = MechanismExplorer(MockExplorerBackend([initial_output(initial)])).run(
            store, initial.metadata.case_id, artifact_dir=tmp_path / "explorer")
        assert output.success, output.validation_errors
        yield store, store.load_case(initial.metadata.case_id)


def isolate_question(store, case, *, family, operation, inputs, question_id="Q_TARGET", text=None,
                     planned_operations=None, cancel_original=True):
    if cancel_original:
        for question in case.evidence_questions:
            case = store.manually_cancel_question(case.metadata.case_id, question.question_id,
                                                  expected_revision=case.metadata.case_revision)
    specification = {"evidence_type": family, "operation": operation, "inputs": inputs}
    if planned_operations is not None:
        specification = {"evidence_type": family, "planned_operations": planned_operations}
    question = EvidenceQuestion(
        question_id=question_id, question_text=text or f"Investigate {family} claim for X→A.",
        relevant_hypothesis_ids=("H1", "H2"), discriminates_between=("H1", "H2"),
        derived_from_prediction_ids=("P1",), suggested_evidence_type=family,
        query_spec=specification,
    )
    return store.manually_add_evidence_question(case.metadata.case_id, question,
                                               expected_revision=case.metadata.case_revision)


def run_case(store, case, tmp_path, *tools, config=None, backend=None, run_id="RUN_ACCEPTANCE"):
    agent = EvidenceInvestigator(backend=backend, registry=EvidenceToolRegistry(tools), config=config)
    result = agent.run(store, case.metadata.case_id, run_id=run_id, artifact_dir=tmp_path / run_id)
    updated = store.load_case(case.metadata.case_id)
    assert result.success, result.validation_errors
    assert updated.clue == case.clue
    assert updated.mechanistic_question == case.mechanistic_question
    assert updated.hypotheses == case.hypotheses  # Includes every prediction and verdict.
    assert updated.action_state.current_phase == "critique_needed"
    assert updated.action_state.next_actor == "critic"
    assert updated.investigation_history[:len(case.investigation_history)] == case.investigation_history
    validate_case(updated)
    verify_history(updated)
    return result, updated


def experimental_candidate(*, paper="SYNTHETIC_EFFECT", null=False, context="K562", support="sufficient"):
    return {
        "paper_id": paper, "title": "Synthetic X knockout experiment", "year": 2026,
        "claim_tested": "X regulates A", "experiment_identifier": f"exp_{paper}",
        "experiment_type": "CRISPR knockout", "perturbed_entity": "X", "measured_entity": "A",
        "observed_effect": "A was unchanged after X knockout" if null else "A decreased after X knockout",
        "biological_context": context, "cell_type_or_model": context, "directness": "direct",
        "source_excerpt_or_summary": "Synthetic controlled X perturbation with A measurement.",
        "source_reference": f"mock://synthetic/{paper}", "source_quality": "primary_experiment",
        "support_quality": support, "negative_evidence_type": "explicit_null_result" if null else "not_applicable",
        "sufficient_power": null, "relation_effect": "challenges" if null else "supports",
        "limitations": ["Synthetic fixture, not a real publication."],
    }


def test_network_first_from_explorer_provenance_followup_roundtrip(explored, tmp_path):
    store, case = explored
    result, updated = run_case(store, case, tmp_path,
        MockDatasetTool(), MockNetworkTool(), MockLiteratureTool())
    assert result.selected_question_id == "Q1"
    assert result.tool_calls[0]["tool_id"] == "mock_network"
    assert len(result.priority_assessment) == 3
    assert len(updated.evidence_records) == 3
    assert result.created_followup_question_ids
    for evidence in updated.evidence_records:
        assert evidence.directness == "indirect"
        assert "does not establish causal" in " ".join(evidence.limitations)
        assert evidence.provenance.parameters["run_id"] == result.run_id
        raw = Path(evidence.raw_result_reference)
        assert hashlib.sha256(raw.read_bytes()).hexdigest() == evidence.provenance.artifact_sha256
        assert json.loads(raw.read_text())["status"] == "success"
    followup = next(q for q in updated.evidence_questions if q.question_id in result.created_followup_question_ids)
    assert followup.derived_from_question_ids == ("Q1",)
    assert set(followup.derived_from_evidence_ids) == set(result.created_evidence_ids)
    assert followup.investigation_depth == "verification"
    ranked = reprioritize_pending_questions(updated, EvidenceToolRegistry((MockNetworkTool(), MockLiteratureTool())))
    assert ranked.selected_question_id == followup.question_id
    assert load_case(save_case(updated, tmp_path / "updated_case_file.json")) == updated


def test_dataset_comparison_retains_80_of_100_vs_20_of_100(explored, tmp_path):
    store, case = explored
    case = isolate_question(store, case, family="dataset", operation="compare_conditional_frequency",
        inputs={"target_gene": "C", "conditioning_gene": "B", "target_state": 1},
        text="Does B state alter C response in the dataset?")
    rows = [{"B": 1, "C": 1}] * 80 + [{"B": 1, "C": 0}] * 20
    rows += [{"B": 0, "C": 1}] * 20 + [{"B": 0, "C": 0}] * 80
    result, updated = run_case(store, case, tmp_path, MockNetworkTool(), MockDatasetTool(rows), MockLiteratureTool())
    assert result.tool_calls[0]["tool_id"] == "mock_dataset"
    assert result.question_final_status == "answered"
    record = updated.evidence_records[0]
    data = record.provenance.parameters["dataset"]
    assert (data["group_positive"]["numerator"], data["group_positive"]["denominator"]) == (80, 100)
    assert (data["group_negative"]["numerator"], data["group_negative"]["denominator"]) == (20, 100)
    assert data["difference"] == pytest.approx(.6)
    assert data["uncertainty"]["lower"] is not None
    assert "80/100" in record.result_summary and "20/100" in record.result_summary
    assert record.support_quality == "sufficient"
    assert all(a.relation != "challenges" for a in updated.evidence_assessments)


def test_dataset_eight_cells_remain_insufficient(explored, tmp_path):
    store, case = explored
    case = isolate_question(store, case, family="dataset", operation="conditional_frequency",
        inputs={"target_gene": "C", "target_state": 1, "conditions": {"B": 1}},
        text="What is C frequency among B positive cells?")
    rows = [{"B": 1, "C": 1}] * 6 + [{"B": 1, "C": 0}] * 2
    result, updated = run_case(store, case, tmp_path, MockDatasetTool(rows))
    assert result.tool_calls[0]["status"] == "insufficient_data"
    assert result.question_final_status == "unresolved"
    record = updated.evidence_records[0]
    assert record.support_quality == "insufficient"
    assert "8 cells" in record.result_summary
    assert "0.75" not in record.result_summary
    assert result.created_gap_ids
    assert {a.relation for a in updated.evidence_assessments} == {"inconclusive"}


@pytest.mark.parametrize("mode", ["direct", "null", "comention", "no_result", "conflict"])
def test_literature_acquisition_respects_evidence_type(explored, tmp_path, mode):
    store, case = explored
    case = isolate_question(store, case, family="literature", operation="search_regulatory_relation",
        inputs={"source_gene": "X", "target_gene": "A", "context": "K562"},
        text="Is X→A supported by a direct experiment in K562?")
    candidates, retrieved = [], []
    if mode in {"direct", "conflict"}:
        candidates.append(experimental_candidate())
    if mode in {"null", "conflict"}:
        candidates.append(experimental_candidate(paper="SYNTHETIC_NULL", null=True))
    if mode == "comention":
        retrieved.append({"paper_id": "SYNTHETIC_MENTION", "title": "X and A associations",
                          "source_excerpt_or_summary": "X and A are mentioned together without an experiment.",
                          "source_reference": "mock://mentions"})
    result, updated = run_case(store, case, tmp_path,
        MockLiteratureTool(retrieved_items=retrieved, verified_candidates=candidates), MockDatasetTool(), MockNetworkTool())
    assert result.tool_calls[0]["tool_id"] == "mock_literature"
    if mode == "no_result":
        assert result.tool_calls[0]["status"] == "no_result"
        assert not updated.evidence_records and not updated.evidence_assessments
        assert result.question_final_status == "unresolved" and result.created_gap_ids
    elif mode == "comention":
        assert updated.evidence_records[0].directness == "contextual"
        assert result.question_final_status == "partially_answered"
        assert {a.relation for a in updated.evidence_assessments} == {"neutral"}
    else:
        assert all(e.directness == "direct" for e in updated.evidence_records)
        assert all(e.context_match == "matched" for e in updated.evidence_records)
        if mode == "null":
            assert updated.evidence_records[0].negative_evidence_type == "explicit_null_result"
            assert any(a.relation == "challenges" and a.hypothesis_id == "H1" for a in updated.evidence_assessments)
        if mode == "conflict":
            assert len(updated.evidence_records) == 2
            assert updated.contradictions and updated.contradictions[0].status == "open"
            assert all(e.potential_conflict for e in updated.evidence_records)
            assert result.question_final_status == "partially_answered"


def test_bad_backend_after_acquisition_rolls_back_and_run_id_is_idempotent(explored, tmp_path):
    store, case = explored
    backend = MockInvestigatorBackend(interpret_tool_result={"hypotheses": [{"status": "retained"}]})
    agent = EvidenceInvestigator(backend=backend, registry=EvidenceToolRegistry((MockNetworkTool(),)))
    result = agent.run(store, case.metadata.case_id, run_id="RUN_INVALID", artifact_dir=tmp_path / "invalid")
    assert not result.success and result.validation_errors
    assert len(result.tool_calls) == 1  # Failure happens after a real mock acquisition.
    assert Path(result.tool_calls[0]["raw_result_reference"]).exists()
    updated = store.load_case(case.metadata.case_id)
    for section in ("clue", "mechanistic_question", "hypotheses", "evidence_questions", "evidence_records",
                    "evidence_assessments", "evidence_gaps", "contradictions", "action_state"):
        assert getattr(updated, section) == getattr(case, section)
    assert [e.action for e in updated.investigation_history[len(case.investigation_history):]] == [
        "INVESTIGATOR_STARTED", "INVESTIGATOR_FAILED"]
    call_count = len(backend.calls)
    repeat = agent.run(store, case.metadata.case_id, run_id="RUN_INVALID", artifact_dir=tmp_path / "invalid")
    assert repeat == result and len(backend.calls) == call_count
    assert store.load_case(case.metadata.case_id) == updated


def test_successful_run_id_does_not_reacquire_or_append(explored, tmp_path):
    store, case = explored
    backend = MockInvestigatorBackend()
    agent = EvidenceInvestigator(backend=backend, registry=EvidenceToolRegistry((MockNetworkTool(),)))
    result = agent.run(store, case.metadata.case_id, run_id="RUN_ONCE", artifact_dir=tmp_path / "once")
    assert result.success, result.validation_errors
    updated = store.load_case(case.metadata.case_id)
    count = len(backend.calls)
    assert agent.run(store, case.metadata.case_id, run_id="RUN_ONCE", artifact_dir=tmp_path / "once") == result
    assert len(backend.calls) == count
    assert store.load_case(case.metadata.case_id) == updated


def test_five_planned_operations_stop_at_three_calls(explored, tmp_path):
    store, case = explored
    operations = [{"operation": "query_edge", "evidence_type": "network",
                   "inputs": {"source_gene": "X", "target_gene": target}} for target in ("A", "B", "C", "A", "B")]
    case = isolate_question(store, case, family="network", operation="query_edge", inputs={},
                            planned_operations=operations)
    result, updated = run_case(store, case, tmp_path, MockNetworkTool(),
        config=InvestigatorConfig(max_tool_calls_per_run=3, max_new_followup_questions=0))
    assert len(result.tool_calls) == 3
    assert len(result.query_plans[0]["planned_operations"]) == 5
    assert len(updated.evidence_records) == 3
    assert any(e.action == "BUDGET_REACHED" for e in updated.investigation_history)
    assert result.recommended_next_actor == "critic"


def test_same_network_edge_links_two_questions_without_body_duplication(explored, tmp_path):
    store, case = explored
    case = isolate_question(store, case, family="network", operation="query_edge",
                            inputs={"source_gene": "X", "target_gene": "A"}, question_id="Q_EDGE")
    first, updated = run_case(store, case, tmp_path, MockNetworkTool(), run_id="RUN_EDGE")
    original = updated.evidence_records[0]
    updated = isolate_question(store, updated, family="network", operation="query_paths",
        inputs={"source_gene": "X", "target_gene": "A", "max_hops": 1}, question_id="Q_PATH", cancel_original=False)
    second, final = run_case(store, updated, tmp_path, MockNetworkTool(), run_id="RUN_PATH")
    assert not second.created_evidence_ids and second.linked_evidence_ids == first.created_evidence_ids
    assert len(final.evidence_records) == 1
    record = final.evidence_records[0]
    assert set(record.question_ids) == {"Q_EDGE", "Q_PATH"}
    assert record.evidence_id == original.evidence_id and record.provenance == original.provenance


def test_human_priority_cancellation_and_stale_question_recovery(explored, tmp_path):
    store, case = explored
    case = store.manually_prioritize_question(case.metadata.case_id, "Q2", expected_revision=case.metadata.case_revision)
    result, updated = run_case(store, case, tmp_path, MockNetworkTool(), MockLiteratureTool())
    assert result.selected_question_id == "Q2"
    updated = store.manually_cancel_question(updated.metadata.case_id, "Q1", expected_revision=updated.metadata.case_revision)
    updated = store.update_evidence_question_status(updated.metadata.case_id, "Q3", "selected",
        actor="evidence_investigator", expected_revision=updated.metadata.case_revision)
    updated = store.update_evidence_question_status(updated.metadata.case_id, "Q3", "in_progress",
        actor="evidence_investigator", expected_revision=updated.metadata.case_revision)
    assert not recover_stale_in_progress_questions(store, updated.metadata.case_id, stale_after_seconds=3600)
    recovered = recover_stale_in_progress_questions(store, updated.metadata.case_id,
        stale_after_seconds=3600, now=utc_now() + timedelta(hours=2))
    assert recovered == ("Q3",)
    final = store.load_case(updated.metadata.case_id)
    assert next(q.status for q in final.evidence_questions if q.question_id == "Q1") == "cancelled"
    assert next(q.status for q in final.evidence_questions if q.question_id == "Q3") == "pending"
    assert final.investigation_history[-1].action == "STALE_QUESTION_RECOVERED"


def test_tool_failure_is_retriable_gap_without_negative_evidence(explored, tmp_path):
    class TimeoutNetwork(MockNetworkTool):
        def query_shared_regulators(self, target_genes, context=None):
            raise TimeoutError("synthetic timeout")

    store, case = explored
    result, updated = run_case(store, case, tmp_path, TimeoutNetwork())
    assert result.tool_calls[0]["status"] == "failed"
    assert result.tool_calls[0]["failure_reason"] == "timeout"
    assert result.question_final_status == "pending"
    assert not updated.evidence_records and not updated.evidence_assessments
    assert result.created_gap_ids
    assert any(e.action == "TOOL_CALL_FAILED" for e in updated.investigation_history)


@pytest.mark.parametrize("quality", ["limited", "insufficient"])
def test_literature_does_not_upgrade_source_support_quality(explored, tmp_path, quality):
    store, case = explored
    case = isolate_question(store, case, family="literature", operation="search_regulatory_relation",
        inputs={"source_gene": "X", "target_gene": "A", "context": "K562"},
        text="Is X→A supported by a direct experiment in K562?")
    result, updated = run_case(store, case, tmp_path,
        MockLiteratureTool(verified_candidates=[experimental_candidate(support=quality)]))
    assert updated.evidence_records[0].support_quality == quality
    if quality == "insufficient":
        assert result.question_final_status != "answered"
        assert {assessment.relation for assessment in updated.evidence_assessments} == {"inconclusive"}


def test_direct_experiment_in_other_context_does_not_fully_answer_context_matched_question(explored, tmp_path):
    store, case = explored
    case = isolate_question(store, case, family="literature", operation="search_regulatory_relation",
        inputs={"source_gene": "X", "target_gene": "A", "context": "K562"},
        text="Is X→A supported by a direct experiment in K562?")
    result, updated = run_case(store, case, tmp_path,
        MockLiteratureTool(verified_candidates=[experimental_candidate(context="HEK293")]))
    assert updated.evidence_records[0].directness == "direct"
    assert updated.evidence_records[0].context_match == "mismatched"
    assert result.question_final_status in {"unresolved", "partially_answered"}
    assert result.created_gap_ids
    assert {assessment.relation for assessment in updated.evidence_assessments} == {"neutral"}


def test_new_verification_followup_runs_before_older_queue_entries(explored, tmp_path):
    store, case = explored
    first, updated = run_case(store, case, tmp_path, MockNetworkTool(), MockLiteratureTool(), run_id="RUN_SCREEN")
    backend = MockInvestigatorBackend()
    second, final = run_case(store, updated, tmp_path, MockNetworkTool(), MockLiteratureTool(),
                             backend=backend, run_id="RUN_VERIFY")
    assert second.selected_question_id in first.created_followup_question_ids
    assert second.selected_question_id not in {"Q2", "Q3"}
    assert second.tool_calls[0]["operation"] == "search_claim"
    assert second.question_final_status == "answered"
    records = [e for e in final.evidence_records if e.evidence_id in second.created_evidence_ids]
    assert {e.provenance.parameters["literature"]["measured_entity"] for e in records} == {"A", "B", "C"}
    assert all(e.directness == "direct" for e in records)
    addressed = [g for g in final.evidence_gaps if second.selected_question_id in g.related_question_ids]
    assert addressed and all(g.status == "addressed" for g in addressed)
    assert any(event.action == "EVIDENCE_GAP_UPDATED" for event in final.investigation_history)
    context = backend.calls[0]["context"]
    assert {h["hypothesis_id"] for h in context["active_hypotheses"]} == {"H1", "H2", "H3"}
    assert all(h["weakening_conditions"] for h in context["active_hypotheses"])
    assert all(q.status == "pending" for q in final.evidence_questions if q.question_id in {"Q2", "Q3"})
