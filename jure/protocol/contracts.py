"""Typed, model-authored discrimination and targeted revision acceptance."""
from typing import Literal
from pydantic import Field, model_validator
from jure.casefile.models import FrozenModel, Identifier, Text


class HypothesisExpectation(FrozenModel):
    hypothesis_id: Identifier
    prediction: Text


class PossibleOutcome(FrozenModel):
    outcome_id: Identifier
    observation: Text
    favors: tuple[Identifier, ...] = ()
    weakens: tuple[Identifier, ...] = ()
    non_discriminating: bool = Field(default=False, strict=True)
    interpretation_limit: Text
    reason: Text | None = None  # Optional for historical records; copied from Explorer in pairwise v1.


class DiscriminationSpec(FrozenModel):
    targets: tuple[Identifier, ...] = Field(min_length=2)
    expectations: tuple[HypothesisExpectation, ...] = Field(min_length=2)
    observable: Text
    capability_ids: tuple[Identifier, ...] = Field(min_length=1)
    possible_outcomes: tuple[PossibleOutcome, ...] = Field(min_length=2)
    scope_limit: Text

    @model_validator(mode='after')
    def linked_comparison(self):
        targets=set(self.targets)
        if len(targets)!=len(self.targets):raise ValueError('Duplicate comparison target')
        ids=[x.hypothesis_id for x in self.expectations]
        if set(ids)!=targets or len(ids)!=len(targets):raise ValueError('One expectation is required per target')
        outcome_ids=[x.outcome_id for x in self.possible_outcomes]
        if len(set(outcome_ids))!=len(outcome_ids):raise ValueError('Duplicate outcome ID')
        for outcome in self.possible_outcomes:
            if (set(outcome.favors)|set(outcome.weakens))-targets:
                raise ValueError('Outcome references a hypothesis outside targets')
            if set(outcome.favors)&set(outcome.weakens):raise ValueError('Outcome both favors and weakens the same target')
            if outcome.non_discriminating and (outcome.favors or outcome.weakens):
                raise ValueError('Non-discriminating outcome cannot favor or weaken targets')
        if not any(o.non_discriminating for o in self.possible_outcomes):
            raise ValueError('Include an explicitly non-discriminating outcome')
        if not any(o.favors or o.weakens for o in self.possible_outcomes):
            raise ValueError('Include at least one conditionally discriminating outcome')
        return self


class InformationUpdate(FrozenModel):
    outcome_id: Identifier | None = None
    status: Literal['discriminating_observation','partial','non_discriminating','query_failed']
    explanation: Text
    unresolved_comparison: Text


class DefectCheck(FrozenModel):
    defect_id: Identifier
    status: Literal['RESOLVED','PARTIAL','UNRESOLVED']
    reason: Text
    resolution_object_ids: tuple[Identifier, ...] = ()


class RevisionAcceptance(FrozenModel):
    request_id: Identifier
    submission_run_id: Identifier
    status: Literal['RESOLVED','PARTIAL','UNRESOLVED']
    checks: tuple[DefectCheck, ...] = Field(min_length=1)
    summary: Text

    @model_validator(mode='after')
    def consistent_status(self):
        if len({x.defect_id for x in self.checks})!=len(self.checks):raise ValueError('Duplicate defect check')
        expected=('RESOLVED' if all(x.status=='RESOLVED' for x in self.checks) else
                  'UNRESOLVED' if all(x.status=='UNRESOLVED' for x in self.checks) else 'PARTIAL')
        if self.status!=expected:raise ValueError(f'Overall acceptance must be {expected} for these checks')
        if any(x.status=='RESOLVED' and not x.resolution_object_ids for x in self.checks):
            raise ValueError('Resolved defects need references to submitted Case File objects')
        return self


def revision_defects(request):
    # Stable identifiers label the Critic's verbatim requirements, never new science.
    return [{'defect_id':f'D{i+1}','requirement':text}
            for i,text in enumerate(request.required_changes)]


def acceptance_records(case, request_id=None):
    return [e.metadata['acceptance'].to_dict() if hasattr(e.metadata['acceptance'],'to_dict')
            else dict(e.metadata['acceptance']) for e in case.investigation_history
            if e.action=='REVISION_ACCEPTANCE_COMPLETED'
            and (request_id is None or e.metadata['acceptance']['request_id']==request_id)]


def accepted_revision_count(case):
    return len({x['request_id'] for x in effective_acceptance_records(case) if x['status']=='RESOLVED'})


def effective_acceptance_records(case, request_id=None):
    """Apply explicit human protocol corrections; preserve original judgments."""
    from copy import deepcopy
    records=deepcopy(acceptance_records(case,request_id))
    corrections=[e.metadata for e in case.investigation_history
                 if e.actor=='controller' and e.metadata.get('controller_event')=='REVISION_REQUIREMENT_WITHDRAWN']
    for record in records:
        removed={d for c in corrections if c['request_id']==record['request_id'] for d in c['removed_defect_ids']}
        if not removed:continue
        record['historical_status']=record['status']
        record['withdrawn_defect_ids']=sorted(removed)
        record['checks']=[c for c in record['checks'] if c['defect_id'] not in removed]
        if not record['checks']:raise ValueError('Correction cannot erase every revision requirement')
        record['status']=('RESOLVED' if all(c['status']=='RESOLVED' for c in record['checks']) else
                          'UNRESOLVED' if all(c['status']=='UNRESOLVED' for c in record['checks']) else 'PARTIAL')
    return records


def pending_submission(case):
    checked={x['submission_run_id'] for x in acceptance_records(case)}
    return next((e.metadata for e in reversed(case.investigation_history)
                 if e.metadata.get('explorer_event')=='REVISION_SUBMITTED'
                 and e.metadata['run_id'] not in checked),None)


def latest_revision_state(case):
    if not case.critic_audits.revision_requests:return None,[]
    request=case.critic_audits.revision_requests[-1]
    return request,effective_acceptance_records(case,request.request_id)
