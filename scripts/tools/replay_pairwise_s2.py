"""Replay already paid-for S2 outputs in RAM; no model/evidence execution."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from jure.casefile import CaseStore, load_case
from jure.casefile.history import verify_history
from jure.agents.explorer.agent import MechanismExplorer
from jure.agents.explorer.models import ExplorerConfig
from jure.agents.explorer.pairwise_adapter import PairwiseExplorerBackend, VERSION, METHOD_A, METHOD_B
from jure.runtime.backends import CheckedTransport


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def run(output):
    source = Path('outputs/explorer_pairwise_v1_20260928/smoke')
    frozen = json.loads((source / 'SMOKE_FROZEN.json').read_text())
    entry = next(x for x in frozen['cases'] if x['slot'] == 'S2')
    hashes = {str(p): sha(p) for p in source.rglob('*') if p.is_file()}
    hashes.update(frozen['pilot_checkpoints'])
    hashes[entry['path']] = entry['sha256']
    assert all(sha(p) == h for p, h in hashes.items())
    output.mkdir(parents=True, exist_ok=False)
    saved = {}
    for call, mode in ((2, METHOD_A), (3, METHOD_B)):
        directory = source / 'model_calls' / f'call_{call:04d}_explorer'
        request = json.loads(json.loads((directory / 'request.json').read_text())['messages'][1]['content'])
        response = json.loads((directory / 'response.json').read_text())
        assert request['mode'] == mode and response['finish_reason'] == 'stop'
        saved[mode] = response['content']
    reads = []
    def archived_provider(request, *, role):
        assert role == 'explorer' and request['mode'] == (METHOD_A, METHOD_B)[len(reads)]
        reads.append(request['mode'])
        return saved[request['mode']]
    transport = CheckedTransport(archived_provider, 'explorer', schema_retries=0, protocol_v3=True)
    backend = PairwiseExplorerBackend(transport)
    config = ExplorerConfig(protocol_v3=True, validation_policy='three_layer', min_hypotheses=3,
        max_hypotheses=4, max_retries=0, max_context_chars=750000, round_budget_basis='completed')
    with CaseStore() as store:
        initial = load_case(entry['path']); store.import_case(initial)
        result = MechanismExplorer(backend, config).run(store, initial.metadata.case_id,
            capability_summary=frozen['capability_summary'], artifact_dir=output / 'offline_explorer')
        case = store.load_case(initial.metadata.case_id); verify_history(case)
        summary = dict(version=VERSION, evaluation='OFFLINE_REPLAY_OF_SAVED_REAL_OUTPUTS',
            prior_live_status='FAILED_UNCHANGED', schema_stages_passed=sum(r['status'] == 'valid' for r in transport.requests),
            temporary_store_submission=result.success, errors=list(result.validation_errors),
            hypotheses=len(case.hypotheses), questions=len(case.evidence_questions), next_actor=case.action_state.next_actor,
            content_retention=backend.last_audit, normalization_changes=[a['changes'] for a in transport.normalization_audits],
            new_model_calls=0, saved_output_reads=len(reads), investigator_calls=0, critic_calls=0, evidence_calls=0,
            case_a_launched=False, scientific_validity='NOT_ASSESSED', new_live_pass_rate='NOT_MEASURED',
            source_hashes_unchanged=all(sha(p) == h for p, h in hashes.items()), sources=hashes)
        assert not case.evidence_records and not case.critic_audits.hypothesis_audits
        assert summary['source_hashes_unchanged']
        if backend.last_compiled:
            save(output / 'OFFLINE_COMPILED_PROPOSAL.json', backend.last_compiled.model_dump(mode='json'))
        save(output / 'REPLAY_RESULT.json', summary)
        print(json.dumps({k: v for k, v in summary.items() if k != 'sources'}, ensure_ascii=False))
        return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--output', required=True)
    run(Path(parser.parse_args().output))
