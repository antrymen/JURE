"""Synthetic tests only; no biological conclusions or external calls."""
from copy import deepcopy
import json
import pytest
from jure.casefile import CaseStore
from jure.casefile.history import verify_history
from jure.agents.explorer.agent import MechanismExplorer
from jure.agents.explorer.backend import MockExplorerBackend, JSONExplorerBackend
from jure.agents.explorer.context import build_explorer_context, explorer_write_contract
from jure.agents.explorer.models import ExplorerConfig, ExplorerOutput
from jure.agents.explorer.admission import admit_proposal
from jure.agents.explorer.content_adapter import ContentExplorerBackend, compile_initial, extract_content
from jure.agents.critic import MechanismCritic, CriticConfig, MockCriticBackend
from jure.agents.critic.context import build_critic_context
from jure.agents.investigator import EvidenceInvestigator
from jure.protocol.admission import latest_admission, investigation_completed_after_proposal
from jure.runtime.backends import CheckedTransport
from test_protocol_v3 import proposal as make_proposal, CAPS, AcceptanceBackend
from jure.agents.explorer.demo import synthetic_clue

CONFIG = ExplorerConfig(protocol_v3=True, validation_policy='three_layer', max_retries=0)
CARDS = [{'tool_id':'data_experiment','availability':'available'}]

@pytest.fixture
def fixture():
    with CaseStore() as store:
        case = store.create_case_from_clue(synthetic_clue(), cell_context='K562')
        yield store, case, make_proposal(case)


def admit(case, payload):
    return admit_proposal(payload, case, config=CONFIG, capability_summary=CAPS)[1]


def test_scientific_flags_commit_without_repair_and_reach_c1(fixture, tmp_path):
    store, case, payload = fixture
    payload['hypotheses'][0]['assumptions'].append('ZXCV99 may mediate the response; this is unverified.')
    payload['predictions'][0]['statement'] = 'This pathway is biologically important.'
    backend = MockExplorerBackend([payload])
    result = MechanismExplorer(backend, CONFIG).run(store, case.metadata.case_id, capability_summary=CAPS)
    assert result.success, result.validation_errors
    assert result.admission_checks[-1]['decision'] == 'ADMIT_TO_INVESTIGATOR'
    after = store.load_case(case.metadata.case_id)
    assert after.action_state.next_actor == 'investigator'
    assert after.hypotheses[0].predictions[0].statement == payload['predictions'][0]['statement']
    flags = build_critic_context(after, 'C1')['proposal_admission']['audit_flags']
    assert {'UNSUPPORTED_NAMED_ENTITY','OBSERVABILITY_UNCLEAR'} <= {f['code'] for f in flags}
    assert not after.evidence_records and not after.critic_audits.hypothesis_audits
    from jure.agents.investigator.context import build_investigator_context
    assert build_investigator_context(after)['proposal_admission']['audit_flags'] == flags
    investigate(store, case.metadata.case_id, tmp_path)
    assert investigation_completed_after_proposal(store.load_case(case.metadata.case_id))
    verify_history(after)


@pytest.mark.parametrize('kind', ['neutral','contrast','prediction_question','expectation'])
def test_completeness_refusal_is_atomic_and_not_machine_error(fixture, kind):
    store, case, payload = fixture
    if kind == 'neutral': payload['evidence_questions'][0]['discrimination']['possible_outcomes'].pop()
    elif kind == 'contrast': payload['contrasts'].pop()
    elif kind == 'prediction_question': payload['evidence_questions'].pop()
    else: payload['evidence_questions'][0]['discrimination']['expectations'].pop()
    assert admit(case, payload).decision == 'RETURN_TO_EXPLORER'
    result = MechanismExplorer(MockExplorerBackend([payload]), CONFIG).run(store, case.metadata.case_id, capability_summary=CAPS)
    assert not result.success and result.admission_checks[-1]['decision'] == 'RETURN_TO_EXPLORER'
    after = store.load_case(case.metadata.case_id)
    assert not after.hypotheses and not after.evidence_questions and after.clue == case.clue


@pytest.mark.parametrize('kind', ['json','lineage','capability','contradiction','prediction','enum','edge','boolean'])
def test_machine_errors_never_reach_c1(fixture, kind):
    store, case, payload = fixture
    if kind == 'json': payload = '{'
    elif kind == 'lineage': payload['hypotheses'][0]['derived_from']=[{'object_type':'evidence_record','object_id':'FAKE'}]
    elif kind == 'capability': payload['evidence_questions'][0]['discrimination']['capability_ids']=['invented.capability']
    elif kind == 'contradiction': payload['evidence_questions'][0]['discrimination']['possible_outcomes'][-1]['favors']=['H1']
    elif kind == 'prediction': payload['evidence_questions'][0]['derived_from_prediction_ids']=['MISSING']
    elif kind == 'enum': payload['hypotheses'][0]['status']='supported'
    elif kind == 'boolean': payload['evidence_questions'][0]['discrimination']['possible_outcomes'][-1]['non_discriminating']='true'
    else: payload['hypotheses'][0]['structure']['directed_edges']=['X->Y']
    assert admit(case, payload).decision == 'REJECT'


def test_known_unavailable_and_repeated_prose_are_c1_flags(fixture):
    _, case, payload = fixture
    spec = payload['evidence_questions'][0]['discrimination']
    spec['capability_ids']=['knowledge.gene_context']
    spec['expectations'][1]['prediction']=spec['expectations'][0]['prediction']
    result=admit(case,payload)
    assert result.decision=='ADMIT_TO_INVESTIGATOR'
    assert {'CAPABILITY_LIMIT','DISCRIMINATION_UNCLEAR'} <= {f.code for f in result.audit_flags}
    # The persistent comparison preserves identical prose for the real Critic.
    from jure.protocol.contracts import DiscriminationSpec
    DiscriminationSpec.model_validate(spec)


def test_content_adapter_preserves_missing_neutral_for_completeness_gate(fixture):
    _, case, payload=fixture
    raw=extract_content(ExplorerOutput.model_validate(payload))
    raw['hypotheses'][0]['predictions'][0]['evidence_question']['possible_outcomes'].pop()
    before=deepcopy(raw)
    context=build_explorer_context(case,'initial');context['capability_summary']=CAPS
    context['write_contract']=explorer_write_contract(CONFIG)
    compiled,audit=compile_initial(raw,context)
    assert raw==before and audit['content_retained']
    assert admit(case,compiled).decision=='RETURN_TO_EXPLORER'


def test_investigator_precedes_critic_c1_and_c2(fixture, tmp_path):
    store, case, payload=fixture
    result=MechanismExplorer(MockExplorerBackend([payload]),CONFIG).run(store,case.metadata.case_id,capability_summary=CAPS)
    assert result.success, result.validation_errors
    backend=MockCriticBackend()
    critic=MechanismCritic(backend,CriticConfig(protocol_v3=True))
    blocked=critic.run(store,case.metadata.case_id,available_capabilities=CARDS)
    assert not blocked.success and not backend.calls
    investigate(store,case.metadata.case_id,tmp_path)
    from jure.agents.critic.demo import add_synthetic_evidence
    before=add_synthetic_evidence(store,store.load_case(case.metadata.case_id),source_type='grn',directness='indirect',source_quality='curated_database',support_quality='limited')
    assert before.evidence_records and not before.critic_audits.hypothesis_audits
    result=critic.run(store,case.metadata.case_id,available_capabilities=CARDS)
    assert result.success,result.validation_errors
    after=store.load_case(case.metadata.case_id)
    assert after.critic_audits.claim_audits
    assert backend.calls[0]['context']['evidence_records']
    methods=[c['method'] for c in backend.calls]
    assert methods.index('audit_hypotheses') < methods.index('audit_evidence') < methods.index('attribute_failure')
    verify_history(after)


def test_transport_uses_content_schema_not_legacy_identifiers(fixture):
    store,case,payload=fixture
    raw=extract_content(ExplorerOutput.model_validate(payload))
    calls=[]
    def provider(request, *, role):
        calls.append(request)
        return json.dumps(raw)
    transport=CheckedTransport(provider,'explorer',schema_retries=0,protocol_v3=True)
    result=MechanismExplorer(ContentExplorerBackend(transport),CONFIG).run(store,case.metadata.case_id,capability_summary=CAPS)
    assert result.success,result.validation_errors
    assert len(calls)==1 and calls[0]['mode']=='initial_content'
    assert store.load_case(case.metadata.case_id).action_state.next_actor=='investigator'


def test_revision_is_investigated_then_accepted_inside_critic(fixture, tmp_path):
    from jure.casefile.critic_models import RevisionRequest,HypothesisAuditResult
    from jure.casefile import ActionState
    from jure.protocol.contracts import accepted_revision_count
    store,case,payload=fixture;cid=case.metadata.case_id
    result=MechanismExplorer(MockExplorerBackend([payload]),CONFIG).run(store,cid,capability_summary=CAPS)
    assert result.success,result.validation_errors
    investigate(store,cid,tmp_path/'first')
    case=store.load_case(cid)
    request=RevisionRequest(required_changes=('Synthetic defect',),reason='Synthetic defect',affected_hypothesis_ids=('H1',),critic_round=1)
    case=store.append_critic_records(cid,revision_requests=(request,),hypothesis_audits=(HypothesisAuditResult(case_id=cid,overall_status='revision_required',audit_summary='Synthetic defect',critic_round=1),),actor='critic',expected_revision=case.metadata.case_revision)
    case=store.set_action_state(cid,ActionState(current_phase='exploration_needed',next_actor='explorer'),actor='critic',expected_revision=case.metadata.case_revision)
    result=MechanismExplorer(MockExplorerBackend([make_proposal(case,'R1')]),CONFIG).run(store,cid,mode='reframe',reframe_reason='Synthetic defect',capability_summary=CAPS)
    assert result.success,result.validation_errors
    case=store.load_case(cid)
    assert case.action_state.next_actor=='investigator' and accepted_revision_count(case)==0
    critic=MechanismCritic(AcceptanceBackend(),CriticConfig(protocol_v3=True))
    assert not critic.run(store,cid,available_capabilities=CARDS).success
    investigate(store,cid,tmp_path/'revised')
    audited=critic.run(store,cid,available_capabilities=CARDS,artifact_dir=tmp_path/'critic')
    assert audited.success,audited.validation_errors
    case=store.load_case(cid)
    assert accepted_revision_count(case)==1 and case.critic_audits.hypothesis_audits[-1].overall_status=='pass'
    assert case.critic_audits.claim_audits
    events=[e.action for e in case.investigation_history]
    assert events.index('REVISION_ACCEPTANCE_COMPLETED') > max(i for i,e in enumerate(events) if e=='INVESTIGATOR_COMPLETED')
    verify_history(case)


def test_c1_can_reject_admitted_flags_and_no_evidence_audit_runs(fixture, tmp_path):
    from jure.agents.critic.hypothesis_audit import audit_hypotheses
    store,case,payload=fixture
    payload['hypotheses'][0]['assumptions'].append('ZXCV99 is an unverified candidate.')
    result=MechanismExplorer(MockExplorerBackend([payload]),CONFIG).run(store,case.metadata.case_id,capability_summary=CAPS)
    assert result.success,result.validation_errors
    def reject(context):
        assert context['proposal_admission']['audit_flags']
        audit=audit_hypotheses(context).model_dump(mode='json')
        audit.update(overall_status='revision_required',coverage_issues=['Synthetic C1 concern.'])
        return audit
    investigate(store,case.metadata.case_id,tmp_path)
    backend=MockCriticBackend(audit_hypotheses=reject)
    result=MechanismCritic(backend,CriticConfig(protocol_v3=True)).run(store,case.metadata.case_id,available_capabilities=CARDS)
    assert result.success,result.validation_errors
    after=store.load_case(case.metadata.case_id)
    assert after.action_state.next_actor=='explorer'
    assert not after.critic_audits.claim_audits
    assert not {'decompose_claims','audit_evidence'} & {c['method'] for c in backend.calls}


def test_failed_c1_never_decomposes_claims_even_with_evidence(fixture, tmp_path):
    from jure.agents.critic.hypothesis_audit import audit_hypotheses
    store,case,payload=fixture
    assert MechanismExplorer(MockExplorerBackend([payload]),CONFIG).run(store,case.metadata.case_id,capability_summary=CAPS).success
    investigate(store,case.metadata.case_id,tmp_path)
    from jure.agents.critic.demo import add_synthetic_evidence
    add_synthetic_evidence(store,store.load_case(case.metadata.case_id),source_type='grn',directness='indirect',source_quality='curated_database',support_quality='limited')
    def reject(context):
        assert context['evidence_records']
        audit=audit_hypotheses(context).model_dump(mode='json')
        audit.update(overall_status='revision_required',coverage_issues=['Synthetic hypothesis-design defect.'])
        return audit
    backend=MockCriticBackend(audit_hypotheses=reject)
    result=MechanismCritic(backend,CriticConfig(protocol_v3=True)).run(store,case.metadata.case_id,available_capabilities=CARDS)
    assert result.success,result.validation_errors
    case=store.load_case(case.metadata.case_id)
    assert case.action_state.next_actor=='explorer'
    assert case.evidence_records and not case.mechanistic_claims and not case.critic_audits.claim_audits
    assert not {'decompose_claims','audit_evidence'} & {c['method'] for c in backend.calls}


@pytest.mark.parametrize('missing', ['outcomes','predictions','alternatives','capabilities','weakening'])
def test_content_completeness_has_same_boundary_as_typed_proposal(fixture,missing):
    store,case,payload=fixture
    raw=extract_content(ExplorerOutput.model_validate(payload))
    h=raw['hypotheses'][0];p=h['predictions'][0];q=p['evidence_question']
    if missing=='outcomes':q['possible_outcomes']=[]
    elif missing=='predictions':h['predictions']=[]
    elif missing=='alternatives':
        p['alternatives']=[]
        for outcome in q['possible_outcomes']:
            outcome['weakens']=[]
            outcome['favors']=[x for x in outcome['favors'] if x==1]
    elif missing=='capabilities':q['available_observables']=[]
    else:h['weakening_conditions']=[]
    result=MechanismExplorer(ContentExplorerBackend(lambda _:raw),CONFIG).run(store,case.metadata.case_id,capability_summary=CAPS)
    assert not result.success and result.admission_checks[-1]['decision']=='RETURN_TO_EXPLORER'
    assert not store.load_case(case.metadata.case_id).hypotheses


def test_new_model_configuration_has_no_live_or_expensive_fallback():
    from pathlib import Path
    from jure.llm.glm import GLMConfig
    settings=json.loads(Path('configs/explorer_admission_v2.json').read_text())
    model=GLMConfig.model_validate_json(Path(settings['model_config']).read_text())
    assert model.model=='glm-4.7-flash' and model.automatic_provider_retries==0
    assert settings['case_execution']=='PAUSED'
    assert settings['policy_version']=='explorer-admission-v2'
    assert settings['workflow_order']==['explorer','machine_completeness_gate','investigator','critic(C1->C2)']
    assert ExplorerConfig(**settings['explorer']).max_retries==0


def test_runtime_freeze_records_three_agent_order_and_versioned_interfaces(tmp_path):
    from pathlib import Path
    from jure.runtime.pilot import freeze
    config=json.loads(Path('configs/agent_pilot_glm47_admission_v1_a.json').read_text())
    frozen=freeze(tmp_path,config)
    assert frozen['workflow_order']==['explorer','investigator','critic(C1->C2)']
    assert frozen['admission_contracts']['policy_version']=='explorer-admission-v2'
    assert 'investigator' in frozen['admission_contracts']
    assert frozen['base_prompts_modified'] is False


from jure.agents.investigator import MockInvestigatorBackend


class SyntheticInvestigatorBackend(MockInvestigatorBackend):
    def operationalize_question(self, context, question_id):
        result=super().operationalize_question(context,question_id)
        q=next(q for q in context['pending_questions'] if q['question_id']==question_id)
        result['discrimination']=q['query_spec']['discrimination']
        return result

    def interpret_tool_result(self,context,plan,result):
        response=super().interpret_tool_result(context,plan,result)
        response['information_update']={'outcome_id':None,'status':'non_discriminating',
            'explanation':'Synthetic acquisition only.','unresolved_comparison':'Mechanisms remain unresolved.'}
        return response


def investigate(store,cid,path):
    from jure.agents.investigator import InvestigatorConfig
    from jure.tools.evidence import EvidenceToolRegistry
    registry=EvidenceToolRegistry();registry.protocol_v3=True
    result=EvidenceInvestigator(SyntheticInvestigatorBackend(),registry,
        InvestigatorConfig(protocol_v3=True,max_questions_per_run=1,max_tool_calls_per_run=1)).run(store,cid,artifact_dir=path)
    assert result.success,result.validation_errors
    assert store.load_case(cid).action_state.next_actor=='critic'
    return result
