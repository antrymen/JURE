"""User-authorized removal of an automatically appended summary requirement."""
import json
from pathlib import Path
from jure.casefile import ActionState
from jure.protocol.contracts import acceptance_records,effective_acceptance_records
from jure.tools.real.registry import file_sha


def apply_defect_correction(store,case_id,spec):
    path=Path(spec['path'])
    if file_sha(path)!=spec['sha256']:raise ValueError('Correction manifest changed')
    correction=json.loads(path.read_text());case=store.load_case(case_id)
    if file_sha(correction['source_case_file'])!=correction['source_sha256']:
        raise ValueError('Correction source changed')
    request=next(r for r in case.critic_audits.revision_requests if r.request_id==correction['request_id'])
    if (correction['removed_defect_id']!='D12' or len(request.required_changes)!=12
            or request.required_changes[-1]!=request.reason
            or [r['requirement'] for r in correction['effective_requirements']]!=list(request.required_changes[:-1])):
        raise ValueError('Only the documented automatically appended summary may be withdrawn')
    before=case;records=acceptance_records(case,request.request_id)
    if not records or any(c['status']!='RESOLVED' for c in records[-1]['checks'] if c['defect_id']!='D12'):
        raise ValueError('Remaining defects lack actual Critic resolution')
    case=store.append_history_event(case_id,actor='controller',expected_revision=case.metadata.case_revision,
        summary='User withdrew automatically appended D12 summary; reopen for independent C1 then C2.',
        metadata={'controller_event':'REVISION_REQUIREMENT_WITHDRAWN','request_id':request.request_id,
          'removed_defect_ids':['D12'],'correction_manifest':str(path),'correction_sha256':spec['sha256'],
          'user_authorization':spec['user_authorization'],
          'instruction':'D12 was an automatically appended diagnosis summary and is withdrawn. D1-D11 retain the Critic original RESOLVED judgments. Historical PARTIAL/STOP records remain historical. Perform an independent full C1; this correction is not a C1 pass or evidence verdict. Evidence sufficiency and pending claim interpretation belong in C2.',
          'budgets_reset':False,'scientific_content_modified':False})
    assert effective_acceptance_records(case,request.request_id)[-1]['status']=='RESOLVED'
    case=store.set_action_state(case_id,ActionState(current_phase='critique_needed',next_actor='critic'),
        actor='controller',expected_revision=case.metadata.case_revision)
    for field in ('clue','hypotheses','mechanistic_question','evidence_questions','evidence_records','critic_audits'):
        assert getattr(before,field)==getattr(case,field)
    return case
