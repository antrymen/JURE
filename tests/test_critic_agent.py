"""The thirteen individual synthetic scenarios and transactional boundaries."""
import json

import pytest

from jure.agents.critic import CriticConfig, MechanismCritic, MockCriticBackend
from jure.agents.critic.context import build_critic_context
from jure.agents.critic.demo import add_synthetic_evidence, create_case, sufficient_case
from jure.casefile import CaseStore, EvidenceQuestion, PredictionRecord, load_case, save_case, validate_case
from jure.casefile.history import verify_history


@pytest.fixture
def explored(tmp_path):
    with CaseStore(tmp_path / "case.sqlite") as store:
        yield store, create_case(store)


def run_audit(store, case, tmp_path, *, backend=None, config=None, run_id=None, capabilities=None):
    agent = MechanismCritic(backend=backend, config=config)
    result = agent.run(store, case.metadata.case_id, run_id=run_id,
                       artifact_dir=tmp_path / (run_id or "critic"),
                       available_capabilities=("dataset", "network", "literature") if capabilities is None else capabilities)
    assert result.success, result.validation_errors
    after = store.load_case(case.metadata.case_id)
    assert after.clue == case.clue
    assert after.evidence_records == case.evidence_records
    assert after.mechanistic_question == case.mechanistic_question
    assert after.evidence_questions == case.evidence_questions
    assert after.investigation_history[:len(case.investigation_history)] == case.investigation_history
    for old, new in zip(case.hypotheses, after.hypotheses):
        assert new.predictions == old.predictions
        assert new.current_revision_id == old.current_revision_id
        assert new.current_revision.model_dump(exclude={"status"}) == old.current_revision.model_dump(exclude={"status"})
    validate_case(after)
    verify_history(after)
    return result, after


def states(case):
    return {h.hypothesis_id: h.current_revision.status for h in case.hypotheses}


def route(case):
    return case.critic_audits.routing_decisions[-1].route_to


def test_unexplored_source_returns_to_investigator_and_keeps_review(explored, tmp_path):
    from jure.agents.critic.backend import StopEvaluation
    from jure.casefile.critic_models import SourceReview
    from jure.agents.investigator.context import build_investigator_context
    store, case = explored
    class SourceBlindStop(MockCriticBackend):
        def evaluate_stop(self, context):
            assert context['source_review_targets']
            return StopEvaluation(no_further_queries=True, limitation_kind='capability',
                reason='Fixture attempts an incorrect RNA-only STOP.', source_reviews=tuple(
                    SourceReview(target_id=t['target_id'], source='literature',
                        evidence_need='Known experimental mechanism connection',
                        status='SOURCE_UNEXPLORED', rationale='Suitable source has not been investigated.')
                    for t in context['source_review_targets']))
    _, after = run_audit(store, case, tmp_path, backend=SourceBlindStop(),
        config=CriticConfig(source_aware_stopping=True))
    assert route(after) == 'investigator'
    assert not after.critic_audits.stop_records
    review = build_investigator_context(after)['latest_source_review']
    assert review['enforced'] and review['unexplored_target_ids']


def test_legacy_scope_defaults_preserve_history_and_detect_tampering(explored, tmp_path):
    store, case = explored
    _, after = run_audit(store, case, tmp_path)
    raw = after.model_dump(mode='json')
    def strip(section):
        audits=section.get('critic_audits', {})
        for record in audits.get('evidence_audits', []):
            for key in ('mechanism_support','case_specific_support','context_transferability'):
                record.pop(key, None)
        for record in audits.get('stop_records', []):
            record.pop('source_reviews', None)
    strip(raw)
    for event in raw['investigation_history']:
        strip(event['changes']['before']); strip(event['changes']['after'])
    before=json.dumps(raw['investigation_history'], sort_keys=True)
    restored=validate_case(raw)
    verify_history(restored)
    assert json.dumps(raw['investigation_history'], sort_keys=True)==before
    # Compatibility fills missing defaults only, never excuses a scientific edit.
    tampered=restored.model_copy(update={'mechanistic_claims': tuple(
        c.model_copy(update={'statement': 'Unrecorded scientific change'})
        for c in restored.mechanistic_claims)})
    with pytest.raises(ValueError, match='snapshot does not match'):
        verify_history(tampered)


def test_synthetic_01_hypothesis_pass_enters_evidence_audit(explored, tmp_path):
    store, case = explored
    backend = MockCriticBackend()
    result, after = run_audit(store, case, tmp_path, backend=backend)
    assert after.critic_audits.hypothesis_audits[-1].overall_status == "pass"
    assert after.mechanistic_claims and result.claim_audit_ids
    assert route(after) == "investigator"
    methods = [call["method"] for call in backend.calls]
    assert methods.index("audit_hypotheses") < methods.index("decompose_claims") < methods.index("audit_evidence")
    assert methods.index("audit_evidence") < methods.index("attribute_failure") < methods.index("decide_route")


def test_failed_critic_attempt_does_not_consume_completed_audit_round(explored):
    from jure.agents.explorer.context import explorer_write_contract
    from jure.agents.explorer.models import ExplorerConfig
    store,case=explored
    config=CriticConfig(round_budget_basis='completed')
    failed=MechanismCritic(MockCriticBackend(audit_hypotheses={}),config).run(store,case.metadata.case_id)
    assert not failed.success and failed.critic_round==1
    backend=MockCriticBackend()
    contract=explorer_write_contract(ExplorerConfig(round_budget_basis='completed'))
    completed=MechanismCritic(backend,config).run(store,case.metadata.case_id,explorer_contract=contract)
    assert completed.success and completed.critic_round==1, completed.validation_errors
    assert all(call['context']['explorer_write_contract']==contract for call in backend.calls)


def _revise_as_duplicate(store, case, hypothesis_id):
    source = case.hypotheses[0].current_revision
    case = store.update_hypothesis(case.metadata.case_id, hypothesis_id,
        mechanism_statement=source.mechanism_statement, mechanism_type=source.mechanism_type,
        weakening_conditions=source.weakening_conditions, reason="Synthetic duplicate mechanism fixture.",
        actor="explorer", expected_revision=case.metadata.case_revision)
    hypothesis = next(h for h in case.hypotheses if h.hypothesis_id == hypothesis_id)
    source_p = case.hypotheses[0].predictions[0]
    prediction = PredictionRecord(prediction_id=f"P_DUP_{hypothesis_id}", hypothesis_id=hypothesis_id,
        hypothesis_revision_id=hypothesis.current_revision_id, statement=source_p.statement,
        expected_if_true=source_p.expected_if_true, weakened_if_observed=source_p.weakened_if_observed,
        discriminates_from_hypotheses=tuple(h.hypothesis_id for h in case.hypotheses if h.hypothesis_id != hypothesis_id))
    case = store.add_prediction(case.metadata.case_id, prediction, actor="explorer", expected_revision=case.metadata.case_revision)
    return store.add_evidence_question(case.metadata.case_id, EvidenceQuestion(
        question_id=f"Q_DUP_{hypothesis_id}", question_text="Does shared upstream connectivity explain A/B/C?",
        derived_from_prediction_ids=(prediction.prediction_id,),
        relevant_hypothesis_ids=(hypothesis_id, "H1"), discriminates_between=(hypothesis_id, "H1"),
        suggested_evidence_type="network"), actor="explorer", expected_revision=case.metadata.case_revision)


@pytest.mark.parametrize('protocol_v3', [False, True])
def test_synthetic_02_redundancy_routes_explorer_without_c2(explored, tmp_path, protocol_v3):
    store, case = explored
    case = _revise_as_duplicate(store, case, "H2")
    backend = MockCriticBackend()
    _, after = run_audit(store, case, tmp_path, backend=backend,
                         config=CriticConfig(protocol_v3=protocol_v3), capabilities=[])
    assert route(after) == "explorer"
    assert after.action_state.current_phase == "exploration_needed"
    assert after.critic_audits.hypothesis_audits[-1].overall_status == "revision_required"
    assert after.critic_audits.revision_requests[-1].required_changes
    audit = after.critic_audits.hypothesis_audits[-1]
    request = after.critic_audits.revision_requests[-1]
    assert request.required_changes == tuple(dict.fromkeys(
        change for h in audit.per_hypothesis for change in h.required_revisions))
    assert request.reason == after.critic_audits.failure_attributions[-1].reason_summary
    assert "audit_evidence" not in [c["method"] for c in backend.calls]
    assert not after.mechanistic_claims


def test_synthetic_03_missing_alternative_requests_revision_without_h4(explored, tmp_path):
    from jure.agents.explorer import MechanismExplorer, MockExplorerBackend
    from jure.agents.explorer.demo import initial_output
    store, original = explored
    case = store.create_case_from_clue(original.clue, cell_context="K562")
    proposal = initial_output(case)
    for index, source, target in ((0, "A", "C"), (2, "C", "A")):
        proposal["hypotheses"][index].update(
            title=f"Direct {source} to {target} possibility", mechanism_type=f"direct_{source}_{target}",
            mechanism_statement=f"A direct {source} to {target} response may explain the A+B-C+ shift after perturbation X in K562.",
            structure={"causal_structure": f"direct_{source}_{target}", "directness": "direct",
                       "cell_state_explanation": False, "conditional_dependence": False,
                       "directed_edges": [[source, target]]})
        proposal["predictions"][index].update(
            statement=f"Perturbing {source} should alter {target} expression in K562.",
            expected_if_true=f"A direct {source} intervention should change {target} expression.",
            weakened_if_observed=f"A sufficiently powered {source} intervention leaves {target} unchanged.")
        proposal["evidence_questions"][index].update(
            question_text=f"Is {source}→{target} supported by matched direct perturbation evidence?",
            suggested_evidence_type="literature")
    proposal["hypotheses"][2].update(
        mechanism_statement="A reverse feedback architecture initiated by C, relayed through B, and returning to A may account for A+B-C+ prevalence after perturbation X in K562.",
        structure={"causal_structure": "reverse_feedback", "directness": "direct",
                   "cell_state_explanation": False, "conditional_dependence": False,
                   "directed_edges": [["C", "B"], ["B", "A"]]})
    proposal["predictions"][2].update(
        statement="C perturbation should affect B and subsequently A in the reverse feedback architecture.",
        expected_if_true="C perturbation changes B before A in the measured response.",
        weakened_if_observed="Matched C perturbation leaves both B and A responses unchanged.")
    proposal["evidence_questions"][2]["question_text"] = "Do direct experiments support C→B and B→A in K562?"
    proposal["contrasts"] = [
        {"hypothesis_a": "H1", "hypothesis_b": "H2", "difference": "Direct A to C versus the intermediate B cascade."},
        {"hypothesis_a": "H1", "hypothesis_b": "H3", "difference": "A to C direct response versus reverse C to B to A feedback."},
        {"hypothesis_a": "H2", "hypothesis_b": "H3", "difference": "A to B to C forward cascade versus reverse C to B to A feedback."},
    ]
    result = MechanismExplorer(MockExplorerBackend([proposal])).run(store, case.metadata.case_id)
    assert result.success, result.validation_errors
    case = store.load_case(case.metadata.case_id)
    _, after = run_audit(store, case, tmp_path)
    assert route(after) == "explorer"
    assert after.critic_audits.hypothesis_audits[-1].coverage_issues
    assert {h.hypothesis_id for h in after.hypotheses} == {"H1", "H2", "H3"}
    assert after.critic_audits.revision_requests[-1].issues
    assert not after.critic_audits.evidence_audits


def test_synthetic_04_network_only_has_critical_gap(explored, tmp_path):
    store, case = explored
    case = add_synthetic_evidence(store, case, source_type="grn", directness="indirect",
                                  source_quality="curated_database", support_quality="limited")
    _, after = run_audit(store, case, tmp_path)
    assert states(after)["H1"] == "partially_supported"
    assert route(after) == "investigator"
    assert any(g.critical and "H1" in g.related_hypotheses for g in after.evidence_gaps)
    assert after.critic_audits.investigation_requests


def test_synthetic_05_overclaim_preserves_original_evidence(explored, tmp_path):
    store, case = explored
    case = add_synthetic_evidence(store, case, source_type="grn", directness="direct",
        source_quality="curated_database", summary="GRN shows X→B, therefore X causally regulates B.")
    original = case.evidence_records[0]
    _, after = run_audit(store, case, tmp_path)
    audit = after.critic_audits.evidence_audits[0]
    assert audit.overclaim_detected
    assert audit.directness_assessment != "direct"
    assert audit.critic_interpretation
    assert after.evidence_records[0] == original
    assert any(e.action == "EVIDENCE_OVERCLAIM_DETECTED" for e in after.investigation_history)


def test_synthetic_06_direct_contradiction_never_supported(explored, tmp_path):
    store, case = explored
    case = add_synthetic_evidence(store, case, evidence_id="E_EFFECT")
    case = add_synthetic_evidence(store, case, relation="challenges", evidence_id="E_NULL")
    _, after = run_audit(store, case, tmp_path)
    assert states(after)["H1"] in {"challenged", "insufficient"}
    assert any(set(c.evidence_ids) >= {"E_EFFECT", "E_NULL"} for c in after.contradictions)
    assert route(after) == "investigator"


def test_synthetic_07_new_evidence_breaks_entire_space(explored, tmp_path):
    store, case = explored
    _, case = run_audit(store, case, tmp_path, run_id="C_BEFORE_BREAK")
    for hid in ("H1", "H2", "H3"):
        case = add_synthetic_evidence(store, case, hid, relation="challenges")
    _, after = run_audit(store, case, tmp_path, run_id="C_AFTER_BREAK")
    assert set(states(after).values()) == {"challenged"}
    assert route(after) == "explorer"
    assert after.critic_audits.routing_decisions[-1].reason_type == "hypothesis_space_inadequate"
    assert after.critic_audits.revision_requests[-1].evidence_that_triggered_reframe


def test_synthetic_08_sufficient_stop_preserves_uncertainty_and_counterevidence(explored, tmp_path):
    store, case = explored
    case = sufficient_case(store, case)
    result, after = run_audit(store, case, tmp_path)
    assert states(after) == {"H1": "supported", "H2": "challenged", "H3": "challenged"}
    stop = after.critic_audits.stop_records[-1]
    assert stop.stop_type == "evidence_sufficient" and stop.remaining_uncertainties
    assert stop.key_challenging_evidence_ids
    assert result.final_report_id and result.stop_record_id
    report = after.critic_audits.final_reports[-1]
    assert report.observation and report.interpretation and report.uncertainty
    assert "proven" not in report.overall_case_summary.casefold()


def test_synthetic_09_limited_stop_keeps_remaining_hypotheses_and_experiment(explored, tmp_path):
    store, case = explored
    for hid in ("H1", "H2"):
        case = add_synthetic_evidence(store, case, hid, source_type="grn", directness="indirect",
                                      source_quality="curated_database", support_quality="limited")
    _, after = run_audit(store, case, tmp_path, capabilities=())
    stop = after.critic_audits.stop_records[-1]
    assert stop.stop_type == "evidence_limited"
    assert stop.recommended_experiments and stop.unresolved_critical_gaps
    assert set(stop.remaining_hypotheses) >= {"H1", "H2"}
    assert stop.why_current_tools_cannot_resolve


def test_synthetic_10_generic_comentions_do_not_prevent_stall(explored, tmp_path):
    store, case = explored
    for index in range(3):
        case = add_synthetic_evidence(store, case, evidence_id=f"E_MENTION_{index}",
            directness="contextual", source_quality="secondary_source", support_quality="limited",
            claim_tested="Co-mention or contextual search hit", summary="A and B are mentioned together.")
        _, case = run_audit(store, case, tmp_path, run_id=f"C_STALL_{index}")
    assert case.critic_audits.progress_snapshots[-1].new_evidence_count == 0
    assert case.critic_audits.stop_records[-1].stop_type == "evidence_limited"
    assert case.critic_audits.stop_records[-1].stop_reason == "investigation_saturation"
    actions = [e.action for e in case.investigation_history]
    assert "INVESTIGATION_STALLED" in actions and "FINAL_CRITIC_AUDIT_STARTED" in actions


@pytest.mark.parametrize("enough", [False, True])
def test_synthetic_11_budget_triggers_final_audit_before_either_stop(explored, tmp_path, enough):
    store, case = explored
    if enough:
        case = sufficient_case(store, case)
    _, after = run_audit(store, case, tmp_path, config=CriticConfig(max_total_tool_calls=0))
    actions = [e.action for e in after.investigation_history]
    expected = "STOP_EVIDENCE_SUFFICIENT" if enough else "STOP_EVIDENCE_LIMITED"
    assert actions.index("FINAL_CRITIC_AUDIT_STARTED") < actions.index(expected)
    assert after.critic_audits.stop_records[-1].stop_type == ("evidence_sufficient" if enough else "evidence_limited")


def test_synthetic_12_one_unresolved_critical_component_caps_synthesis(explored, tmp_path):
    store, case = explored
    # H2 requires A→B and B→C; evidence of only A→B cannot resolve the cascade.
    case = add_synthetic_evidence(store, case, "H2", claim_tested="A regulates B")
    _, after = run_audit(store, case, tmp_path)
    claims = [c for c in after.mechanistic_claims if c.hypothesis_id == "H2"]
    assert len(claims) >= 2
    assert all(c.criticality_reason for c in claims if c.critical)
    assert any(c.status == "insufficient" for c in claims)
    assert states(after)["H2"] != "supported"
    assert any(g.critical and "H2" in g.related_hypotheses for g in after.evidence_gaps)


@pytest.mark.parametrize("forbidden", ["search_pubmed", "query_grn", "create_hypothesis", "clue", "evidence_records", "confidence"])
def test_synthetic_13_forbidden_backend_actions_rollback(explored, tmp_path, forbidden):
    store, case = explored
    backend = MockCriticBackend(audit_hypotheses={forbidden: {"value": "unauthorized"}})
    result = MechanismCritic(backend=backend).run(store, case.metadata.case_id,
        run_id=f"C_INVALID_{forbidden}", artifact_dir=tmp_path / forbidden)
    assert not result.success and result.validation_errors
    after = store.load_case(case.metadata.case_id)
    for section in ("clue", "hypotheses", "evidence_records", "evidence_questions", "mechanistic_question",
                    "mechanistic_claims", "evidence_gaps", "contradictions", "action_state", "critic_audits"):
        assert getattr(after, section) == getattr(case, section)
    assert [e.action for e in after.investigation_history[len(case.investigation_history):]] == ["CRITIC_STARTED", "CRITIC_FAILED"]
    verify_history(after)


def test_late_backend_failure_rolls_back_claims_gaps_and_statuses(explored, tmp_path):
    store, case = explored
    backend = MockCriticBackend(decide_route={"route_to": "investigator", "clue": {"delta": .9}})
    result = MechanismCritic(backend=backend).run(store, case.metadata.case_id, run_id="C_LATE_BAD")
    assert not result.success and result.validation_errors
    assert "audit_evidence" in [c["method"] for c in backend.calls]
    after = store.load_case(case.metadata.case_id)
    assert after.hypotheses == case.hypotheses
    assert after.mechanistic_claims == case.mechanistic_claims
    assert after.evidence_gaps == case.evidence_gaps
    assert after.critic_audits == case.critic_audits


def test_run_id_is_idempotent_and_artifacts_round_trip(explored, tmp_path):
    store, case = explored
    backend = MockCriticBackend()
    agent = MechanismCritic(backend=backend)
    first = agent.run(store, case.metadata.case_id, run_id="C_ONCE", artifact_dir=tmp_path / "exports")
    assert first.success, first.validation_errors
    after = store.load_case(case.metadata.case_id)
    calls = len(backend.calls)
    assert agent.run(store, case.metadata.case_id, run_id="C_ONCE", artifact_dir=tmp_path / "exports") == first
    assert len(backend.calls) == calls and store.load_case(case.metadata.case_id) == after
    assert load_case(save_case(after, tmp_path / "roundtrip.json")) == after
    for name in ("hypothesis_evidence_matrix.json", "hypothesis_evidence_matrix.csv", "investigation_trajectory.json"):
        paths = list((tmp_path / "exports").rglob(name))
        assert len(paths) == 1 and paths[0].read_text()
    trajectory = json.loads(next((tmp_path / "exports").rglob("investigation_trajectory.json")).read_text())
    assert trajectory


def test_context_is_stage_scoped_and_detached(explored):
    store, case = explored
    case = add_synthetic_evidence(store, case)
    c1 = build_critic_context(case, "hypothesis")
    assert "evidence_records" in c1 and "investigation_history" not in c1
    assert "source_payload" not in c1["clue"]
    c2 = build_critic_context(case, "evidence")
    assert c2["evidence_records"] and c2["provenance_summaries"]
    c2["hypotheses"][0]["current_revision"]["mechanism_statement"] = "mutated detached context"
    assert case.hypotheses[0].current_revision.mechanism_statement != "mutated detached context"


@pytest.mark.parametrize("quality", ["limited", "insufficient", "unknown"])
def test_low_support_never_promoted_to_supported(explored, tmp_path, quality):
    store, case = explored
    case = add_synthetic_evidence(store, case, support_quality=quality)
    _, after = run_audit(store, case, tmp_path)
    assert states(after)["H1"] != "supported"


def test_incomplete_provenance_cannot_fully_support_claim(explored, tmp_path):
    store, case = explored
    case = add_synthetic_evidence(store, case, complete_provenance=False)
    _, after = run_audit(store, case, tmp_path)
    assert states(after)["H1"] != "supported"
    assert after.critic_audits.evidence_audits[0].provenance_check != "complete"


def test_no_retrieved_evidence_is_not_a_challenge(explored, tmp_path):
    store, case = explored
    case = add_synthetic_evidence(store, case, relation="challenges", negative_evidence_type="not_found",
                                  summary="No publication was found for this relation.")
    _, after = run_audit(store, case, tmp_path)
    assert states(after)["H1"] == "insufficient"


def test_context_mismatch_does_not_establish_matched_challenge(explored, tmp_path):
    store, case = explored
    case = add_synthetic_evidence(store, case, relation="challenges", context_match="mismatched")
    _, after = run_audit(store, case, tmp_path)
    assert states(after)["H1"] not in {"supported", "challenged"}


def test_ten_contextual_papers_do_not_outvote_direct_challenge(explored, tmp_path):
    store, case = explored
    for index in range(10):
        case = add_synthetic_evidence(store, case, evidence_id=f"E_CONTEXTUAL_{index}",
            directness="contextual", source_quality="secondary_source", support_quality="limited")
    case = add_synthetic_evidence(store, case, relation="challenges", evidence_id="E_DIRECT_CHALLENGE")
    _, after = run_audit(store, case, tmp_path)
    assert states(after)["H1"] == "challenged"


def test_unknown_reference_in_claim_output_is_rejected(explored, tmp_path):
    store, case = explored
    def decompose(context):
        response = MockCriticBackend().decompose_claims(context)
        response["claims"][0]["derived_from_prediction_ids"] = ["P_DOES_NOT_EXIST"]
        return response
    result = MechanismCritic(backend=MockCriticBackend(decompose_claims=decompose)).run(store, case.metadata.case_id)
    assert not result.success and result.validation_errors
    assert not store.load_case(case.metadata.case_id).mechanistic_claims


def test_supported_hypothesis_can_be_challenged_by_new_direct_evidence(explored, tmp_path):
    store, case = explored
    case = add_synthetic_evidence(store, case, evidence_id="E_SUPPORT")
    _, supported = run_audit(store, case, tmp_path, run_id="C_SUPPORT")
    assert states(supported)["H1"] == "supported"
    challenged = add_synthetic_evidence(store, supported, evidence_id="E_CHALLENGE", relation="challenges")
    _, after = run_audit(store, challenged, tmp_path, run_id="C_CHALLENGE")
    assert states(after)["H1"] == "challenged"
    changes = [c for c in after.critic_audits.status_changes if c.hypothesis_id == "H1"]
    assert [(c.previous_status, c.new_status) for c in changes] == [
        ("proposed", "supported"), ("supported", "challenged")]
    assert all(c.claim_ids and c.evidence_ids and c.reason for c in changes)


def test_context_difference_is_recorded_instead_of_forcing_matched_contradiction(explored, tmp_path):
    store, case = explored
    case = add_synthetic_evidence(store, case, evidence_id="E_K562")
    case = add_synthetic_evidence(store, case, evidence_id="E_OTHER_CONTEXT", relation="challenges",
                                  context_match="mismatched")
    _, after = run_audit(store, case, tmp_path)
    contradiction = next(c for c in after.contradictions if set(c.evidence_ids) == {"E_K562", "E_OTHER_CONTEXT"})
    assert contradiction.potential_context_dependency
    assert contradiction.context_difference and contradiction.possible_explanations
    assert states(after)["H1"] != "challenged"


def test_progress_counts_gap_resolved_between_critic_calls(explored, tmp_path):
    from jure.agents.critic.stall_detection import progress_snapshot
    store, case = explored
    _, audited = run_audit(store, case, tmp_path)
    gap = audited.evidence_gaps[0]
    acquired = store.update_evidence_gap_status(case.metadata.case_id, gap.gap_id, 'addressed',
        actor='evidence_investigator', expected_revision=audited.metadata.case_revision)
    progress = progress_snapshot(acquired, acquired, 2, 'investigator')
    assert progress.resolved_gap_count == 1
    assert gap.gap_id in progress.resolved_gap_ids


def test_synthesis_rejects_invented_descriptive_coverage_counts():
    from jure.agents.critic.validation import validate_synthesis
    from jure.casefile.critic_models import MechanisticClaim, ClaimAuditRecord, HypothesisSynthesis
    claim = MechanisticClaim(claim_id='CLAIM_COUNT', hypothesis_id='H_COUNT', statement='A component remains untested.')
    audit = ClaimAuditRecord(claim_id=claim.claim_id, status='insufficient', summary='No relevant evidence.')
    synthesis = HypothesisSynthesis(hypothesis_id=claim.hypothesis_id, status='insufficient',
        insufficient_claim_ids=(claim.claim_id,), summary='Insufficient evidence.')
    with pytest.raises(ValueError, match='coverage counts'):
        validate_synthesis(synthesis, (claim,), (audit,), CriticConfig())
