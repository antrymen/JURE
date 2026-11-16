"""Deterministic protocol metrics; never author or re-adjudicate scientific claims."""
import argparse
from collections import Counter
import json
from datetime import datetime, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from jure.casefile.store import load_case
from jure.casefile.history import verify_history
from jure.protocol.contracts import DiscriminationSpec, RevisionAcceptance, revision_defects
from jure.runtime.pilot import code_manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', required=True)
    parser.add_argument('--cases', default='AB')
    args = parser.parse_args()
    root = Path(args.run)
    frozen = json.loads((root / 'PILOT_RUNTIME_FROZEN.json').read_text())
    config = frozen['protocol']
    results = []
    if not args.cases or any(letter not in 'AB' for letter in args.cases):
        raise ValueError('Protocol evaluation only supports the requested A/B scope')
    for letter in args.cases:
        directory = root / letter
        summary = json.loads((directory / 'case_run_summary.json').read_text())
        case = load_case(directory / 'case_file/case_file.json')
        verify_history(case)
        stages = json.loads((directory / 'stage_results.json').read_text())
        errors = []
        comparisons = 0
        for question in case.evidence_questions:
            value = question.query_spec.get('discrimination')
            if value is not None:
                DiscriminationSpec.model_validate(value)
                comparisons += 1
        submissions = {e.metadata['run_id']: e.metadata for e in case.investigation_history
                       if e.metadata.get('explorer_event') == 'REVISION_SUBMITTED'}
        checks = []
        for event in case.investigation_history:
            if event.action != 'REVISION_ACCEPTANCE_COMPLETED':
                continue
            acceptance = RevisionAcceptance.model_validate(event.metadata['acceptance'])
            request = next(r for r in case.critic_audits.revision_requests
                           if r.request_id == acceptance.request_id)
            if acceptance.submission_run_id not in submissions:
                errors.append('Acceptance without committed submission')
            if {c.defect_id for c in acceptance.checks} != {d['defect_id'] for d in revision_defects(request)}:
                errors.append('Defect coverage mismatch')
            checks.append(acceptance.model_dump(mode='json'))
        passed_rounds = {a.critic_round for a in case.critic_audits.hypothesis_audits
                         if a.overall_status == 'pass'}
        claim_audits = case.critic_audits.claim_audits
        if any(a.critic_round not in passed_rounds for a in claim_audits):
            errors.append('Claim audit without committed C1 pass in the same round')
        bounded = (summary['cumulative_model_calls'] <= config['provider_max_calls_per_case']
                   and summary['tool_calls'] <= config['registry_budgets']['total']
                   and max((s['transition'] for s in stages), default=0) <= config['max_transitions'])
        if not bounded:
            errors.append('Declared global budget exceeded')
        updates = [e.metadata for e in case.investigation_history
                   if e.action == 'DISCRIMINATION_PROGRESS_RECORDED']
        call_records=[]
        cursor=directory
        seen=set()
        while cursor not in seen:
            seen.add(cursor)
            call_records.extend(json.loads(p.read_text()) for p in sorted((cursor/'model_calls').glob('call_*/call.json')))
            ancestor=json.loads((cursor/'case_run_summary.json').read_text()).get('predecessor')
            if not ancestor:break
            cursor=Path(ancestor['directory'])
        result = {
            'case': letter, 'completed': summary['completed'], 'failure': summary['failure'],
            'stop_reason': summary['stop_reason'], 'c1_statuses': [a.overall_status for a in case.critic_audits.hypothesis_audits],
            'c2_attempted': summary['c2_attempted_this_run'],
            'c2_committed_after_c1': bool(claim_audits) and all(a.critic_round in passed_rounds for a in claim_audits),
            'claims': len(case.mechanistic_claims), 'claim_audits': len(claim_audits),
            'claim_status_counts': dict(Counter(c.status for c in case.mechanistic_claims)),
            'evidence_audits': len(case.critic_audits.evidence_audits),
            'hypothesis_syntheses': len(case.critic_audits.hypothesis_syntheses),
            'hypotheses': summary['hypotheses'], 'evidence_records': summary['evidence_records'],
            'questions': len(case.evidence_questions), 'questions_with_comparison': comparisons,
            'revision_submissions': len(submissions), 'revision_acceptance': checks,
            'unchecked_submission_ids': sorted(set(submissions) - {c['submission_run_id'] for c in checks}),
            'information_updates': len(updates),
            'information_update_status_counts': dict(Counter(u['information_update']['status'] for u in updates)),
            'tool_calls': summary['tool_calls'],
            'tool_selection': summary['tool_selection'], 'critic_source_rechecks': summary['critic_recheck_calls'],
            'model_calls': summary['cumulative_model_calls'], 'current_run_usage': summary['model']['usage'],
            'cumulative_reported_usage': {key:sum((r.get('usage') or {}).get(key,0) for r in call_records)
                                          for key in ('prompt_tokens','completion_tokens','total_tokens')},
            'cumulative_usage_complete': len(call_records)==summary['cumulative_model_calls'] and all(r.get('usage') is not None for r in call_records),
            'budgets_respected': bounded,
            'critic_routes': summary['critic_routes'], 'errors': errors,
        }
        results.append(result)
    output = {
        'scope': 'Codex deterministic engineering audit, not an Agent scientific verdict or independent verification of biological discrimination',
        'evaluated_cases': list(args.cases),
        'audited_at': datetime.now(timezone.utc).isoformat(),
        'primary_criterion_met': any(r['c2_committed_after_c1'] for r in results),
        'runtime_unchanged': code_manifest() == frozen['code_sha256'],
        'cd_not_started': not (root / 'C').exists() and not (root / 'D').exists(),
        'protocol_checks_passed': not any(r['errors'] for r in results), 'cases': results,
        'interpretation_limit': 'Small engineering pilot with combined interface changes and preserved technical attempts; not a powered benchmark or single-component causal ablation.',
    }
    (root / 'PROTOCOL_EVALUATION.json').write_text(json.dumps(output, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(output, ensure_ascii=False))


if __name__ == '__main__':
    main()
