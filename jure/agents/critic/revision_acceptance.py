"""Targeted Critic acceptance, separate from a full C1/C2 audit round."""
from pathlib import Path
from jure.casefile import ActionState,CaseStore,new_id
from jure.casefile.store import _atomic_write
from jure.casefile.critic_models import RoutingDecision
from jure.protocol.contracts import RevisionAcceptance,revision_defects,acceptance_records
from .context import build_critic_context
from .result import CriticRunResult


def validate_acceptance(result,request,submission,case):
    if result.request_id!=request.request_id or result.submission_run_id!=submission['run_id']:
        raise ValueError('Acceptance must reference the exact request and submitted run')
    if {x.defect_id for x in result.checks}!={x['defect_id'] for x in revision_defects(request)}:
        raise ValueError('Acceptance must check each registered defect exactly once')
    current={h.hypothesis_id:h.current_revision_id for h in case.hypotheses}
    if current!=dict(submission['submitted_revision_ids']):raise ValueError('Submitted hypothesis revisions changed before acceptance')
    known=set(current)|{r.revision_id for h in case.hypotheses for r in h.revisions}
    known|={p.prediction_id for h in case.hypotheses for p in h.predictions}
    known|={q.question_id for q in case.evidence_questions}
    known|={e.evidence_id for e in case.evidence_records}
    known|={c.claim_id for c in case.mechanistic_claims}
    known|={g.gap_id for g in case.evidence_gaps}
    for check in result.checks:
        if set(check.resolution_object_ids)-known:raise ValueError('Acceptance references an unknown Case File object')
        # A previously resolved defect can cite an unchanged object. Whether
        # that object resolves the scientific defect is the Critic's judgment.


def run_revision_acceptance(agent,store,case_id,submission,*,artifact_dir=None,available_capabilities=None,explorer_contract=None,continue_full_audit=False):
    from .agent import _Recorder
    source=store.load_case(case_id);run_id=new_id('ACCEPT')
    request=next(r for r in source.critic_audits.revision_requests if r.request_id==submission['request_id'])
    base=dict(run_id=run_id,case_id=case_id,critic_round=max(1,request.critic_round),
              source_case_revision=source.metadata.case_revision,
              artifact_path=str(Path(artifact_dir).resolve()/'critic_run.json') if artifact_dir else None)
    try:
        if source.action_state.current_phase=='stopped':raise ValueError('Cannot accept a revision in a stopped case')
        prior=acceptance_records(source,request.request_id)
        if any(x['status']=='RESOLVED' for x in prior):raise ValueError('Request already accepted')
        if len(prior)>=agent.config.max_revision_acceptance_attempts:raise ValueError('Revision acceptance attempt limit reached')
        started=_Recorder(store,source,run_id).event('REVISION_ACCEPTANCE_STARTED',request_id=request.request_id,submission_run_id=submission['run_id'])
        with CaseStore() as stage:
            stage.import_case(started);rec=_Recorder(stage,started,run_id)
            context=build_critic_context(rec.case,'hypothesis',max_chars=agent.config.max_context_chars,
                revision_request=request.model_dump(mode='json'),revision_defects=revision_defects(request),
                submission=dict(submission),prior_acceptance_checks=prior,
                available_capabilities=list(available_capabilities or []),explorer_write_contract=explorer_contract,
                acceptance_contract='Check only the registered defects against the submitted revisions. Every RESOLVED needs current object references. Do not invent additional hypotheses, choose evidence tools, or substitute acceptance for C1. PARTIAL/UNRESOLVED returns to Explorer within the fixed attempt limit.')
            answer=agent._ask('accept_revision',RevisionAcceptance,context)
            validate_acceptance(answer,request,submission,rec.case)
            rec.event('REVISION_ACCEPTANCE_COMPLETED',acceptance=answer.model_dump(mode='json'),
                successful_revision=answer.status=='RESOLVED',attempt=len(prior)+1)
            exhausted=answer.status!='RESOLVED' and len(prior)+1>=agent.config.max_revision_acceptance_attempts
            route='investigator' if answer.status=='RESOLVED' else 'explorer'
            c1_pending = answer.status == 'RESOLVED' and continue_full_audit
            failure_type=(rec.case.critic_audits.failure_attributions[-1].reason_type
                          if rec.case.critic_audits.failure_attributions else 'prediction_problem')
            stop=report=None
            if exhausted:
                from .backend import StopEvaluation
                from .stopping import make_stop_records
                from .stall_detection import budget_state
                rec.event('REVISION_ACCEPTANCE_EXHAUSTED',request_id=request.request_id)
                budgets=budget_state(rec.case,agent.config,max(1,request.critic_round))
                evaluation=agent._ask('evaluate_stop',StopEvaluation,
                    build_critic_context(rec.case,'final',max_chars=agent.config.max_context_chars,
                        revision_acceptance=answer.model_dump(mode='json'),budget_state=budgets,
                        available_capabilities=list(available_capabilities or []),
                        termination_contract='The fixed revision acceptance attempt budget is exhausted. Explain unresolved defects and limits; do not claim evidence/source exhaustion or invent a new hypothesis.'))
                for hypothesis in rec.case.hypotheses:
                    if hypothesis.status not in {'rejected','insufficient'}:
                        rec.call('update_hypothesis',hypothesis.hypothesis_id,status='insufficient',
                            reason='Revision defects remain unaccepted; no evidence verdict was reached.',critic_round=request.critic_round)
                # Report interpretation is the Critic's targeted acceptance text,
                # not a fabricated new C1 audit. The prior C1 record is unchanged.
                audit=rec.case.critic_audits.hypothesis_audits[-1].model_copy(update={'audit_summary':answer.summary})
                stop,report=make_stop_records(rec.case,audit,[],evaluation,
                    ('revision_budget_exhausted','revision_budget_exhausted'),request.critic_round,
                    budgets,{'investigation_stalled':False})
                rec.append(stop_records=(stop,),final_reports=(report,))
                decision=RoutingDecision(route_to='stop',reason_type=failure_type,reason_summary=answer.summary,
                    related_hypothesis_ids=request.affected_hypothesis_ids,critic_round=request.critic_round)
                rec.append(routing_decisions=(decision,))
                state=ActionState(current_phase='stopped',next_actor='none',stop_reason='revision_budget_exhausted')
            elif c1_pending:
                # Acceptance only resolves the named defects. It is not a full
                # C1 scientific judgment or an Investigator routing decision.
                rec.event('REVISION_ACCEPTED_FULL_AUDIT_PENDING', submission_run_id=submission['run_id'])
                state=ActionState(current_phase='critique_needed', next_actor='critic')
            else:
                state=ActionState(current_phase='evidence_needed' if route=='investigator' else 'exploration_needed',next_actor=route)
                decision=RoutingDecision(route_to=route,reason_type='no_problem' if answer.status=='RESOLVED' else failure_type,
                    reason_summary=answer.summary,related_hypothesis_ids=request.affected_hypothesis_ids,critic_round=request.critic_round)
                rec.append(routing_decisions=(decision,))
            rec.call('set_action_state',state)
            result=CriticRunResult(**base,success=True,committed_case_revision=rec.case.metadata.case_revision+1,
                stop_record_id=stop.stop_id if stop else None,final_report_id=report.report_id if report else None)
            rec.event('REVISION_ACCEPTANCE_RUN_COMPLETED',run_artifact=result.model_dump(mode='json'))
            store.commit_critic_case(case_id,rec.case,expected_revision=started.metadata.case_revision)
    except Exception as error:
        result=CriticRunResult(**base,validation_errors=(f'{type(error).__name__}: {str(error)[:2000]}',))
        _Recorder(store,store.load_case(case_id),run_id).event('REVISION_ACCEPTANCE_FAILED',run_artifact=result.model_dump(mode='json'))
    if artifact_dir:_atomic_write(Path(artifact_dir)/'critic_run.json',result.model_dump_json(indent=2)+'\n')
    return result
