"""Replay real paid prefix without any network or new acquisition."""
import json,hashlib
from pathlib import Path
import pytest
from jure.runtime.saved_prefix import SavedPrefixProvider,SavedPrefixBinding
from jure.runtime.backends import CheckedTransport,validate_investigator_interface
from jure.agents.investigator.backend import JSONInvestigatorBackend
from jure.agents.investigator.agent import EvidenceInvestigator
from jure.agents.investigator.result import InvestigatorConfig
from jure.casefile.store import CaseStore,load_case

ROOT=Path('outputs/agent_pilot_v1_20260928/run_024_scientific_content_case_a/A')


def test_valid_selection_survives_extra_priority_annotations():
    folder=ROOT/'model_calls/call_0009_investigator'
    request=json.loads(json.loads((folder/'request.json').read_text())['messages'][1]['content'])
    response=json.loads((folder/'structured_output.json').read_text())
    validate_investigator_interface(request,response)
    response['selected_question_id']='Q4.1_artifact_vs_coordinated'
    with pytest.raises(ValueError):validate_investigator_interface(request,response)


@pytest.mark.parametrize('config_name,unfinished',[
    ('agent_pilot_scientific_content_case_a_resume_i.json','operationalize_question'),
    ('agent_pilot_scientific_content_case_a_resume_i2.json','select_tool'),
])
def test_paid_prefix_reaches_only_unfinished_step_without_network(tmp_path,config_name,unfinished):
    cfg=json.loads((Path('configs')/config_name).read_text())
    class NoNetwork:
        calls=0
        def __init__(self):self.blocked=[]
        def __call__(self,request,*,role):
            self.blocked.append(request['method'])
            raise RuntimeError('OFFLINE_CHECK_REACHED_UNFINISHED_STEP')
    class ArtifactOnly:
        mode='REAL'
        def put_artifact(self,value):
            raw=json.dumps(value,sort_keys=True,ensure_ascii=False).encode();sha=hashlib.sha256(raw).hexdigest()
            p=tmp_path/(sha+'.json');p.write_bytes(raw);return {'path':str(p),'sha256':sha}
    source=load_case(Path(cfg['resume_sources']['A']['directory'])/'case_file/case_file.json')
    live=NoNetwork();provider=SavedPrefixProvider(live,cfg['saved_investigator_prefix'])
    binding=SavedPrefixBinding(ArtifactOnly(),source.metadata.case_id,cfg['saved_investigator_prefix']);binding.protocol_v3=True
    request=json.loads(json.loads((ROOT/'model_calls/call_0001_investigator/request.json').read_text())['messages'][1]['content'])
    binding.metadata_snapshot=lambda:request['context']['tool_capabilities']
    backend=JSONInvestigatorBackend(CheckedTransport(provider,'investigator',schema_retries=0,protocol_v3=True))
    with CaseStore() as store:
        store.import_case(source)
        result=EvidenceInvestigator(backend,binding,InvestigatorConfig(**cfg['investigator'])).run(store,source.metadata.case_id,artifact_dir=tmp_path/'investigator')
    assert not result.success
    assert any('OFFLINE_CHECK_REACHED_UNFINISHED_STEP' in e for e in result.validation_errors),result.validation_errors
    assert not provider.remaining and not binding.remaining
    assert live.blocked==[unfinished]
    assert len(result.tool_calls)==3 and live.calls==0


def test_replayed_executions_do_not_consume_budget_twice():
    from jure.casefile.history import count_evidence_tool_calls
    for run in ('run_024_scientific_content_case_a','run_025_saved_prefix_case_a','run_026_saved_plan_case_a'):
        case=load_case(Path('outputs/agent_pilot_v1_20260928')/run/'A/case_file/case_file.json')
        assert count_evidence_tool_calls(case)==13


def test_saved_critic_acceptance_keeps_judgment_and_valid_evidence_refs():
    from jure.protocol.contracts import RevisionAcceptance,pending_submission
    from jure.agents.critic.revision_acceptance import validate_acceptance
    root=Path('outputs/agent_pilot_v1_20260928/run_027_saved_plan_case_a/A')
    case=load_case(root/'case_file/case_file.json')
    answer=RevisionAcceptance.model_validate_json((root/'model_calls/call_0003_critic/structured_output.json').read_text())
    original=answer.model_dump(mode='json')
    request=next(r for r in case.critic_audits.revision_requests if r.request_id==answer.request_id)
    submission=pending_submission(case)
    validate_acceptance(answer,request,submission,case)
    assert answer.status=='PARTIAL' and answer.model_dump(mode='json')==original
    broken=answer.model_copy(update={'checks':(answer.checks[0].model_copy(update={'resolution_object_ids':('missing_object',)}),)+answer.checks[1:]})
    with pytest.raises(ValueError,match='unknown Case File object'):
        validate_acceptance(broken,request,submission,case)


def test_c1_pass_keeps_nonblocking_coverage_notes():
    from jure.casefile import HypothesisAuditResult
    from jure.agents.critic.validation import validate_hypothesis_audit
    root=Path('outputs/agent_pilot_v1_20260928/run_029_case_a_c1_c2/A')
    case=load_case(root/'case_file/case_file.json')
    audit=HypothesisAuditResult.model_validate_json((root/'model_calls/call_0001_critic/structured_output.json').read_text())
    before=audit.model_dump(mode='json')
    validate_hypothesis_audit(case,audit)
    assert audit.overall_status=='pass' and audit.coverage_issues and audit.model_dump(mode='json')==before
    invalid=audit.model_copy(update={'per_hypothesis':(audit.per_hypothesis[0].model_copy(update={'testability':'fail'}),)+audit.per_hypothesis[1:]})
    with pytest.raises(ValueError,match='explicit failed design dimension'):
        validate_hypothesis_audit(case,invalid)


def test_recheck_dispatch_binds_only_a_unique_existing_source():
    from jure.protocol.normalization import normalize_output
    from jure.runtime.backends import RecheckPlan
    p=Path('outputs/agent_pilot_v1_20260928/run_030_case_a_c2/A/model_calls/call_0002_critic')
    context=json.loads(json.loads((p/'request.json').read_text())['messages'][1]['content'])['context']
    raw=json.loads((p/'response.json').read_text())['content']
    result,audit=normalize_output(raw,role='critic',method='plan_rechecks',schema=RecheckPlan.model_json_schema(),context=context)
    RecheckPlan.model_validate(result)
    assert result['queries'][0].pop('tool_name')=='data_experiment'
    assert result==json.loads((p/'structured_output.json').read_text())
    assert audit['changes'][0]['rule']=='existing_evidence_source_tool_binding'
    missing,_=normalize_output(raw,role='critic',method='plan_rechecks',schema=RecheckPlan.model_json_schema(),context={})
    assert 'tool_name' not in missing['queries'][0]


def test_synthesis_counts_are_derived_without_rewriting_judgment():
    from jure.protocol.normalization import normalize_output
    from jure.agents.critic.backend import _SCHEMAS
    from jure.agents.critic.validation import validate_synthesis
    from jure.agents.critic.result import CriticConfig
    from jure.casefile.critic_models import MechanisticClaim,ClaimEvidenceAudit
    p=Path('outputs/agent_pilot_v1_20260928/run_032_case_a_completion/A/model_calls/call_0001_critic')
    context=json.loads(json.loads((p/'request.json').read_text())['messages'][1]['content'])['context']
    raw=json.loads((p/'response.json').read_text())['content']
    original=json.loads((p/'structured_output.json').read_text())
    result,_=normalize_output(raw,role='critic',method='synthesize_hypothesis',schema=_SCHEMAS['synthesize_hypothesis'].model_json_schema(),context=context)
    validate_synthesis(_SCHEMAS['synthesize_hypothesis'].model_validate(result),
        [MechanisticClaim.model_validate(c) for c in context['claims']],
        [ClaimEvidenceAudit.model_validate(c) for c in context['claim_audits']],CriticConfig())
    assert result['coverage']['unresolved_critical_claims']==1
    assert {k:v for k,v in result.items() if k!='coverage'}=={k:v for k,v in original.items() if k!='coverage'}
