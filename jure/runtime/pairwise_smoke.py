"""Five Explorer examples, two internal calls each; no tools or other agents."""
import argparse
import getpass
import json
from pathlib import Path

from jure.casefile import CaseStore, load_case
from jure.agents.explorer.agent import MechanismExplorer
from jure.agents.explorer.models import ExplorerConfig
from jure.agents.explorer.pairwise_adapter import PairwiseExplorerBackend, VERSION
from jure.runtime.backends import CheckedTransport
from jure.runtime.contract_smoke import save, sha
from jure.runtime.pilot import code_manifest
from jure.llm.glm import GLMConfig, GLMTransport


def call_outcomes(records):
    """Availability failures stay separate from malformed model output."""
    unavailable = {'provider_http_error', 'provider_connection_error',
                   'provider_response_has_no_choices', 'provider_response_has_no_final_content'}
    return dict(provider_availability_failures=sum(r.get('error') in unavailable for r in records),
        complete_final_responses=sum(r.get('finish_reason') == 'stop' and r.get('error') not in unavailable for r in records),
        incomplete_final_responses=sum(r.get('error') == 'provider_response_incomplete' for r in records),
        invalid_json_responses=sum(r.get('error') in {'provider_response_is_not_json', 'provider_response_is_not_json_object'} for r in records))


def prepare(root, config_path='configs/explorer_pairwise_smoke_v1.json'):
    config = json.loads(Path(config_path).read_text())
    old = json.loads(Path(config['selection_source']).read_text())
    if len(old['cases']) != 5:
        raise ValueError('Exactly five frozen inputs are required')
    for row in old['cases']:
        if sha(row['path']) != row['sha256']:
            raise ValueError('Historical input changed')
    root.mkdir(parents=True, exist_ok=False)
    frozen = dict(config=config, interface=VERSION, cases=old['cases'], code=code_manifest(),
        selection_source_sha256=sha(config['selection_source']), script_sha256=sha(__file__),
        capability_source=old['capability_source'], capability_source_sha256=old['capability_source_sha256'],
        capability_summary=old['capability_summary'],
        protocol_document_sha256=sha('docs/tools/SCIENTIFIC_PROTOCOL_FROZEN_V1.md'),
        provider_config=json.loads(Path(config['model_config']).read_text()),
        pilot_checkpoints={p: sha(p) for p in old['pilot_checkpoints']})
    save(root / 'SMOKE_FROZEN.json', frozen)
    print(json.dumps(dict(status='PREPARED_NOT_RUN', inputs=5, calls_per_input=2, max_model_calls=10)))


def validate_frozen(frozen):
    if code_manifest() != frozen['code'] or sha(__file__) != frozen['script_sha256']:
        raise ValueError('Frozen code changed; do not modify or silently refreeze an active run')
    if sha(frozen['config']['selection_source']) != frozen['selection_source_sha256']:
        raise ValueError('Frozen selection changed')
    if sha(frozen['capability_source']) != frozen['capability_source_sha256']:
        raise ValueError('Capability source changed')
    if sha('docs/tools/SCIENTIFIC_PROTOCOL_FROZEN_V1.md') != frozen['protocol_document_sha256']:
        raise ValueError('Frozen scientific protocol changed')
    if any(sha(row['path']) != row['sha256'] for row in frozen['cases']):
        raise ValueError('Input changed')
    if any(sha(p) != h for p, h in frozen['pilot_checkpoints'].items()):
        raise ValueError('Historical pilot checkpoint changed')


def run(root):
    frozen = json.loads((root / 'SMOKE_FROZEN.json').read_text())
    validate_frozen(frozen)
    if (root / 'model_calls').exists():
        raise FileExistsError('Do not rerun or reset the budget in an existing smoke run')
    provider_config = GLMConfig(**{**frozen['provider_config'], 'max_calls': 10})
    allowed = frozen['config'].get('allowed_models', ['glm-4.7-flash'])
    if provider_config.model not in allowed:
        raise ValueError('Provider model is not explicitly allowed by this frozen smoke configuration')
    key = getpass.getpass('GLM API key (hidden): ')
    provider = GLMTransport(config=provider_config, api_key=key, trace_dir=root / 'model_calls')
    del key
    rows = []
    for entry in frozen['cases']:
        validate_frozen(frozen)
        print(json.dumps(dict(event='PAIRWISE_EXPLORER_STARTED', slot=entry['slot'])), flush=True)
        transport = CheckedTransport(provider, 'explorer', schema_retries=0, provider_retry_delays=(), protocol_v3=True)
        backend = PairwiseExplorerBackend(transport)
        config = ExplorerConfig(protocol_v3=True, validation_policy='three_layer', min_hypotheses=3,
            max_hypotheses=4, max_retries=0, max_context_chars=750000, round_budget_basis='completed')
        start = provider.calls
        with CaseStore() as store:
            initial = load_case(entry['path'])
            store.import_case(initial)
            result = MechanismExplorer(backend, config).run(store, initial.metadata.case_id,
                capability_summary=frozen['capability_summary'], artifact_dir=root / entry['slot'] / 'explorer')
            case = store.load_case(initial.metadata.case_id)
            assert not case.evidence_records and not case.critic_audits.hypothesis_audits
            audit = backend.last_audit
            row = dict(slot=entry['slot'], type=entry['type'], model_calls=provider.calls-start,
                **call_outcomes(provider.records[start:]),
                submitted_to_temporary_store=result.success,
                validated_internal_stages=sum(r.get('status') == 'valid' for r in transport.requests),
                machine_contract_pass=bool(backend.last_compiled),
                pair_coverage=audit['pair_coverage'] if audit else None,
                no_self_alternative=audit['no_self_alternative'] if audit else None,
                outcome_consistency=audit['outcome_consistency'] if audit else None,
                scientific_content_retained=audit['content_retained'] if audit else None,
                errors=list(result.validation_errors))
            save(root / entry['slot'] / 'stage_trace.json', backend.stage_trace)
            if backend.last_compiled:
                save(root / entry['slot'] / 'compiled_proposal.json', backend.last_compiled.model_dump(mode='json'))
                save(root / entry['slot'] / 'adapter_audit.json', audit)
        rows.append(row)
        save(root / 'SMOKE_ROWS.json', rows)
        save(root / 'USAGE.json', provider.summary())
        print(json.dumps(dict(event='PAIRWISE_EXPLORER_FINISHED', **row)), flush=True)
    validate_frozen(frozen)
    summary = dict(inputs=5, model_calls=provider.calls,
        **call_outcomes(provider.records),
        validated_internal_stages=sum(r['validated_internal_stages'] for r in rows),
        fully_validated_examples=sum(r['validated_internal_stages'] == 2 for r in rows),
        machine_contract_passes=sum(r['machine_contract_pass'] for r in rows),
        temporary_proposal_submissions=sum(r['submitted_to_temporary_store'] for r in rows),
        usage=provider.summary(), provider_failures_separate=True, scientific_validity='NOT_ASSESSED',
        evidence_tool_calls=0, investigator_calls=0, critic_calls=0, case_a_launched=False,
        persistent_pilot_writes=0, source_hashes_unchanged=True, review_required=True,
        evaluation=frozen['config']['evaluation'])
    save(root / 'SMOKE_SUMMARY.json', summary)
    print(json.dumps(summary), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['prepare', 'run'])
    parser.add_argument('--output', required=True)
    parser.add_argument('--config', default='configs/explorer_pairwise_smoke_v1.json')
    args = parser.parse_args()
    if args.action == 'prepare':
        prepare(Path(args.output), args.config)
    else:
        run(Path(args.output))
