"""One authorized Case C Investigator/Critic revision test; never loop after it."""
import argparse,getpass,json,os,shutil,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from jure.casefile import CaseStore,ActionState,load_case
from jure.casefile.history import verify_history,agent_round_counts
from jure.agents.critic.result import CriticConfig
from jure.agents.critic.stall_detection import budget_state
from jure.runtime.pilot import save,freeze,run_case,code_manifest
from jure.tools.real.registry import file_sha

ROOT=Path('outputs/case_c_claim_source_revision_test_20260930')
BASE=Path('outputs/case_c_second_cycle_20260929/run_004/C')
SOURCE_SHA='721cee2e6b782ac3c5ff0908c3e38a602589959479b0af2fc3051807fc0c016b'
CONFIG=ROOT/'protocol.json'

def prepare():
    source_path=BASE/'case_file/case_file.json'
    assert file_sha(source_path)==SOURCE_SHA
    source=load_case(source_path)
    old=json.loads((BASE/'case_run_summary.json').read_text())
    assert old['cumulative_model_calls']==49 and old['tool_calls']==12
    assert source.action_state.current_phase=='stopped'
    assert all(agent_round_counts(source,r)['completed']==2 for r in ('investigator','critic'))
    original=json.loads(Path('configs/agent_case_c_second_cycle_reconciliation.json').read_text())
    config={k:original[k] for k in ('model_config','explorer','investigator','critic','registry_budgets','protocol_v3','initial_case_sources')}
    config['investigator'].update(source_aware_planning=True,max_questions_per_run=2,max_tool_calls_per_run=6)
    # The controller's two transitions terminate the trial; do not fabricate a
    # scientific STOP just because the third audit is the last allowed trial stage.
    config['critic'].update(source_aware_stopping=True,max_critic_rounds=4,max_investigator_rounds=4,max_total_tool_calls=20)
    config['registry_budgets']['total']=20
    authorization=dict(user_instruction='值得跑一次真实 Case C revision test。跑完以后，无论有没有 winner，先停下来比较 old protocol vs claim-source protocol v1，再决定 Case C 是否继续承担主案例。',
        old_checkpoint=str(BASE),old_sha256=SOURCE_SHA,inherited_model_calls=49,inherited_tool_calls=12,
        new_model_calls_cap=30,new_tool_calls_cap=8,new_investigator_cycles=1,new_critic_cycles=1,
        automatic_continuation=False,scientific_objects_modified=False)
    checkpoint=ROOT/'preparation/C';checkpoint.mkdir(parents=True,exist_ok=False)
    with CaseStore(checkpoint/'case_store.sqlite') as store:
        store.import_case(source)
        current=store.append_history_event(source.metadata.case_id,actor='controller',expected_revision=source.metadata.case_revision,
            summary='User authorized one separately labelled claim-source protocol revision test; retain old STOP, science and cumulative usage.',
            metadata={'controller_event':'USER_AUTHORIZED_BUDGET_EXTENSION','authorization':authorization,
                'budget_state':budget_state(source,CriticConfig(**config['critic']),2),
                'protocol_revision':'claim-source-v1','not_a_scientific_critic_route':True})
        current=store.set_action_state(current.metadata.case_id,ActionState(current_phase='evidence_needed',next_actor='investigator'),actor='controller',expected_revision=current.metadata.case_revision)
        for field in ('clue','mechanistic_question','hypotheses','evidence_questions','evidence_records','evidence_assessments','mechanistic_claims','evidence_gaps','contradictions','critic_audits'):
            assert getattr(source,field)==getattr(current,field),field
        assert current.investigation_history[:len(source.investigation_history)]==source.investigation_history
        verify_history(current);store.export_case(current.metadata.case_id,checkpoint/'case_file')
    for name in ('stage_results.json','tool_trace.jsonl','model_usage.json'):shutil.copyfile(BASE/name,checkpoint/name)
    save(checkpoint/'case_run_summary.json',{**old,'checkpoint_only':True,'completed':False,'stop_reason':None,'failure':None})
    config.update(protocol_id='case_c_claim_source_v1_revision_test',case_order=['C'],case_execution_policy='case_c_claim_source_revision_test',
        user_authorization=authorization['user_instruction'],budget_extension_authorization=authorization,
        resume_sources={'C':{'directory':str(checkpoint),'case_sha256':file_sha(checkpoint/'case_file/case_file.json')}},
        provider_max_calls_per_case=79,max_transitions=7,critic_rechecks_per_round=2,
        schema_retries=0,failed_stage_retries=0,provider_retry_delays_seconds=[],
        policy='One Investigator then one Critic invocation only, preserve old science and ledger; no winner target, no host-authored claims or tool queries, no Day8, no automatic repairs/retries/extra rounds. Protocol revision comparison is descriptive, not a controlled ablation.')
    save(CONFIG,config);save(ROOT/'AUTHORIZATION_AND_BOUNDARY.json',authorization)
    assert file_sha(source_path)==SOURCE_SHA
    return config

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--prepare-only',action='store_true');args=parser.parse_args()
    config=json.loads(CONFIG.read_text()) if CONFIG.exists() else prepare()
    assert config['max_transitions']==7 and config['provider_max_calls_per_case']==79 and config['registry_budgets']['total']==20
    assert config['schema_retries']==config['failed_stage_retries']==0
    assert config['investigator']['source_aware_planning'] and config['critic']['source_aware_stopping']
    frozen=freeze(ROOT,config)
    if args.prepare_only:
        print(json.dumps({'prepared':str(CONFIG),'remaining_model_calls':30,'remaining_tools':8,'stages':['investigator','critic']}));return
    if (ROOT/'C').exists():raise FileExistsError('Single trial already started; no automatic rerun allowed')
    key=os.environ.get('JURE_GLM_API_KEY') or getpass.getpass('GLM API key (hidden): ')
    result=run_case('C',ROOT,config,key);del key
    assert file_sha(BASE/'case_file/case_file.json')==SOURCE_SHA
    assert code_manifest()==frozen['code_sha256'],'Runtime changed during test'
    save(ROOT/'TRIAL_BOUNDARY.json',{'trial_ended':True,'automatic_continuation':False,
        'scientific_case_stopped':result['completed'],'failure':result['failure'],
        'next_action':'Offline old-vs-new comparison only; no further Agent cycle.'})
if __name__=='__main__':main()
