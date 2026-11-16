"""Prepare auditable A/B engineering recovery inputs; make no model calls."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from jure.casefile import CaseStore, load_case
from jure.casefile.history import snapshot_at_revision, count_evidence_tool_calls
from jure.tools.real.registry import file_sha
from jure.runtime.pilot import save, resume_checkpoint
from jure.agents.critic.result import CriticConfig
from jure.agents.critic.stall_detection import budget_state
from jure.agents.explorer.models import ExplorerConfig, ExplorerOutput
from jure.agents.explorer.validation import validate_explorer_output


def main():
    base = Path('outputs/agent_pilot_v1_20260928')
    source = base / 'run_008_glm5_v16'
    target = base / 'repair_v17_preparation'
    target.mkdir(exist_ok=False)
    source_a = source / 'A/case_file/case_file.json'
    original_sha = file_sha(source_a)
    original = load_case(source_a)
    stages = json.loads((source / 'A/stage_results.json').read_text())
    critic = next(s for s in stages if s['role'] == 'critic' and s['success'])
    revision = critic['source_case_revision']
    checkpoint = snapshot_at_revision(original, revision)
    if checkpoint.action_state.next_actor != 'critic' or checkpoint.critic_audits.final_reports:
        raise ValueError('Expected the exact pre-Critic historical snapshot')
    traces = [json.loads(s) for s in (source / 'A/tool_trace.jsonl').read_text().splitlines()]
    if len(traces) != count_evidence_tool_calls(checkpoint):
        raise ValueError('Source trace contains acquisitions outside this recovery snapshot')
    a_dir = target / 'A'
    a_dir.mkdir()
    with CaseStore() as store:
        store.import_case(checkpoint)
        store.export_case(checkpoint.metadata.case_id, a_dir / 'case_file')
    retained_stages = [s for s in stages if
        (s.get('committed_case_revision') or s['source_case_revision']) <= revision]
    save(a_dir / 'stage_results.json', retained_stages)
    (a_dir / 'tool_trace.jsonl').write_text((source / 'A/tool_trace.jsonl').read_text())
    original_summary = json.loads((source / 'A/case_run_summary.json').read_text())
    summary = {**original_summary, 'completed': False, 'technical_gate_passed': False,
        'stop_reason': None, 'checkpoint_only': True, 'failure': None,
        'successful_roles': sorted({s['role'] for s in retained_stages if s['success']}),
        'critic_routes': [], 'claim_status_counts': {},
        'hypothesis_states': {h.hypothesis_id: h.status for h in checkpoint.hypotheses},
        'current_run_stages': 0,
        'predecessor': {'directory': str(source / 'A'), 'case_sha256': original_sha}}
    save(a_dir / 'case_run_summary.json', summary)
    save(a_dir / 'model_usage.json', original_summary['model'])
    save(a_dir / 'RECOVERY_PROVENANCE.json', {
        'source_directory': str(source / 'A'), 'source_case_sha256': original_sha,
        'source_revision': original.metadata.case_revision, 'recovered_revision': revision,
        'reason': 'Repair the attempted-round budget policy; retry Critic from its exact prior input.',
        'original_stop_preserved': True, 'source_history_prefix_exact': True,
        'all_prior_provider_costs_charged': original_summary['cumulative_model_calls'],
        'not_an_independent_replication': True, 'new_model_calls': 0,
    })
    config = json.loads(Path('configs/agent_pilot_glm5_v16.json').read_text())
    config.update(protocol_id='jure_real_agent_pilot_glm5_v1.7', case_order=['A', 'B'],
                  checkpoint_failed_investigator_allowance_cap=0)
    for role in ('explorer', 'critic'):
        config[role]['round_budget_basis'] = 'completed'
    config['resume_sources'] = {
        'A': {'directory': str(a_dir), 'case_sha256': file_sha(a_dir / 'case_file/case_file.json')},
        'B': {'directory': str(source / 'B'), 'case_sha256': file_sha(source / 'B/case_file/case_file.json')},
    }
    config['policy'] = (
        'A/B engineering repair only. Keep all original runs. A retries Critic from its exact audited '
        'pre-Critic snapshot; its earlier STOP is preserved in the source run. B resumes its full '
        'committed state and failed-attempt history. Investigation round budgets count successful '
        'commits; failed attempts remain bounded by stage/provider/controller limits and all real '
        'tool/provider costs remain charged. No per-case round allowance. Explorer uses the canonical '
        'Case File namespace for Critic request lineage. Revision requests are design provenance, '
        'never new evidence. Both roles receive the same Explorer write contract and batch bounds. '
        'All scientific revisions, tool choices, audits and routing remain Agent-authored. No C/D run '
        'is authorized by this repair preparation. This is not an independent scientific replication.'
    )
    config_path = Path('configs/agent_pilot_glm5_v17_ab_repair.json')
    save(config_path, config)
    for letter, spec in config['resume_sources'].items():
        initial = load_case(Path('outputs/pilot_preparation_v1_20260928/initial_cases') / letter / 'case_file.json')
        resume_checkpoint(initial, spec)
    b = load_case(source / 'B/case_file/case_file.json')
    raw_output = source / 'B/model_calls/call_0017_explorer/structured_output.json'
    errors = validate_explorer_output(ExplorerOutput.model_validate_json(raw_output.read_text()), b, 'reframe',
        config=ExplorerConfig(**config['explorer']), reframe_reason=b.critic_audits.revision_requests[-1].reason)
    report = {'new_model_calls': 0, 'C_D_paused': True, 'config': str(config_path),
        'A': {'source_unchanged': file_sha(source_a) == original_sha, 'exact_historical_revision': revision,
              'checkpoint_sha256': config['resume_sources']['A']['case_sha256'],
              'old_budget': budget_state(checkpoint, CriticConfig(**{**config['critic'], 'round_budget_basis': 'started'}), 1),
              'new_budget': budget_state(checkpoint, CriticConfig(**config['critic']), 1)},
        'B': {'source_sha256': config['resume_sources']['B']['case_sha256'],
              'original_uncommitted_output_sha256': file_sha(raw_output),
              'read_only_revalidation_errors': list(errors), 'uncommitted_output_promoted': False}}
    save(target / 'REPAIR_PREPARATION.json', report)
    print(json.dumps({'prepared': str(target), 'A_revision': revision, 'B_remaining_validation_errors': errors,
                      'model_calls': 0}, ensure_ascii=False))


if __name__ == '__main__':
    main()
