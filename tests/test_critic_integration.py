"""State-driven three-agent integration with real mock-tool acquisition.

The controller only dispatches ActionState.next_actor. Mock observations, not a
prescribed route sequence or call counter, determine Critic decisions.
"""
import hashlib
import json
from pathlib import Path

from jure.agents.critic import MechanismCritic
from jure.agents.explorer import MechanismExplorer, MockExplorerBackend
from jure.agents.explorer.demo import initial_output, synthetic_clue
from jure.agents.investigator import EvidenceInvestigator, InvestigatorConfig, MockInvestigatorBackend
from jure.agents.investigator.prioritization import prioritize_context
from jure.casefile import CaseStore, load_case, save_case, validate_case
from jure.casefile.history import verify_history
from jure.tools.evidence import EvidenceToolRegistry, MockLiteratureTool, MockNetworkTool


def _proposal_with_shared_necessary_prediction(case):
    proposal = initial_output(case)
    for h in proposal["hypotheses"]:
        hid = h["hypothesis_id"]
        h["mechanism_statement"] += " This explanation requires an X perturbation effect on A in K562 cells."
        h["weakening_conditions"].append("A sufficiently powered X intervention leaves A unchanged in K562 cells.")
        proposal["predictions"].append({
            "prediction_id": f"P_SHARED_{hid}", "hypothesis_id": hid,
            "statement": "The necessary directed effect X→A should alter A expression after X perturbation in K562 cells.",
            "expected_if_true": "Perturbing X should measurably alter A in a matched experiment.",
            "weakened_if_observed": "A sufficiently powered matched X perturbation leaves A unchanged.",
            # The three distinct original predictions still discriminate mechanisms.
            "discriminates_from_hypotheses": [other for other in ("H1", "H2", "H3") if other != hid],
        })
    proposal["evidence_questions"].append({
        "question_id": "Q_SHARED", "question_text": "Is X→A supported by a direct perturbation experiment in K562 cells?",
        "derived_from_prediction_ids": [f"P_SHARED_H{i}" for i in (1, 2, 3)],
        "relevant_hypothesis_ids": ["H1", "H2", "H3"], "discriminates_between": ["H1", "H2", "H3"],
        "suggested_evidence_type": "literature",
    })
    return proposal


def _reframe_from_evidence(context):
    evidence = [e for e in context["existing_evidence"]
                if e["negative_evidence_type"] == "explicit_null_result"]
    assert evidence, "Explorer must receive the actual observation triggering reframe"
    assert context.get("critic_revision_requests"), "Critic revision request must reach Explorer"
    return {
        "observation_interpretation": context["observation_interpretation_required"],
        "mechanistic_question": context["current_mechanistic_question"]["question_text"],
        "hypotheses": [{
            "hypothesis_id": "H4", "operation": "add", "title": "Alternate A to C response",
            "mechanism_type": "alternate_direct_response",
            "mechanism_statement": "A direct A to C response may contribute to the A+B-C+ shift after perturbation X in K562, without requiring the excluded X to A step.",
            "derived_from_clue_id": context["clue"]["clue_id"],
            "derived_from": [{"object_type": "evidence", "object_id": evidence[0]["evidence_id"]}],
            "reason": "A matched null observation challenges the shared X to A requirement; test an alternative A to C response.",
            "assumptions": ["An A to C response can operate without an X to A effect in this context."],
            "unresolved_points": ["Whether A perturbation changes C remains to be investigated."],
            "weakening_conditions": ["A sufficiently powered A perturbation has no effect on C in K562."],
            "structure": {"causal_structure": "alternate_direct_response", "directness": "direct",
                "cell_state_explanation": False, "conditional_dependence": False, "directed_edges": [["A", "C"]]},
        }],
        "predictions": [{
            "prediction_id": "P4", "hypothesis_id": "H4", "statement": "A→C should alter C expression after A perturbation in K562 cells.",
            "expected_if_true": "A perturbation should alter C even without the X to A step.",
            "weakened_if_observed": "A sufficiently powered A perturbation leaves C unchanged in K562.",
            "discriminates_from_hypotheses": ["H1", "H2", "H3"],
        }],
        "evidence_questions": [{
            "question_id": "Q4", "question_text": "Is A→C supported by a direct perturbation experiment in K562 cells?",
            "derived_from_prediction_ids": ["P4"], "relevant_hypothesis_ids": ["H4", "H1", "H2", "H3"],
            "discriminates_between": ["H4", "H1", "H2", "H3"], "suggested_evidence_type": "literature",
        }],
        "contrasts": [{"hypothesis_a": "H4", "hypothesis_b": hid, "difference": difference}
            for hid, difference in (
                ("H1", "A to C direct response without the X to A requirement versus a shared upstream mechanism requiring that step."),
                ("H2", "A to C direct response versus an A to B to C cascade requiring X to A."),
                ("H3", "An A to C direct response within cells versus a shift in cell-state composition requiring X to A."),
            )],
    }


def _candidate(source, target, *, null):
    return {
        "paper_id": f"SYNTHETIC_{source}_{target}_{'NULL' if null else 'EFFECT'}",
        "title": "Supplied synthetic perturbation experiment", "year": 2026,
        "claim_tested": f"{source}→{target}", "experiment_identifier": f"synthetic_{source}_{target}",
        "experiment_type": "controlled perturbation", "perturbed_entity": source, "measured_entity": target,
        "observed_effect": f"{target} remained unchanged after {source} perturbation" if null else f"{target} decreased after {source} perturbation",
        "biological_context": "K562", "cell_type_or_model": "K562", "directness": "direct",
        "source_excerpt_or_summary": "Synthetic adequately powered matched perturbation experiment.",
        "source_reference": f"mock://three_agent/{source}/{target}",
        "source_quality": "primary_experiment", "support_quality": "sufficient",
        "negative_evidence_type": "explicit_null_result" if null else "not_applicable",
        "sufficient_power": True, "relation_effect": "challenges" if null else "supports",
        "limitations": ["Synthetic fixture only; not a real published experiment."],
    }


def _scientific_question_priority(context):
    """Dynamic acquisition priorities based on the unresolved scientific state."""
    result = prioritize_context(context).model_dump(mode="json")
    pending = {q["question_id"]: q for q in context["pending_questions"]}
    evidence = context.get("existing_evidence", ())
    novel = [q for q in pending.values() if "P4" in q.get("derived_from_prediction_ids", ())]
    shared = [q for q in pending.values() if len(q.get("derived_from_prediction_ids", ())) >= 3]
    networks = [q for q in pending.values() if q.get("suggested_evidence_type") == "network"]
    if novel and any(e["negative_evidence_type"] == "explicit_null_result" for e in evidence):
        selected, reason = novel[0], "A new hypothesis removes the experimentally excluded step; test its distinguishing prediction."
    elif shared and evidence:
        selected, reason = shared[0], "Network candidates cannot establish the necessary shared step; a matched experiment can challenge all current explanations."
    elif networks and not evidence:
        selected, reason = networks[0], "Survey candidate architecture before direct verification of its required components."
    else:
        return result
    result["selected_question_id"] = selected["question_id"]
    for assessment in result["assessments"]:
        if assessment["question_id"] == selected["question_id"]:
            assessment.update(priority_class="high", priority_reason=reason)
    result["assessments"].sort(key=lambda a: a["question_id"] != selected["question_id"])
    return result


def test_synthetic_14_three_agents_route_from_mock_observations(tmp_path):
    with CaseStore(tmp_path / "three_agents.sqlite") as store:
        case = store.create_case_from_clue(synthetic_clue(), cell_context="K562", source_dataset="synthetic_dataset")
        initial = _proposal_with_shared_necessary_prediction(case)
        explorer_backend = MockExplorerBackend(lambda mode, context, feedback:
            initial if mode == "initial" else _reframe_from_evidence(context))
        explorer = MechanismExplorer(explorer_backend)
        registry = EvidenceToolRegistry([MockNetworkTool(), MockLiteratureTool(verified_candidates=[
            _candidate("X", "A", null=True), _candidate("A", "C", null=False)])])
        investigator_backend = MockInvestigatorBackend(prioritize_questions=_scientific_question_priority)
        investigator = EvidenceInvestigator(backend=investigator_backend, registry=registry,
            config=InvestigatorConfig(max_new_followup_questions=0))
        critic = MechanismCritic()
        calls, routes, queue_snapshots = [], [], []
        # The bound is a test assertion against runaway control flow. Decisions
        # inside this loop exclusively come from the authoritative ActionState.
        for turn in range(15):
            before = store.load_case(case.metadata.case_id)
            if before.action_state.current_phase == "stopped":
                break
            actor = before.action_state.next_actor
            if not before.hypotheses:
                actor = "explorer"
            calls.append(actor)
            run_id = f"E2E_{turn}_{actor}"
            if actor == "explorer":
                if before.hypotheses:
                    request = before.critic_audits.revision_requests[-1]
                    result = explorer.run(store, case.metadata.case_id, mode="reframe",
                        reframe_reason=request.reason, artifact_dir=tmp_path / run_id)
                else:
                    result = explorer.run(store, case.metadata.case_id, artifact_dir=tmp_path / run_id)
            elif actor == "investigator":
                result = investigator.run(store, case.metadata.case_id, run_id=run_id, artifact_dir=tmp_path / run_id)
            elif actor == "critic":
                result = critic.run(store, case.metadata.case_id, run_id=run_id,
                    artifact_dir=tmp_path / run_id, available_capabilities=("network", "literature"))
            else:
                raise AssertionError(f"Unsupported next actor: {actor}")
            assert result.success, (actor, result.validation_errors)
            after = store.load_case(case.metadata.case_id)
            validate_case(after)
            verify_history(after)
            assert after.clue == before.clue
            assert after.investigation_history[:len(before.investigation_history)] == before.investigation_history
            if actor == "investigator":
                assert after.hypotheses == before.hypotheses
                assert after.mechanistic_question == before.mechanistic_question
            elif actor == "critic":
                assert after.evidence_records == before.evidence_records
                assert after.evidence_questions == before.evidence_questions
                assert {h.hypothesis_id for h in after.hypotheses} == {h.hypothesis_id for h in before.hypotheses}
                routes.append(after.critic_audits.routing_decisions[-1].route_to)
            else:
                assert after.evidence_records == before.evidence_records
            queue_snapshots.append({q.question_id: q.status for q in after.evidence_questions})
        else:
            raise AssertionError("The three-agent case did not terminate within its bounded loop")
        final = store.load_case(case.metadata.case_id)
        assert calls == ["explorer", "investigator", "critic", "investigator", "critic", "explorer", "investigator", "critic"]
        assert routes == ["investigator", "explorer", "stop"]
        assert queue_snapshots[0]["Q1"] == "pending"
        assert any(q.get("Q1") == "answered" for q in queue_snapshots)
        assert any(q.get("Q_SHARED") == "answered" for q in queue_snapshots)
        assert queue_snapshots[-1]["Q4"] == "answered"
        assert any("Q4" not in q for q in queue_snapshots)
        assert final.critic_audits.stop_records[-1].stop_type == "evidence_sufficient"
        assert final.critic_audits.final_reports[-1].uncertainty
        assert final.critic_audits.status_changes
        assert {s.new_status for s in final.critic_audits.status_changes} >= {"challenged", "supported"}
        assert len(final.hypotheses) == 4
        for evidence in final.evidence_records:
            raw = Path(evidence.raw_result_reference)
            assert raw.exists() and hashlib.sha256(raw.read_bytes()).hexdigest() == evidence.provenance.artifact_sha256
            assert json.loads(raw.read_text())["status"] == "success"
        assert load_case(save_case(final, tmp_path / "three_agent_case.json")) == final
        history_actions = [e.action for e in final.investigation_history]
        assert history_actions.count("CRITIC_COMPLETED") == 3
        assert history_actions.count("INVESTIGATOR_COMPLETED") == 3
        assert "ROUTE_TO_EXPLORER" in history_actions and "STOP_EVIDENCE_SUFFICIENT" in history_actions
        assert any(call["mode"] == "reframe" for call in explorer_backend.calls)
        assert any(call["context"].get("critic_investigation_requests") for call in investigator_backend.calls)


def test_critic_budget_caps_next_investigator_multistep_plan(tmp_path):
    from jure.agents.critic import CriticConfig
    from jure.agents.critic.demo import create_case
    with CaseStore(tmp_path / "budget.sqlite") as store:
        case = create_case(store)
        registry = EvidenceToolRegistry([MockNetworkTool(), MockLiteratureTool()])
        first = EvidenceInvestigator(registry=registry, config=InvestigatorConfig(max_new_followup_questions=0)).run(
            store, case.metadata.case_id, artifact_dir=tmp_path / "first")
        assert first.success and len(first.tool_calls) == 1
        critic = MechanismCritic(config=CriticConfig(max_total_tool_calls=2))
        audit = critic.run(store, case.metadata.case_id, run_id="C_GLOBAL_BUDGET")
        assert audit.success, audit.validation_errors
        before = store.load_case(case.metadata.case_id)
        assert before.critic_audits.investigation_requests
        def choose_cascade(context):
            response = prioritize_context(context).model_dump(mode="json")
            response["selected_question_id"] = "Q2"
            return response
        def plan_both_cascade_steps(context, question_id):
            response = MockInvestigatorBackend().operationalize_question(context, question_id)
            response["planned_operations"] = [
                {"operation": "search_regulatory_relation", "evidence_type": "literature",
                 "inputs": {"source_gene": source, "target_gene": target, "context": "K562"}}
                for source, target in (("A", "B"), ("B", "C"))]
            return response
        investigator = EvidenceInvestigator(registry=registry,
            backend=MockInvestigatorBackend(prioritize_questions=choose_cascade,
                                            operationalize_question=plan_both_cascade_steps),
            config=InvestigatorConfig(max_tool_calls_per_run=3, max_new_followup_questions=0))
        second = investigator.run(store, case.metadata.case_id, artifact_dir=tmp_path / "second")
        assert second.success, second.validation_errors
        assert len(second.query_plans[0]["planned_operations"]) == 2
        assert len(second.tool_calls) == 1, "The remaining global budget must cap the local multi-step plan"
        after = store.load_case(case.metadata.case_id)
        assert sum(e.action == "TOOL_CALL_STARTED" for e in after.investigation_history) == 2
        assert any(e.action == "BUDGET_REACHED" for e in after.investigation_history)
        final = critic.run(store, case.metadata.case_id, run_id="C_GLOBAL_FINAL")
        assert final.success, final.validation_errors
        stopped = store.load_case(case.metadata.case_id)
        assert stopped.critic_audits.stop_records[-1].stop_reason == "budget_exhausted"
        count = sum(e.action == "TOOL_CALL_STARTED" for e in stopped.investigation_history)
        blocked = investigator.run(store, case.metadata.case_id, artifact_dir=tmp_path / "blocked")
        assert not blocked.success and not blocked.tool_calls
        assert sum(e.action == "TOOL_CALL_STARTED" for e in store.load_case(case.metadata.case_id).investigation_history) == count


def test_investigator_consumes_critic_request_and_owns_queue_changes(tmp_path):
    from jure.agents.critic.demo import create_case
    with CaseStore(tmp_path / "request.sqlite") as store:
        case = create_case(store)
        registry = EvidenceToolRegistry([MockNetworkTool(), MockLiteratureTool()])
        initial = EvidenceInvestigator(registry=registry,
            config=InvestigatorConfig(max_new_followup_questions=0)).run(store, case.metadata.case_id,
                                                                        artifact_dir=tmp_path / "initial")
        assert initial.success
        pre_critic = store.load_case(case.metadata.case_id)
        audit = MechanismCritic().run(store, case.metadata.case_id)
        assert audit.success, audit.validation_errors
        pre_investigator = store.load_case(case.metadata.case_id)
        assert pre_investigator.evidence_questions == pre_critic.evidence_questions
        request = pre_investigator.critic_audits.investigation_requests[-1]
        assert request.target_gap_ids and request.target_claim_ids
        backend = MockInvestigatorBackend()
        result = EvidenceInvestigator(registry=registry, backend=backend).run(store, case.metadata.case_id,
                                                                              artifact_dir=tmp_path / "requested")
        assert result.success, result.validation_errors
        after = store.load_case(case.metadata.case_id)
        assert any(call["context"].get("critic_investigation_requests") for call in backend.calls)
        assert after.hypotheses == pre_investigator.hypotheses
        assert after.evidence_questions != pre_investigator.evidence_questions
        existing_ids = {q.question_id for q in pre_investigator.evidence_questions}
        new_questions = [q for q in after.evidence_questions if q.question_id not in existing_ids]
        assert new_questions
        assert all(q.created_by in {"investigator", "evidence_investigator"} for q in new_questions)
        validate_case(after)
        verify_history(after)


def test_failed_acquisition_still_consumes_global_tool_budget(tmp_path):
    """An executed acquisition costs budget even when interpretation rolls back."""
    from jure.agents.critic import CriticConfig
    from jure.agents.critic.demo import create_case

    executions = []

    class CountingNetwork(MockNetworkTool):
        def query_shared_regulators(self, target_genes, context=None):
            executions.append(tuple(target_genes))
            return super().query_shared_regulators(target_genes, context=context)

    with CaseStore(tmp_path / "failed_acquisition_budget.sqlite") as store:
        case = create_case(store)
        investigator = EvidenceInvestigator(
            registry=EvidenceToolRegistry([CountingNetwork()]),
            backend=MockInvestigatorBackend(interpret_tool_result={"hypotheses": [{"status": "supported"}]}))
        failed = investigator.run(store, case.metadata.case_id, run_id="I_EXECUTED_THEN_FAILED",
                                  artifact_dir=tmp_path / "failed")
        assert not failed.success and failed.validation_errors
        assert len(executions) == len(failed.tool_calls) == 1
        after_failure = store.load_case(case.metadata.case_id)
        assert not after_failure.evidence_records
        assert not any(e.action == "TOOL_CALL_STARTED" for e in after_failure.investigation_history)
        assert after_failure.investigation_history[-1].action == "INVESTIGATOR_FAILED"
        assert len(after_failure.investigation_history[-1].metadata["run_artifact"]["tool_calls"]) == 1

        audit = MechanismCritic(config=CriticConfig(max_total_tool_calls=1)).run(
            store, case.metadata.case_id, run_id="C_COUNTS_FAILED_TOOL")
        assert audit.success, audit.validation_errors
        stopped = store.load_case(case.metadata.case_id)
        final_audit = next(e for e in reversed(stopped.investigation_history)
                           if e.action == "FINAL_CRITIC_AUDIT_STARTED")
        assert final_audit.metadata["budget_state"]["total_tool_calls"] == 1
        assert final_audit.metadata["budget_state"]["tool_calls_remaining"] == 0
        assert stopped.critic_audits.stop_records[-1].stop_type == "evidence_limited"
        assert stopped.critic_audits.stop_records[-1].stop_reason == "budget_exhausted"
        assert stopped.action_state.current_phase == "stopped"

        blocked = investigator.run(store, case.metadata.case_id, run_id="I_BLOCKED_AFTER_FAILED_BUDGET",
                                   artifact_dir=tmp_path / "blocked")
        assert not blocked.success and not blocked.tool_calls
        assert len(executions) == 1, "Rolled-back acquisitions must not permit another physical tool execution"
        verify_history(store.load_case(case.metadata.case_id))


def test_investigator_guard_uses_critic_completed_round_policy(tmp_path):
    from jure.agents.critic import CriticConfig
    from jure.agents.critic.demo import create_case
    from jure.casefile.history import agent_round_counts
    with CaseStore(tmp_path/'round_recovery.sqlite') as store:
        case=create_case(store)
        # An empty priority response is a legal no-selection result. Use an
        # unassessed selection to exercise actual failed attempts and budget recovery.
        invalid=EvidenceInvestigator(backend=MockInvestigatorBackend(
            prioritize_questions={'selected_question_id': 'UNKNOWN_UNASSESSED'}))
        for index in range(2):
            result=invalid.run(store,case.metadata.case_id,run_id=f'FAILED_{index}',artifact_dir=tmp_path/f'failed_{index}')
            assert not result.success and not result.tool_calls
        critic=MechanismCritic(config=CriticConfig(round_budget_basis='completed',max_investigator_rounds=1))
        result=critic.run(store,case.metadata.case_id,run_id='AFTER_FAILURES')
        assert result.success, result.validation_errors
        audited=store.load_case(case.metadata.case_id)
        assert audited.action_state.next_actor=='investigator'
        budget=next(e.metadata['budget_state'] for e in reversed(audited.investigation_history)
                    if e.action=='FINAL_CRITIC_AUDIT_STARTED')
        assert budget['investigator_rounds']==0 and budget['investigator_rounds_remaining']==1
        investigator=EvidenceInvestigator(registry=EvidenceToolRegistry([MockNetworkTool(),MockLiteratureTool()]))
        result=investigator.run(store,case.metadata.case_id,run_id='VALID_RETRY',artifact_dir=tmp_path/'valid')
        assert result.success and result.tool_calls, result.validation_errors
        final=store.load_case(case.metadata.case_id)
        assert agent_round_counts(final,'investigator')=={'started':3,'completed':1,'failed':2}
        blocked=investigator.run(store,case.metadata.case_id,run_id='NO_MORE_ROUNDS',artifact_dir=tmp_path/'blocked')
        assert not blocked.success and not blocked.tool_calls
        assert any('budget exhausted' in e for e in blocked.validation_errors)
