"""Launch the existing three Agents with real backends; obey persisted routing."""
import argparse,ast,getpass,hashlib,json,os
from pathlib import Path
from jure.casefile import CaseStore
from jure.casefile.store import load_case
from jure.casefile.history import verify_history
from jure.llm.glm import GLMConfig,GLMTransport
from jure.tools.real.factory import build_registry
from jure.tools.real.registry import file_sha,digest
from jure.agents.explorer.agent import MechanismExplorer
from jure.agents.explorer.backend import JSONExplorerBackend
from jure.agents.explorer.models import ExplorerConfig
from jure.agents.explorer.context import explorer_write_contract
from jure.agents.investigator.agent import EvidenceInvestigator
from jure.agents.investigator.backend import JSONInvestigatorBackend
from jure.agents.investigator.result import InvestigatorConfig
from jure.agents.critic.agent import MechanismCritic
from jure.agents.critic.result import CriticConfig
from .real_registry import RealInvestigatorRegistry
from .backends import CheckedTransport,RealCriticBackend,RECHECK_INSTRUCTIONS


def save(path,obj):
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    Path(path).write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False)+'\n')

def log(path,obj):
    with Path(path).open('a') as f:f.write(json.dumps(obj,ensure_ascii=False,allow_nan=False)+'\n')
    print(json.dumps(obj,ensure_ascii=False),flush=True)

def code_manifest():
    return {str(p):file_sha(p) for root in ('jure/runtime','jure/agents','jure/tools/real','jure/integrations','jure/llm','jure/casefile','jure/protocol') for p in sorted(Path(root).rglob('*.py'))}


def initial_case_path(letter, config):
    """Explicit, hash-bound new selection; never replace original pilot files."""
    spec = config.get('initial_case_sources', {}).get(letter)
    if spec is None:
        return Path('outputs/pilot_preparation_v1_20260928/initial_cases') / letter / 'case_file.json'
    path = Path(spec['path'])
    if file_sha(path) != spec['sha256']:
        raise ValueError('Explicit initial Case File hash changed')
    return path

def freeze(root,config):
    if config['explorer'].get('round_budget_basis','started') != config['critic'].get('round_budget_basis','started'):
        raise ValueError('Explorer and Critic must share the same round-budget basis')
    path=root/'PILOT_RUNTIME_FROZEN.json'
    from jure.agents.explorer.backend import SYSTEM_INSTRUCTIONS as explorer_prompt
    from jure.agents.investigator.backend import SYSTEM_INSTRUCTIONS as investigator_prompt
    from jure.agents.critic.backend import SYSTEM_INSTRUCTIONS as critic_prompt
    expected=json.loads(Path('outputs/agent_pilot_v1_20260928/base_prompt_hashes.json').read_text())
    prompts={'explorer':explorer_prompt,'investigator':investigator_prompt,'critic':critic_prompt}
    prompt_hashes={r:hashlib.sha256(p.encode()).hexdigest() for r,p in prompts.items()}
    if any(prompt_hashes[r]!=expected[r]['sha256'] for r in prompts):raise ValueError('Base Agent prompt changed')
    value={'protocol':config,'provider_config':json.loads(Path(config['model_config']).read_text()),'base_prompt_sha256':prompt_hashes,'code_sha256':code_manifest(),'recheck_interface_instructions':RECHECK_INSTRUCTIONS,
        'base_prompts_modified':False,'fixed_tool_order':False,'scientific_output_authors':['explorer','investigator','critic'],
        'resume_sources':config.get('resume_sources',{}),'initial_cases':{x:file_sha(Path('outputs/pilot_preparation_v1_20260928/initial_cases')/x/'case_file.json') for x in 'ABCD'}}
    planning_enabled = config['investigator'].get('source_aware_planning', False)
    review_enabled = config['critic'].get('source_aware_stopping', False)
    if planning_enabled != review_enabled:
        raise ValueError('Claim-source protocol requires both evidence planning and source-aware stopping')
    if planning_enabled:
        from jure.agents.investigator.backend import EVIDENCE_PLANNING_INSTRUCTIONS
        from jure.agents.critic.backend import SOURCE_REVIEW_INSTRUCTIONS
        value['claim_source_protocol'] = dict(version='claim-source-v1',
            investigator_instructions=EVIDENCE_PLANNING_INSTRUCTIONS,
            critic_instructions=SOURCE_REVIEW_INSTRUCTIONS,
            historical_cases_rewritten=False, automatic_budget_extension=False)
    if config.get('initial_case_sources'):
        value['active_initial_cases'] = {letter: {'path': str(initial_case_path(letter, config)),
            'sha256': file_sha(initial_case_path(letter, config))} for letter in config['case_order']}
    if config['explorer'].get('validation_policy') == 'three_layer':
        from jure.agents.explorer.content_adapter import ADMISSION_INSTRUCTIONS, CONTENT_INSTRUCTIONS
        from jure.protocol.admission import CRITIC_ADMISSION_INSTRUCTIONS, INVESTIGATOR_ADMISSION_INSTRUCTIONS, POLICY_VERSION
        value['admission_contracts'] = {'policy_version': POLICY_VERSION, 'initial_content': CONTENT_INSTRUCTIONS, 'explorer': ADMISSION_INSTRUCTIONS, 'investigator': INVESTIGATOR_ADMISSION_INSTRUCTIONS, 'critic': CRITIC_ADMISSION_INSTRUCTIONS}
        value['workflow_order'] = ['explorer', 'investigator', 'critic(C1->C2)']
        from jure.agents.explorer.scientific_content import VERSION, INSTRUCTIONS
        value['explorer_interfaces'] = {'initial': VERSION, 'reframe': VERSION,
            'instructions': INSTRUCTIONS, 'whole_proposal_retries': False, 'max_missing_field_patches': 1}
    if config.get('protocol_v3'):
        from jure.protocol.capabilities import ROLE_CONTRACTS,CATALOG
        value['protocol_role_contracts']=ROLE_CONTRACTS
        value['capability_catalog']=json.loads(json.dumps(CATALOG))
        if not all(config[role].get('protocol_v3') for role in ('explorer','investigator','critic')):
            raise ValueError('Protocol v3 must be enabled for all roles')
        if config['critic']['max_revision_acceptance_attempts']>config['failed_stage_retries']+1:
            raise ValueError('Acceptance attempts cannot exceed the existing per-stage attempt allowance')
    if path.exists():
        old=json.loads(path.read_text())
        if old!=value:raise ValueError('Frozen runtime differs; use a new declared run directory, do not silently modify an active pilot')
    else:save(path,value)
    return value

def resume_checkpoint(initial, specification):
    directory=Path(specification['directory'])
    path=directory/'case_file/case_file.json'
    if file_sha(path)!=specification['case_sha256']:raise ValueError('Resume checkpoint hash changed')
    source=load_case(path);verify_history(source)
    if source.metadata.case_id!=initial.metadata.case_id or source.clue!=initial.clue:
        raise ValueError('Resume checkpoint belongs to another case or modified clue')
    # Completed checkpoints may be carried forward; run_case exits its loop
    # immediately for STOP and never invokes another scientific action.
    stages=json.loads((directory/'stage_results.json').read_text())
    stages=[{**s,'inherited_from':str(directory)} for s in stages]
    traces=[json.loads(line) for line in (directory/'tool_trace.jsonl').read_text().splitlines() if line]
    summary=json.loads((directory/'case_run_summary.json').read_text())
    previous_calls=summary.get('cumulative_model_calls',summary['model']['calls'])
    return source,stages,traces,previous_calls


def validate_independent_resume(config, letters):
    """Existing A/B investigations may resume independently, never fresh cases."""
    if config.get('resume_execution_policy')!='independent_existing_checkpoints':return False
    if not letters or any(letter not in 'AB' for letter in letters):
        raise ValueError('Independent repair is restricted to existing A/B checkpoints')
    for letter in letters:
        specification=config.get('resume_sources',{}).get(letter)
        if not specification:raise ValueError('Independent repair requires a checkpoint for every case')
        initial=load_case(Path('outputs/pilot_preparation_v1_20260928/initial_cases')/letter/'case_file.json')
        source,stages,_,_=resume_checkpoint(initial,specification)
        roles={s['role'] for s in stages if s['success']}
        if roles!={'explorer','investigator','critic'} or not source.critic_audits.routing_decisions:
            raise ValueError('Independent repair requires prior committed E/I/C execution and Critic routing')
    return True



def validate_admission_recovery(config, letters):
    """Explicit new-interface recovery; preserve usage instead of restarting A."""
    if config.get('case_execution_policy') != 'admission_v1_technical_recovery':
        return False
    if letters != 'A' or config.get('case_order') != ['A']:
        raise ValueError('Admission recovery is restricted to Case A')
    if not config.get('protocol_v3') or config['explorer'].get('validation_policy') != 'three_layer':
        raise ValueError('Recovery requires the three-layer protocol')
    spec = config.get('resume_sources', {}).get('A')
    if not spec or set(config['resume_sources']) != {'A'}:
        raise ValueError('Recovery must import the existing A checkpoint')
    initial = load_case(Path('outputs/pilot_preparation_v1_20260928/initial_cases/A/case_file.json'))
    source, stages, traces, prior_calls = resume_checkpoint(initial, spec)
    if (source.action_state.current_phase != 'clue_ready' or source.mechanistic_question
            or source.hypotheses or source.evidence_records or traces
            or not stages or stages[-1]['success']):
        raise ValueError('Recovery only applies to the unsubmitted engineering failure')
    previous = json.loads((Path(spec['directory']).parent / 'PILOT_RUNTIME_FROZEN.json').read_text())
    if previous['initial_cases']['A'] != file_sha(Path('outputs/pilot_preparation_v1_20260928/initial_cases/A/case_file.json')):
        raise ValueError('Initial A changed')
    old = previous['protocol']
    for field in ('provider_max_calls_per_case', 'max_transitions'):
        if config[field] > old[field]:
            raise ValueError('Recovery cannot increase global budgets')
    for field in ('max_critic_rounds', 'max_investigator_rounds', 'max_explorer_reframes',
                  'max_total_tool_calls', 'max_revision_acceptance_attempts'):
        if config['critic'][field] > old['critic'][field]:
            raise ValueError('Recovery cannot increase scientific budgets')
    if config['registry_budgets']['total'] > old['registry_budgets']['total']:
        raise ValueError('Recovery cannot increase evidence tool budget')
    caps = config.get('per_case_retry_caps', {}).get('A', {})
    recovery = config.get('technical_recovery', {})
    if (recovery.get('inherited_model_calls') != prior_calls
            or recovery.get('new_interface_generation_attempts') != 2
            or config['schema_retries'] != 0
            or caps.get('failed_stage_retries') != 0
            or config['explorer']['max_retries'] != 1
            or caps.get('explorer_max_retries') != 1):
        raise ValueError('Recovery must preserve usage and bound new-interface attempts to two')
    model = GLMConfig.model_validate_json(Path(config['model_config']).read_text())
    if model.model != 'glm-4.7-flash':
        raise ValueError('Recovery uses the declared inexpensive model only')
    return True


def validate_investigation_first_resume(config, letters):
    if config.get('case_execution_policy') != 'admission_v2_initial_handoff_continuation':
        return False
    if letters != 'A' or config.get('case_order') != ['A'] or set(config.get('resume_sources', {})) != {'A'}:
        raise ValueError('Handoff continuation is restricted to existing Case A')
    from .admission_migration import validate_migration_source
    spec = config['resume_sources']['A']
    initial = load_case('outputs/pilot_preparation_v1_20260928/initial_cases/A/case_file.json')
    source, stages, traces, calls = resume_checkpoint(initial, spec)
    validate_migration_source(source)
    if traces or not stages or stages[-1]['role'] != 'critic' or stages[-1]['success']:
        raise ValueError('Expected the uncommitted pre-investigation Critic failure')
    previous = json.loads((Path(spec['directory']).parent/'PILOT_RUNTIME_FROZEN.json').read_text())
    old = previous['protocol']
    if json.loads(Path(config['model_config']).read_text()) != previous['provider_config']:
        raise ValueError('Continuation must preserve provider settings')
    if not all(config[r].get('protocol_v3') for r in ('explorer', 'investigator', 'critic')) or config['explorer'].get('validation_policy') != 'three_layer':
        raise ValueError('Continuation requires three-layer protocol v3')
    for field in ('provider_max_calls_per_case', 'max_transitions', 'schema_retries', 'failed_stage_retries'):
        if config[field] > old[field]: raise ValueError('Continuation cannot increase execution budgets')
    for role, fields in {
        'critic': ('max_critic_rounds','max_investigator_rounds','max_explorer_reframes','max_total_tool_calls','max_revision_acceptance_attempts'),
        'investigator': ('max_questions_per_run','max_tool_calls_per_run','max_new_followup_questions'),
        'explorer': ('max_retries',),
    }.items():
        for field in fields:
            if config[role][field] > old[role][field]: raise ValueError('Continuation cannot increase scientific budgets')
    if config['registry_budgets'] != old['registry_budgets'] or config['per_case_retry_caps'] != old['per_case_retry_caps']:
        raise ValueError('Continuation must preserve tool budgets and effective retry caps')
    if config.get('checkpoint_failed_investigator_allowance_cap',0) != 0:
        raise ValueError('Continuation cannot replenish Investigator rounds')
    if config.get('handoff_migration', {}).get('inherited_model_calls') != calls:
        raise ValueError('Continuation must record actual inherited calls')
    return True


def validate_provider_switch_continuation(config, letters):
    """An explicit provider switch preserves the existing scientific contract."""
    policy = config.get('case_execution_policy')
    amended = policy == 'authorized_case_a_three_transition_extension'
    if policy != 'authorized_provider_switch_continuation' and not amended:
        return False
    if letters != 'A' or config.get('case_order') != ['A'] or set(config.get('resume_sources', {})) != {'A'}:
        raise ValueError('This provider switch is restricted to existing Case A')
    spec = config['resume_sources']['A']
    initial = load_case('outputs/pilot_preparation_v1_20260928/initial_cases/A/case_file.json')
    source, stages, traces, calls = resume_checkpoint(initial, spec)
    expected_actor = 'explorer' if amended else 'investigator'
    if source.action_state.next_actor != expected_actor or not source.hypotheses or not stages:
        raise ValueError(f'Continue the saved {expected_actor} handoff, not a fresh Explorer proposal')
    previous = json.loads((Path(spec['directory']).parent/'PILOT_RUNTIME_FROZEN.json').read_text())
    old = previous['protocol']
    if amended:
        amendment = config.get('transition_amendment', {})
        if (amendment.get('user_authorization') != '可以'
                or amendment.get('previous_limit') != 12
                or amendment.get('additional_transitions') != 3
                or amendment.get('source_sha256') != spec['case_sha256']
                or old['max_transitions'] != 12
                or config['max_transitions'] != 15
                or max(s['transition'] for s in stages) != 12):
            raise ValueError('Explicit amendment permits only three transitions after the frozen limit 12')
    for field in ('explorer', 'investigator', 'critic', 'critic_rechecks_per_round',
                  'schema_retries', 'failed_stage_retries', 'max_transitions',
                  'provider_max_calls_per_case', 'registry_budgets', 'per_case_retry_caps',
                  'provider_retry_delays_seconds', 'protocol_v3'):
        if field == 'max_transitions' and amended:
            continue
        if config[field] != old[field]:
            raise ValueError(f'Provider switch cannot change scientific or execution settings: {field}')
    if config.get('checkpoint_failed_investigator_allowance_cap', 0) != 0:
        raise ValueError('Provider switch cannot replenish Investigator rounds')
    model = GLMConfig.model_validate_json(Path(config['model_config']).read_text())
    switch = config.get('provider_switch', {})
    if (not switch.get('user_authorization') or switch.get('inherited_model_calls') != calls
            or switch.get('from_model') != previous['provider_config']['model']
            or switch.get('to_model') != model.model
            or config.get('technical_continuation') != 'preserve_all_calls_and_committed_v3_state'):
        raise ValueError('Record explicit provider switch authorization and actual inherited usage')
    if model.max_calls != old['provider_max_calls_per_case'] or model.automatic_provider_retries:
        raise ValueError('Provider switch cannot increase call allowance or add provider retries')
    return True


def validate_content_recovery(config, letters):
    replay = config.get('case_execution_policy') == 'scientific_content_investigator_recovery'
    critic_replay = config.get('case_execution_policy') == 'scientific_content_critic_recovery'
    if config.get('case_execution_policy') != 'scientific_content_recovery' and not replay and not critic_replay:
        return False
    if letters != 'A' or config['case_order'] != ['A'] or set(config['resume_sources']) != {'A'}:
        raise ValueError('Content recovery is restricted to Case A')
    spec=config['resume_sources']['A']
    source,stages,traces,calls=resume_checkpoint(load_case('outputs/pilot_preparation_v1_20260928/initial_cases/A/case_file.json'),spec)
    previous=json.loads((Path(spec['directory']).parent/'PILOT_RUNTIME_FROZEN.json').read_text())
    if critic_replay:
        manifest=config['saved_investigator_prefix']
        if (source.action_state.next_actor!='critic' or len(traces)!=14 or calls!=66
                or stages[-1]['success'] or stages[-1]['role']!='critic'
                or max(s['transition'] for s in stages)!=15
                or len(manifest['responses'])!=1 or manifest['tools'] or manifest['envelopes']):
            raise ValueError('Critic recovery must preserve the completed investigation and failed logical stage15')
        row=manifest['responses'][0]
        if row.get('role')!='critic' or row['method']!='accept_revision' or file_sha(row['path'])!=row['sha256']:
            raise ValueError('Critic recovery requires the immutable saved acceptance')
        for key in ('explorer','investigator','critic','critic_rechecks_per_round','schema_retries',
                    'failed_stage_retries','max_transitions','provider_max_calls_per_case','registry_budgets',
                    'per_case_retry_caps','provider_retry_delays_seconds','protocol_v3'):
            if config[key]!=previous['protocol'][key]:raise ValueError(f'Replay cannot reset {key}')
        if json.loads(Path(config['model_config']).read_text())!=previous['provider_config']:
            raise ValueError('Replay cannot change model settings')
        return True
    if replay:
        manifest=config['saved_investigator_prefix']
        original=load_case(Path(spec['directory'])/'initial_snapshot/case_file.json')
        if any(getattr(source,k)!=getattr(original,k) for k in ('clue','hypotheses','mechanistic_question',
                'evidence_questions','evidence_records','evidence_assessments','evidence_gaps','contradictions','critic_audits')):
            raise ValueError('Saved stage prefix requires unchanged scientific inputs')
        if (source.action_state.next_actor!='investigator' or len(traces)!=13
                or stages[-1]['success'] or stages[-1]['role']!='investigator'
                or max(s['transition'] for s in stages)!=14
                or len(manifest['responses'])!=calls-53 or len(manifest['tools'])!=3):
            raise ValueError('Replay must resume the interrupted Investigator stage with all usage retained')
        for row in manifest['responses']+manifest['tools']+manifest['envelopes']:
            if file_sha(row['path'])!=row['sha256']:raise ValueError('Saved prefix changed')
        for key in ('explorer','investigator','critic','critic_rechecks_per_round','schema_retries',
                    'failed_stage_retries','max_transitions','provider_max_calls_per_case','registry_budgets',
                    'per_case_retry_caps','provider_retry_delays_seconds','protocol_v3'):
            if config[key]!=previous['protocol'][key]:raise ValueError(f'Replay cannot reset {key}')
        if json.loads(Path(config['model_config']).read_text())!=previous['provider_config']:
            raise ValueError('Replay cannot change model settings')
        return True
    recovery=json.loads((Path(spec['directory'])/'offline_recovery.json').read_text())
    if (source.action_state.next_actor!='investigator' or calls!=53 or len(traces)!=10
            or max(s['transition'] for s in stages)!=13 or recovery['new_model_calls']!=0
            or not recovery['scientific_content_unchanged']):
        raise ValueError('Recovery must preserve actual usage and the validated saved Explorer response')
    if file_sha(recovery['raw_response_path'])!=recovery['raw_response_sha256']:
        raise ValueError('Recovered model response changed')
    old=previous['protocol']
    for key in ('explorer','investigator','critic','critic_rechecks_per_round','schema_retries',
                'failed_stage_retries','max_transitions','provider_max_calls_per_case','registry_budgets',
                'per_case_retry_caps','provider_retry_delays_seconds','protocol_v3'):
        if config[key]!=old[key]:raise ValueError(f'Content recovery cannot reset {key}')
    if json.loads(Path(config['model_config']).read_text())!=previous['provider_config']:
        raise ValueError('Keep the authorized inexpensive model')
    return True


def run_case(letter,root,config,key):
    # A technical continuation may tighten remaining local attempts, never
    # replenish attempts already consumed by the interrupted stage.
    from copy import deepcopy
    config=deepcopy(config)
    caps=config.get('per_case_retry_caps',{}).get(letter,{})
    if 'explorer_max_retries' in caps:
        config['explorer']['max_retries']=min(config['explorer']['max_retries'],caps['explorer_max_retries'])
    if 'failed_stage_retries' in caps:
        config['failed_stage_retries']=min(config['failed_stage_retries'],caps['failed_stage_retries'])
    directory=root/letter;directory.mkdir(exist_ok=False)
    initial=initial_case_path(letter, config)
    source=load_case(initial);source_sha=file_sha(initial);case_id=source.metadata.case_id
    if source.mechanistic_question or source.hypotheses or source.evidence_records:raise ValueError('Pilot must start from an uninvestigated initial case')
    prior_stages=[];prior_traces=[];prior_calls=0
    predecessor=config.get('resume_sources',{}).get(letter)
    if predecessor:source,prior_stages,prior_traces,prior_calls=resume_checkpoint(source,predecessor)
    store=CaseStore(directory/'case_store.sqlite');store.import_case(source)
    save(directory/'checkpoint_provenance.json',{'predecessor':predecessor,'imported_revision':source.metadata.case_revision,'prior_model_calls':prior_calls})
    store.export_case(case_id,directory/'initial_snapshot')
    if config.get('defect_correction'):
        from .defect_correction import apply_defect_correction
        source=apply_defect_correction(store,case_id,config['defect_correction'])
        store.export_case(case_id,directory/'post_correction_snapshot')
    if config.get('case_execution_policy') == 'admission_v2_initial_handoff_continuation':
        from .admission_migration import migrate_initial_handoff
        source = migrate_initial_handoff(store, case_id, predecessor=predecessor)
        save(directory/'handoff_migration.json', {'source':predecessor,
            'event_id':source.investigation_history[-1].event_id,
            'case_revision':source.metadata.case_revision,
            'route':source.action_state.next_actor, 'inherited_model_calls':prior_calls,
            'scientific_objects_modified':False, 'budgets_reset':False})
        store.export_case(case_id,directory/'post_migration_snapshot')
    if prior_calls>=config['provider_max_calls_per_case']:raise ValueError('Cumulative provider call budget exhausted')
    provider_config=GLMConfig.model_validate_json(Path(config['model_config']).read_text()).model_copy(update={'max_calls':config['provider_max_calls_per_case']-prior_calls})
    provider=GLMTransport(config=provider_config,api_key=key,trace_dir=directory/'model_calls')
    registry=build_registry(directory/'tools',run_id=root.name+'_'+letter,case_store=store,allow_frozen_counts=False,budgets={**config['registry_budgets'],'total':max(0,config['registry_budgets']['total']-len(prior_traces))})
    registry.snapshot(directory/'registry_snapshot.json')
    if registry.specs['data_experiment'].availability!='READY':raise ValueError('Full real data backend required')
    binding=RealInvestigatorRegistry(registry,case_id)
    if config.get('saved_investigator_prefix'):
        from .saved_prefix import SavedPrefixProvider,SavedPrefixBinding
        provider=SavedPrefixProvider(provider,config['saved_investigator_prefix'])
        binding=SavedPrefixBinding(registry,case_id,config['saved_investigator_prefix'])
    binding.protocol_v3=config.get('protocol_v3',False)
    continuation_context={}
    if config.get('continuation_context'):
        spec=config['continuation_context']
        if file_sha(spec['path'])!=spec['sha256']:raise ValueError('Continuation context changed')
        continuation_context=json.loads(Path(spec['path']).read_text())
    transports={role:CheckedTransport(provider,role,schema_retries=config['schema_retries'],provider_retry_delays=config.get('provider_retry_delays_seconds',()),protocol_v3=binding.protocol_v3,
        continuation_context=continuation_context if role in ('investigator','critic') else None) for role in ('explorer','investigator','critic')}
    # Carry technical feedback across a process boundary; no old output is promoted.
    if prior_stages and not prior_stages[-1]['success']:
        previous_manifest=json.loads((Path(predecessor['directory']).parent/'PILOT_RUNTIME_FROZEN.json').read_text())
        same_interface=previous_manifest.get('admission_contracts')==json.loads((root/'PILOT_RUNTIME_FROZEN.json').read_text()).get('admission_contracts')
        if same_interface and not config.get('saved_investigator_prefix'):
            transports[prior_stages[-1]['role']].stage_feedback=list(prior_stages[-1].get('validation_errors',[]))
        else:
            save(directory/'feedback_provenance.json',{'active_feedback_inherited':False,
                'reason':'Interface contract changed; obsolete diagnostic instructions are not active feedback.',
                'historical_stage_errors_preserved':True,'predecessor':predecessor})
    if config.get('same_turn_consistency_feedback'):
        feedback=config['same_turn_consistency_feedback']
        if (not config.get('saved_investigator_prefix') or not prior_stages
                or prior_stages[-1]['role']!='critic' or prior_stages[-1]['success']
                or list(prior_stages[-1].get('validation_errors',[]))!=[feedback]
                or feedback!='ValueError: C1 failure must be attributed to hypothesis/prediction design'):
            raise ValueError('Critic consistency feedback must match the saved failed stage')
        transports['critic'].stage_feedback=[feedback]
    effective_critic_config=dict(config['critic'])
    allowance=0
    if (predecessor and source.action_state.current_phase!='stopped'
            and effective_critic_config.get('round_budget_basis', 'started')=='started'):
        failed_starts=sum(e.action=='INVESTIGATOR_STARTED' for e in source.investigation_history)-sum(e.action=='INVESTIGATOR_COMPLETED' for e in source.investigation_history)
        allowance=min(max(0,failed_starts),config.get('checkpoint_failed_investigator_allowance_cap',0))
        effective_critic_config['max_investigator_rounds']+=allowance
    save(directory/'effective_budgets.json',{'critic':effective_critic_config,'checkpoint_technical_round_allowance':allowance,'provider_calls_remaining':provider_config.max_calls,'prior_tool_calls':len(prior_traces)})
    explorer_backend = JSONExplorerBackend(transports['explorer'])
    if config['explorer'].get('validation_policy') == 'three_layer':
        from jure.agents.explorer.scientific_content import ScientificContentBackend
        explorer_backend = ScientificContentBackend(transports['explorer'])
    agents={
        'explorer':MechanismExplorer(explorer_backend,ExplorerConfig(**config['explorer'])),
        'investigator':EvidenceInvestigator(JSONInvestigatorBackend(transports['investigator']),binding,InvestigatorConfig(**config['investigator'])),
        'critic':MechanismCritic(RealCriticBackend(transports['critic'],registry,case_id,max_rechecks=config['critic_rechecks_per_round'],
            saved_rechecks=config.get('saved_critic_rechecks',())),CriticConfig(**effective_critic_config))}
    events=directory/'execution_trace.jsonl';stages=prior_stages[:];failure=None
    transition_offset=max((s['transition'] for s in prior_stages),default=0)
    if config.get('saved_investigator_prefix'):
        # Resume the interrupted logical stage, replaying paid work; no extra
        # scientific round or new full-stage retry is granted.
        transition_offset-=1
    def export_traces():
        registry.export_traces(directory/'tool_trace_current.jsonl')
        current=(directory/'tool_trace_current.jsonl').read_text()
        (directory/'tool_trace.jsonl').write_text(''.join(json.dumps(t,ensure_ascii=False)+'\n' for t in prior_traces)+current)
    try:
        for transition in range(transition_offset+1,config['max_transitions']+1):
            case=store.load_case(case_id)
            if case.action_state.current_phase=='stopped':break
            role='explorer' if case.mechanistic_question is None else case.action_state.next_actor
            if role not in agents:raise ValueError('Case has no executable Agent route')
            success=False
            for attempt in range(1,config['failed_stage_retries']+2):
                kwargs={'artifact_dir':directory/f'{transition:02d}_{role}_attempt{attempt}'}
                case=store.load_case(case_id)
                if role=='explorer':
                    mode='initial' if case.mechanistic_question is None else 'reframe';kwargs['mode']=mode
                    if binding.protocol_v3:
                        from jure.protocol.capabilities import capability_summary
                        kwargs['capability_summary']=capability_summary(binding.metadata_snapshot())
                    if mode=='reframe':
                        if not case.critic_audits.revision_requests:raise ValueError('Explorer reframe requires an actual Critic request')
                        kwargs['reframe_reason']=case.critic_audits.revision_requests[-1].reason
                if role=='critic':
                    kwargs['available_capabilities']=binding.metadata_snapshot()
                    kwargs['explorer_contract']=explorer_write_contract(agents['explorer'].config)
                log(events,{'event':'AGENT_STARTED','case':letter,'role':role,'transition':transition,'attempt':attempt,'revision':case.metadata.case_revision})
                result=agents[role].run(store,case_id,**kwargs);stages.append({'role':role,'transition':transition,'attempt':attempt,**result.model_dump(mode='json')})
                case=store.load_case(case_id);store.export_case(case_id,directory/'case_file')
                export_traces();save(directory/'model_usage.json',provider.summary());save(directory/'stage_results.json',stages)
                log(events,{'event':'AGENT_COMPLETED' if result.success else 'AGENT_FAILED','case':letter,'role':role,'transition':transition,
                    'attempt':attempt,'revision':case.metadata.case_revision,'next_actor':case.action_state.next_actor,
                    'phase':case.action_state.current_phase,'validation_errors':list(result.validation_errors),
                    'hypotheses':len(case.hypotheses),'evidence_records':len(case.evidence_records),'model_calls':provider.calls})
                if result.success:
                    success=True;transports[role].stage_feedback=[];break
                transports[role].stage_feedback=list(result.validation_errors)
            if not success:
                failure=f'{role} failed bounded validation attempts';break
        else:
            if store.load_case(case_id).action_state.current_phase!='stopped':
                failure='controller_transition_limit_reached; no scientific STOP was fabricated'
    except KeyboardInterrupt:
        failure='host_interrupted; no scientific STOP was fabricated'
        log(events,{'event':'HOST_INTERRUPTED','case':letter,'error':failure})
    except Exception as error:
        failure=f'{type(error).__name__}: {str(error)[:2000]}'
        log(events,{'event':'HOST_FAILURE','case':letter,'error':failure})
    finally:
        final=store.load_case(case_id);verify_history(final)
        store.export_case(case_id,directory/'case_file');export_traces()
        save(directory/'model_usage.json',provider.summary());save(directory/'stage_results.json',stages)
        traces=prior_traces+[json.loads(r[0]) for r in registry.db.execute('SELECT payload FROM traces WHERE run_id=? ORDER BY rowid',(registry.run_id,))]
        success_roles={s['role'] for s in stages if s['success']}
        completed=final.action_state.current_phase=='stopped' and failure is None
        real_sources=all(file_sha(t['result_reference']['path'])==t['result_reference']['sha256'] and json.loads(Path(t['result_reference']['path']).read_text())['source_mode']=='REAL' for t in traces)
        gate=real_sources and completed and success_roles=={'explorer','investigator','critic'} and bool(traces) and bool(final.evidence_records) and file_sha(initial)==source_sha
        summary={'case':letter,'case_id':case_id,'completed':completed,'technical_gate_passed':gate,'failure':failure,
            'stop_reason':final.action_state.stop_reason,'successful_roles':sorted(success_roles),'initial_source_unchanged':file_sha(initial)==source_sha,
            'hypotheses':len(final.hypotheses),'hypothesis_revisions':sum(len(h.revisions) for h in final.hypotheses),
            'evidence_records':len(final.evidence_records),'tool_calls':len(traces),
            'tool_status_counts':{s:sum(t['status']==s for t in traces) for s in sorted({t['status'] for t in traces})},
            'tool_selection':{t:sum(r['tool_name']==t for r in traces) for t in sorted({r['tool_name'] for r in traces})},
            'critic_recheck_calls':sum(t['actor']=='critic' for t in traces),
            'c2_entered':bool(final.critic_audits.claim_audits),
            'c2_attempted_this_run':any(r.get('operation') in {'decompose_claims','plan_rechecks','audit_evidence'} for r in provider.records),
            'claim_audits':len(final.critic_audits.claim_audits),
            'revision_acceptance': [e.metadata['acceptance'] for e in final.investigation_history if e.action=='REVISION_ACCEPTANCE_COMPLETED'],
            'discrimination_progress_events':sum(e.action=='DISCRIMINATION_PROGRESS_RECORDED' for e in final.investigation_history),
            'critic_routes':[r.route_to for r in final.critic_audits.routing_decisions],
            'hypothesis_states':{h.hypothesis_id:h.status for h in final.hypotheses},
            'claim_status_counts':{s:sum(c.status==s for c in final.mechanistic_claims) for s in sorted({c.status for c in final.mechanistic_claims})},
            'model':provider.summary(),'predecessor':predecessor,'cumulative_model_calls':prior_calls+provider.calls,'current_run_stages':len(stages)-len(prior_stages),'all_tool_sources_real':real_sources,'mock_used':False,'scientific_report_source':'committed Critic final report; no Codex case interpretation'}
        save(directory/'case_run_summary.json',summary)
        if final.critic_audits.final_reports:save(directory/'final_case_report.json',final.critic_audits.final_reports[-1].model_dump(mode='json'))
        save(directory/'schema_validation_trace.json',{r:t.requests for r,t in transports.items()})
        if config.get('saved_investigator_prefix'):
            save(directory/'saved_prefix_replay.json',{'responses':provider.replayed,'tools':binding.replayed,
                'remaining_responses':len(provider.remaining),'remaining_tools':len(binding.remaining),
                'inherited_paid_calls':prior_calls,'inherited_tool_calls':len(prior_traces),
                'logical_transition_resumed':transition_offset+1,'budgets_reset':False})
        log(events,{'event':'CASE_FINISHED',**summary})
    return summary

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',default='outputs/agent_pilot_v1_20260928/run_001');p.add_argument('--config',default='configs/agent_pilot_v1.json');p.add_argument('--cases',default='ABCD');p.add_argument('--prompt-key',action='store_true');a=p.parse_args()
    config=json.loads(Path(a.config).read_text());root=Path(a.output);root.mkdir(parents=True,exist_ok=True)
    if list(a.cases)!=[c for c in config['case_order'] if c in a.cases] or any(c not in 'ABCD' for c in a.cases):raise ValueError('Cases must follow frozen A/B/C/D order')
    independent=validate_independent_resume(config,a.cases)
    independent=validate_admission_recovery(config,a.cases) or independent
    independent=validate_investigation_first_resume(config,a.cases) or independent
    independent=validate_provider_switch_continuation(config,a.cases) or independent
    independent=validate_content_recovery(config,a.cases) or independent
    if config.get('case_execution_policy') == 'user_guided_case_c_second_cycle':
        from .continuation import validate_case_c_second_cycle
        validate_case_c_second_cycle(config,a.cases)
        independent=True
    if config.get('case_execution_policy') == 'user_selected_single_cycle':
        if (a.cases != 'C' or config['case_order'] != ['C']
                or set(config.get('initial_case_sources', {})) != {'C'}
                or not config.get('user_authorization')
                or config['max_transitions'] != 3
                or config['provider_max_calls_per_case'] > 40):
            raise ValueError('New selection requires explicit C source, user authorization and one bounded E/I/C cycle')
        from triage.pilot import assert_initial
        assert_initial(load_case(initial_case_path('C', config)))
        independent = True
    if config.get('case_execution_policy')=='independent_ab_protocol_evaluation':
        if not config.get('protocol_v3') or any(c not in 'AB' for c in a.cases):
            raise ValueError('Protocol evaluation requires fresh A/B initial cases')
        if config.get('resume_sources'):
            if config.get('technical_continuation')!='preserve_all_calls_and_committed_v3_state':
                raise ValueError('Only explicitly declared technical continuation is allowed')
            for letter,spec in config['resume_sources'].items():
                if letter not in a.cases:raise ValueError('Resume case outside evaluation')
                previous=json.loads((Path(spec['directory']).parent/'PILOT_RUNTIME_FROZEN.json').read_text())
                if not previous['protocol'].get('protocol_v3') or previous['initial_cases'][letter]!=file_sha(Path('outputs/pilot_preparation_v1_20260928/initial_cases')/letter/'case_file.json'):
                    raise ValueError('Continuation must preserve this v3 initial-case lineage')
                if json.loads(Path(config['model_config']).read_text())!=previous['provider_config']:
                    raise ValueError('Continuation cannot change the provider settings')
                for field in ('provider_max_calls_per_case','max_transitions'):
                    if config[field]>previous['protocol'][field]:raise ValueError('Continuation cannot increase global budgets')
                if config['registry_budgets']['total']>previous['protocol']['registry_budgets']['total']:
                    raise ValueError('Continuation cannot increase real tool budget')
        independent=True
    frozen=freeze(root,config);key=getpass.getpass('GLM API key (hidden): ') if a.prompt_key else os.environ.get('JURE_GLM_API_KEY','')
    summaries=[]
    for letter in a.cases:
        if letter!='A' and not independent:
            prior=root/'A/case_run_summary.json'
            if not prior.exists() or not json.loads(prior.read_text())['technical_gate_passed']:raise ValueError('A technical gate required before B–D')
        result=run_case(letter,root,config,key);summaries.append(result);save(root/'pilot_summary.json',summaries)
        if not result['technical_gate_passed'] and not independent:break
    del key
    if code_manifest()!=frozen['code_sha256']:raise ValueError('Runtime code changed during the pilot; results require explicit development-run designation')

if __name__=='__main__':main()
