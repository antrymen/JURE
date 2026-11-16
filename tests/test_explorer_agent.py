"""Synthetic reasoning contracts, role boundaries, and atomic case writes."""

from copy import deepcopy
import json
from pathlib import Path
import sqlite3

import pytest

from jure.agents.explorer.agent import MechanismExplorer
from jure.agents.explorer.backend import MockExplorerBackend
from jure.agents.explorer.demo import initial_output, run as run_demo, synthetic_clue
from jure.agents.explorer.models import ExplorerConfig
from jure.casefile import (
    CaseStore, ContradictionRecord, EvidenceGap, EvidenceQuestion, EvidenceRecord,
    MechanisticQuestion, Provenance, load_case,
)


@pytest.fixture
def store(tmp_path):
    with CaseStore(tmp_path / "cases.sqlite") as current:
        yield current


@pytest.fixture
def case(store):
    return store.create_case_from_clue(synthetic_clue(), cell_context="K562")


def execute(store, case, output, **kwargs):
    backend = MockExplorerBackend([output])
    result = MechanismExplorer(backend, ExplorerConfig(max_retries=0)).run(
        store, case.metadata.case_id, **kwargs,
    )
    return result, store.load_case(case.metadata.case_id)


def events(case):
    return [event.metadata.get("explorer_event") for event in case.investigation_history]


def assert_no_proposals(case):
    assert case.mechanistic_question is None
    assert case.hypotheses == ()
    assert case.evidence_questions == ()
    assert case.evidence_records == ()
    assert case.action_state.current_phase == "clue_ready"
    assert case.action_state.next_actor == "none"


def test_synthetic_1_initial_exploration_creates_competing_space_and_handoff(store, case, tmp_path):
    result, after = execute(store, case, initial_output(case), artifact_dir=tmp_path / "runs")
    assert result.success, result.validation_errors
    assert result.attempts == 1
    assert result.created_hypothesis_ids == ("H1", "H2", "H3")
    assert result.created_prediction_ids == ("P1", "P2", "P3")
    assert result.created_evidence_question_ids == ("Q1", "Q2", "Q3")
    assert after.mechanistic_question.question_id == result.mechanistic_question_id
    assert after.mechanistic_question.derived_from_clue_id == case.clue.clue_id
    assert "K562" in after.mechanistic_question.question_text
    assert len({h.current_revision.mechanism_type for h in after.hypotheses}) == 3
    for hypothesis in after.hypotheses:
        assert hypothesis.current_revision.status == "proposed"
        assert hypothesis.current_revision.weakening_conditions
        assert hypothesis.predictions
        for prediction in hypothesis.predictions:
            assert prediction.hypothesis_revision_id == hypothesis.current_revision_id
            assert prediction.weakened_if_observed
            assert prediction.discriminates_from_hypotheses
    assert any(set(q.discriminates_between) == {"H1", "H2"} for q in after.evidence_questions)
    assert after.evidence_records == ()
    assert after.action_state.current_phase == "evidence_needed"
    assert after.action_state.next_actor == "investigator"
    assert result.committed_case_revision == after.metadata.case_revision
    assert {
        "EXPLORER_STARTED", "OBSERVATION_INTERPRETED", "MECHANISTIC_QUESTION_CREATED",
        "HYPOTHESIS_CREATED", "PREDICTION_CREATED", "EVIDENCE_QUESTION_CREATED", "EXPLORER_COMPLETED",
    } <= set(events(after))
    artifact = json.loads(Path(result.artifact_path).read_text())
    assert artifact == result.model_dump(mode="json")
    assert after.investigation_history[-1].metadata["run_artifact"] == artifact


@pytest.mark.parametrize("overclaim", [
    "Perturbation X activates A, represses B and activates C.",
    "MFI proves A and B regulate C.",
    "Perturbation X upregulates A and C and downregulates B.",
])
def test_synthetic_2_observation_cannot_assert_causality_or_redefine_states(store, case, overclaim):
    output = initial_output(case)
    output["observation_interpretation"] = overclaim
    result, after = execute(store, case, output)
    assert not result.success
    assert result.validation_errors
    assert_no_proposals(after)
    assert "EXPLORER_FAILED" in events(after)


def test_synthetic_3_paraphrased_hypotheses_are_rejected(store, case):
    output = initial_output(case)
    same_structure = {
        "causal_structure": "direct_regulation", "directness": "direct",
        "cell_state_explanation": False, "conditional_dependence": False,
        "directed_edges": [["A", "C"]],
    }
    for hypothesis, statement in zip(output["hypotheses"], (
        "A regulates C.", "A may control C.", "C is affected by A.",
    )):
        hypothesis.update(mechanism_statement=statement, mechanism_type="direct_regulation",
                          structure=deepcopy(same_structure))
    result, after = execute(store, case, output)
    assert not result.success
    assert any("redundan" in error.lower() or "structur" in error.lower() for error in result.validation_errors)
    assert_no_proposals(after)


def test_synthetic_4_untestable_prediction_is_regenerated_with_feedback(store, case):
    invalid = initial_output(case)
    invalid["predictions"][0]["statement"] = "This pathway is biologically important."
    backend = MockExplorerBackend([invalid, initial_output(case)])
    result = MechanismExplorer(backend, ExplorerConfig(max_retries=1)).run(store, case.metadata.case_id)
    assert result.success, result.validation_errors
    assert result.attempts == 2
    assert backend.calls[0]["feedback"] == ()
    assert backend.calls[1]["feedback"]
    after = store.load_case(case.metadata.case_id)
    assert after.hypotheses[0].predictions[0].statement == initial_output(case)["predictions"][0]["statement"]
    assert len(after.hypotheses) == 3
    assert events(after).count("HYPOTHESIS_CREATED") == 3


@pytest.mark.parametrize("lineage", [[], ["P_MISSING"]])
def test_synthetic_5_evidence_question_requires_valid_prediction_lineage(store, case, lineage):
    invalid = initial_output(case)
    invalid["evidence_questions"][0]["derived_from_prediction_ids"] = lineage
    result, after = execute(store, case, invalid)
    assert not result.success
    assert_no_proposals(after)


def test_synthetic_5_evidence_question_preserves_prediction_and_hypothesis_links(store, case):
    result, after = execute(store, case, initial_output(case))
    assert result.success, result.validation_errors
    question = next(q for q in after.evidence_questions if q.question_id == "Q1")
    assert question.derived_from_prediction_ids == ("P1",)
    assert question.relevant_hypothesis_ids == ("H1", "H2")
    assert question.discriminates_between == ("H1", "H2")


@pytest.mark.parametrize("violation", ["evidence", "retained", "rejected", "score", "tool", "clue"])
def test_synthetic_6_explorer_rejects_evidence_verdict_score_tool_and_clue_writes(store, case, violation):
    output = initial_output(case)
    if violation == "evidence":
        output["evidence_records"] = [{"result_summary": "Paper PMID XXX supports H1."}]
    elif violation in {"retained", "rejected"}:
        output["hypotheses"][0]["status"] = violation
    elif violation == "score":
        output["hypotheses"][0]["probability"] = 0.8
    elif violation == "tool":
        output["evidence_questions"][0]["preferred_tool"] = "STRING"
    else:
        output["clue"] = {"delta_frequency": 0.99}
    result, after = execute(store, case, output)
    assert not result.success
    assert_no_proposals(after)
    assert after.clue.model_dump_json() == case.clue.model_dump_json()


def investigated_case(store, case):
    result, current = execute(store, case, initial_output(case))
    assert result.success, result.validation_errors
    for index in (1, 2):
        current = store.add_evidence_record(
            case.metadata.case_id, EvidenceRecord(
                evidence_id=f"E{index}", question_id=f"Q{index}", source_type="other",
                claim_tested=f"Supplied synthetic test of prediction P{index}",
                result_summary="The supplied observation D is not explained by the current mechanisms.",
                limitations=("This is manually supplied synthetic evidence, not retrieved evidence.",),
                provenance=Provenance(source_id=f"synthetic_fixture_{index}"),
            ), actor="investigator", expected_revision=current.metadata.case_revision,
        )
    current = store.add_evidence_gap(
        case.metadata.case_id, EvidenceGap(
            gap_id="G1", description="Neither H1 nor H2 explains observation D.",
            related_hypotheses=("H1", "H2"), related_predictions=("P1", "P2"),
        ), actor="investigator", expected_revision=current.metadata.case_revision,
    )
    return store.add_contradiction(
        case.metadata.case_id, ContradictionRecord(
            contradiction_id="C1", description="The supplied results do not agree with the proposed intermediate steps.",
            evidence_ids=("E1", "E2"), hypothesis_ids=("H2",),
        ), actor="critic", expected_revision=current.metadata.case_revision,
    )


def reframe_output(case, operation):
    payload = initial_output(case)
    changed_id = "H4" if operation == "add" else "H2"
    payload["hypotheses"] = [{
        "hypothesis_id": changed_id, "operation": operation,
        "title": "Conditional response mechanism",
        "mechanism_statement": "The C response may depend jointly on the A and B states in K562 cells after perturbation X.",
        "mechanism_type": "conditional_response",
        "derived_from_clue_id": case.clue.clue_id,
        "derived_from": [
            {"object_type": "hypothesis", "object_id": "H2"},
            {"object_type": "evidence", "object_id": "E1"},
            {"object_type": "evidence_gap", "object_id": "G1"},
        ],
        "reason": "The supplied evidence leaves the conditional response unexplained.",
        "assumptions": ["A and B joint-state contexts can be compared in the supplied dataset."],
        "unresolved_points": ["Whether the conditional response is reproducible remains unknown."],
        "weakening_conditions": ["The C response is identical across adequately measured A and B joint states."],
        "structure": {
            "causal_structure": "conditional_response", "directness": "unspecified",
            "cell_state_explanation": False, "conditional_dependence": True,
            "directed_edges": [],
        },
    }]
    payload["predictions"] = [{
        "prediction_id": "P4", "hypothesis_id": changed_id,
        "statement": "The C response should differ between the A+B- and other A/B joint-state contexts.",
        "expected_if_true": "The conditional C frequency difference should persist after matching cell-state proportions.",
        "weakened_if_observed": "The C response is identical across the measured A/B joint-state contexts.",
        "discriminates_from_hypotheses": ["H1", "H3"],
    }]
    payload["evidence_questions"] = [{
        "question_id": "Q4",
        "question_text": "Does the C response vary across A/B joint-state contexts after matching cell-state proportions in K562 cells?",
        "derived_from_prediction_ids": ["P4"], "relevant_hypothesis_ids": [changed_id, "H1", "H3"],
        "discriminates_between": [changed_id, "H1", "H3"], "suggested_evidence_type": "dataset",
    }]
    payload["contrasts"] = [
        {"hypothesis_a": changed_id, "hypothesis_b": other,
         "difference": difference}
        for other, difference in (
            ("H1", "Joint-state conditional response versus a shared upstream connection."),
            ("H3", "Conditional response within matched cells versus changing cell-state proportions."),
        )
    ]
    if operation == "add":
        payload["contrasts"].append({
            "hypothesis_a": "H4", "hypothesis_b": "H2",
            "difference": "Conditional dependence on joint states versus a sequential directed cascade.",
        })
    return payload


@pytest.mark.parametrize('reference_kind', ['revision_request', 'hypothesis'])
def test_critic_request_is_valid_typed_reframe_lineage(store, case, reference_kind):
    from jure.casefile.critic_models import RevisionRequest
    before = investigated_case(store, case)
    request = RevisionRequest(request_id='RR_TEST', reason='Revise the testable alternatives.',
                              affected_hypothesis_ids=('H2',), evidence_that_triggered_reframe=('E1',))
    before = store.append_critic_records(case.metadata.case_id, revision_requests=(request,),
        actor='critic', expected_revision=before.metadata.case_revision)
    payload = reframe_output(before, 'add')
    payload['hypotheses'][0]['derived_from'] = [{'object_type': reference_kind, 'object_id': 'RR_TEST'}]
    result, after = execute(store, before, payload, mode='reframe', reframe_reason=request.reason)
    if reference_kind == 'revision_request':
        assert result.success, result.validation_errors
        assert after.hypotheses[-1].current_revision.derived_from[-1].object_id == 'RR_TEST'
        assert after.evidence_records == before.evidence_records
    else:
        assert not result.success and any('invalid lineage' in e for e in result.validation_errors)
        assert after.hypotheses == before.hypotheses


def test_critic_request_does_not_ground_new_molecular_names(store, case):
    from jure.casefile.critic_models import RevisionRequest
    before = investigated_case(store, case)
    request = RevisionRequest(request_id='RR_TEST', reason='Consider the unsourced XYZZY9 name.',
                              affected_hypothesis_ids=('H2',))
    before = store.append_critic_records(case.metadata.case_id, revision_requests=(request,),
        actor='critic', expected_revision=before.metadata.case_revision)
    payload = reframe_output(before, 'add')
    payload['hypotheses'][0]['derived_from'] = [{'object_type': 'revision_request', 'object_id': 'RR_TEST'}]
    payload['hypotheses'][0]['title'] = 'Possible XYZZY9 mechanism'
    result, after = execute(store, before, payload, mode='reframe', reframe_reason=request.reason)
    assert not result.success and any('XYZZY9' in e for e in result.validation_errors)
    assert not any('invalid lineage' in e for e in result.validation_errors)
    assert after.hypotheses == before.hypotheses


def test_missing_comparison_feedback_identifies_unchanged_hypothesis(store,case):
    before=investigated_case(store,case)
    payload=reframe_output(before,'add')
    payload['contrasts']=[c for c in payload['contrasts'] if c['hypothesis_b']!='H3']
    result,after=execute(store,before,payload,mode='reframe',reframe_reason='Unit comparison request')
    assert not result.success
    assert any("('H3', 'H4')" in e and 'Unchanged, non-rejected' in e for e in result.validation_errors)
    assert after.hypotheses==before.hypotheses


@pytest.mark.parametrize('basis', ['completed', 'started'])
def test_failed_reframe_retry_obeys_declared_round_basis(store, case, basis):
    from jure.casefile.history import agent_round_counts
    before = investigated_case(store, case)
    before = store.append_history_event(case.metadata.case_id, actor='critic',
        expected_revision=before.metadata.case_revision, action='FINAL_CRITIC_AUDIT_STARTED',
        summary='Unit budget snapshot', metadata={'budget_state': {
            'explorer_reframes': 0, 'explorer_reframes_remaining': 1}})
    valid = reframe_output(before, 'add'); invalid = deepcopy(valid)
    invalid['observation_interpretation'] = 'Invalid unit output'
    backend = MockExplorerBackend([invalid, valid])
    agent = MechanismExplorer(backend, ExplorerConfig(max_retries=0, round_budget_basis=basis))
    first = agent.run(store, case.metadata.case_id, mode='reframe', reframe_reason='Unit audit request')
    assert not first.success
    second = agent.run(store, case.metadata.case_id, mode='reframe', reframe_reason='Unit audit request')
    assert second.success == (basis == 'completed'), second.validation_errors
    if second.success:
        counts = agent_round_counts(store.load_case(case.metadata.case_id), 'explorer', mode='reframe')
        assert counts == {'started': 2, 'completed': 1, 'failed': 1}
        third = agent.run(store, case.metadata.case_id, mode='reframe', reframe_reason='Unit audit request')
        assert not third.success and any('budget exhausted' in e for e in third.validation_errors)
        assert len(backend.calls) == 2


@pytest.mark.parametrize("operation", ["add", "revise"])
def test_synthetic_7_reframe_preserves_history_and_creates_traceable_changes(store, case, operation):
    before = investigated_case(store, case)
    backend = MockExplorerBackend([reframe_output(before, operation)])
    reason = "Existing hypotheses do not explain observation D in the supplied evidence."
    result = MechanismExplorer(backend, ExplorerConfig(max_retries=0)).run(
        store, case.metadata.case_id, mode="reframe", reframe_reason=reason,
    )
    assert result.success, result.validation_errors
    after = store.load_case(case.metadata.case_id)
    old_hypotheses = {h.hypothesis_id: h for h in before.hypotheses}
    new_hypotheses = {h.hypothesis_id: h for h in after.hypotheses}
    assert old_hypotheses.keys() <= new_hypotheses.keys()
    assert after.investigation_history[:len(before.investigation_history)] == before.investigation_history
    assert after.evidence_records == before.evidence_records
    assert after.evidence_gaps == before.evidence_gaps
    assert after.contradictions == before.contradictions
    changed_id = "H4" if operation == "add" else "H2"
    changed = new_hypotheses[changed_id]
    assert any(ref.object_type == "hypothesis" and ref.object_id == "H2"
               for ref in changed.current_revision.derived_from)
    assert changed.predictions[-1].hypothesis_revision_id == changed.current_revision_id
    assert after.evidence_questions[-1].derived_from_prediction_ids == ("P4",)
    if operation == "add":
        assert result.created_hypothesis_ids == ("H4",)
        assert result.revised_hypothesis_ids == ()
        assert "HYPOTHESIS_ADDED_AFTER_REFRAME" in events(after)
    else:
        assert result.created_hypothesis_ids == ()
        assert result.revised_hypothesis_ids == ("H2",)
        assert changed.revisions[:-1] == old_hypotheses["H2"].revisions
        assert changed.current_revision.supersedes_revision_id == old_hypotheses["H2"].current_revision_id
        assert changed.current_revision.reason
        assert changed.predictions[:-1] == old_hypotheses["H2"].predictions
        assert "HYPOTHESIS_REVISED" in events(after)
    context_text = json.dumps(backend.calls[0]["context"])
    for required in ("E1", "E2", "G1", "C1", reason):
        assert required in context_text


def test_synthetic_8_complete_clue_serialization_is_immutable(store, case):
    original_clue = case.clue.model_dump_json()
    result, after = execute(store, case, initial_output(case))
    assert result.success, result.validation_errors
    assert after.clue.model_dump_json() == original_clue
    assert "detected" in result.observation_interpretation
    assert "undetected" in result.observation_interpretation
    assert "upregulated" not in result.observation_interpretation.lower()
    assert "downregulated" not in result.observation_interpretation.lower()


@pytest.mark.parametrize("invalid_kind", ["malformed_json", "missing_hypothesis", "missing_prediction", "invalid_id"])
def test_backend_validation_failures_retry_once_without_partial_writes(store, case, invalid_kind):
    invalid = initial_output(case)
    if invalid_kind == "malformed_json":
        invalid = '{"hypotheses": ['
    elif invalid_kind == "missing_hypothesis":
        invalid["hypotheses"] = []
    elif invalid_kind == "missing_prediction":
        invalid["predictions"] = invalid["predictions"][:-1]
    else:
        invalid["predictions"][0]["hypothesis_id"] = "H_MISSING"
    backend = MockExplorerBackend([invalid, initial_output(case)])
    result = MechanismExplorer(backend, ExplorerConfig(max_retries=1)).run(store, case.metadata.case_id)
    assert result.success, result.validation_errors
    assert result.attempts == 2
    assert backend.calls[1]["feedback"]
    after = store.load_case(case.metadata.case_id)
    assert len(after.hypotheses) == 3
    assert len(after.evidence_questions) == 3


def test_retry_exhaustion_saves_failure_artifact_without_proposals(store, case, tmp_path):
    backend = MockExplorerBackend(["not json"] * 5)
    result = MechanismExplorer(backend, ExplorerConfig(max_retries=2)).run(
        store, case.metadata.case_id, artifact_dir=tmp_path / "runs",
    )
    assert not result.success
    assert result.attempts == len(backend.calls) == 3
    assert result.created_hypothesis_ids == ()
    assert result.committed_case_revision is None
    after = store.load_case(case.metadata.case_id)
    assert_no_proposals(after)
    assert events(after)[-1] == "EXPLORER_FAILED"
    assert json.loads(Path(result.artifact_path).read_text())["success"] is False
    assert after.investigation_history[-1].metadata["run_artifact"]["validation_errors"]


def test_failure_at_final_handoff_rolls_back_all_proposals(store, case, monkeypatch):
    actual_set_action_state = store.set_action_state

    def fail_after_handoff(*args, **kwargs):
        actual_set_action_state(*args, **kwargs)
        raise RuntimeError("simulated failure after the final write")

    monkeypatch.setattr(store, "set_action_state", fail_after_handoff)
    result, after = execute(store, case, initial_output(case))
    assert not result.success
    assert any("simulated failure" in error for error in result.validation_errors)
    assert result.created_hypothesis_ids == ()
    assert_no_proposals(after)
    assert after.clue == case.clue
    assert "HYPOTHESIS_CREATED" not in events(after)
    assert "EXPLORER_COMPLETED" not in events(after)
    with CaseStore(store.path) as reopened:
        assert reopened.load_case(case.metadata.case_id) == after


def test_concurrent_case_change_during_reasoning_is_preserved_and_not_retried(store, case):
    def concurrently_written_response(mode, context, feedback):
        with CaseStore(store.path) as other:
            latest = other.load_case(case.metadata.case_id)
            other.append_history_event(
                case.metadata.case_id, summary="Independent investigator annotation",
                actor="investigator", expected_revision=latest.metadata.case_revision,
            )
        return initial_output(case)

    backend = MockExplorerBackend(concurrently_written_response)
    result = MechanismExplorer(backend).run(store, case.metadata.case_id)
    assert not result.success
    assert len(backend.calls) == 1
    assert any("RevisionConflict" in error for error in result.validation_errors)
    after = store.load_case(case.metadata.case_id)
    assert_no_proposals(after)
    assert any(event.summary == "Independent investigator annotation" for event in after.investigation_history)
    assert after.investigation_history[:len(case.investigation_history)] == case.investigation_history


def test_case_store_atomic_batch_reverts_earlier_successful_commands(store, case):
    with pytest.raises(ValueError):
        with store.atomic(case.metadata.case_id, expected_revision=case.metadata.case_revision) as current:
            current = store.add_mechanistic_question(
                case.metadata.case_id, MechanisticQuestion(
                    question_id="MQ_ATOMIC", question_text="What explains this shift?",
                    derived_from_clue_id=case.clue.clue_id,
                ), actor="explorer", expected_revision=current.metadata.case_revision,
            )
            store.add_evidence_question(
                case.metadata.case_id, EvidenceQuestion(
                    question_id="Q_ATOMIC", question_text="A question with an invalid reference",
                    derived_from_prediction_ids=("P_MISSING",),
                ), actor="explorer", expected_revision=current.metadata.case_revision,
            )
    assert store.load_case(case.metadata.case_id) == case


def test_repeated_initial_and_reframe_without_reason_fail_before_backend(store, case):
    result, after = execute(store, case, initial_output(case))
    assert result.success, result.validation_errors
    for mode in ("initial", "reframe"):
        backend = MockExplorerBackend([])
        result = MechanismExplorer(backend).run(store, case.metadata.case_id, mode=mode)
        assert not result.success
        assert backend.calls == []
        current = store.load_case(case.metadata.case_id)
        assert current.hypotheses == after.hypotheses
        assert current.evidence_questions == after.evidence_questions


def test_demo_runs_offline_and_exports_replayable_case(tmp_path):
    result, paths = run_demo(tmp_path / "demo")
    assert result.success
    case = load_case(paths["json"])
    assert case.action_state.next_actor == "investigator"
    assert case.evidence_records == ()
    assert load_case(paths["yaml"]) == case
    assert Path(result.artifact_path).is_file()


def test_case_change_before_started_audit_returns_failure_without_backend_call(store, case, monkeypatch):
    actual_append = store.append_history_event
    raced = False

    def append_with_competing_writer(case_id, **kwargs):
        nonlocal raced
        if kwargs["summary"] == "EXPLORER_STARTED" and not raced:
            raced = True
            with CaseStore(store.path) as other:
                latest = other.load_case(case_id)
                other.append_history_event(
                    case_id, summary="Concurrent write before Explorer startup audit",
                    actor="investigator", expected_revision=latest.metadata.case_revision,
                )
        return actual_append(case_id, **kwargs)

    monkeypatch.setattr(store, "append_history_event", append_with_competing_writer)
    backend = MockExplorerBackend([initial_output(case)])
    result = MechanismExplorer(backend).run(store, case.metadata.case_id)
    assert not result.success
    assert backend.calls == []
    assert result.attempts == 0
    assert any("RevisionConflict" in error for error in result.validation_errors)
    after = store.load_case(case.metadata.case_id)
    assert_no_proposals(after)
    assert any(event.summary == "Concurrent write before Explorer startup audit"
               for event in after.investigation_history)
    assert "EXPLORER_FAILED" in events(after) or result.warnings


def test_sqlite_error_at_final_handoff_rolls_back_and_returns_audited_failure(store, case, monkeypatch):
    actual_set_action_state = store.set_action_state

    def fail_after_handoff(*args, **kwargs):
        actual_set_action_state(*args, **kwargs)
        raise sqlite3.OperationalError("simulated SQLite failure after handoff")

    monkeypatch.setattr(store, "set_action_state", fail_after_handoff)
    result, after = execute(store, case, initial_output(case))
    assert not result.success
    assert any("OperationalError" in error for error in result.validation_errors)
    assert result.created_hypothesis_ids == ()
    assert_no_proposals(after)
    assert "EXPLORER_FAILED" in events(after)
    assert "EXPLORER_COMPLETED" not in events(after)
    assert "HYPOTHESIS_CREATED" not in events(after)
    with CaseStore(store.path) as reopened:
        assert reopened.load_case(case.metadata.case_id) == after


def test_failure_audit_sqlite_error_returns_failure_with_warning(store, case, monkeypatch):
    actual_append = store.append_history_event

    def fail_failure_audit(case_id, **kwargs):
        if kwargs["summary"] == "EXPLORER_FAILED":
            raise sqlite3.OperationalError("simulated persistent failure writing audit")
        return actual_append(case_id, **kwargs)

    monkeypatch.setattr(store, "append_history_event", fail_failure_audit)
    result, after = execute(store, case, "invalid JSON")
    assert not result.success
    assert result.validation_errors
    assert result.warnings
    assert any("audit" in warning.lower() for warning in result.warnings)
    assert_no_proposals(after)
