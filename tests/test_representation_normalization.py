from copy import deepcopy
import json
from pathlib import Path
import pytest
from jure.protocol.normalization import normalize_output, decode_json, RepresentationError
from jure.agents.investigator.backend import investigator_output_json_schema
from jure.agents.investigator.prioritization import PrioritizationResult


def historical_priority():
    root=Path('outputs/agent_pilot_v1_20260928/run_019_glm47_admission_v2_a/A/model_calls/call_0001_investigator')
    request=json.loads(json.loads((root/'request.json').read_text())['messages'][1]['content'])
    return json.loads((root/'structured_output.json').read_text()),request


def test_actual_medium_high_is_repaired_without_model_or_selection_change():
    raw,req=historical_priority();before=deepcopy(raw)
    normalized,audit=normalize_output(raw,role='investigator',method='prioritize_questions',
        schema=investigator_output_json_schema('prioritize_questions'),context=req['context'])
    PrioritizationResult.model_validate(normalized)
    assert raw==before and normalized['selected_question_id']==raw['selected_question_id']
    assert audit['changes']==[{'path':'$.assessments[1].discriminative_value',
        'rule':'declared_priority_alias_medium_high_to_high','raw_value':'medium-high','normalized_value':'high'}]
    assert all(a['priority_reason']==b['priority_reason'] for a,b in zip(raw['assessments'],normalized['assessments']))


@pytest.mark.parametrize('wrapper',[lambda x:'```JSON\n'+json.dumps(x)+'\n```',lambda x:json.dumps({'output':x}),lambda x:json.dumps(json.dumps(x))])
def test_presentation_wrappers_preserve_content(wrapper):
    raw,req=historical_priority()
    normalized,audit=normalize_output(wrapper(raw),role='investigator',method='prioritize_questions',schema=req['response_schema'],context=req['context'])
    assert normalized['assessments'][0]['priority_reason']==raw['assessments'][0]['priority_reason']
    assert audit['changes']


@pytest.mark.parametrize('raw',['{"a":1,"a":2}','{"a":NaN}','Explanation: {"a":1}','{"a":'])
def test_ambiguous_or_incomplete_json_is_not_guessed(raw):
    with pytest.raises(ValueError):decode_json(raw)


def test_complete_object_footer_is_audited_without_changing_content():
    raw=' {"statement":"Please continue inside scientific text", "ok":true}\n\nPlease continue'
    value, changes=decode_json(raw)
    assert value=={'statement':'Please continue inside scientific text','ok':True}
    assert changes[0]['raw_value']==raw
    assert json.loads(changes[0]['normalized_value'])==value


def test_paid_case_c_tool_selection_array_replays_without_rewriting_science():
    from jure.agents.investigator.backend import ToolSelection
    root=Path('outputs/case_c_claim_source_revision_test_20260930/C/model_calls/call_0005_investigator')
    raw=json.loads((root/'response.json').read_text())['content']
    original=json.loads(raw)
    selected,changes=decode_json(raw,array_item_model=ToolSelection)
    assert selected==original[0]
    assert changes[0]['rule']=='unique_typed_object_in_array'
    assert changes[0]['raw_value']==original
    request=json.loads(json.loads((root/'request.json').read_text())['messages'][1]['content'])
    normalized,audit=normalize_output(raw,role='investigator',method='select_tool',
        schema=request['response_schema'],context=request['context'],expected_model=ToolSelection)
    assert normalized==original[0]
    assert audit['changes'][0]['normalized_value']==original[0]


def test_tool_selection_array_rejects_ambiguous_or_scientific_extra_members():
    from jure.agents.investigator.backend import ToolSelection
    choice={'tool_id':'data_experiment','reason':'Use current observable.'}
    for items in ([choice,choice], [choice,{'claim':'new scientific content'}], [choice,42]):
        with pytest.raises(ValueError):
            decode_json(json.dumps(items),array_item_model=ToolSelection)


@pytest.mark.parametrize('raw', ['{"ok":true}\n{"ok":false}',
    '{"ok":true}\n[1,2]', '{"ok":\nPlease continue',
    '{"ok":true,"ok":false}\nPlease continue', '{"x":NaN}\nPlease continue'])
def test_footer_recovery_cannot_guess_or_drop_content(raw):
    with pytest.raises(ValueError):decode_json(raw)


def test_unknown_verdict_not_mapped_and_prose_unchanged():
    schema={'type':'object','properties':{'status':{'enum':['supported','challenged']},'statement':{'type':'string'}}}
    raw={'status':'mostly-supported','statement':'Medium-high evidence may support Day6 pathway X.'}
    normalized,audit=normalize_output(raw,role='critic',method='audit_evidence',schema=schema)
    assert normalized==raw and not audit['changes']


def test_wrong_type_and_ambiguous_ids_are_not_rebound():
    schema={'type':'object','properties':{'related_evidence_ids':{'type':'array','items':{'type':'string'}}}}
    for context in ({'evidence_questions':[{'question_id':'Q1'}],'evidence_records':[]},
        {'evidence_records':[{'evidence_id':'e1'},{'evidence_id':'E1'}]}):
        raw={'related_evidence_ids':['Q1',' E1 ']}
        normalized,_=normalize_output(raw,role='critic',method='attribute_failure',schema=schema,context=context)
        assert normalized==raw


def test_normalization_does_not_complete_scientific_design():
    from jure.agents.explorer.content_adapter import AdmissionContent
    raw={'mechanistic_question':'Why?', 'hypotheses':[], 'contrasts':[]}
    normalized,audit=normalize_output(raw,role='explorer',method='initial_content',schema=AdmissionContent.model_json_schema())
    assert normalized==raw and not audit['changes']


def test_paid_case_b_pair_selection_accepts_local_handle_context_unchanged():
    root=Path('outputs/agent_pilot_v1_20260928/run_035_case_b_continuation/B/model_calls/call_0002_explorer')
    req=json.loads(json.loads((root/'request.json').read_text())['messages'][1]['content'])
    raw=json.loads((root/'response.json').read_text())['content']
    before=deepcopy(req['context'])
    normalized,audit=normalize_output(raw,role='explorer',method='pair_selection',
        schema=req['response_schema'],context=req['context'])
    assert normalized==json.loads(raw)
    assert req['context']==before and not audit['changes']
    assert len(normalized)==10


def test_mapping_catalogs_bind_only_explicit_ids_not_local_handle_keys():
    context={'hypotheses':{'h1':{'hypothesis_id':'H1','predictions':{
        'h1.p1':{'prediction_id':'P1'},'h1.p2':{'statement':'Keep local science.'}}}}}
    schema={'type':'object','properties':{'hypothesis_id':{'type':'string'},
        'derived_from_prediction_ids':{'type':'array','items':{'type':'string'}}}}
    raw={'hypothesis_id':' h1 ','derived_from_prediction_ids':[' p1 ','h1.p2']}
    normalized,_=normalize_output(raw,role='explorer',method='pair_details',schema=schema,context=context)
    assert normalized=={'hypothesis_id':'H1','derived_from_prediction_ids':['P1','h1.p2']}


def test_deterministic_critic_ids_and_case_binding_do_not_guess_references():
    from jure.casefile.critic_models import HypothesisAuditResult
    raw={'overall_status':'PASS','audit_summary':'Unit text.','per_hypothesis':[]}
    kwargs=dict(role='critic',method='audit_hypotheses',schema=HypothesisAuditResult.model_json_schema(),context={'case_id':'case1'})
    a,audit=normalize_output(raw,**kwargs);b,_=normalize_output(raw,**kwargs)
    assert a==b and a['case_id']=='case1' and a['audit_summary']==raw['audit_summary']
    assert 'per_hypothesis' in a and a['per_hypothesis']==[]


def test_explicit_edges_are_structural_and_ambiguous_edges_unchanged():
    from jure.agents.explorer.models import MechanismStructure
    raw={'causal_structure':'Hypothetical bridge.', 'directness':'indirect','cell_state_explanation':False,
         'conditional_dependence':False,'directed_edges':['X -> Y','A -> B -> C']}
    n,a=normalize_output(raw,role='explorer',method='initial',schema=MechanismStructure.model_json_schema())
    assert n['directed_edges']==[['X','Y'],'A -> B -> C']
    assert len(a['changes'])==1


def test_transport_audits_from_separate_instances_do_not_collide(tmp_path):
    from jure.runtime.backends import CheckedTransport
    class Provider:
        trace_dir=tmp_path
        calls=0
        def __call__(self,request,*,role):
            self.calls+=1
            return '{"tool_id":null,"reason":"Unit fixture."}'
    provider=Provider()
    for _ in range(2):CheckedTransport(provider,'investigator')({'method':'select_tool'})
    assert len(list((tmp_path/'normalization').glob('*.json')))==2


def test_all_registered_capability_aliases_are_reversible_without_choice_change():
    from jure.agents.explorer.content_adapter import OBSERVABLES,AdmissionContentQuestion
    for name,cid in OBSERVABLES.items():
        raw={'available_observables':[cid,'invented.capability'],'question':'Unchanged scientific question.'}
        normalized,audit=normalize_output(raw,role='explorer',method='initial_content',
            schema=AdmissionContentQuestion.model_json_schema())
        assert normalized['available_observables']==[name,'invented.capability']
        assert normalized['question']==raw['question']
        assert OBSERVABLES[normalized['available_observables'][0]]==cid
        assert audit['changes'][0]['raw_value']==cid


@pytest.mark.parametrize('call',[3,4,5])
def test_frozen_smoke_responses_replay_offline_after_namespace_fix(call):
    from jure.runtime.contract_review import evaluate
    root=Path('outputs/contract_stabilization_v1_20260928/smoke/model_calls')/f'call_{call:04d}_explorer'
    req=json.loads(json.loads((root/'request.json').read_text())['messages'][1]['content'])
    raw=json.loads((root/'response.json').read_text())['content']
    before=evaluate(raw,'explorer',req.get('method',req.get('mode')),req['context'],normalize=False)
    after=evaluate(raw,'explorer',req.get('method',req.get('mode')),req['context'])
    assert not before['schema_pass'] and after['schema_pass']
    assert any(c['rule']=='registered_capability_id_to_display_name' for c in after['normalization_audit']['changes'])
