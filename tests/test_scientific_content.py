"""Offline content/patch checks. No provider or evidence tool calls."""
from copy import deepcopy
import json
from pathlib import Path
import pytest
from jure.casefile import CaseStore
from jure.casefile.store import load_case
from jure.casefile.history import verify_history
from jure.agents.explorer.scientific_content import (ScientificContentBackend, ScientificDraft,
    assemble_changes, assemble_pairs, apply_patch_fields, pair_models, compact_context)
from jure.agents.explorer.context import build_explorer_context
from jure.agents.explorer.agent import MechanismExplorer
from jure.agents.explorer.models import ExplorerConfig
from jure.agents.explorer.admission import admit_proposal
from jure.protocol.normalization import decode_json

ROOT=Path('outputs/agent_pilot_v1_20260928/run_022_glm53_flash_case_a_extension/A')

def fixture():
    case=load_case(ROOT/'initial_snapshot/case_file.json')
    request=json.loads(json.loads((ROOT/'model_calls/call_0001_explorer/request.json').read_text())['messages'][1]['content'])
    ctx=request['context'];cfg=ExplorerConfig(**json.loads(Path('configs/agent_pilot_glm53_flash_case_a_extension.json').read_text())['explorer'])
    return case,ctx,cfg


def test_every_pair_decided_but_no_forced_experiment_and_no_science_rewrite():
    case,ctx,cfg=fixture()
    draft={'changes':[{'target':'H1','reason':'Synthetic test revision','fields':{'unresolved_points':['Synthetic unresolved issue.']},'predictions':[]}]}
    before=deepcopy(draft)
    proposal,view,handles,pmap,pairs=assemble_changes(draft,ctx)
    choices={k:{'status':'NOT_CURRENTLY_INFORMATIVE','reason':'Synthetic capability limitation.'} for k in pairs}
    pair_models(pairs).model_validate(choices)
    out=assemble_pairs(proposal,handles,pmap,pairs,choices,{})
    assert len(out.pair_decisions)==3 and not out.evidence_questions
    assert out.hypotheses[0].unresolved_points==('Synthetic unresolved issue.',)
    assert out.hypotheses[0].mechanism_statement==case.hypotheses[0].current_revision.mechanism_statement
    assert draft==before
    _,admission=admit_proposal(out.model_dump(mode='json'),case,config=cfg,mode='reframe',reframe_reason=ctx['reframe_reason'],capability_summary=ctx['capability_summary'])
    assert not admission.blocking_messages


def test_missing_pair_decision_is_not_silently_invented():
    _,ctx,_=fixture()
    proposal,view,handles,pmap,pairs=assemble_changes({'changes':[]},ctx)
    with pytest.raises(ValueError):pair_models(pairs).model_validate({})


def test_patch_only_appends_missing_leaf_and_never_rewrites():
    original={'pair_1':{'outcomes':{'favoring_first':{'observation':'Original'}}}}
    patch={'field_0':{'observation':'Agent neutral outcome'}}
    result=apply_patch_fields(original,[('pair_1','outcomes','non_discriminating')],patch)
    assert result['pair_1']['outcomes']['favoring_first']==original['pair_1']['outcomes']['favoring_first']
    assert 'non_discriminating' not in original['pair_1']['outcomes']
    with pytest.raises(ValueError):apply_patch_fields(original,[('pair_1','outcomes','favoring_first')],patch)
    with pytest.raises(ValueError):apply_patch_fields(original,[('pair_1','outcomes','non_discriminating')],{'field_0':{},'extra':'rewrite'})


def test_new_backend_uses_same_path_for_revision_and_no_full_rewrite():
    case,ctx,cfg=fixture();calls=[]
    draft={'changes':[{'target':'H1','reason':'Synthetic scope edit','fields':{'unresolved_points':['Synthetic limit.']},'predictions':[]}]}
    def transport(req):
        calls.append(req)
        if req['mode']=='hypothesis_changes':return draft
        if req['mode']=='pair_selection':return {k:{'status':'NOT_CURRENTLY_INFORMATIVE','reason':'Synthetic limit.'} for k in req['context']['pairs']}
        raise AssertionError('Unexpected tool or full regeneration')
    backend=ScientificContentBackend(transport)
    with CaseStore() as store:
        store.import_case(case)
        result=MechanismExplorer(backend,cfg).run(store,case.metadata.case_id,mode='reframe',reframe_reason=ctx['reframe_reason'],capability_summary=ctx['capability_summary'])
        assert result.success,result.validation_errors
        final=store.load_case(case.metadata.case_id);verify_history(final)
        assert final.action_state.next_actor=='investigator'
        assert final.evidence_records==case.evidence_records
        assert [r['mode'] for r in calls]==['hypothesis_changes','pair_selection']


@pytest.mark.parametrize('number',[1,2])
def test_paid_answers_survive_extraction_references_and_atomic_write(number):
    case,ctx,cfg=fixture();folder=ROOT/f'model_calls/call_{number:04d}_explorer'
    raw=json.loads((folder/'response.json').read_text())['content']
    value,changes=decode_json(raw);before=deepcopy(value)
    class SavedBackend:
        whole_proposal_retries=False
        generate_initial=lambda *a,**k: (_ for _ in ()).throw(AssertionError('No fresh proposal'))
        def generate_reframe(self,*a,**k):return value
    with CaseStore() as store:
        store.import_case(case)
        result=MechanismExplorer(SavedBackend(),cfg).run(store,case.metadata.case_id,mode='reframe',reframe_reason=ctx['reframe_reason'],capability_summary=ctx['capability_summary'])
        assert result.success,result.validation_errors
        final=store.load_case(case.metadata.case_id);verify_history(final)
        assert final.action_state.next_actor=='investigator'
        assert final.evidence_records==case.evidence_records and value==before
        for q in value['evidence_questions']:
            saved=next(x for x in final.evidence_questions if x.question_id==q['question_id'])
            assert saved.question_text==q['question_text']
            assert list(saved.derived_from_prediction_ids)==q['derived_from_prediction_ids']
        for p in value['predictions']:
            saved=next(x for h in final.hypotheses for x in h.predictions if x.prediction_id==p['prediction_id'])
            assert saved.statement==p['statement']


def test_semantic_patch_fills_only_missing_outcome_in_one_call():
    from jure.agents.explorer.scientific_content import PairDetail
    outcome={'observation':'Synthetic observation','reason':'Synthetic reason','interpretation_limit':'Synthetic limit'}
    detail=dict(difference='Synthetic difference',question='Synthetic question?',observable='Synthetic frequency',
        capability_ids=['state.joint'],expected_under_first='First expectation',expected_under_second='Second expectation',
        outcomes={'favoring_first':outcome,'favoring_second':outcome},scope_limit='Synthetic scope',prediction_refs=['h1.p1'])
    calls=[]
    def transport(req):
        calls.append(req)
        if req['mode']=='pair_details':return detail
        assert req['mode']=='semantic_patch'
        assert req['context']['missing_fields']=={'field_0':['outcomes','non_discriminating']}
        return {'field_0':outcome}
    backend=ScientificContentBackend(transport)
    result=backend._ask('pair_details',PairDetail,{},'Test only')
    assert result['outcomes']['favoring_first']==detail['outcomes']['favoring_first']
    assert result['outcomes']['non_discriminating']==outcome
    assert len(calls)==2 and backend.audit['patches'][0]['patch_id']=='P01'
    with pytest.raises(ValueError,match='allowance exhausted'):
        backend._ask('pair_details',PairDetail,{},'Test only')
    assert len(calls)==3  # No second repair, no full-proposal regeneration.


def test_initial_content_compiles_without_internal_identifiers_from_model():
    from jure.agents.explorer.scientific_content import ScientificFields
    _,oldctx,cfg=fixture()
    initial=load_case('outputs/pilot_preparation_v1_20260928/initial_cases/A/case_file.json')
    ctx=build_explorer_context(initial,'initial',max_chars=750000)
    ctx['schema_requirements'].update(min_hypotheses=3,max_hypotheses=4)
    draft={'mechanistic_question':oldctx['current_mechanistic_question']['question_text'],'changes':[]}
    for h in compact_context(oldctx)['hypotheses']:
        fields=deepcopy(h['fields']);fields['structure']['directed_edges']=[dict(source=a,target=b) for a,b in fields['structure']['directed_edges']]
        pred={k:h['predictions'][-1][k] for k in ('statement','expected_if_true','weakened_if_observed')}
        draft['changes'].append({'target':None,'reason':'Synthetic initial design','fields':fields,'predictions':[pred]})
    proposal,view,handles,pmap,pairs=assemble_changes(draft,ctx)
    choices={k:{'status':'NOT_CURRENTLY_INFORMATIVE','reason':'Synthetic limited capabilities'} for k in pairs}
    out=assemble_pairs(proposal,handles,pmap,pairs,choices,{})
    assert len(out.hypotheses)==3 and len(out.pair_decisions)==3
    assert all(h.operation=='add' for h in out.hypotheses)
    _,admission=admit_proposal(out.model_dump(mode='json'),initial,config=cfg,capability_summary=oldctx['capability_summary'])
    assert not admission.blocking_messages
