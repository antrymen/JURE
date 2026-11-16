"""Synthetic contract fixtures only; never used in the real benchmark."""
from copy import deepcopy
import json
import pytest
from pydantic import ValidationError

from jure.casefile import CaseStore
from jure.casefile.history import verify_history
from jure.agents.explorer.agent import MechanismExplorer
from jure.agents.explorer.demo import initial_output,synthetic_clue
from jure.agents.explorer.models import ExplorerConfig,ExplorerOutput
from jure.agents.explorer.context import build_explorer_context
from jure.agents.explorer.content_adapter import (ExplorerContent,ContentExplorerBackend,compile_initial,
    extract_content,AdapterError,canonical_hash)
from jure.agents.explorer.contract_checks import reference_errors
from jure.protocol.capabilities import capability_summary

CAPS=capability_summary([{'tool_id':tool,'availability':'available'} for tool in ('data_experiment','knowledge_graph','literature','clue_query')])


@pytest.fixture
def fixture(tmp_path):
    with CaseStore(tmp_path/'unit.sqlite') as store:
        case=store.create_case_from_clue(synthetic_clue(),cell_context='K562')
        proposal=initial_output(case)
        for p,q in zip(proposal['predictions'],proposal['evidence_questions']):
            targets=[p['hypothesis_id'],*p['discriminates_from_hypotheses']]
            q.update(relevant_hypothesis_ids=targets,discriminates_between=targets)
            q['discrimination']={'targets':targets,'expectations':[
                {'hypothesis_id':target,'prediction':p['expected_if_true'] if target==p['hypothesis_id'] else f'An alternative conditional frequency pattern under {target}.'} for target in targets],
                'observable':'Conditional state frequency','capability_ids':['state.conditional'],
                'possible_outcomes':[{'outcome_id':'O1','observation':'Predeclared pattern','favors':[targets[0]],'weakens':[targets[1]],'non_discriminating':False,'interpretation_limit':'No causal proof.'},
                                     {'outcome_id':'O2','observation':'No usable difference','favors':[],'weakens':[],'non_discriminating':True,'interpretation_limit':'Insufficient comparison.'}],
                'scope_limit':'Synthetic fixture only.'}
        content=extract_content(ExplorerOutput.model_validate(proposal))
        context=build_explorer_context(case,'initial');context['capability_summary']=CAPS
        context['schema_requirements'].update(min_hypotheses=3,max_hypotheses=4)
        yield store,case,content,context


def test_adapter_assigns_ids_lineage_and_lossless_content_without_evidence(fixture):
    store,case,content,context=fixture
    assert not any(key in json.dumps(ExplorerContent.model_json_schema()) for key in ('derived_from_clue_id','prediction_id','question_id'))
    before=deepcopy(content)
    output,audit=compile_initial(content,context)
    assert content==before
    assert extract_content(output)==content
    assert audit['input_content_sha256']==audit['roundtrip_content_sha256']==canonical_hash(content)
    assert not reference_errors(output,case,CAPS)
    assert output.hypotheses[0].hypothesis_id=='H1'
    assert output.hypotheses[0].derived_from[0].object_id==case.clue.clue_id
    assert output.evidence_questions[0].derived_from_prediction_ids==('P1.1',)
    assert compile_initial(content,context)[0]==output


def test_real_explorer_commit_boundary_uses_adapter_and_no_investigator(fixture,tmp_path):
    store,case,content,context=fixture
    captured=[]
    def transport(request):captured.append(request);return content
    backend=ContentExplorerBackend(transport)
    result=MechanismExplorer(backend,ExplorerConfig(min_hypotheses=3,max_retries=0,protocol_v3=True)).run(store,case.metadata.case_id,capability_summary=CAPS)
    assert result.success,result.validation_errors
    after=store.load_case(case.metadata.case_id);verify_history(after)
    assert len(after.hypotheses)==3 and not after.evidence_records and not after.mechanistic_claims
    assert after.clue==case.clue and len(captured)==1
    assert after.action_state.next_actor=='investigator'  # routing only; never execute it
    assert 'response_schema' in captured[0]


@pytest.mark.parametrize('kind',['unknown_alternative','self_alternative','outcome_outside_targets','unknown_contrast'])
def test_adapter_rejects_unresolvable_scientific_references_without_guessing(fixture,kind):
    _,_,content,context=fixture;p=content['hypotheses'][0]['predictions'][0]
    if kind=='unknown_alternative':p['alternatives'][0]['hypothesis']=15
    elif kind=='self_alternative':p['alternatives'][0]['hypothesis']=1
    elif kind=='outcome_outside_targets':p['evidence_question']['possible_outcomes'][0]['favors']=[15]
    else:content['contrasts'][0]['hypothesis_b']=15
    with pytest.raises(AdapterError):compile_initial(content,context)


def test_missing_scientific_outcomes_or_alternatives_not_filled_in(fixture):
    _,_,content,context=fixture
    content['hypotheses'][0]['predictions'][0]['alternatives']=[]
    with pytest.raises(ValidationError):compile_initial(content,context)


def test_forbidden_metadata_is_rejected_not_silently_discarded(fixture):
    _,_,content,context=fixture;content['hypotheses'][0]['derived_from_clue_id']='invented'
    with pytest.raises(ValidationError):compile_initial(content,context)


def test_entity_normalization_is_exact_supplied_symbol_case_only(fixture):
    _,_,content,context=fixture
    content['hypotheses'][1]['structure']['directed_edges'][0]['source']='a'
    content['hypotheses'][1]['structure']['directed_edges'][0]['target']='unknown_alias'
    output,audit=compile_initial(content,context)
    assert output.hypotheses[1].structure.directed_edges[0]==('A','unknown_alias')
    assert len(audit['entity_normalizations'])==1 and audit['content_retained']
    assert output.hypotheses[1].mechanism_statement==content['hypotheses'][1]['mechanism_statement']


def test_unavailable_capability_and_reframe_are_not_guessed(fixture):
    _,_,content,context=fixture
    context['capability_summary']={'observables':[]}
    with pytest.raises(AdapterError,match='not available'):compile_initial(content,context)
    context['mode']='reframe'
    with pytest.raises(AdapterError,match='initial proposals only'):compile_initial(content,context)


def test_schema_pass_does_not_bypass_scientific_guard(fixture):
    store,case,content,context=fixture
    content['hypotheses'][0]['predictions'][0]['statement']='This pathway is biologically important.'
    output,_=compile_initial(content,context)
    assert not reference_errors(output,case,CAPS)
    result=MechanismExplorer(ContentExplorerBackend(lambda _:content),ExplorerConfig(min_hypotheses=3,max_retries=0,protocol_v3=True)).run(store,case.metadata.case_id,capability_summary=CAPS)
    assert not result.success and any('not a testable' in e for e in result.validation_errors)
    assert not store.load_case(case.metadata.case_id).hypotheses
