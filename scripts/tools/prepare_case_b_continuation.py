"""Prepare the explicitly authorized one-revision B continuation; no LLM calls.

Copy the existing Critic's latest requirement verbatim into its current request
record. Do not author a hypothesis, alter evidence, or label a defect resolved.
"""
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from jure.casefile import ActionState, CaseStore, load_case
from jure.casefile.critic_models import RevisionRequest
from jure.casefile.history import agent_round_counts, verify_history
from jure.runtime.pilot import save, validate_independent_resume
from jure.tools.real.registry import file_sha


def main():
    base = Path('outputs/agent_pilot_v1_20260928')
    source_dir = base / 'run_014_glm53_v22_ab_repair/B'
    target = base / 'case_b_continuation_preparation_20260929/B'
    target.mkdir(parents=True, exist_ok=False)
    source_path = source_dir / 'case_file/case_file.json'
    source_sha = file_sha(source_path)
    source = load_case(source_path)
    verify_history(source)
    summary = json.loads((source_dir / 'case_run_summary.json').read_text())
    audit = source.critic_audits.hypothesis_audits[-1]
    assert source.action_state.current_phase == 'stopped'
    assert audit.audit_id == 'HA_round2_HSPA9_DDIT4_PHGDH_TRIB3'
    assert audit.overall_status == 'revision_required'
    assert summary['cumulative_model_calls'] == 49 and summary['tool_calls'] == 9
    assert agent_round_counts(source, 'explorer', mode='reframe')['completed'] == 1
    assert agent_round_counts(source, 'investigator')['completed'] == 2
    assert agent_round_counts(source, 'critic')['completed'] == 2
    assert not source.critic_audits.claim_audits

    # The first coverage entry is the exact outstanding design requirement.
    # The remaining entries describe evidence limitations, not repair tasks.
    requirement = audit.coverage_issues[0]
    assert requirement.startswith('Critical coverage failure:')
    request = RevisionRequest(
        request_id='RR_B_legacy_C1_coverage_continuation',
        reason=audit.audit_summary,
        affected_hypothesis_ids=tuple(h.hypothesis_id for h in source.hypotheses),
        issues=audit.coverage_issues,
        required_changes=(requirement,),
        critic_round=audit.critic_round,
        created_at=audit.created_at,
    )
    with CaseStore(target / 'case_store.sqlite') as store:
        store.import_case(source)
        current = store.append_history_event(
            source.metadata.case_id, actor='controller',
            expected_revision=source.metadata.case_revision,
            summary='User authorized exactly one additional Explorer revision for Case B.',
            metadata={
                'controller_event': 'USER_AUTHORIZED_CASE_CONTINUATION',
                'user_authorization': '允许',
                'authorization_context': 'One additional Explorer revision, then Investigator and Critic; cumulative model/tool caps 80/18 unchanged.',
                'source_case_file': str(source_path), 'source_sha256': source_sha,
                'legacy_completed_reframes': 1, 'additional_reframe_submissions': 1,
                'legacy_model_calls': 49, 'legacy_tool_calls': 9,
                'original_stop_retained': True,
                'request_assembly': {
                    'scientific_author': 'critic', 'source_audit_id': audit.audit_id,
                    'reason_source': 'audit_summary',
                    'required_changes_source': 'coverage_issues[0]',
                    'content_copied_verbatim': True, 'new_model_call': False,
                    'not_a_new_C1_or_acceptance': True,
                },
                'budget_accounting': 'Legacy completed reframe remains charged in this ledger. Current protocol allows at most one additional submission (one Explorer transition), at most one accepted revision, and no replenishment of Investigator/Critic rounds or model/tool calls.',
            })
        # Persistence represents the existing Critic author, not a host verdict.
        current = store.append_critic_records(
            current.metadata.case_id, revision_requests=(request,), actor='critic',
            expected_revision=current.metadata.case_revision)
        current = store.set_action_state(
            current.metadata.case_id,
            ActionState(current_phase='exploration_needed', next_actor='explorer'),
            actor='controller', expected_revision=current.metadata.case_revision)
        verify_history(current)
        for field in ('clue', 'hypotheses', 'mechanistic_question', 'evidence_questions',
                      'evidence_records', 'evidence_assessments', 'mechanistic_claims',
                      'evidence_gaps', 'contradictions'):
            assert getattr(current, field) == getattr(source, field), field
        for field in source.critic_audits.model_fields:
            old, new = getattr(source.critic_audits, field), getattr(current.critic_audits, field)
            assert (new == (*old, request)) if field == 'revision_requests' else (new == old), field
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
    config = json.loads(Path('configs/agent_pilot_case_a_final_completion.json').read_text())
    keep = ('model_config', 'explorer', 'investigator', 'critic', 'critic_rechecks_per_round',
            'registry_budgets', 'provider_max_calls_per_case')
    config = {key: config[key] for key in keep}
    config['explorer'].update(max_hypotheses=5, max_retries=1)
    config['critic'].update(max_revision_acceptance_attempts=1, max_explorer_reframes=1)
    config.update(
        protocol_id='jure_case_b_authorized_one_revision_continuation',
        case_order=['B'], protocol_v3=True, schema_retries=0,
        failed_stage_retries=0, max_transitions=12, provider_retry_delays_seconds=[],
        resume_execution_policy='independent_existing_checkpoints',
        resume_sources={'B': {'directory': str(target),
                             'case_sha256': file_sha(target / 'case_file/case_file.json')}},
        policy='User-authorized B continuation only. Exactly one additional Explorer submission after legacy transition9, followed by Investigator then Critic. All hypotheses, predictions, evidence choices, acceptance and C1/C2 decisions remain JURE Agent-authored. Preserve historical STOP and all paid calls. No Mechanism Resolution Framework implementation; A/C/D paused.',
        continuation_authorization={
            'user_reply': '允许', 'source_case_sha256': source_sha,
            'legacy_completed_reframes': 1, 'additional_reframe_submissions': 1,
            'max_total_completed_reframes_including_legacy': 2,
            'current_protocol_accepted_revision_cap': 1,
            'hypothesis_bound_reason': 'Existing Critic explicitly requested an additional standalone hypothesis alongside H1-H4; allow up to five without authoring its content.',
            'inherited_model_calls': 49, 'remaining_model_calls': 31,
            'inherited_tool_calls': 9, 'remaining_tool_calls': 9,
            'max_completed_investigator_rounds': 3, 'max_completed_critic_rounds': 3,
        },
    )
    config_path = Path('configs/agent_pilot_case_b_continuation.json')
    save(config_path, config)
    assert validate_independent_resume(config, 'B')
    assert file_sha(source_path) == source_sha
    save(target / 'PREPARATION_VERIFICATION.json', {
        'history_verified': True, 'historical_science_unchanged': True,
        'historical_audits_and_stop_unchanged': True, 'history_prefix_exact': True,
        'source_unchanged': True, 'new_request_copies_existing_critic': True,
        'new_model_calls': 0, 'new_evidence_queries': 0,
        'config': str(config_path), 'source': str(source_dir),
    })
    print(json.dumps({'prepared': str(target), 'config': str(config_path),
                      'model_calls_remaining': 31, 'tool_calls_remaining': 9}))


if __name__ == '__main__':
    main()
