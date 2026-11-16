"""Fast scientific termination contracts over immutable snapshots, without a store."""
from types import SimpleNamespace

import pytest

from jure.agents.critic.backend import StopEvaluation
from jure.agents.critic.result import CriticConfig
from jure.agents.critic.stopping import make_stop_records, stop_choice
from jure.agents.explorer.demo import synthetic_clue
from jure.casefile import (
    CaseFile, CaseMetadata, ClaimAuditRecord, ContradictionRecord, CriticAudits,
    EvidenceAuditRecord, EvidenceGap, EvidenceQuestion, EvidenceRecord,
    HypothesisAuditResult, HypothesisRecord, HypothesisRevision, HypothesisSynthesis,
    MechanisticClaim, MechanisticQuestion, PerHypothesisAudit, PredictionRecord, Provenance,
)


@pytest.fixture
def audited_snapshot():
    """One partially supported architecture, two challenged alternatives, one optional detail."""
    clue = synthetic_clue()
    hypotheses, questions, evidence, claims, claim_audits, evidence_audits, syntheses = [], [], [], [], [], [], []
    for index in range(1, 4):
        hid, rid, pid, qid, cid, eid = (f"H{index}", f"HR{index}", f"P{index}", f"Q{index}", f"CLAIM{index}", f"E{index}")
        status = "partially_supported" if index == 1 else "challenged"
        claim_status = "supported" if index == 1 else "challenged"
        revision = HypothesisRevision(revision_id=rid, title=f"Mechanism {index}",
            mechanism_statement=f"Candidate mechanism {index} may explain the joint state.",
            mechanism_type="shared_upstream" if index == 1 else "alternative", status=status)
        prediction = PredictionRecord(prediction_id=pid, hypothesis_id=hid, hypothesis_revision_id=rid,
            statement=f"Mechanism {index} predicts a specific observable joint-state response.",
            expected_if_true=f"Discriminating response {index} occurs.",
            weakened_if_observed=f"Response {index} is absent under a well-powered intervention.",
            discriminates_from_hypotheses=tuple(f"H{other}" for other in range(1, 4) if other != index))
        hypotheses.append(HypothesisRecord(hypothesis_id=hid, current_revision_id=rid,
                                           revisions=(revision,), predictions=(prediction,)))
        questions.append(EvidenceQuestion(question_id=qid, question_text=prediction.statement,
                                          derived_from_prediction_ids=(pid,), relevant_hypothesis_ids=(hid,)))
        evidence.append(EvidenceRecord(evidence_id=eid, question_id=qid, claim_tested=prediction.statement,
            result_summary="Synthetic matched direct intervention supports the prediction." if index == 1 else
                           "Synthetic matched direct intervention contradicts the prediction.",
            source_type="literature", directness="direct", context_match="matched",
            source_quality="primary_experiment", support_quality="sufficient",
            provenance=Provenance(source_id=f"fixture_{eid}", source_uri=f"mock://{eid}", tool="fixture")))
        claims.append(MechanisticClaim(claim_id=cid, hypothesis_id=hid, hypothesis_revision_id=rid,
            statement=prediction.statement, derived_from_prediction_ids=(pid,), status=claim_status,
            critical=True, criticality_reason="The architecture requires this response to account for the observation."))
        claim_audits.append(ClaimAuditRecord(claim_id=cid, status=claim_status, evidence_ids=(eid,),
            supporting_evidence_ids=(eid,) if index == 1 else (),
            challenging_evidence_ids=() if index == 1 else (eid,), summary="Synthetic direct evidence audit", critic_round=1))
        evidence_audits.append(EvidenceAuditRecord(evidence_id=eid, claim_ids=(cid,), relevance="relevant",
            directness_assessment="direct", context_assessment="matched", source_quality_assessment="primary_experiment",
            support_quality_assessment="sufficient", provenance_check="complete",
            critic_interpretation="Synthetic evidence directly tests this prediction.", critic_round=1))
        syntheses.append(HypothesisSynthesis(hypothesis_id=hid, hypothesis_revision_id=rid, status=status,
            supported_claim_ids=(cid,) if index == 1 else (), challenged_claim_ids=() if index == 1 else (cid,),
            insufficient_claim_ids=("CLAIM_DETAIL",) if index == 1 else (),
            remaining_uncertainties=("The timing of the downstream response remains unmeasured.",) if index == 1 else (),
            summary="The mechanism skeleton is supported, while an optional detail is unresolved." if index == 1 else
                    "Matched direct evidence challenges a necessary prediction.", critic_round=1))
    detail = MechanisticClaim(claim_id="CLAIM_DETAIL", hypothesis_id="H1", hypothesis_revision_id="HR1",
        statement="The response has a particular temporal order.", derived_from_prediction_ids=("P1",),
        status="insufficient", critical=False,
        criticality_reason="Response timing refines the mechanism but does not determine the supported architecture.")
    claims.append(detail)
    claim_audits.append(ClaimAuditRecord(claim_id=detail.claim_id, status="insufficient", gap_ids=("G_DETAIL",),
                                        summary="Timing has not been measured.", critic_round=1))
    gap = EvidenceGap(gap_id="G_DETAIL", description="Temporal ordering is not measured.", related_hypotheses=("H1",),
                      related_claim_ids=(detail.claim_id,), related_predictions=("P1",), critical=False)
    case = CaseFile(metadata=CaseMetadata(case_id="CASE_STOP", perturbation=clue.perturbation), clue=clue,
        mechanistic_question=MechanisticQuestion(question_id="MQ_STOP", question_text="Which mechanism explains the observed joint-state shift?",
                                                 derived_from_clue_id=clue.clue_id),
        hypotheses=tuple(hypotheses), evidence_questions=tuple(questions), evidence_records=tuple(evidence),
        mechanistic_claims=tuple(claims), evidence_gaps=(gap,),
        critic_audits=CriticAudits(claim_audits=tuple(claim_audits), evidence_audits=tuple(evidence_audits),
                                  hypothesis_syntheses=tuple(syntheses)))
    audit = HypothesisAuditResult(case_id=case.metadata.case_id, overall_status="pass",
        per_hypothesis=tuple(PerHypothesisAudit(hypothesis_id=h.hypothesis_id) for h in hypotheses),
        audit_summary="The mechanisms have testable, falsifiable and discriminating predictions.", critic_round=1)
    evaluation = StopEvaluation(evidence_sufficient=True, hypothesis_discriminated=True,
        reason="The core architecture is distinguished from the challenged alternatives; the remaining timing gap is not critical.",
        remaining_uncertainties=("Mechanistic generalization beyond the audited context remains untested.",))
    return SimpleNamespace(case=case, audit=audit, syntheses=tuple(syntheses), evaluation=evaluation,
        budgets={"hard_limit_reached": False, "explorer_reframe_limit_reached": False, "reached_limits": []},
        stall={"investigation_stalled": False}, config=CriticConfig())


def choose(fixture, *, route="stop", **changes):
    values = dict(case=fixture.case, audit=fixture.audit, syntheses=fixture.syntheses,
                  evaluation=fixture.evaluation, budgets=fixture.budgets, stall=fixture.stall, config=fixture.config,
                  route=route)
    values.update(changes)
    return stop_choice(**values)


@pytest.mark.parametrize('status', ['SOURCE_UNEXPLORED', None])
@pytest.mark.parametrize('stalled', [False, True])
def test_source_review_prevents_premature_stop_even_when_stalled(audited_snapshot, status, stalled):
    from jure.casefile.critic_models import SourceReview
    f = audited_snapshot
    gap = f.case.evidence_gaps[0].model_copy(update={'critical': True})
    case = f.case.model_copy(update={'evidence_gaps': (gap,)})
    reviews = () if status is None else (SourceReview(target_id=gap.gap_id,
        source='literature', evidence_need='Experimental temporal ordering',
        status=status, rationale='Only dataset queries have been attempted.'),)
    evaluation = StopEvaluation(no_further_queries=True, reason='RNA cannot answer.', source_reviews=reviews)
    config = f.config.model_copy(update={'source_aware_stopping': True, 'protocol_v3': True})
    assert choose(f, case=case, evaluation=evaluation, config=config,
                  stall={'investigation_stalled': stalled}) is None
    # Scientific incompleteness must never override an operational spending limit.
    budgets = {**f.budgets, 'hard_limit_reached': True, 'reached_limits': ['total_tool_calls']}
    choice = choose(f, case=case, evaluation=evaluation, config=config, budgets=budgets)
    assert choice == ('tool_budget_exhausted', 'tool_budget_exhausted')
    stop, _ = report(f, choice, case=case, evaluation=evaluation, budgets=budgets)
    assert stop.source_reviews == reviews
    assert any('budget' in v for v in stop.why_current_tools_cannot_resolve)


@pytest.mark.parametrize('status,kind,expected', [
    ('SOURCE_EXHAUSTED', 'evidence', 'evidence_limited'),
    ('SOURCE_UNAVAILABLE', 'capability', 'capability_limited'),
])
def test_reviewed_source_limits_can_stop_without_mandatory_tool_diversity(audited_snapshot, status, kind, expected):
    from jure.casefile.critic_models import SourceReview
    f = audited_snapshot
    gap = f.case.evidence_gaps[0].model_copy(update={'critical': True})
    case = f.case.model_copy(update={'evidence_gaps': (gap,)})
    evaluation = StopEvaluation(no_further_queries=True, limitation_kind=kind,
        reason='Required readout remains unresolved.', source_reviews=(SourceReview(
            target_id=gap.gap_id, source='time-resolved experiment',
            evidence_need='Temporal ordering', status=status,
            rationale='Critic assessment of the relevant source, not a quota for all tool families.'),))
    config = f.config.model_copy(update={'source_aware_stopping': True, 'protocol_v3': True})
    assert choose(f, case=case, evaluation=evaluation, config=config)[0] == expected


def report(fixture, choice, **changes):
    values = dict(case=fixture.case, audit=fixture.audit, syntheses=fixture.syntheses,
                  evaluation=fixture.evaluation, choice=choice, critic_round=1, budgets=fixture.budgets, stall=fixture.stall)
    values.update(changes)
    return make_stop_records(**values)


def test_partial_support_with_only_noncritical_gap_can_stop_sufficient(audited_snapshot):
    fixture = audited_snapshot
    choice = choose(fixture)
    assert choice == ("evidence_sufficient", "hypotheses_discriminated")
    stop, final = report(fixture, choice)
    assert stop.final_hypothesis_states["H1"] == "partially_supported"
    assert not stop.unresolved_critical_gaps
    assert fixture.case.evidence_gaps[0].description in stop.remaining_uncertainties
    assert final.final_hypotheses[0].status == "partially_supported"
    assert "E1" in stop.key_supporting_evidence_ids
    assert set(stop.key_challenging_evidence_ids) == {"E2", "E3"}
    assert final.observation == final.clue_summary
    assert "observed prevalence" in final.observation
    assert final.interpretation != final.observation
    assert final.uncertainty


def test_multiple_compatible_explanations_can_be_retained_when_explicitly_assessed(audited_snapshot):
    fixture = audited_snapshot
    claims = tuple(c.model_copy(update={"status": "supported"}) if c.hypothesis_id == "H2" else c
                   for c in fixture.case.mechanistic_claims)
    syntheses = tuple(s.model_copy(update={"status": "supported", "supported_claim_ids": ("CLAIM2",),
        "challenged_claim_ids": (), "summary": "This non-exclusive mechanism describes a compatible second layer."})
        if s.hypothesis_id == "H2" else s for s in fixture.syntheses)
    hypotheses = tuple(h.model_copy(update={"revisions": (
        h.current_revision.model_copy(update={"status": "supported"}),)}) if h.hypothesis_id == "H2" else h
        for h in fixture.case.hypotheses)
    claim_audits = tuple(a.model_copy(update={"status": "supported", "supporting_evidence_ids": ("E2",),
                                             "challenging_evidence_ids": ()}) if a.claim_id == "CLAIM2" else a
                         for a in fixture.case.critic_audits.claim_audits)
    records = tuple(e.model_copy(update={"result_summary": "Synthetic matched direct intervention supports the compatible second mechanism."})
                    if e.evidence_id == "E2" else e for e in fixture.case.evidence_records)
    case = fixture.case.model_copy(update={"mechanistic_claims": claims, "hypotheses": hypotheses,
        "evidence_records": records, "critic_audits": fixture.case.critic_audits.model_copy(update={
            "hypothesis_syntheses": syntheses, "claim_audits": claim_audits})})
    uncertain = fixture.evaluation.model_copy(update={"hypothesis_discriminated": False})
    assert choose(fixture, case=case, syntheses=syntheses, evaluation=uncertain) is None
    explicit = fixture.evaluation.model_copy(update={
        "reason": "H1 and H2 describe compatible mechanism layers; the evidence distinguishes both from the excluded H3 alternative."
    })
    choice = choose(fixture, case=case, syntheses=syntheses, evaluation=explicit)
    assert choice == ("evidence_sufficient", "hypotheses_discriminated")
    stop, final = report(fixture, choice, case=case, syntheses=syntheses, evaluation=explicit)
    assert set(stop.remaining_hypotheses) == {"H1", "H2"}
    assert {h.hypothesis_id: h.status for h in final.final_hypotheses} == {
        "H1": "partially_supported", "H2": "supported", "H3": "challenged"}


@pytest.mark.parametrize("no_further_queries", [False, True])
def test_c1_failure_cannot_be_overridden_by_sufficient_flags(audited_snapshot, no_further_queries):
    fixture = audited_snapshot
    audit = fixture.audit.model_copy(update={"overall_status": "revision_required", "coverage_issues": ("Missing alternative",)})
    evaluation = fixture.evaluation.model_copy(update={"no_further_queries": no_further_queries})
    assert choose(fixture, audit=audit, evaluation=evaluation, route="explorer") is None


def test_hypothesis_space_problem_routes_to_explorer_even_after_passing_c1(audited_snapshot):
    assert choose(audited_snapshot, route="explorer") is None


def test_prediction_only_critical_gap_prevents_sufficient_stop(audited_snapshot):
    fixture = audited_snapshot
    gap = EvidenceGap(gap_id="G_PREDICTION", description="A necessary discriminating observation remains unavailable.",
                      related_predictions=("P1",), critical=True, resolvable_with_current_tools=True)
    case = fixture.case.model_copy(update={"evidence_gaps": fixture.case.evidence_gaps + (gap,)})
    assert choose(fixture, case=case) is None


def test_prediction_only_critical_gap_survives_evidence_limited_report(audited_snapshot):
    fixture = audited_snapshot
    gap = EvidenceGap(gap_id="G_PREDICTION", description="A necessary discriminating observation remains unavailable.",
                      related_predictions=("P1",), critical=True, resolvable_with_current_tools=False)
    case = fixture.case.model_copy(update={"evidence_gaps": fixture.case.evidence_gaps + (gap,)})
    evaluation = fixture.evaluation.model_copy(update={"no_further_queries": True,
        "why_current_tools_cannot_resolve": ("The remaining intervention is absent from all available sources.",)})
    choice = choose(fixture, case=case, evaluation=evaluation)
    assert choice == ("evidence_limited", "critical_evidence_unavailable")
    stop, final = report(fixture, choice, case=case, evaluation=evaluation)
    assert gap.gap_id in stop.unresolved_critical_gaps
    assert gap.description in stop.remaining_uncertainties
    assert stop.recommended_experiments
    assert final.recommended_experiments
    assert final.investigation_limitations


def test_context_dependency_is_preserved_without_becoming_hard_contradiction(audited_snapshot):
    fixture = audited_snapshot
    conflict = ContradictionRecord(contradiction_id="CONTEXT_DIFF", description="Reported responses differ between cellular contexts.",
        claim_ids=("CLAIM1",), evidence_ids=("E1", "E2"), hypothesis_ids=("H1",), status="unresolved",
        critical=True, context_difference="One result is in K562 and the other is in HEK293.",
        possible_explanations=("The regulatory relationship may depend on cellular context.",), potential_context_dependency=True)
    case = fixture.case.model_copy(update={"contradictions": (conflict,)})
    syntheses = tuple(s.model_copy(update={"contradictions": (conflict.contradiction_id,),
        "remaining_uncertainties": s.remaining_uncertainties + (conflict.context_difference,)})
        if s.hypothesis_id == "H1" else s for s in fixture.syntheses)
    choice = choose(fixture, case=case, syntheses=syntheses)
    assert choice == ("evidence_sufficient", "hypotheses_discriminated")
    stop, final = report(fixture, choice, case=case, syntheses=syntheses)
    assert conflict.context_difference in stop.remaining_uncertainties
    assert final.final_hypotheses[0].contradictions == (conflict.contradiction_id,)


def test_same_context_conflict_on_critical_claim_blocks_sufficient_without_manual_critical_flag(audited_snapshot):
    fixture = audited_snapshot
    conflict = ContradictionRecord(contradiction_id="DIRECT_CONFLICT", description="Matched direct interventions disagree.",
        claim_ids=("CLAIM1",), evidence_ids=("E1", "E2"), hypothesis_ids=("H1",), status="unresolved")
    assert not conflict.critical
    case = fixture.case.model_copy(update={"contradictions": (conflict,)})
    assert choose(fixture, case=case) is None
    resolved = conflict.model_copy(update={"status": "resolved"})
    assert choose(fixture, case=case.model_copy(update={"contradictions": (resolved,)})) == (
        "evidence_sufficient", "hypotheses_discriminated")


def test_final_audit_can_find_sufficient_evidence_at_hard_budget(audited_snapshot):
    fixture = audited_snapshot
    budgets = {**fixture.budgets, "hard_limit_reached": True, "reached_limits": ["total_tool_calls"]}
    assert choose(fixture, budgets=budgets) == ("evidence_sufficient", "hypotheses_discriminated")


def test_unresolved_critical_claim_blocks_sufficient_despite_advisory_flags(audited_snapshot):
    fixture = audited_snapshot
    claims = tuple(c.model_copy(update={"status": "insufficient"}) if c.claim_id == "CLAIM1" else c
                   for c in fixture.case.mechanistic_claims)
    case = fixture.case.model_copy(update={"mechanistic_claims": claims})
    assert choose(fixture, case=case) is None
