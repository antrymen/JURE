"""Offline synthetic tests of responsibility, not biological judgments."""
from copy import deepcopy
import pytest
from jure.casefile import CaseStore
from jure.agents.explorer.demo import synthetic_clue,initial_output
from jure.protocol.capabilities import capability_summary
from scripts.tools.validator_audit import evaluate_payload,classify_old,project_without_repair

CAPS=capability_summary([{'tool_id':'data_experiment','availability':'available'}])
BOUNDS={'min_hypotheses':3,'max_hypotheses':4,'protocol_v3':True}


@pytest.fixture
def proposal():
    with CaseStore() as store:
        case=store.create_case_from_clue(synthetic_clue(),cell_context='K562')
        value=initial_output(case)
        for q in value['evidence_questions']:
            targets=q['discriminates_between']
            q['discrimination']={'targets':targets,'expectations':[{'hypothesis_id':h,'prediction':f'Conditional frequency pattern {i}.'} for i,h in enumerate(targets)],
                'observable':'Conditional state frequency','capability_ids':['state.conditional'],
                'possible_outcomes':[{'outcome_id':f'O{i}','observation':f'Pattern {i}', 'favors':[h], 'weakens':[], 'non_discriminating':False,'interpretation_limit':'No causal verdict.'} for i,h in enumerate(targets)] +
                    [{'outcome_id':'ON','observation':'No usable difference','favors':[],'weakens':[],'non_discriminating':True,'interpretation_limit':'No verdict.'}],
                'scope_limit':'Synthetic fixture.'}
        yield case,value


def test_flags_never_become_rejects_or_evidence(proposal):
    case,value=proposal;before=case.model_dump(mode='json')
    value['hypotheses'][0]['assumptions'].append('ZXCV99 is an unnamed-in-input candidate mediator.')
    value['predictions'][0]['statement']='This pathway is biologically important.'
    result=evaluate_payload(value,case,CAPS,BOUNDS)
    assert result['existing_split_eligible'] and result['requested_split_eligible']
    assert {'UNSUPPORTED_NAMED_ENTITY','OBSERVABILITY_UNCLEAR'}<={f['code'] for f in result['findings']}
    assert case.model_dump(mode='json')==before and not case.evidence_records


def test_wrong_edge_type_stays_hard_machine_error(proposal):
    case,value=proposal;value['hypotheses'][0]['structure']['directed_edges']=['X->Y']
    result=evaluate_payload(value,case,CAPS,BOUNDS)
    assert not result['existing_split_eligible'] and not result['structure_evaluated']
    assert all(f['layer']=='machine' for f in result['findings'])


@pytest.mark.parametrize('missing',['neutral','contrast','question','expectation'])
def test_absent_scientific_structure_returns_to_explorer(proposal,missing):
    case,value=proposal;q=value['evidence_questions'][0]
    if missing=='neutral':q['discrimination']['possible_outcomes'].pop()
    elif missing=='contrast':value['contrasts'].pop()
    elif missing=='question':value['evidence_questions'].pop()
    else:q['discrimination']['expectations'].pop()
    result=evaluate_payload(value,case,CAPS,BOUNDS)
    assert not result['existing_split_eligible']
    assert any(f['layer']=='completeness' for f in result['findings'])
    assert not any(f['layer']=='machine' for f in result['findings'])


def test_reciprocal_branches_are_an_explicit_additional_rule(proposal):
    case,value=proposal;q=value['evidence_questions'][0]
    q['discrimination']['possible_outcomes'][1]['favors']=[]
    q['discrimination']['possible_outcomes'][1]['weakens']=['H1']
    result=evaluate_payload(value,case,CAPS,BOUNDS)
    assert result['existing_split_eligible'] and not result['requested_split_eligible']
    assert any(f['code']=='MISSING_RECIPROCAL_FAVOR_BRANCH' for f in result['findings'])


def test_unknown_and_unavailable_capabilities_have_different_responsibilities(proposal):
    case,value=proposal;q=value['evidence_questions'][0]
    q['discrimination']['capability_ids']=['knowledge.gene_context']
    result=evaluate_payload(value,case,CAPS,BOUNDS)
    assert result['existing_split_eligible']
    assert any(f['code']=='CAPABILITY_LIMIT' for f in result['findings'])
    q['discrimination']['capability_ids']=['invented.measurement']
    result=evaluate_payload(value,case,CAPS,BOUNDS)
    assert not result['existing_split_eligible']
    assert any(f['code']=='UNKNOWN_CAPABILITY_ID' for f in result['findings'])


def test_known_hypothesis_outside_this_comparison_is_not_auto_added(proposal):
    case,value=proposal;value['evidence_questions'][0]['discrimination']['possible_outcomes'][0]['favors']=['H3']
    result=evaluate_payload(value,case,CAPS,BOUNDS)
    assert not result['existing_split_eligible']
    assert any(f['layer']=='machine' and f['code']=='INVALID_REFERENCE' for f in result['findings'])


def test_neutral_flag_with_favoring_label_is_a_machine_contradiction(proposal):
    case,value=proposal;value['evidence_questions'][0]['discrimination']['possible_outcomes'][-1]['favors']=['H1']
    result=evaluate_payload(value,case,CAPS,BOUNDS)
    assert not result['existing_split_eligible']
    assert any(f['code']=='CONTRADICTORY_OUTCOME_LABELS' for f in result['findings'])


def test_offline_projection_observes_but_does_not_complete_missing_branch(proposal):
    from jure.agents.explorer.models import ExplorerOutput
    from jure.agents.explorer.content_adapter import extract_content
    from jure.agents.explorer.context import build_explorer_context
    case,value=proposal
    content=extract_content(ExplorerOutput.model_validate(value))
    content['hypotheses'][0]['predictions'][0]['evidence_question']['possible_outcomes'].pop()
    before=deepcopy(content)
    context=build_explorer_context(case,'initial');context['capability_summary']=CAPS
    context['schema_requirements'].update(min_hypotheses=3,max_hypotheses=4)
    payload=project_without_repair(content,context)
    assert content==before
    assert not any(o['non_discriminating'] for o in payload['evidence_questions'][0]['discrimination']['possible_outcomes'])
    assert not evaluate_payload(payload,case,CAPS,BOUNDS)['existing_split_eligible']


def test_original_diagnostics_are_not_all_called_json_failures():
    assert classify_old('Value error, Include an explicitly non-discriminating outcome')==('completeness','MISSING_NEUTRAL_OUTCOME')
    assert classify_old('hypothesis H1 must label its directed edge X->Y')==('critic_flag','CAUSAL_LANGUAGE_TOO_STRONG')
