"""Evidence-aware termination with deterministic critical-claim safeguards."""
from jure.casefile.critic_models import (
    CriticFinalReport, FinalHypothesisReport, RecommendedExperiment, StopRecord,
)
from .context import active_claims
from jure.protocol.source_review import has_source_review_blockers


def _gap_relevant(gap, claim_ids, prediction_ids, hypothesis_ids):
    if gap.related_claim_ids:
        return bool(claim_ids.intersection(gap.related_claim_ids))
    if gap.related_predictions:
        return bool(prediction_ids.intersection(gap.related_predictions))
    return bool(hypothesis_ids.intersection(gap.related_hypotheses))


def stop_choice(case, audit, syntheses, evaluation, budgets, stall, config, route):
    claims = active_claims(case)
    viable = [s for s in syntheses if s.status in {'supported', 'partially_supported'}]
    viable_ids = {s.hypothesis_id for s in viable}
    viable_claims = {c.claim_id for c in claims if c.hypothesis_id in viable_ids}
    viable_predictions = {pid for c in claims if c.hypothesis_id in viable_ids
                          for pid in c.derived_from_prediction_ids}
    critical_gaps = [g for g in case.evidence_gaps if g.critical and g.status != 'addressed'
                     and _gap_relevant(g, viable_claims, viable_predictions, viable_ids)]
    critical_claims = {c.claim_id for c in claims if c.critical and c.hypothesis_id in viable_ids}
    conflicts = [c for c in case.contradictions if c.status != 'resolved' and not c.potential_context_dependency and
                 (critical_claims.intersection(c.claim_ids) or
                  (not c.claim_ids and viable_ids.intersection(c.hypothesis_ids)))]
    enough = (route != 'explorer' and audit.overall_status == 'pass' and bool(viable)
              and all(c.status == 'supported' for c in claims if c.critical and c.hypothesis_id in viable_ids)
              and not conflicts and not critical_gaps and evaluation.evidence_sufficient
              and evaluation.hypothesis_discriminated)
    source_blocked = config.source_aware_stopping and has_source_review_blockers(case, evaluation)
    if enough and not source_blocked and config.allow_evidence_sufficient_stop:
        return 'evidence_sufficient', 'hypotheses_discriminated'
    hard = budgets['hard_limit_reached'] or (route == 'explorer' and budgets['explorer_reframe_limit_reached'])
    # A stagnating RNA-only loop does not exhaust an appropriate untried source.
    # Hard operational limits still apply; no automatic extra budget is granted.
    if source_blocked and not hard:
        return None
    limited = hard or stall['investigation_stalled'] or (route != 'explorer' and evaluation.no_further_queries)
    if not limited:
        return None
    if not config.allow_evidence_limited_stop:
        if hard:
            # Disabling a report policy cannot permit budget overshoot.
            raise ValueError('Hard investigation budget reached; evidence-limited stop is disabled. No further route was committed.')
        return None
    if config.protocol_v3:
        if (route=='explorer' and budgets['explorer_reframe_limit_reached']) or 'revision_acceptance_attempts' in budgets['reached_limits']:
            return 'revision_budget_exhausted','revision_budget_exhausted'
        if 'total_tool_calls' in budgets['reached_limits']:
            return 'tool_budget_exhausted','tool_budget_exhausted'
        if hard:return 'agent_budget_exhausted','agent_budget_exhausted'
        if stall['investigation_stalled']:return 'stalled','stalled'
        if evaluation.limitation_kind=='capability':return 'capability_limited','capability_limited'
        return 'evidence_limited','critical_evidence_unavailable'
    if hard:
        reason = 'hypothesis_space_unresolved' if route == 'explorer' and budgets['explorer_reframe_limit_reached'] else 'budget_exhausted'
    elif stall['investigation_stalled']:
        reason = 'investigation_saturation'
    elif route == 'explorer':
        reason = 'hypothesis_space_unresolved'
    elif any(g.critical and g.status != 'addressed' for g in case.evidence_gaps):
        reason = 'critical_evidence_unavailable'
    else:
        reason = 'tool_limit'
    return 'evidence_limited', reason


def recommended_experiments(case, syntheses):
    claims = active_claims(case)
    remaining = [s for s in syntheses if s.status != 'challenged']
    hids = tuple(s.hypothesis_id for s in remaining) or tuple(h.hypothesis_id for h in case.hypotheses)
    unresolved = [c for c in claims if c.hypothesis_id in hids and c.status != 'supported']
    predictions = [p for h in case.hypotheses if h.hypothesis_id in hids for p in h.predictions
                   if p.hypothesis_revision_id == h.current_revision_id]
    outcomes = {}
    for prediction in predictions:
        outcomes.setdefault(prediction.hypothesis_id, []).append({
            'prediction_id': prediction.prediction_id,
            'expected_if_true': prediction.expected_if_true,
            'would_weaken': prediction.weakened_if_observed,
        })
    return (RecommendedExperiment(
        objective='Resolve the remaining claim uncertainty and discriminate the retained mechanisms.',
        target_uncertainty='; '.join(c.statement for c in unresolved) or 'The current hypothesis space remains unresolved.',
        intervention=f'A prospectively controlled perturbation or matched observation designed around the existing predictions for {case.clue.perturbation}.',
        measurement=f'Joint expression states of {", ".join(case.clue.pattern.genes)} in {case.metadata.cell_context or "the original biological context"}, with sufficient support and appropriate controls.',
        expected_discriminating_outcomes=outcomes, related_hypothesis_ids=hids,
        related_claim_ids=tuple(c.claim_id for c in unresolved),
        rationale='These are conditional outcomes from existing predictions, not predicted experimental facts.',
        feasibility_notes=('Future validation suggestion only; no experiment is executed.',
                           'Intervention target and power must be established before experimental design is finalized.'),
    ),)


def make_stop_records(case, audit, syntheses, evaluation, choice, critic_round, budgets, stall):
    stop_type, reason = choice
    claims = active_claims(case)
    current_cids = {c.claim_id for c in claims}
    current_hids = {h.hypothesis_id for h in case.hypotheses if h.current_revision.status != 'rejected'}
    current_pids = {p.prediction_id for h in case.hypotheses for p in h.predictions
                    if h.hypothesis_id in current_hids and p.hypothesis_revision_id == h.current_revision_id}
    states = {s.hypothesis_id: s.status for s in syntheses}
    for hid in current_hids:
        states.setdefault(hid, 'insufficient')
    audits = [a for a in case.critic_audits.claim_audits if a.critic_round == critic_round]
    gaps = [g for g in case.evidence_gaps if _gap_relevant(g, current_cids, current_pids, current_hids)]
    uncertainties = tuple(dict.fromkeys((*evaluation.remaining_uncertainties,
        *(u for s in syntheses for u in s.remaining_uncertainties),
        *(g.description for g in gaps if g.status != 'addressed'))))
    if not uncertainties:
        uncertainties = ('No additional uncertainty identified within the current evidence scope; causal generalization remains untested.',)
    limitations = list(evaluation.why_current_tools_cannot_resolve)
    if budgets['hard_limit_reached']:
        limitations.append('The configured operational budget was reached: ' + ', '.join(budgets['reached_limits']) +
                           '. Potentially useful queries may remain unexecuted; budget exhaustion does not establish source saturation.')
    if reason in {'hypothesis_space_unresolved','revision_budget_exhausted'}:
        limitations.append('The hypothesis space still requires revision and the permitted reframe budget is exhausted or no justified reframe remains.')
    if stall['investigation_stalled']:
        limitations.append('Consecutive audits found no new discriminating evidence or reduction in unresolved uncertainty.')
    if stop_type != 'evidence_sufficient' and not limitations:
        limitations.append('The declared available capabilities cannot obtain the required discriminating observation.')
    experiments = evaluation.recommended_experiments
    if stop_type != 'evidence_sufficient' and not experiments:
        experiments = recommended_experiments(case, syntheses)
    supporting = tuple(sorted({eid for a in audits for eid in a.supporting_evidence_ids}))
    challenging = tuple(sorted({eid for a in audits for eid in a.challenging_evidence_ids}))
    summary = (('Current evidence sufficiently distinguishes the audited explanations within the recorded scope. '
                'The supported or partially supported interpretation retains the listed uncertainty.')
               if stop_type == 'evidence_sufficient' else
               'Current available evidence does not sufficiently distinguish all remaining explanations; '
               'the audit stops with explicit unresolved claims and future validation suggestions.')
    if stop_type not in {'evidence_sufficient','evidence_limited'}:
        summary=f'Investigation stopped with {stop_type}. Unresolved claims and the recorded limitation remain; this does not establish source exhaustion or a winning mechanism.'
    stop = StopRecord(stop_type=stop_type, stop_reason=reason, final_hypothesis_states=states,
        source_reviews=evaluation.source_reviews,
        remaining_hypotheses=tuple(hid for hid, state in states.items() if state != 'challenged'),
        remaining_uncertainties=uncertainties,
        unresolved_critical_gaps=tuple(g.gap_id for g in gaps if g.critical and g.status != 'addressed'),
        resolved_gaps=tuple(g.gap_id for g in gaps if g.status == 'addressed'),
        key_supporting_evidence_ids=supporting, key_challenging_evidence_ids=challenging,
        why_current_tools_cannot_resolve=tuple(limitations),
        evidence_already_checked=tuple(sorted({a.evidence_id for a in case.critic_audits.evidence_audits})),
        recommended_experiments=experiments, critic_summary=summary, critic_round=critic_round)
    by_hid = {s.hypothesis_id: s for s in syntheses}
    final_hypotheses = []
    for hypothesis in case.hypotheses:
        if hypothesis.hypothesis_id not in states:
            continue
        synthesis = by_hid.get(hypothesis.hypothesis_id)
        hclaims = {c.claim_id for c in claims if c.hypothesis_id == hypothesis.hypothesis_id}
        final_hypotheses.append(FinalHypothesisReport(hypothesis_id=hypothesis.hypothesis_id,
            status=states[hypothesis.hypothesis_id], mechanism_statement=hypothesis.current_revision.mechanism_statement,
            key_supported_claims=synthesis.supported_claim_ids if synthesis else (),
            key_challenged_claims=synthesis.challenged_claim_ids if synthesis else (),
            critical_gaps=synthesis.critical_gaps if synthesis else (),
            key_evidence_ids=tuple(sorted({eid for a in audits if a.claim_id in hclaims for eid in a.evidence_ids})),
            contradictions=synthesis.contradictions if synthesis else (),
            remaining_uncertainties=synthesis.remaining_uncertainties if synthesis else (audit.audit_summary,)))
    shift = case.clue.perturbation_shift
    observation = (f'{case.clue.pattern.pattern_string}: observed prevalence {shift.control_frequency:g} '
                   f'in control and {shift.perturb_frequency:g} after {case.clue.perturbation}; '
                   f'delta={shift.delta_frequency:g}. {case.clue.interpretation_boundary}')
    report = CriticFinalReport(case_id=case.metadata.case_id, stop_type=stop_type,
        mechanistic_question=case.mechanistic_question.question_text if case.mechanistic_question else 'No valid mechanistic question is available.',
        clue_summary=observation, observation=observation,
        interpretation=' '.join(s.summary for s in syntheses) or audit.audit_summary,
        uncertainty=uncertainties, final_hypotheses=tuple(final_hypotheses),
        overall_case_summary=summary, recommended_experiments=experiments,
        investigation_limitations=tuple(limitations))
    return stop, report
