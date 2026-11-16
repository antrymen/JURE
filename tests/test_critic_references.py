"""Offline typed-reference regression, including the saved Case A failure."""
from copy import deepcopy
import json
from pathlib import Path
import pytest
from jure.agents.critic.references import (CriticReferenceError, bind_failure_reference_schema,
                                          validate_failure_references)
from jure.agents.critic.backend import JSONCriticBackend, critic_output_json_schema
from jure.runtime.backends import CheckedTransport


def context():
    return {'case_id':'UNIT','hypotheses':[{'hypothesis_id':'H1'}],
            'claims':[],'evidence_records':[],'evidence_gaps':[],
            'evidence_questions':[{'question_id':'Q1'}]}


def attribution(**overrides):
    return {'reason_type':'hypothesis_problem','reason_summary':'Synthetic design concern.',
            'related_hypothesis_ids':['H1'],'related_evidence_ids':[],**overrides}


def test_empty_evidence_schema_allows_only_empty_list_and_preserves_other_types():
    schema=bind_failure_reference_schema(critic_output_json_schema('attribute_failure'),context())
    assert schema['properties']['related_evidence_ids']['maxItems']==0
    assert schema['properties']['related_hypothesis_ids']['items']['enum']==['H1']
    assert 'Q1' not in json.dumps(schema)
    with pytest.raises(CriticReferenceError,match='evidence_record'):
        validate_failure_references(attribution(related_evidence_ids=['Q1']),context())


def test_reference_membership_uses_type_not_id_prefix():
    c=context();c['evidence_records']=[{'evidence_id':'Q_but_actual_evidence'}]
    c['evidence_questions']=[{'question_id':'E_but_actual_question'}]
    validate_failure_references(attribution(related_evidence_ids=['Q_but_actual_evidence']),c)
    with pytest.raises(CriticReferenceError):
        validate_failure_references(attribution(related_evidence_ids=['E_but_actual_question']),c)


@pytest.mark.parametrize('field', ['related_evidence_ids','related_claim_ids','related_gap_ids','related_hypothesis_ids'])
def test_each_typed_field_rejects_question_ids(field):
    with pytest.raises(CriticReferenceError):
        validate_failure_references(attribution(**{field:['Q1']}),context())


def test_correction_retries_only_failed_method_and_never_edits_response():
    bad=attribution(related_evidence_ids=['Q1']);before=deepcopy(bad)
    good=attribution();requests=[]
    def provider(request,*,role):
        requests.append(deepcopy(request))
        return json.dumps(bad if len(requests)==1 else good)
    checked=CheckedTransport(provider,'critic',schema_retries=1)
    result=JSONCriticBackend(checked).attribute_failure(context())
    parsed=json.loads(result)
    assert parsed.pop('attribution_id').startswith('N_')
    assert parsed==good and bad==before
    assert [r['method'] for r in requests]==['attribute_failure','attribute_failure']
    assert 'evidence_record' in requests[1]['schema_validation_feedback'][0]
    assert json.loads(requests[1]['prior_uncommitted_response'])==bad
    assert requests[0]['response_schema']['properties']['related_evidence_ids']['maxItems']==0
    assert checked.requests[0]['status']=='schema_invalid'


def test_zero_retry_budget_remains_zero():
    requests=[]
    def provider(request,*,role):
        requests.append(request);return json.dumps(attribution(related_evidence_ids=['Q1']))
    with pytest.raises(CriticReferenceError):
        JSONCriticBackend(CheckedTransport(provider,'critic',schema_retries=0)).attribute_failure(context())
    assert len(requests)==1


def test_actual_case_a_failure_is_rejected_before_case_commit_without_repair():
    root=Path('outputs/agent_pilot_v1_20260928/run_018_glm47_admission_v1_a/A/model_calls/call_0004_critic')
    raw=(root/'structured_output.json').read_bytes()
    response=json.loads(raw)
    request=json.loads((root/'request.json').read_text())
    c=json.loads(request['messages'][1]['content'])['context']
    assert not c['evidence_records']
    with pytest.raises(CriticReferenceError,match='Q1.1'):
        validate_failure_references(response,c)
    assert (root/'structured_output.json').read_bytes()==raw
    assert response['related_evidence_ids']==['Q1.1','Q2.1','Q3.1']
