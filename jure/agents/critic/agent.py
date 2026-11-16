"""C1 → C2 → failure attribution → dynamic route/STOP, with atomic commits."""
from pathlib import Path
from pydantic import TypeAdapter
from jure.casefile import ActionState, CaseStore, new_id
from jure.casefile.models import Identifier
from jure.casefile.critic_models import (
    FailureAttribution, HypothesisAuditResult, HypothesisSynthesis,
    InvestigationRequest, RevisionRequest, RoutingDecision,
)
from jure.casefile.store import _atomic_write
from jure.casefile.history import agent_round_counts
from .artifacts import export_critic_artifacts
from .backend import (BackendRouteProposal, ClaimDecompositionResult, EvidenceAuditResult,
                      MockCriticBackend, StopEvaluation)
from .context import active_claims, build_critic_context
from .result import CriticConfig, CriticRunResult
from .routing import constrained_route
from .stall_detection import budget_state, progress_snapshot, stall_state
from .stopping import make_stop_records, stop_choice
from .validation import (normalize_claims, parse_backend_output, validate_evidence_audit,
                         validate_hypothesis_audit, validate_synthesis)


class _Recorder:
    def __init__(self, store, case, run_id):
        self.store, self.case, self.run_id = store, case, run_id

    def call(self, name, *args, **kwargs):
        self.case = getattr(self.store, name)(self.case.metadata.case_id, *args,
            actor='critic', expected_revision=self.case.metadata.case_revision, **kwargs)
        return self.case

    def append(self, **records):
        return self.call('append_critic_records', **records)

    def event(self, action, **metadata):
        return self.call('append_history_event', action=action, summary=action,
                         metadata={'run_id': self.run_id, **metadata})


class MechanismCritic:
    def __init__(self, backend=None, config=None):
        self.backend = backend or MockCriticBackend()
        self.config = CriticConfig.model_validate(config.model_dump(mode='json')
                       if hasattr(config, 'model_dump') else (config or {}))

    def _ask(self, method, model, context):
        # Every boundary is detached; backend has no mutable CaseFile or tool handle.
        result = parse_backend_output(model, getattr(self.backend, method)(context),
                                      max_chars=self.config.max_response_chars)
        if method == 'attribute_failure':
            from .references import validate_failure_references
            validate_failure_references(result, context)
        return result

    def run(self, store: CaseStore, case_id: str, *, run_id=None, artifact_dir=None,
            available_capabilities=None, explorer_contract=None):
        run_id = TypeAdapter(Identifier).validate_python(run_id or new_id('CRITIC'))
        source = store.load_case(case_id)
        for event in reversed(source.investigation_history):
            if event.metadata.get('run_id') == run_id and event.metadata.get('run_artifact'):
                return CriticRunResult.model_validate(event.metadata['run_artifact'])
        from jure.protocol.admission import investigation_first, investigation_completed_after_proposal
        post_investigation = investigation_first(source)
        if post_investigation and (not investigation_completed_after_proposal(source)
                or source.action_state.next_actor != 'critic'):
            return CriticRunResult(run_id=run_id, case_id=case_id, critic_round=1,
                source_case_revision=source.metadata.case_revision,
                validation_errors=('Critic review requires a completed Investigator round and Critic route after this proposal.',))
        if self.config.protocol_v3:
            from jure.protocol.contracts import pending_submission
            from .revision_acceptance import run_revision_acceptance
            submission=pending_submission(source)
            if submission:
                acceptance = run_revision_acceptance(self,store,case_id,submission,
                    artifact_dir=(Path(artifact_dir)/'revision_acceptance' if post_investigation and artifact_dir else artifact_dir),
                    available_capabilities=available_capabilities,explorer_contract=explorer_contract,
                    continue_full_audit=post_investigation)
                source=store.load_case(case_id)
                if not post_investigation or not acceptance.success or source.action_state.next_actor != 'critic':
                    return acceptance
        critic_round = 1 + agent_round_counts(source, 'critic')[self.config.round_budget_basis]
        directory = Path(artifact_dir).resolve() if artifact_dir is not None else None
        base = dict(run_id=run_id, case_id=case_id, critic_round=critic_round,
                    source_case_revision=source.metadata.case_revision,
                    artifact_path=str(directory / 'critic_run.json') if directory else None)
        from jure.protocol.admission import latest_admission
        admission = latest_admission(source)
        audit = None
        warnings = []
        rec = None
        try:
            if source.action_state.current_phase == 'stopped':
                raise ValueError('Critic cannot reopen a stopped case')
            started = _Recorder(store, source, run_id).event('CRITIC_STARTED', critic_round=critic_round)
            with CaseStore() as stage:
                stage.import_case(started)
                rec = _Recorder(stage, started, run_id)
                common = dict(critic_round=critic_round, context_timestamp=source.metadata.updated_at.isoformat(),
                    config=self.config.model_dump(mode='json'),
                    available_capabilities=list(available_capabilities) if available_capabilities is not None else None)
                if explorer_contract is not None:
                    common['explorer_write_contract'] = explorer_contract
                if self.config.protocol_v3:
                    from jure.protocol.capabilities import capability_summary
                    from jure.protocol.contracts import latest_revision_state
                    common['capability_summary']=capability_summary(available_capabilities or [])
                    request,acceptances=latest_revision_state(rec.case)
                    common['revision_acceptance_history']=acceptances
                def context(kind, **extra):
                    return build_critic_context(rec.case, kind, max_chars=self.config.max_context_chars,
                                                **common, **extra)
                # C1 is always recomputed. The configurable requirement cannot authorize C2 after failure.
                audit = self._ask('audit_hypotheses', HypothesisAuditResult, context('hypothesis'))
                audit = audit.model_copy(update={'critic_round': critic_round})
                validate_hypothesis_audit(rec.case, audit)
                if self.config.protocol_v3 and audit.overall_status=='pass' and request and not any(x['status']=='RESOLVED' for x in acceptances):
                    raise ValueError('C1 cannot pass while the last revision request remains unaccepted')
                rec.append(hypothesis_audits=(audit,))
                rec.event('HYPOTHESIS_AUDIT_COMPLETED', audit_id=audit.audit_id, overall_status=audit.overall_status,
                    admission_run_id=admission.metadata['run_id'] if admission else None)
                syntheses, claim_audits, gap_ids, contradiction_ids = [], [], [], []
                if audit.overall_status == 'pass':
                    decomposition = self._ask('decompose_claims', ClaimDecompositionResult,
                        context('hypothesis', hypothesis_audit=audit.model_dump(mode='json'),
                                claims=[c.model_dump(mode='json') for c in active_claims(rec.case)]))
                    claims = normalize_claims(rec.case, decomposition.claims)
                    from .validation import scientific_review_flags
                    common['scientific_review_flags'] = scientific_review_flags(rec.case, claims)
                    existing = {c.claim_id for c in rec.case.mechanistic_claims}
                    fresh = tuple(c for c in claims if c.claim_id not in existing)
                    if fresh:
                        rec.append(claims=fresh)
                    rec.event('CLAIMS_DECOMPOSED', claim_ids=[c.claim_id for c in claims])
                    focused = context('evidence', hypothesis_audit=audit.model_dump(mode='json'))
                    evidence_audit = self._ask('audit_evidence', EvidenceAuditResult, focused)
                    validate_evidence_audit(rec.case, evidence_audit, claims, focused)
                    common['scientific_review_flags'] += scientific_review_flags(rec.case, result=evidence_audit)
                    if common['scientific_review_flags']:
                        rec.event('SCIENTIFIC_REVIEW_FLAGS', flags=common['scientific_review_flags'],
                            contract='Advisory only; Critic judges science, code enforces references and record consistency.')
                    for entry in getattr(self.backend, 'last_recheck_trace', ()):
                        rec.event('CRITIC_SOURCE_RECHECK', **entry)
                    # Preserve canonical gap/contradiction IDs across audits and remap references.
                    gmap, cmap = {}, {}
                    for gap in evidence_audit.evidence_gaps:
                        old = next((g for g in rec.case.evidence_gaps if g.gap_id == gap.gap_id or (
                            g.related_claim_ids and g.related_claim_ids == gap.related_claim_ids
                            and g.description == gap.description)), None)
                        if old:
                            gmap[gap.gap_id] = old.gap_id
                            evidence_links = tuple(dict.fromkeys((*old.related_evidence_ids, *gap.related_evidence_ids)))
                            question_links = tuple(dict.fromkeys((*old.related_question_ids, *gap.related_question_ids)))
                            if (old.status == 'addressed' or evidence_links != old.related_evidence_ids
                                    or question_links != old.related_question_ids):
                                rec.call('update_evidence_gap', old.gap_id,
                                    status='open' if old.status == 'addressed' else old.status,
                                    related_evidence_ids=evidence_links, related_question_ids=question_links)
                        else:
                            rec.call('add_evidence_gap', gap.model_copy(update={'status': 'open'}))
                            gap_ids.append(gap.gap_id)
                            rec.event('EVIDENCE_GAP_CREATED', gap_id=gap.gap_id)
                    for contradiction in evidence_audit.contradictions:
                        old = next((c for c in rec.case.contradictions if c.contradiction_id == contradiction.contradiction_id or (
                            c.claim_ids == contradiction.claim_ids and set(c.evidence_ids) == set(contradiction.evidence_ids))), None)
                        if old:
                            cmap[contradiction.contradiction_id] = old.contradiction_id
                        else:
                            rec.call('add_contradiction', contradiction)
                            contradiction_ids.append(contradiction.contradiction_id)
                            rec.event('CONTRADICTION_CREATED', contradiction_id=contradiction.contradiction_id)
                    claim_audits = [a.model_copy(update={'critic_round': critic_round,
                        'gap_ids': tuple(gmap.get(g, g) for g in a.gap_ids),
                        'contradiction_ids': tuple(cmap.get(c, c) for c in a.contradiction_ids)})
                        for a in evidence_audit.claim_audits]
                    e_audits = tuple(a.model_copy(update={'critic_round': critic_round}) for a in evidence_audit.evidence_audits)
                    rec.append(evidence_audits=e_audits, claim_audits=tuple(claim_audits))
                    for item in claim_audits:
                        previous = next(c for c in rec.case.mechanistic_claims if c.claim_id == item.claim_id)
                        if previous.status != item.status:
                            rec.call('update_mechanistic_claim_status', item.claim_id, item.status)
                    for gap in rec.case.evidence_gaps:
                        linked = [a for a in claim_audits if a.claim_id in gap.related_claim_ids]
                        if linked and all(a.status in {'supported', 'challenged'} for a in linked) and gap.status != 'addressed':
                            rec.call('update_evidence_gap_status', gap.gap_id, 'addressed')
                    rec.event('EVIDENCE_AUDITED', evidence_audit_ids=[a.evidence_audit_id for a in e_audits])
                    for item in e_audits:
                        if item.overclaim_detected:
                            rec.event('EVIDENCE_OVERCLAIM_DETECTED', evidence_id=item.evidence_id,
                                      evidence_audit_id=item.evidence_audit_id)
                    for hypothesis in rec.case.hypotheses:
                        if hypothesis.current_revision.status == 'rejected':
                            continue
                        synthesis = self._ask('synthesize_hypothesis', HypothesisSynthesis,
                            context('evidence', target_hypothesis_id=hypothesis.hypothesis_id,
                                    hypothesis_audit=audit.model_dump(mode='json'),
                                    claim_audits=[a.model_dump(mode='json') for a in claim_audits]))
                        if synthesis.hypothesis_id != hypothesis.hypothesis_id:
                            raise ValueError('Backend synthesized a different hypothesis')
                        synthesis = synthesis.model_copy(update={'critic_round': critic_round,
                            'hypothesis_revision_id': hypothesis.current_revision_id})
                        validate_synthesis(synthesis, active_claims(rec.case), claim_audits, self.config)
                        rec.append(hypothesis_syntheses=(synthesis,))
                        syntheses.append(synthesis)
                final_args = dict(hypothesis_audit=audit.model_dump(mode='json'),
                    hypothesis_syntheses=[s.model_dump(mode='json') for s in syntheses],
                    claim_audits=[a.model_dump(mode='json') for a in claim_audits])
                failure = self._ask('attribute_failure', FailureAttribution, context('final', **final_args))
                failure = failure.model_copy(update={'critic_round': critic_round})
                if audit.overall_status != 'pass' and failure.reason_type not in {'hypothesis_problem', 'prediction_problem', 'hypothesis_space_inadequate'}:
                    raise ValueError('C1 failure must be attributed to hypothesis/prediction design')
                rec.append(failure_attributions=(failure,))
                rec.event('FAILURE_ATTRIBUTED', attribution=failure.model_dump(mode='json'))
                # Status updates follow audit and failure attribution, with full structured lineage.
                for synthesis in syntheses:
                    hypothesis = next(h for h in rec.case.hypotheses if h.hypothesis_id == synthesis.hypothesis_id)
                    if hypothesis.current_revision.status != synthesis.status:
                        cids = tuple(c.claim_id for c in active_claims(rec.case) if c.hypothesis_id == hypothesis.hypothesis_id)
                        eids = tuple(sorted({eid for a in claim_audits if a.claim_id in cids for eid in a.evidence_ids}))
                        rec.call('update_hypothesis', hypothesis.hypothesis_id, status=synthesis.status,
                            reason=synthesis.summary, claim_ids=cids, evidence_ids=eids,
                            gap_ids=synthesis.critical_gaps, critic_round=critic_round)
                        rec.event('HYPOTHESIS_STATUS_CHANGED', hypothesis_id=hypothesis.hypothesis_id,
                                  previous_status=hypothesis.current_revision.status, new_status=synthesis.status)
                final_args['failure_attribution'] = failure.model_dump(mode='json')
                proposal = self._ask('decide_route', BackendRouteProposal, context('final', **final_args))
                route = constrained_route(failure, proposal, hypothesis_passed=audit.overall_status == 'pass')
                budgets = budget_state(rec.case, self.config, critic_round)
                progress = progress_snapshot(source, rec.case, critic_round, route, run_id=run_id)
                stalled = stall_state(source, progress, self.config)
                if stalled['investigation_stalled']:
                    rec.event('INVESTIGATION_STALLED', **stalled)
                # Every STOP proposal (including budget/stall) has an explicit final audit.
                rec.event('FINAL_CRITIC_AUDIT_STARTED', budget_state=budgets, stall_state=stalled)
                evaluation = self._ask('evaluate_stop', StopEvaluation,
                    context('final', **final_args, budget_state=budgets, stall_state=stalled))
                from jure.protocol.source_review import source_review_blockers
                source_blockers = source_review_blockers(rec.case, evaluation)
                rec.event('SOURCE_REVIEW_COMPLETED',
                    source_reviews=[r.model_dump(mode='json') for r in evaluation.source_reviews],
                    **source_blockers, enforced=self.config.source_aware_stopping,
                    budget_state=budgets)
                choice = stop_choice(rec.case, audit, syntheses, evaluation, budgets, stalled, self.config, route)
                stop = report = None
                if choice:
                    if not syntheses:
                        # A final design-limited audit records the unavailable evidential verdict
                        # rather than silently presenting proposed/old support as a new verdict.
                        for hypothesis in rec.case.hypotheses:
                            if hypothesis.current_revision.status not in {'rejected', 'insufficient'}:
                                rec.call('update_hypothesis', hypothesis.hypothesis_id, status='insufficient',
                                    reason='Hypothesis design requires revision; evidential support cannot be concluded in this final audit.',
                                    critic_round=critic_round)
                                rec.event('HYPOTHESIS_STATUS_CHANGED', hypothesis_id=hypothesis.hypothesis_id,
                                          previous_status=hypothesis.current_revision.status, new_status='insufficient')
                    stop, report = make_stop_records(rec.case, audit, syntheses, evaluation, choice,
                                                     critic_round, budgets, stalled)
                    rec.append(stop_records=(stop,), final_reports=(report,))
                    route = 'stop'
                elif route == 'stop':
                    route = 'explorer' if audit.overall_status != 'pass' else 'investigator'
                    warnings.append('STOP proposal did not meet deterministic evidence-sufficiency or limitation requirements.')
                if route == 'explorer':
                    issues = tuple(dict.fromkeys((*audit.coverage_issues,
                        *(issue for h in audit.per_hypothesis for issue in h.issues), failure.reason_summary)))
                    changes = tuple(dict.fromkeys(change for h in audit.per_hypothesis for change in h.required_revisions))
                    # The overall diagnosis belongs in reason/issues, not in
                    # the independently checked Explorer revision requirements.
                    if not changes:
                        changes = ('Revise the affected mechanism assumptions and their discriminating predictions to account for the cited audit issues.',)
                    rec.append(revision_requests=(RevisionRequest(reason=failure.reason_summary,
                        affected_hypothesis_ids=failure.related_hypothesis_ids or tuple(h.hypothesis_id for h in rec.case.hypotheses),
                        issues=issues, required_changes=changes,
                        evidence_that_triggered_reframe=failure.related_evidence_ids,
                        preserve_elements=('Original clue observations and statistical values.',
                                           'All prior evidence, provenance, and historical hypothesis revisions.'), critic_round=critic_round),))
                    rec.event('HYPOTHESIS_REVISION_REQUESTED')
                elif route == 'investigator':
                    relevant_gaps = [g for g in rec.case.evidence_gaps if g.status != 'addressed'
                                     and (not g.related_claim_ids or set(g.related_claim_ids).intersection(c.claim_id for c in active_claims(rec.case)))]
                    rec.append(investigation_requests=(InvestigationRequest(
                        target_gap_ids=tuple(g.gap_id for g in relevant_gaps),
                        target_claim_ids=tuple(c.claim_id for c in active_claims(rec.case) if c.status != 'supported'),
                        objective='Obtain evidence that resolves the named critical gaps or distinguishes the conflicting predictions.',
                        why_needed=failure.reason_summary,
                        desired_evidence_characteristics=('Relevant to the linked claim and prediction.',
                            'Direct and context-matched where the claim requires a causal interpretation.',
                            'Traceable provenance, sufficient support, and explicit challenging observations.'), critic_round=critic_round),))
                decision = RoutingDecision(route_to=route, reason_type=failure.reason_type,
                    reason_summary=(stop.critic_summary if stop else failure.reason_summary),
                    related_hypothesis_ids=failure.related_hypothesis_ids,
                    related_claim_ids=failure.related_claim_ids, related_evidence_ids=failure.related_evidence_ids,
                    related_gap_ids=failure.related_gap_ids, critic_round=critic_round)
                progress = progress.model_copy(update={'route': route, 'investigation_stalled': stalled['investigation_stalled']})
                rec.append(routing_decisions=(decision,), progress_snapshots=(progress,))
                state = (ActionState(current_phase='stopped', next_actor='none', stop_reason=stop.stop_type)
                         if stop else ActionState(current_phase='exploration_needed' if route == 'explorer' else 'evidence_needed', next_actor=route))
                rec.call('set_action_state', state)
                rec.event('STOP_' + stop.stop_type.upper() if stop else 'ROUTE_TO_' + route.upper(),
                          routing_decision_id=decision.decision_id)
                result = CriticRunResult(**base, success=True, hypothesis_audit_id=audit.audit_id,
                    claim_audit_ids=tuple(a.claim_audit_id for a in claim_audits),
                    hypothesis_synthesis_ids=tuple(s.synthesis_id for s in syntheses),
                    created_gap_ids=tuple(gap_ids), created_contradiction_ids=tuple(contradiction_ids),
                    status_changes=tuple(s.change_id for s in rec.case.critic_audits.status_changes if s.critic_round == critic_round),
                    routing_decision_id=decision.decision_id, stop_record_id=stop.stop_id if stop else None,
                    final_report_id=report.report_id if report else None, warnings=tuple(warnings),
                    committed_case_revision=rec.case.metadata.case_revision + 1)
                rec.event('CRITIC_COMPLETED', run_artifact=result.model_dump(mode='json'))
                store.commit_critic_case(case_id, rec.case, expected_revision=started.metadata.case_revision)
        except Exception as error:
            # All staged scientific writes roll back; retain only the failed-run diagnostic.
            result = CriticRunResult(**base, warnings=tuple(warnings),
                validation_errors=(f'{type(error).__name__}: {str(error)[:2000]}',))
            try:
                latest = store.load_case(case_id)
                _Recorder(store, latest, run_id).event('CRITIC_FAILED', run_artifact=result.model_dump(mode='json'))
            except Exception as audit_error:
                result = result.model_copy(update={'warnings': result.warnings + (f'Failure audit unavailable: {type(audit_error).__name__}',)})
        if directory:
            try:
                if result.success:
                    export_critic_artifacts(store.load_case(case_id), result, directory)
                else:
                    _atomic_write(directory / 'critic_run.json', result.model_dump_json(indent=2) + '\n')
            except OSError as error:
                result = result.model_copy(update={'warnings': result.warnings +
                    (f'Export failed ({type(error).__name__}); committed records remain in the CaseStore.',)})
        return result
