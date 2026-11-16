"""Reopen B under the user's explicit budget-extension authorization.

Preserve pilot v1 and all science. Assemble the existing Critic's continuation
recommendations verbatim; do not choose evidence queries or author hypotheses.
"""
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from jure.casefile import ActionState, CaseStore, load_case
from jure.casefile.critic_models import InvestigationRequest
from jure.casefile.history import agent_round_counts, verify_history
from jure.runtime.pilot import save, validate_independent_resume
from jure.tools.real.registry import file_sha


def main():
    base = Path('outputs/agent_pilot_v1_20260928')
    source_dir = base / 'run_040_case_b_completion/B'
    target = base / 'case_b_budget_extension_preparation_20260929/B'
    source_path = source_dir / 'case_file/case_file.json'
    source = load_case(source_path)
    source_sha = file_sha(source_path)
    summary = json.loads((source_dir / 'case_run_summary.json').read_text())
    evaluation_path = source_dir / 'model_calls/call_0003_critic/structured_output.json'
    evaluation = json.loads(evaluation_path.read_text())
    failure = source.critic_audits.failure_attributions[-1]
    assert source.action_state.current_phase == 'stopped'
    assert summary['completed'] and summary['cumulative_model_calls'] == 78
    assert summary['tool_calls'] == 15
    assert source.critic_audits.hypothesis_audits[-1].overall_status == 'pass'
    assert not evaluation['no_further_queries'] and not evaluation['evidence_sufficient']
    assert failure.reason_type == 'evidence_missing'
    assert all(agent_round_counts(source, role)['completed'] == 3
               for role in ('investigator', 'critic'))

    old_config = json.loads(Path('configs/agent_pilot_case_b_synthesis_field_recovery.json').read_text())
    config = {key: old_config[key] for key in (
        'model_config', 'explorer', 'investigator', 'critic',
        'critic_rechecks_per_round', 'registry_budgets',
        'protocol_v3', 'schema_retries', 'failed_stage_retries',
        'provider_retry_delays_seconds', 'resume_execution_policy')}
    config['investigator']['max_tool_calls_per_run'] = 6
    config['critic'].update(max_critic_rounds=5, max_investigator_rounds=5,
                            max_total_tool_calls=32)
    config['registry_budgets']['total'] = 32
    authorization = {
        'user_instruction': '放宽给case b的预算',
        'baseline_run': str(source_dir), 'source_sha256': source_sha,
        'inherited_model_calls': 78, 'inherited_tool_calls': 15,
        'old_caps': {'model_calls': 80, 'tool_calls': 18,
                     'investigator_rounds': 3, 'critic_rounds': 3,
                     'investigator_tools_per_round': 4},
        'new_caps': {'model_calls': 130, 'tool_calls': 32,
                     'investigator_rounds': 5, 'critic_rounds': 5,
                     'investigator_tools_per_round': 6},
        'additional_explorer_revision_allowance': 0,
        'protocol_prompts_and_scientific_rules_unchanged': True,
        'separate_budget_extension_not_pilot_v1_result': True,
    }
    request = InvestigationRequest(
        request_id='IR_B_budget_extension_from_C3',
        target_gap_ids=failure.related_gap_ids,
        target_claim_ids=failure.related_claim_ids,
        objective=evaluation['reason'],
        why_needed='\n'.join(evaluation['remaining_uncertainties']),
        desired_evidence_characteristics=tuple(
            item['measurement'] for item in evaluation['recommended_experiments']),
        critic_round=failure.critic_round,
    )
    target.mkdir(parents=True, exist_ok=False)
    with CaseStore(target / 'case_store.sqlite') as store:
        store.import_case(source)
        current = store.append_history_event(
            source.metadata.case_id, actor='controller',
            expected_revision=source.metadata.case_revision,
            summary='User authorized a separate Case B budget-extension continuation.',
            metadata={
                'controller_event': 'USER_AUTHORIZED_BUDGET_EXTENSION',
                'authorization': authorization,
                'historical_stop_and_all_science_retained': True,
                'request_assembly': {
                    'scientific_author': 'critic',
                    'source_evaluation_path': str(evaluation_path),
                    'source_evaluation_sha256': file_sha(evaluation_path),
                    'objective_source': 'reason',
                    'why_needed_source': 'remaining_uncertainties joined with newlines',
                    'desired_evidence_characteristics_source': 'recommended_experiments[*].measurement',
                    'target_ids_source': failure.attribution_id,
                    'verbatim_content': True,
                    'not_a_new_critic_run_or_routing_decision': True,
                    'query_selection_remains_investigator_owned': True,
                },
            })
        current = store.append_critic_records(
            current.metadata.case_id, investigation_requests=(request,),
            actor='critic', expected_revision=current.metadata.case_revision)
        current = store.set_action_state(
            current.metadata.case_id,
            ActionState(current_phase='evidence_needed', next_actor='investigator'),
            actor='controller', expected_revision=current.metadata.case_revision)
        verify_history(current)
        for field in ('clue', 'hypotheses', 'mechanistic_question', 'evidence_questions',
                      'evidence_records', 'evidence_assessments', 'mechanistic_claims',
                      'evidence_gaps', 'contradictions'):
            assert getattr(current, field) == getattr(source, field), field
        for field in type(source.critic_audits).model_fields:
            old, new = getattr(source.critic_audits, field), getattr(current.critic_audits, field)
            assert new == ((*old, request) if field == 'investigation_requests' else old), field
        assert current.investigation_history[:len(source.investigation_history)] == source.investigation_history
        store.export_case(current.metadata.case_id, target / 'case_file')

    for name in ('stage_results.json', 'tool_trace.jsonl', 'model_usage.json'):
        shutil.copyfile(source_dir / name, target / name)
    save(target / 'case_run_summary.json', {
        **summary, 'completed': False, 'technical_gate_passed': False,
        'stop_reason': None, 'failure': None, 'checkpoint_only': True,
        'current_run_stages': 0,
        'predecessor': {'directory': str(source_dir), 'case_sha256': source_sha},
    })
    config.update(
        protocol_id='jure_case_b_budget_extension_v1', case_order=['B'],
        provider_max_calls_per_case=130, max_transitions=16,
        resume_sources={'B': {'directory': str(target),
                             'case_sha256': file_sha(target / 'case_file/case_file.json')}},
        budget_extension_authorization=authorization,
        policy='B-only explicitly authorized budget extension. Resume Investigator from the preserved final C1/C2 checkpoint. Investigator chooses queries; Critic judges science and routes. No winner target. Preserve cumulative accounting and prior STOP. A/C/D paused. No prompt, scientific protocol, evidence support threshold or tool implementation changes.',
    )
    path = Path('configs/agent_pilot_case_b_budget_extension.json')
    save(path, config)
    assert validate_independent_resume(config, 'B')
    assert file_sha(source_path) == source_sha
    save(target / 'PREPARATION_VERIFICATION.json', {
        'history_verified': True, 'historical_science_unchanged': True,
        'historical_audits_and_stop_unchanged': True, 'history_prefix_exact': True,
        'source_unchanged': True, 'request_copies_existing_critic_verbatim': True,
        'model_calls': 0, 'evidence_queries': 0,
        'authorization': authorization, 'config': str(path),
    })
    print(json.dumps({'config': str(path), 'remaining_model_calls': 52,
                      'remaining_registry_tool_calls': 17,
                      'additional_investigator_critic_rounds': 2}))


if __name__ == '__main__':
    main()
