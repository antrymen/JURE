"""Frozen Explorer-only interface evaluation; no evidence registry is instantiated."""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
import getpass
import hashlib
import json
import multiprocessing
from pathlib import Path

from jure.agents.explorer.agent import MechanismExplorer
from jure.agents.explorer.backend import JSONExplorerBackend
from jure.agents.explorer.models import ExplorerConfig, ExplorerOutput
from jure.agents.explorer.content_adapter import ContentExplorerBackend
from jure.agents.explorer.contract_checks import reference_errors, classify_validation_error
from jure.casefile import CaseStore
from jure.casefile.history import verify_history
from jure.casefile.store import load_case
from jure.llm.glm import GLMConfig, GLMTransport
from jure.protocol.capabilities import capability_summary
from jure.runtime.backends import CheckedTransport
from jure.runtime.pilot import code_manifest
from jure.tools.real.registry import file_sha


def save(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n')


def prepare(root,config_path):
    from clue_discovery.schemas import SelectedCase
    from jure.casefile.selected_adapter import initialize_selected_case
    from triage.pilot import assert_initial
    from triage.pilot_sources import VerifiedPilotSource
    root=Path(root)
    if root.exists():raise FileExistsError('Never replace an existing benchmark')
    config=json.loads(Path(config_path).read_text())
    root.mkdir(parents=True)
    # Freeze rules before inspecting/ranking candidates.
    save(root/'SELECTION_PROTOCOL_FROZEN.json',{'frozen_at':datetime.now(timezone.utc).isoformat(),
        'config':config,'config_sha256':file_sha(config_path)})
    source=VerifiedPilotSource(config['source_run'])
    pilots={letter:load_case(Path('outputs/pilot_preparation_v1_20260928/initial_cases')/letter/'case_file.json') for letter in 'ABCD'}
    used={c.clue.perturbation for c in pilots.values()};index=[]
    lines={case.case_id:i for i,case in enumerate(source.cases,1)}
    for direction,count in config['direction_counts'].items():
        pool=sorted((c for c in source.cases if direction in c.strata),
                    key=lambda c:(hashlib.sha256((config['protocol_id']+':'+c.case_id).encode()).hexdigest(),c.case_id))
        selected=[]
        for case in pool:
            if case.condition_id in used:continue
            used.add(case.condition_id);selected.append(case)
            if len(selected)==count:break
        if len(selected)!=count:raise ValueError('Not enough unique conditions; do not relax frozen selection')
        for case in selected:
            slot=f'E{len(index)+1:02d}'
            selected_case=SelectedCase(case=case,selection_method='rule',
                selection_reason='Explorer-only contract input; frozen hash order, no biological ranking.',
                selector=config['protocol_id'],selected_at=datetime.now(timezone.utc).isoformat(),
                selection_provenance={'triage_sha256':source.checked[str(source.triage_path)],
                    'source_line':lines[case.case_id],'selection_protocol_sha256':file_sha(root/'SELECTION_PROTOCOL_FROZEN.json')})
            with CaseStore() as store:
                initial=initialize_selected_case(selected_case,verified_source=source,store=store);assert_initial(initial)
                directory=root/'initial_cases'/slot;store.export_case(initial.metadata.case_id,directory)
                save(directory/'selected_case.json',selected_case.model_dump(mode='json'))
            index.append({'slot':slot,'case_id':case.case_id,'condition':case.condition_id,'direction':direction,
                          'path':str(directory/'case_file.json'),'sha256':file_sha(directory/'case_file.json')})
    if len(index)!=config['count']:raise ValueError('Count mismatch')
    source.assert_unchanged()
    snapshot=json.loads(Path(config['capability_snapshot']).read_text())
    caps=capability_summary([{'tool_id':t['tool_name'],'availability':'unavailable' if t['availability'] in ('UNAVAILABLE','NOT_IMPLEMENTED') else 'available'} for t in snapshot['tools']])
    provider=json.loads(Path(config['model_config']).read_text());provider['max_calls']=1
    save(root/'INITIAL_CASE_INDEX.json',index)
    save(root/'BENCHMARK_FROZEN.json',{'frozen_at':datetime.now(timezone.utc).isoformat(),'config':config,
         'code_sha256':code_manifest(),'provider_config':provider,'capability_summary':caps,
         'capability_snapshot_sha256':file_sha(config['capability_snapshot']),
         'initial_cases':index,'source_files':source.checked,'expected_candidate_count':len(source.cases),
         'pilot_initial_sha256':{letter:file_sha(Path('outputs/pilot_preparation_v1_20260928/initial_cases')/letter/'case_file.json') for letter in 'ABCD'},
         'pilot_A_calls_already_consumed':8,'pilot_A_remaining_global_calls':72,'benchmark_does_not_reset_or_consume_pilot_ledger':True,
         'evidence_tools_enabled':False,'investigator_enabled':False,'critic_enabled':False})
    print(json.dumps({'prepared':str(root),'inputs':len(index),'arms':config['arms'],'max_provider_calls':2*len(index),'evidence_calls':0}),flush=True)


def worker(root,slot,arm,key):
    root=Path(root);frozen=json.loads((root/'BENCHMARK_FROZEN.json').read_text())
    config=frozen['config'];entry=next(x for x in frozen['initial_cases'] if x['slot']==slot)
    if file_sha(entry['path'])!=entry['sha256']:raise ValueError('Initial input changed')
    initial=load_case(entry['path']);directory=root/'runs'/slot/arm
    directory.mkdir(parents=True,exist_ok=False)
    provider=GLMTransport(config=GLMConfig.model_validate(frozen['provider_config']),api_key=key,trace_dir=directory/'model_calls')
    if arm=='deterministic_adapter':backend=ContentExplorerBackend(lambda request:provider(request,role='explorer'))
    else:backend=JSONExplorerBackend(CheckedTransport(provider,'explorer',schema_retries=0,protocol_v3=True))
    with CaseStore(directory/'case_store.sqlite') as store:
        store.import_case(initial)
        result=MechanismExplorer(backend,ExplorerConfig(**config['explorer'])).run(store,initial.metadata.case_id,
            capability_summary=frozen['capability_summary'],artifact_dir=directory/'explorer')
        final=store.load_case(initial.metadata.case_id);verify_history(final);store.export_case(initial.metadata.case_id,directory/'case_file')
    compiled=None;errors=[];adapter_audit=None
    if arm=='deterministic_adapter':
        compiled=backend.last_compiled;adapter_audit=backend.last_audit
        if backend.last_content:save(directory/'scientific_content.json',backend.last_content.model_dump(mode='json'))
        if backend.last_error:errors.append({'category':classify_validation_error(backend.last_error),'message':str(backend.last_error)[:4000]})
    else:
        path=directory/'model_calls/call_0001_explorer/structured_output.json'
        if path.exists():
            try:compiled=ExplorerOutput.model_validate_json(path.read_text())
            except Exception as error:errors.append({'category':classify_validation_error(error),'message':str(error)[:4000]})
    if compiled:
        save(directory/'compiled_proposal.json',compiled.model_dump(mode='json'))
        errors.extend(reference_errors(compiled,initial,frozen['capability_summary']))
    if adapter_audit:save(directory/'adapter_audit.json',adapter_audit)
    if not compiled and not errors:
        record=provider.records[-1] if provider.records else {}
        code=record.get('error','unknown_provider_failure')
        errors.append({'category':'json_schema' if 'json' in code or 'incomplete' in code else 'provider_failure','message':code})
    # Transport errors are not schema defects even when they passed through the adapter.
    if provider.records and provider.records[-1]['status']!='success':
        code=provider.records[-1].get('error','unknown_provider_failure')
        if not any(x in code for x in ('json','incomplete')):
            errors=[{'category':'provider_failure','message':code}]
    contract_pass=compiled is not None and not errors
    science_errors=list(result.validation_errors) if contract_pass and not result.success else []
    entity_flags=[e for e in science_errors if 'unsupported named molecular specifics' in e]
    if final.evidence_records or final.critic_audits.model_dump()!=initial.critic_audits.model_dump():raise ValueError('Forbidden evidence/Critic execution')
    if final.clue!=initial.clue or file_sha(entry['path'])!=entry['sha256']:raise ValueError('Immutable input changed')
    summary={'slot':slot,'arm':arm,'case_id':entry['case_id'],'contract_pass':contract_pass,
        'proposal_submitted':result.success,'engineering_errors':errors,
        'scientific_content_guard_errors':science_errors,'entity_guard_flags':entity_flags,
        'classification_limit':'Scientific/entity guard failures are automated heuristics, not a biological expert or Critic judgment.',
        'content_retention':adapter_audit,'model':provider.summary(),'retries':max(0,provider.calls-1),
        'evidence_tool_calls':0,'investigator_calls':0,'critic_calls':0,
        'committed_hypotheses':len(final.hypotheses),'case_revision':final.metadata.case_revision,
        'immutable_source_unchanged':True,'history_verified':True,'run_result':result.model_dump(mode='json')}
    save(directory/'RESULT.json',summary)
    return {'slot':slot,'arm':arm,'contract_pass':contract_pass,'proposal_submitted':result.success,'categories':sorted({e['category'] for e in errors}),'tokens':provider.summary()['usage']['total_tokens']}


def summarize(root):
    root=Path(root);frozen=json.loads((root/'BENCHMARK_FROZEN.json').read_text());config=frozen['config']
    results=[json.loads(p.read_text()) for p in sorted((root/'runs').glob('*/*/RESULT.json'))]
    arms={}
    for arm in config['arms']:
        rows=[r for r in results if r['arm']==arm];n=config['count']
        arms[arm]={'planned_attempts':n,'finished_attempts':len(rows),'contract_passes':sum(r['contract_pass'] for r in rows),
            'contract_pass_rate':sum(r['contract_pass'] for r in rows)/n,'submitted':sum(r['proposal_submitted'] for r in rows),
            'submission_rate':sum(r['proposal_submitted'] for r in rows)/n,
            'engineering_failure_categories':dict(Counter(e['category'] for r in rows for e in r['engineering_errors'])),
            'scientific_guard_failed_attempts':sum(bool(r['scientific_content_guard_errors']) for r in rows),
            'entity_guard_flagged_attempts':sum(bool(r['entity_guard_flags']) for r in rows),
            'model_calls':sum(r['model']['calls'] for r in rows),'retries':sum(r['retries'] for r in rows),
            'reported_tokens':sum(r['model']['usage']['total_tokens'] for r in rows),'usage_complete':all(r['model']['usage_complete'] for r in rows),
            'content_retention_verified':sum(bool(r['content_retention'] and r['content_retention']['content_retained']) for r in rows)}
    completed=len(results)==config['count']*len(config['arms'])
    summary={'scope':'Explorer-only engineering interface benchmark, no biological adjudication',
        'completed':completed,'arms':arms,'adapter_contract_threshold_met':completed and arms['deterministic_adapter']['contract_pass_rate']>=config['adapter_acceptance_threshold'],
        'full_proposal_threshold_met':completed and arms['deterministic_adapter']['submission_rate']>=config['adapter_acceptance_threshold'],
        'runtime_unchanged':code_manifest()==frozen['code_sha256'],'evidence_tool_calls':sum(r['evidence_tool_calls'] for r in results),
        'pilot_cases_not_run':True,'pilot_initial_files_unchanged':all(file_sha(Path('outputs/pilot_preparation_v1_20260928/initial_cases')/c/'case_file.json')==s for c,s in frozen['pilot_initial_sha256'].items()),
        'automatic_case_A_launch':False,'interpretation_limit':config['interpretation_limit']}
    save(root/'BENCHMARK_SUMMARY.json',summary)
    return summary


def run(root):
    root=Path(root);frozen=json.loads((root/'BENCHMARK_FROZEN.json').read_text())
    if code_manifest()!=frozen['code_sha256']:raise ValueError('Runtime differs from freeze')
    if (root/'runs').exists():raise FileExistsError('No implicit resume/retry or replacement of fixed attempts')
    key=getpass.getpass('GLM API key (hidden): ')
    jobs=[]
    for i,entry in enumerate(frozen['initial_cases']):
        arms=frozen['config']['arms'] if i%2==0 else list(reversed(frozen['config']['arms']))
        jobs.extend((entry['slot'],arm) for arm in arms)
    with ProcessPoolExecutor(max_workers=frozen['config']['parallel_workers'],mp_context=multiprocessing.get_context('spawn')) as pool:
        pending={pool.submit(worker,str(root),slot,arm,key):(slot,arm) for slot,arm in jobs}
        for future in as_completed(pending):
            try:print(json.dumps(future.result(),ensure_ascii=False),flush=True)
            except Exception as error:
                save(root/('HOST_FAILURE_'+ '_'.join(pending[future])+'.json'),{'error_type':type(error).__name__,'message':str(error)[:2000]})
                print(json.dumps({'host_failure':pending[future],'error_type':type(error).__name__}),flush=True)
            summarize(root)
    del key
    print(json.dumps(summarize(root),ensure_ascii=False),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['prepare','run','summarize']);parser.add_argument('--output',required=True)
    parser.add_argument('--config',default='configs/explorer_contract_benchmark_v1.json');args=parser.parse_args()
    if args.action=='prepare':prepare(args.output,args.config)
    elif args.action=='run':run(args.output)
    else:print(json.dumps(summarize(args.output),ensure_ascii=False))
