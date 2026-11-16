"""One Investigator-authored patch for three missing plan expectations."""
import getpass
import json
import shutil
import sys
from pathlib import Path
from pydantic import BaseModel, ConfigDict, Field

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from jure.agents.investigator.backend import SYSTEM_INSTRUCTIONS
from jure.agents.investigator.query_plan import QueryPlan
from jure.llm.glm import GLMConfig, GLMTransport
from jure.protocol.contracts import HypothesisExpectation
from jure.protocol.normalization import normalize_output
from jure.runtime.pilot import save
from jure.tools.real.registry import file_sha


class ExpectationPatch(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expectations: list[HypothesisExpectation] = Field(min_length=3, max_length=3)


def main():
    base = Path('outputs/agent_pilot_v1_20260928')
    source = base / 'run_042_case_b_budget_extension/B'
    target = base / 'case_b_plan_expectation_patch_20260929'
    target.mkdir(exist_ok=False)
    call = source / 'model_calls/call_0002_investigator'
    original = json.loads((call / 'structured_output.json').read_text())
    payload = json.loads((call / 'request.json').read_text())
    request = json.loads(next(m['content'] for m in payload['messages'] if m['role'] == 'user'))
    context = request['context']
    existing = {e['hypothesis_id'] for e in original['discrimination']['expectations']}
    missing = set(original['discrimination']['targets']) - existing
    assert missing == {'H2', 'H3', 'H4'}
    summary = json.loads((source / 'case_run_summary.json').read_text())
    assert summary['cumulative_model_calls'] == 80
    cfg = GLMConfig.model_validate_json(Path('configs/agent_runtime_glm53_flash.json').read_text()).model_copy(update={'max_calls': 1})
    key = getpass.getpass('GLM API key (hidden): ')
    provider = GLMTransport(config=cfg, api_key=key, trace_dir=target / 'model_calls')
    del key
    raw = provider({
        'method': 'patch_missing_discrimination_expectations',
        'system_instructions': SYSTEM_INSTRUCTIONS + '\nReturn only the local missing-content patch in the supplied schema. Do not regenerate your query plan, change hypotheses, queries, support parameters, target IDs, existing expectations, or outcomes.',
        'context': {
            'existing_plan': original,
            'missing_hypothesis_ids': sorted(missing),
            'active_hypotheses': context['active_hypotheses'],
            'predictions': context['predictions'],
            'tool_capabilities': context['tool_capabilities'],
            'instruction': 'Your plan targets five hypotheses but only gives explicit expectations for H1 and H5. Add exactly one expectation each for H2, H3 and H4 under this same observable. Shared expectations are allowed; do not invent discrimination among biological hypotheses when your plan only distinguishes that group from confounding. This is scientific content authored by Investigator; no host will fill it.',
        },
        'response_schema': ExpectationPatch.model_json_schema(),
    }, role='investigator')
    save(target / 'model_usage.json', provider.summary())
    patch = ExpectationPatch.model_validate_json(raw)
    assert {e.hypothesis_id for e in patch.expectations} == missing
    save(target / 'patch.json', patch.model_dump(mode='json'))
    revised = json.loads(json.dumps(original))
    revised['discrimination']['expectations'].extend(e.model_dump(mode='json') for e in patch.expectations)
    normalized, audit = normalize_output(revised, role='investigator', method='operationalize_question',
        schema=QueryPlan.model_json_schema(), context=context)
    QueryPlan.model_validate(normalized)
    response = target / 'plan_patched_response.json'
    save(response, {'content': json.dumps(revised, ensure_ascii=False), 'author': 'investigator',
        'original_source': str(call / 'structured_output.json'),
        'original_sha256': file_sha(call / 'structured_output.json'),
        'patch_source': str(target / 'patch.json'), 'patch_sha256': file_sha(target / 'patch.json')})
    checkpoint = target / 'B'; checkpoint.mkdir()
    shutil.copytree(source / 'case_file', checkpoint / 'case_file')
    for name in ('stage_results.json', 'tool_trace.jsonl'):
        shutil.copyfile(source / name, checkpoint / name)
    save(checkpoint / 'case_run_summary.json', {**summary, 'cumulative_model_calls': 81,
        'checkpoint_only': True, 'predecessor': {'directory': str(source), 'case_sha256': file_sha(source / 'case_file/case_file.json')},
        'local_semantic_patch': {'author': 'investigator', 'model_calls': 1, 'new_tool_calls': 0}})
    shutil.copyfile(source.parent / 'PILOT_RUNTIME_FROZEN.json', target / 'PILOT_RUNTIME_FROZEN.json')
    config = json.loads(Path('configs/agent_pilot_case_b_budget_guard_recovery.json').read_text())
    priority = source / 'model_calls/call_0001_investigator/response.json'
    config.update(protocol_id='jure_case_b_budget_extension_plan_patch',
        resume_sources={'B': {'directory': str(checkpoint), 'case_sha256': file_sha(checkpoint / 'case_file/case_file.json')}},
        saved_investigator_prefix={'responses': [
            {'path': str(priority), 'sha256': file_sha(priority), 'role': 'investigator', 'method': 'prioritize_questions'},
            {'path': str(response), 'sha256': file_sha(response), 'role': 'investigator', 'method': 'operationalize_question'},
        ], 'tools': [], 'envelopes': []},
        engineering_recovery={'reason': 'Investigator authors only missing H2/H3/H4 expectations; all existing plan text, outcomes and query parameters unchanged.',
            'same_logical_transition': 13, 'inherited_model_calls': 81, 'inherited_tool_calls': 15,
            'no_budget_reset': True})
    save('configs/agent_pilot_case_b_budget_plan_recovery.json', config)
    save(target / 'PATCH_PROVENANCE.json', {'author': 'investigator', 'added_expectations': sorted(missing),
        'old_plan_sha256': file_sha(call / 'structured_output.json'), 'patch_sha256': file_sha(target / 'patch.json'),
        'existing_plan_except_added_expectations_unchanged': True, 'query_plan_validated': True,
        'normalization_audit': audit, 'new_model_calls': 1, 'cumulative_model_calls': 81, 'new_tool_calls': 0})
    print(json.dumps({'plan_valid': True, 'config': 'configs/agent_pilot_case_b_budget_plan_recovery.json', 'remaining_model_calls': 49}))


if __name__ == '__main__':
    main()
