"""Synthetic engineering fixtures. Never scientific examples or real results."""
from copy import deepcopy
import json
import pytest
from pydantic import ValidationError

from test_explorer_content_adapter import fixture, CAPS
from jure.agents.explorer.pairwise_adapter import (
    HypothesisContent, PairwiseExplorerBackend, pair_plan, design_model,
    compile_pairwise, extract_pairwise, AdapterError, METHOD_A, METHOD_B)
from jure.agents.explorer.agent import MechanismExplorer
from jure.agents.explorer.models import ExplorerConfig
from jure.casefile.history import verify_history
from jure.runtime.backends import CheckedTransport


@pytest.fixture
def pair_fixture(fixture):
    store, case, old, context = fixture
    content = deepcopy(old)
    del content['contrasts']
    for h in content['hypotheses']:
        h['rationale'] = 'Synthetic rationale; no empirical result.'
        for p in h['predictions']:
            del p['alternatives'], p['evidence_question']
    content = HypothesisContent.model_validate(content).model_dump(mode='json')
    designs = {}
    for pair in pair_plan(content):
        a, b = pair['first'], pair['second']
        designs[pair['key']] = dict(
            difference=f'Synthetic contrast between positions {a} and {b}.',
            question=f'Synthetic comparison question {a} and {b}?',
            observable='conditional state frequency', available_observables=['conditional state frequency'],
            first_predictions=['prediction_1'], second_predictions=['prediction_1'],
            expected_under_first=f'Expected synthetic observation for {a}.',
            expected_under_second=f'Expected synthetic observation for {b}.',
            outcomes={key:dict(observation=f'Synthetic {label} observation.', reason=f'Synthetic {label} reason.',
                interpretation_limit='Synthetic fixture; no causal inference.')
                for key, label in [('favoring_first', 'FAVORS_FIRST'), ('favoring_second', 'FAVORS_SECOND'),
                                   ('non_discriminating', 'NON_DISCRIMINATING')]},
            scope_limit='Synthetic comparison only.', evidence_type='dataset')
    context['write_contract'] = {'validation_policy': 'three_layer'}
    return store, case, content, designs, context


def test_plan_and_schema_require_every_pair_and_exclude_self(pair_fixture):
    _, _, content, designs, _ = pair_fixture
    plan = pair_plan(content)
    assert [(p['first'], p['second']) for p in plan] == [(1, 2), (1, 3), (2, 3)]
    assert all(p['first'] not in p['first_available_alternatives'] for p in plan)
    assert all(p['second'] not in p['second_available_alternatives'] for p in plan)
    schema = design_model(content).model_json_schema()
    assert schema['required'] == ['pair_1_2', 'pair_1_3', 'pair_2_3']
    assert 'outcome_relation' not in json.dumps(schema)
    del designs['pair_2_3']
    with pytest.raises(ValidationError):
        design_model(content).model_validate(designs)


@pytest.mark.parametrize('error', ['neutral_directional', 'old_flags', 'missing_reason',
    'missing_neutral', 'unknown_prediction', 'duplicate_prediction', 'self_pair', 'alternative_field'])
def test_bad_design_not_repaired(pair_fixture, error):
    _, _, content, designs, context = pair_fixture
    pair = designs['pair_1_2']
    if error == 'neutral_directional': pair['outcomes']['non_discriminating']['outcome_relation'] = 'FAVORS_FIRST'
    elif error == 'old_flags': pair['outcomes']['non_discriminating']['favors'] = [1]
    elif error == 'missing_reason': del pair['outcomes']['favoring_second']['reason']
    elif error == 'missing_neutral': del pair['outcomes']['non_discriminating']
    elif error == 'unknown_prediction': pair['first_predictions'] = ['prediction_99']
    elif error == 'duplicate_prediction': pair['first_predictions'] *= 2
    elif error == 'self_pair': designs['pair_1_1'] = deepcopy(pair)
    elif error == 'alternative_field': pair['alternative_hypothesis'] = 1
    before = deepcopy(designs)
    with pytest.raises(ValidationError): compile_pairwise(content, designs, context)
    assert designs == before


def test_lossless_compilation_and_no_added_weakening_claim(pair_fixture):
    _, _, content, designs, context = pair_fixture
    output, audit = compile_pairwise(content, designs, context)
    assert extract_pairwise(output) == dict(hypotheses=content, designs=designs)
    assert audit['input_content_sha256'] == audit['roundtrip_content_sha256']
    for q in output.evidence_questions:
        outcomes = q.discrimination.possible_outcomes
        assert all(not o.weakens for o in outcomes)
        assert outcomes[2].non_discriminating and not outcomes[2].favors
    assert all(p.hypothesis_id not in p.discriminates_from_hypotheses for p in output.predictions)


def test_uncovered_prediction_requires_agent_not_adapter(pair_fixture):
    _, _, content, designs, context = pair_fixture
    content['hypotheses'][0]['predictions'].append(deepcopy(content['hypotheses'][0]['predictions'][0]))
    with pytest.raises(AdapterError, match='without a comparison'):
        compile_pairwise(content, designs, context)
    designs['pair_1_2']['first_predictions'].append('prediction_2')
    output, _ = compile_pairwise(content, designs, context)
    assert 'P1.2' in output.evidence_questions[0].derived_from_prediction_ids


def test_checked_transport_atomic_commit_and_investigator_handoff(pair_fixture):
    store, case, content, designs, _ = pair_fixture
    captured = []
    def provider(request, *, role):
        assert role == 'explorer'
        captured.append(request)
        return json.dumps(content if request['mode'] == METHOD_A else designs)
    backend = PairwiseExplorerBackend(CheckedTransport(provider, 'explorer', schema_retries=0, protocol_v3=True))
    result = MechanismExplorer(backend, ExplorerConfig(protocol_v3=True, validation_policy='three_layer',
        min_hypotheses=3, max_retries=0)).run(store, case.metadata.case_id, capability_summary=CAPS)
    assert result.success, result.validation_errors
    after = store.load_case(case.metadata.case_id)
    verify_history(after)
    assert [r['mode'] for r in captured] == [METHOD_A, METHOD_B]
    assert len(after.hypotheses) == 3 and len(after.evidence_questions) == 3
    assert after.clue == case.clue and after.action_state.next_actor == 'investigator'
    assert not after.evidence_records and not after.critic_audits.hypothesis_audits
    assert after.evidence_questions[0].query_spec['discrimination']['possible_outcomes'][0]['reason']
    assert any(e.metadata.get('reason') == content['hypotheses'][0]['rationale'] for e in after.investigation_history)


def test_stage_b_failure_never_commits_stage_a(pair_fixture):
    store, case, content, designs, _ = pair_fixture
    del designs['pair_2_3']
    backend = PairwiseExplorerBackend(lambda r: content if r['mode'] == METHOD_A else designs)
    result = MechanismExplorer(backend, ExplorerConfig(protocol_v3=True, validation_policy='three_layer',
        min_hypotheses=3, max_retries=0)).run(store, case.metadata.case_id, capability_summary=CAPS)
    assert not result.success
    after = store.load_case(case.metadata.case_id)
    assert not after.hypotheses and not after.evidence_questions and not after.mechanistic_question
    assert backend.last_compiled is None


def test_no_silent_reframe_or_out_of_bounds_stage_b_call(pair_fixture):
    _, _, content, _, context = pair_fixture
    calls = []
    backend = PairwiseExplorerBackend(lambda r: calls.append(r) or content)
    with pytest.raises(AdapterError): backend.generate_reframe(context)
    context['schema_requirements']['max_hypotheses'] = 2
    with pytest.raises(AdapterError): backend.generate_initial(context)
    assert len(calls) == 1


def test_prose_is_copied_not_scientifically_adjudicated(pair_fixture):
    _, _, content, designs, context = pair_fixture
    # Deliberately bad synthetic science: machine schema must not become a Critic.
    text = 'Synthetic contradictory reason saying first is favored.'
    designs['pair_1_2']['outcomes']['non_discriminating']['reason'] = text
    output, audit = compile_pairwise(content, designs, context)
    assert output.evidence_questions[0].discrimination.possible_outcomes[2].reason == text
    assert audit['scientific_validity'] == 'NOT_ASSESSED'


def test_pair_stage_keeps_existing_registered_capability_normalization(pair_fixture):
    from jure.protocol.normalization import normalize_output
    _, _, content, designs, context = pair_fixture
    designs['pair_1_2']['available_observables'] = ['state.conditional']
    value, audit = normalize_output(designs, role='explorer', method=METHOD_B,
        schema=design_model(content).model_json_schema(), context=context)
    assert value['pair_1_2']['available_observables'] == ['conditional state frequency']
    assert audit['changes'][0]['raw_value'] == 'state.conditional'
    compile_pairwise(content, value, context)


def test_smoke_runner_is_bounded_to_five_synthetic_examples(pair_fixture, tmp_path, monkeypatch):
    from jure.runtime import pairwise_smoke as smoke
    _, case, content, designs, _ = pair_fixture
    initial = tmp_path / 'initial.json'
    initial.write_text(case.model_dump_json())
    root = tmp_path / 'smoke'; root.mkdir()
    frozen = dict(cases=[dict(slot=f'S{i}', type='synthetic', path=str(initial)) for i in range(1, 6)],
        provider_config={'model': 'glm-4.7-flash'}, capability_summary=CAPS,
        config={'evaluation': 'Synthetic runner test; not a real smoke.'})
    (root / 'SMOKE_FROZEN.json').write_text(json.dumps(frozen))
    monkeypatch.setattr(smoke, 'validate_frozen', lambda _: None)
    monkeypatch.setattr(smoke.getpass, 'getpass', lambda _: 'synthetic-not-a-credential')
    captured = []
    class Provider:
        def __init__(self, *, config, api_key, trace_dir):
            assert config.max_calls == 10
            self.calls = 0; self.records = []
        def __call__(self, request, *, role):
            assert role == 'explorer' and self.calls < 10
            self.calls += 1
            self.records.append(dict(status='success', finish_reason='stop'))
            captured.append(request['mode'])
            return json.dumps(content if request['mode'] == METHOD_A else designs)
        def summary(self): return {'calls': self.calls}
    monkeypatch.setattr(smoke, 'GLMTransport', Provider)
    smoke.run(root)
    report = json.loads((root / 'SMOKE_SUMMARY.json').read_text())
    assert captured == [METHOD_A, METHOD_B] * 5
    assert report['temporary_proposal_submissions'] == 5
    assert report['complete_final_responses'] == 10
    assert report['model_calls'] == 10 and not report['case_a_launched']
    assert not report['critic_calls'] and not report['investigator_calls'] and not report['evidence_tool_calls']


def test_availability_failures_are_not_json_or_scientific_failures():
    from jure.runtime.pairwise_smoke import call_outcomes
    result = call_outcomes([{'error': 'provider_http_error'}, {'error': 'provider_connection_error'},
        {'error': 'provider_response_is_not_json', 'finish_reason': 'stop'}])
    assert result['provider_availability_failures'] == 2
    assert result['invalid_json_responses'] == 1 and result['complete_final_responses'] == 1


def test_saved_real_s2_needs_no_redundant_relation_or_new_science(tmp_path):
    from scripts.tools.replay_pairwise_s2 import run
    report = run(tmp_path / 'saved_output_replay')
    assert report['temporary_store_submission'] and report['schema_stages_passed'] == 2
    assert report['hypotheses'] == report['questions'] == 3
    assert report['next_actor'] == 'investigator'
    assert report['new_model_calls'] == report['evidence_calls'] == report['critic_calls'] == 0
    assert report['content_retention']['input_content_sha256'] == report['content_retention']['roundtrip_content_sha256']
    assert report['source_hashes_unchanged'] and not report['case_a_launched']
