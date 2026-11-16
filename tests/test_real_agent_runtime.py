"""Unit contract tests only; isolated doubles never enter pilot runs."""
from types import SimpleNamespace
import json
import pytest
from jure.runtime.real_registry import RealInvestigatorRegistry
from jure.runtime.backends import CheckedTransport, RealCriticBackend, RECHECK_INSTRUCTIONS
from jure.tools.real.contracts import EvidenceEnvelope, CallContext, Status
from jure.agents.critic.backend import SYSTEM_INSTRUCTIONS
from jure.agents.investigator.validation import validate_investigator_action


def envelope(tool='data_experiment', operation='query', status=Status.OK, **updates):
    fields=dict(tool_name=tool, query_id='UNIT_QUERY', raw_query={}, normalized_query={'operation':operation},
        status=status,result={'statistics':{'matched_nt_frequency':.375,'pooled_nt_frequency_descriptive':.5}},
        source_type='STATISTICAL_ASSOCIATION',source_name='UNIT_ONLY',source_version='unit',dataset_id='UNIT_ONLY',
        timestamp='2026-09-28T00:00:00+00:00',parameters={},provenance={},source_mode='REAL',
        context=CallContext(case_id='UNIT_CASE',actor='investigator',stage='UNIT',purpose='TOOL_VALIDATION'),
        cache={'cache_key':'unit'})
    fields.update(updates)
    return EvidenceEnvelope(**fields)

class IsolatedRegistryDouble:
    mode='REAL'
    def __init__(self,env):self.env=env;self.artifacts=[]
    def get_envelope(self,qid):assert qid==self.env.query_id;return self.env
    def put_artifact(self,obj):
        self.artifacts.append(obj)
        return {'sha256':'a'*64,'path':'/unit-only/artifact.json'}

def normalize(env):
    adapter=RealInvestigatorRegistry(IsolatedRegistryDouble(env),'UNIT_CASE')
    question=SimpleNamespace(question_id='UNIT_Q',question_text='Unit question')
    case=SimpleNamespace(metadata=SimpleNamespace(case_id='UNIT_CASE'))
    result=SimpleNamespace(payload={'evidence_envelope':{'query_id':env.query_id}},status='success')
    return adapter.normalize_result(question,result,None,case,None,'UNIT_RUN','dataset')

def test_matched_statistics_and_lineage_survive_native_normalization():
    record=normalize(envelope()).records[0]
    stats=record.provenance.parameters['tool_result']['statistics']
    assert record.provenance.parameters['dataset']['statistics_location']=='provenance.parameters.tool_result'
    assert 'statistics' not in record.provenance.parameters['dataset']
    assert stats['matched_nt_frequency']==.375
    assert stats['pooled_nt_frequency_descriptive']==.5
    assert record.directness=='indirect' and record.support_quality=='sufficient'
    assert record.provenance.parameters['source_mode']=='REAL'
    assert record.raw_result_reference=='/unit-only/artifact.json'

def test_search_hits_do_not_become_evidence_or_select_papers():
    acquired=normalize(envelope('literature','search',result={'pmids':['123']}))
    assert not acquired.records and acquired.question_status=='partially_answered'

@pytest.mark.parametrize('status',[Status.NO_RESULT,Status.SOURCE_ERROR,Status.INVALID_QUERY,Status.BUDGET_EXHAUSTED])
def test_failures_are_gaps_not_negative_experiments(status):
    acquired=normalize(envelope(status=status))
    assert not acquired.records and acquired.gap

def test_abstract_retains_original_text_without_claim_upgrade():
    acquired=normalize(envelope('literature','retrieve',result={'articles':[
        {'pmid':'123','title':'Unit source','source_url':'https://pubmed.ncbi.nlm.nih.gov/123/',
         'abstract_sections':[{'text':'Original fixture passage.'}]}]}))
    record=acquired.records[0]
    assert record.directness=='contextual' and record.context_match=='unknown'
    assert record.provenance.parameters['tool_result']['abstract_sections'][0]['text']=='Original fixture passage.'
    assert not record.provenance.parameters['literature']['experimental_design_assessed']

def test_test_source_and_cross_case_are_rejected():
    with pytest.raises(ValueError): normalize(envelope(source_mode='TEST'))
    with pytest.raises(ValueError): normalize(envelope(context=CallContext(case_id='OTHER',actor='investigator',stage='UNIT',purpose='TOOL_VALIDATION')))
    with pytest.raises(ValueError): RealInvestigatorRegistry(SimpleNamespace(mode='TEST'),'UNIT_CASE')

def test_schema_feedback_does_not_author_or_edit_scientific_response():
    seen=[]
    good=json.dumps({'warnings':[],'possible_gap':None})
    def provider(request,*,role):
        seen.append(request)
        return '{bad' if len(seen)==1 else good
    transport=CheckedTransport(provider,'investigator')
    assert transport({'method':'interpret_tool_result','system_instructions':'unit'})==good
    assert len(seen)==2 and 'schema_validation_feedback' in seen[1]
    assert 'schema_validation_feedback' not in seen[0]

def test_critic_empty_recheck_is_agent_decision_and_base_prompt_is_preserved():
    requests=[]
    def transport(request):
        requests.append(request)
        return json.dumps({'rationale':'No source check needed','queries':[]}) if request['method']=='plan_rechecks' else '{}'
    backend=RealCriticBackend(transport,SimpleNamespace(specs={}), 'UNIT_CASE')
    backend.audit_evidence({'evidence_records':[],'evidence_questions':[]})
    assert [r['method'] for r in requests]==['plan_rechecks','audit_evidence']
    assert requests[-1]['system_instructions']==SYSTEM_INSTRUCTIONS
    assert RECHECK_INSTRUCTIONS!=SYSTEM_INSTRUCTIONS
    assert 'Do not retrieve evidence, call tools,' not in RECHECK_INSTRUCTIONS
    assert requests[-1]['context']['independent_source_rechecks']==[]

def test_critic_unknown_reference_fails_before_acquisition():
    def transport(request):
        return json.dumps({'rationale':'Unit verification','queries':[{'tool_name':'data_experiment','query':{},'reason':'unit','evidence_ids':['MISSING']}]})
    backend=RealCriticBackend(transport,SimpleNamespace(specs={}), 'UNIT_CASE')
    with pytest.raises(ValueError,match='unknown evidence'):backend.audit_evidence({'evidence_records':[]})

def test_transient_provider_retry_keeps_request_and_role_identical(monkeypatch):
    from jure.llm.glm import GLMTransportError
    seen=[];delays=[]
    monkeypatch.setattr('jure.runtime.backends.time.sleep',delays.append)
    def provider(request,*,role):
        seen.append((request,role))
        if len(seen)<3:raise GLMTransportError('provider_http_429')
        return '{}'
    CheckedTransport(provider,'investigator',provider_retry_delays=(15,30))({'method':'interpret_tool_result'})
    assert delays==[15,30] and seen[0]==seen[1]==seen[2]

def test_semantic_retry_retains_exact_agent_output_and_isolates_case():
    seen=[];first='{"warnings":["Original model-authored warning"],"possible_gap":null}'
    def provider(request,*,role):seen.append(request);return first
    transport=CheckedTransport(provider,'investigator')
    base={'method':'interpret_tool_result','context':{'case_id':'C1'}}
    transport(base)
    transport({**base,'feedback':['synthetic validator error']})
    assert seen[-1]['prior_uncommitted_response']==first
    transport({'method':'interpret_tool_result','context':{'case_id':'C2'},'feedback':['error']})
    assert 'prior_uncommitted_response' not in seen[-1]
    transport(base)
    assert 'prior_uncommitted_response' not in seen[-1]

@pytest.mark.parametrize('operation',['query','data_experiment.query'])
@pytest.mark.parametrize('steps',[1,2])
def test_investigator_native_dispatch_commits_provenance_atomically(tmp_path,operation,steps):
    # Isolated synthetic fixture. No published case, provider, network, or real
    # registry is involved; this exercises the adapter/CaseStore hand-off.
    from jure.casefile import CaseStore,EvidenceQuestion
    from jure.agents.explorer.agent import MechanismExplorer
    from jure.agents.explorer.backend import MockExplorerBackend
    from jure.agents.explorer.demo import initial_output,synthetic_clue
    from jure.agents.investigator.agent import EvidenceInvestigator
    from jure.agents.investigator.backend import MockInvestigatorBackend
    from jure.tools.real.contracts import ExperimentQuery,GraphQuery,GeneQuery,LiteratureQuery,ClueQuery
    from jure.runtime.real_registry import FAMILIES
    with CaseStore(tmp_path/'case.sqlite') as store:
        initial=store.create_case_from_clue(synthetic_clue(),cell_context='K562')
        cid=initial.metadata.case_id
        assert MechanismExplorer(MockExplorerBackend([initial_output(initial)])).run(store,cid,artifact_dir=tmp_path/'explorer').success
        case=store.load_case(cid)
        for q in case.evidence_questions:
            case=store.manually_cancel_question(cid,q.question_id,expected_revision=case.metadata.case_revision)
        query={'mode':'MARGINAL','condition':'UNIT_ONLY','state':{'A':1}}
        planning={'claim':'Fixture association', 'gap':'Missing observation',
                  'evidence_need':'case-specific association',
                  'source_choice_reason':'This fixture asks for measured detection.',
                  'expected_information_gain':'Shared component only, not a unique mechanism.'}
        q=EvidenceQuestion(question_id='UNIT_Q',question_text='Unit native acquisition',relevant_hypothesis_ids=('H1','H2'),
            discriminates_between=('H1','H2'),derived_from_prediction_ids=('P1',),suggested_evidence_type='dataset',
            query_spec={'evidence_type':'dataset','planned_operations':[{'operation':operation,'inputs':query,
                'evidence_planning':planning} for _ in range(steps)]})
        case=store.manually_add_evidence_question(cid,q,expected_revision=case.metadata.case_revision)
        reg=IsolatedRegistryDouble(envelope(context=CallContext(case_id=cid,actor='investigator',stage='UNIT',purpose='TOOL_VALIDATION')))
        schemas=dict(zip(FAMILIES,[ExperimentQuery,GraphQuery,LiteratureQuery,GeneQuery,ClueQuery]))
        reg.specs={name:SimpleNamespace(input_model=model,availability='READY',description='Unit fixture',limitations=[],when_to_use='unit',when_not_to_use='production') for name,model in schemas.items()}
        reg.disabled=set()
        reg.bind=lambda *a,**k:SimpleNamespace(call=lambda *args,**kwargs:reg.env)
        seen=[]
        class ContextSpy(MockInvestigatorBackend):
            def select_tool(self,context,plan):
                seen.append(context)
                return super().select_tool(context,plan)
        from jure.agents.investigator.result import InvestigatorConfig
        result=EvidenceInvestigator(ContextSpy(),RealInvestigatorRegistry(reg,cid),
            InvestigatorConfig(source_aware_planning=True)).run(store,cid,artifact_dir=tmp_path/'investigator')
        assert result.success,result.validation_errors
        final=store.load_case(cid)
        assert len(seen)==steps
        assert all(c['source_aware_planning'] for c in seen)
        assert not seen[0]['completed_tool_calls']
        if steps==2:
            assert len(seen[1]['completed_tool_calls'])==1 and len(seen[1]['existing_evidence'])==1
        assert final.hypotheses==case.hypotheses and final.clue==case.clue
        assert final.action_state.next_actor=='critic' and len(final.evidence_records)==1
        assert final.evidence_records[0].provenance.parameters['tool_result']['statistics']['matched_nt_frequency']==.375
        assert final.evidence_records[0].provenance.parameters['investigator_evidence_planning']==planning

def test_resume_checkpoint_preserves_state_history_and_checks_hash(tmp_path):
    from jure.runtime.pilot import resume_checkpoint
    from jure.casefile import CaseStore
    from jure.agents.explorer.demo import synthetic_clue
    from jure.tools.real.registry import file_sha
    with CaseStore(tmp_path/'case.sqlite') as store:
        initial=store.create_case_from_clue(synthetic_clue(),cell_context='K562')
        store.export_case(initial.metadata.case_id,tmp_path/'case_file')
    (tmp_path/'stage_results.json').write_text('[]')
    (tmp_path/'tool_trace.jsonl').write_text('')
    (tmp_path/'case_run_summary.json').write_text(json.dumps({'model':{'calls':7}}))
    specification={'directory':str(tmp_path),'case_sha256':file_sha(tmp_path/'case_file/case_file.json')}
    resumed,stages,traces,calls=resume_checkpoint(initial,specification)
    assert resumed==initial and resumed.investigation_history==initial.investigation_history
    assert stages==traces==[] and calls==7
    with pytest.raises(ValueError,match='hash changed'):resume_checkpoint(initial,{**specification,'case_sha256':'wrong'})
    other=initial.model_copy(update={'metadata':initial.metadata.model_copy(update={'case_id':'OTHER'})})
    with pytest.raises(ValueError,match='another case'):resume_checkpoint(other,specification)

def test_wrong_tool_choice_is_returned_to_agent_before_execution():
    seen=[]
    def provider(request,*,role):
        seen.append(request)
        return json.dumps({'tool_id':'clue_query' if len(seen)==1 else 'data_experiment','reason':'unit choice'})
    request={'method':'select_tool','arguments':{'plan':{'evidence_type':'dataset','planned_operations':[{'operation':'query'}]}},
        'context':{'case_id':'UNIT','tool_capabilities':[
            {'tool_id':'clue_query','tool_type':'other','capabilities':['get_co_response_context'],'availability':'available'},
            {'tool_id':'data_experiment','tool_type':'dataset','capabilities':['query'],'availability':'available'}]}}
    result=json.loads(CheckedTransport(provider,'investigator')(request))
    assert result['tool_id']=='data_experiment'
    assert 'Compatible registered tool IDs' in seen[-1]['schema_validation_feedback'][0]
    assert json.loads(seen[-1]['prior_uncommitted_response'])['tool_id']=='clue_query'


def test_completed_round_budget_does_not_refund_failed_acquisition_cost(tmp_path):
    from jure.casefile import CaseStore
    from jure.agents.explorer.demo import synthetic_clue
    from jure.agents.critic.result import CriticConfig
    from jure.agents.critic.stall_detection import budget_state
    with CaseStore(tmp_path/'budget.sqlite') as store:
        case=store.create_case_from_clue(synthetic_clue(),cell_context='K562')
        for index in range(3):
            case=store.append_history_event(case.metadata.case_id,actor='evidence_investigator',
                expected_revision=case.metadata.case_revision,action='INVESTIGATOR_STARTED',summary='Unit start',
                metadata={'run_id':f'INV_{index}'})
            case=store.append_history_event(case.metadata.case_id,actor='evidence_investigator',
                expected_revision=case.metadata.case_revision,
                action='INVESTIGATOR_COMPLETED' if index==2 else 'INVESTIGATOR_FAILED',summary='Unit outcome',
                metadata={'run_id':f'INV_{index}','run_artifact':{'tool_calls':[{'unit_attempt':index}]}})
        current=budget_state(case,CriticConfig(max_investigator_rounds=3,round_budget_basis='completed'),1)
        legacy=budget_state(case,CriticConfig(max_investigator_rounds=3,round_budget_basis='started'),1)
        assert current['investigator_rounds']==1 and current['investigator_rounds_remaining']==2
        assert not current['hard_limit_reached'] and legacy['hard_limit_reached']
        assert current['total_tool_calls']==legacy['total_tool_calls']==3
        assert current['agent_attempts']['investigator']=={'started':3,'completed':1,'failed':2}


def test_explorer_schema_exposes_actual_batch_bounds_without_editing_response():
    from jure.agents.explorer.backend import JSONExplorerBackend
    requests=[]
    def transport(request):requests.append(request);return 'original response'
    backend=JSONExplorerBackend(transport)
    bounds={'min_hypotheses':3,'max_hypotheses':6,'min_changed_hypotheses':1,'max_changed_hypotheses':5}
    assert backend.generate_initial({'schema_requirements':bounds})=='original response'
    assert backend.generate_reframe({'schema_requirements':bounds})=='original response'
    assert [(r['response_schema']['properties']['hypotheses']['minItems'],
             r['response_schema']['properties']['hypotheses']['maxItems']) for r in requests]==[(3,6),(1,5)]
    backend.generate_reframe({'observation_interpretation_required':'Immutable fixture observation.'})
    assert requests[-1]['response_schema']['properties']['observation_interpretation']['const']=='Immutable fixture observation.'


def test_historical_recovery_is_exact_read_and_keeps_original_unchanged(tmp_path):
    from jure.casefile import CaseStore
    from jure.casefile.history import snapshot_at_revision,verify_history
    from jure.agents.explorer.demo import synthetic_clue,initial_output
    from jure.agents.explorer import MechanismExplorer,MockExplorerBackend
    with CaseStore(tmp_path/'replay.sqlite') as store:
        initial=store.create_case_from_clue(synthetic_clue(),cell_context='K562')
        result=MechanismExplorer(MockExplorerBackend([initial_output(initial)])).run(store,initial.metadata.case_id)
        assert result.success
        final=store.load_case(initial.metadata.case_id);original=final.model_dump_json()
        assert snapshot_at_revision(final,1)==initial
        assert snapshot_at_revision(final,final.metadata.case_revision)==final
        verify_history(final)
        assert final.model_dump_json()==original and store.load_case(initial.metadata.case_id)==final
        for revision in (0,final.metadata.case_revision+1,True):
            with pytest.raises(ValueError):snapshot_at_revision(final,revision)


def test_plan_family_error_is_returned_before_selection_or_acquisition():
    from jure.runtime.backends import validate_investigator_interface,InterfaceContractError
    request={'method':'operationalize_question','context':{'tool_capabilities':[
        {'tool_id':'clue_query','tool_type':'other','capabilities':['clue_query.get_condition_association']}]}}
    response={'evidence_type':'dataset','planned_operations':[
        {'operation':'clue_query.get_condition_association','evidence_type':'dataset'}]}
    with pytest.raises(InterfaceContractError,match='registered operation bindings'):
        validate_investigator_interface(request,response)
    response['planned_operations'][0]['evidence_type']='other'
    validate_investigator_interface(request,response)
    response['planned_operations']=[]
    validate_investigator_interface(request,response)


def test_queue_selection_is_checked_without_requiring_exhaustive_scores():
    from jure.runtime.backends import validate_investigator_interface,InterfaceContractError
    request={'method':'prioritize_questions','context':{'pending_questions':[{'question_id':'Q1'},{'question_id':'Q2'}]}}
    response={'assessments':[{'question_id':'Q1'}], 'selected_question_id':'Q1'}
    validate_investigator_interface(request,response)
    response['assessments'].append({'question_id':'Q2'})
    validate_investigator_interface(request,response)
    response['selected_question_id']='Q3'
    with pytest.raises(InterfaceContractError,match='selectable queue'):
        validate_investigator_interface(request,response)


def test_independent_resume_is_checkpoint_only_and_ab_only(monkeypatch):
    from jure.runtime.pilot import validate_independent_resume
    monkeypatch.setattr('jure.runtime.pilot.load_case',lambda path:object())
    stages=[{'role':r,'success':True} for r in ('explorer','investigator','critic')]
    source=SimpleNamespace(critic_audits=SimpleNamespace(routing_decisions=['explorer']))
    monkeypatch.setattr('jure.runtime.pilot.resume_checkpoint',lambda initial,spec:(source,stages,[],25))
    config={'resume_execution_policy':'independent_existing_checkpoints','resume_sources':{'A':{},'B':{'directory':'unit'}}}
    assert not validate_independent_resume({},'AB')
    assert validate_independent_resume(config,'B')
    with pytest.raises(ValueError,match='checkpoint for every'):validate_independent_resume(config,'AB')
    with pytest.raises(ValueError,match='restricted'):validate_independent_resume(config,'C')
    stages.pop()
    with pytest.raises(ValueError,match='prior committed'):validate_independent_resume(config,'B')
