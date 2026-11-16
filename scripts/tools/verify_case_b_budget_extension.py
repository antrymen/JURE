"""Read-only verification and usage ledger for the explicitly authorized B extension."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from jure.casefile import load_case
from jure.casefile.history import verify_history, agent_round_counts
from jure.runtime.pilot import code_manifest


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('run_directory')
    args = parser.parse_args()
    root = Path(args.run_directory)
    base = root.parent
    final = root / 'B'
    baseline = base / 'run_040_case_b_completion/B'
    before = read(baseline / 'case_file/case_file.json')
    after = read(final / 'case_file/case_file.json')
    case = load_case(final / 'case_file/case_file.json')
    verify_history(case)
    summary = read(final / 'case_run_summary.json')
    manifest = read(root / 'PILOT_RUNTIME_FROZEN.json')
    original_manifest = read(baseline.parent / 'PILOT_RUNTIME_FROZEN.json')
    traces = [json.loads(s) for s in (final / 'tool_trace.jsonl').read_text().splitlines()]
    old_traces = [json.loads(s) for s in (baseline / 'tool_trace.jsonl').read_text().splitlines()]
    roots = sorted(p for p in base.glob('run_*_case_b_budget_extension')
                   if 41 <= int(p.name.split('_')[1]) <= int(root.name.split('_')[1]))
    roots += [base / 'case_b_plan_expectation_patch_20260929',
              base / 'case_b_h5_synthesis_patch_20260929']
    calls = []
    usage = Counter()
    missing_usage = []
    for directory in roots:
        for path in sorted(directory.glob('**/model_calls/call_*/call.json')):
            item = read(path)
            calls.append({'path': str(path), 'sha256': sha(path),
                          **{k: item.get(k) for k in ('role', 'operation', 'status', 'requested_model', 'usage')}})
            data = item.get('usage')
            if not data:
                missing_usage.append(str(path))
                continue
            usage['prompt_tokens'] += data.get('prompt_tokens', 0)
            usage['completion_tokens'] += data.get('completion_tokens', 0)
            usage['cached_tokens'] += (data.get('prompt_tokens_details') or {}).get('cached_tokens', 0)
    old_events = before['investigation_history']
    new_events = after['investigation_history'][len(old_events):]
    rounds = {role: agent_round_counts(case, role)
              for role in ('explorer', 'investigator', 'critic')}
    prior_case = load_case(baseline / 'case_file/case_file.json')
    old_claims = {c['claim_id']: c for c in before['mechanistic_claims']}
    new_claims = {c['claim_id']: c for c in after['mechanistic_claims']}
    def immutable_claim(claim):
        return {k: v for k, v in claim.items() if k != 'status'}
    checks = {
        'history_replay': True,
        'completed': summary['completed'],
        'technical_gate_passed': summary['technical_gate_passed'],
        'case_stopped': after['action_state']['current_phase'] == 'stopped',
        'old_history_prefix_preserved': after['investigation_history'][:len(old_events)] == old_events,
        'original_clue_unchanged': before['clue'] == after['clue'],
        'pilot_v1_B_checkpoint_unchanged': sha(baseline / 'case_file/case_file.json') == 'af757c32feb5d5525cda0f12385b37f45c26c0e0716544c10e6ac1dc8427b114',
        'old_evidence_unchanged': after['evidence_records'][:len(before['evidence_records'])] == before['evidence_records'],
        'hypothesis_revisions_predictions_unchanged': before['hypotheses'] == after['hypotheses'],
        'original_claim_definitions_unchanged': all(immutable_claim(v) == immutable_claim(new_claims[k]) for k, v in old_claims.items()),
        'no_new_explorer_generation': rounds['explorer'] == agent_round_counts(prior_case, 'explorer'),
        'frozen_code_unchanged': code_manifest() == manifest['code_sha256'],
        'base_prompts_unchanged_from_pilot_v1': manifest['base_prompt_sha256'] == original_manifest['base_prompt_sha256'],
        'initial_cases_unchanged': all(sha(Path('outputs/pilot_preparation_v1_20260928/initial_cases') / k / 'case_file.json') == v for k, v in manifest['initial_cases'].items()),
        'tool_trace_prefix_preserved': traces[:len(old_traces)] == old_traces,
        'tool_trace_not_duplicated': len({t['query_id'] for t in traces}) == len(traces),
        'tool_artifact_hashes_valid': all(sha(t['result_reference']['path']) == t['result_reference']['sha256'] for t in traces),
        'all_tool_sources_real': summary['all_tool_sources_real'] and not summary['mock_used'],
        'round_budgets_respected': rounds['investigator']['completed'] <= 5 and rounds['critic']['completed'] <= 5,
        'model_call_ledger_matches': 78 + len(calls) == summary['cumulative_model_calls'],
        'model_budget_respected': summary['cumulative_model_calls'] <= 130,
        'tool_budget_respected': len(traces) <= 32,
        'all_new_calls_use_flash': all(c['requested_model'] == 'glm-5.3-flash' for c in calls),
        'original_stop_and_reports_preserved': all(after['critic_audits'][k][:len(before['critic_audits'][k])] == before['critic_audits'][k] for k in ('stop_records', 'final_reports')),
        'new_final_report': len(after['critic_audits']['final_reports']) > len(before['critic_audits']['final_reports']),
        'new_c2_committed': len(after['critic_audits']['claim_audits']) > len(before['critic_audits']['claim_audits']),
    }
    gross = (usage['prompt_tokens'] * .8 + usage['completion_tokens'] * 2.8) / 1e6
    cached = gross - usage['cached_tokens'] * (.8 - .23) / 1e6
    result = {
        'checks': checks, 'all_checks_passed': all(checks.values()),
        'baseline': str(baseline), 'final': str(final),
        'final_case_sha256': sha(final / 'case_file/case_file.json'),
        'round_counts': rounds, 'model_call_ledger': {
            'baseline': 78, 'new_calls': len(calls), 'cumulative': 78 + len(calls), 'cap': 130, 'calls': calls},
        'new_usage': dict(usage), 'missing_usage_calls': missing_usage,
        'observed_usage_cost_cny': {'gross': gross, 'with_returned_cache': cached,
            'complete_usage': not missing_usage, 'pricing_source': 'outputs/cost_control_20260928/official_pricing.md',
            'note': 'Estimates from saved pricing snapshot, not account billing. Missing usage is not treated as zero cost.'},
        'tool_counts': {'baseline': len(old_traces), 'new': len(traces) - len(old_traces), 'cumulative': len(traces), 'cap': 32},
        'new_tool_status_counts': dict(Counter(t['status'] for t in traces[len(old_traces):])),
        'new_tool_queries': traces[len(old_traces):],
        'evidence_counts': {'baseline': len(before['evidence_records']), 'final': len(after['evidence_records'])},
        'claim_audits_cumulative': len(after['critic_audits']['claim_audits']),
        'unique_claims': len(after['mechanistic_claims']),
        'final_action_state': after['action_state'],
    }
    (root / 'VERIFICATION.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: result[k] for k in ('checks', 'round_counts', 'new_usage', 'missing_usage_calls', 'observed_usage_cost_cny', 'tool_counts')}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
