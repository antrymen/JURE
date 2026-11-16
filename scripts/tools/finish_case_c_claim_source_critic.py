"""Finish the interrupted Critic logical turn using saved C1 and a narrow error correction."""
import getpass
import json
import os
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from jure.casefile import load_case
from jure.casefile.history import verify_history
from jure.runtime.pilot import code_manifest,freeze,run_case,save
from jure.tools.real.registry import file_sha

PARENT=Path('outputs/case_c_claim_source_revision_test_20260930')
PREVIOUS=PARENT/'recovery_001/C'
ROOT=PARENT/'recovery_002'
OLD=Path('outputs/case_c_second_cycle_20260929/run_004/C/case_file/case_file.json')
OLD_SHA='721cee2e6b782ac3c5ff0908c3e38a602589959479b0af2fc3051807fc0c016b'
ERROR='ValueError: C1 failure must be attributed to hypothesis/prediction design'

def main():
    assert file_sha(OLD)==OLD_SHA
    summary=json.loads((PREVIOUS/'case_run_summary.json').read_text())
    assert summary['failure']=='critic failed bounded validation attempts'
    assert summary['cumulative_model_calls']==67 and summary['tool_calls']==18
    assert summary['current_run_stages']==2
    case_path=PREVIOUS/'case_file/case_file.json'
    case=load_case(case_path);verify_history(case)
    assert case.action_state.next_actor=='critic' and len(case.evidence_records)==12
    call=PREVIOUS/'model_calls/call_0012_critic/response.json'
    assert json.loads(call.read_text())['content']
    config=json.loads((PARENT/'protocol.json').read_text())
    config['case_execution_policy']='case_c_claim_source_v1_same_turn_critic_consistency_recovery'
    config['resume_sources']={'C':{'directory':str(PREVIOUS),'case_sha256':file_sha(case_path)}}
    config['saved_investigator_prefix']={'responses':[{'path':str(call),'sha256':file_sha(call),
        'role':'critic','method':'audit_hypotheses'}],'tools':[],'envelopes':[]}
    config['same_turn_consistency_feedback']=ERROR
    config['technical_continuation']='replay_exact_paid_c1_then_retry_inconsistent_attribution'
    config['recovery_authorization']='Complete the already authorized Critic turn with machine-only consistency feedback.'
    assert config['provider_max_calls_per_case']==79 and config['registry_budgets']['total']==20
    assert config['max_transitions']==7 and config['schema_retries']==config['failed_stage_retries']==0
    ROOT.mkdir(parents=True,exist_ok=False)
    save(ROOT/'protocol.json',config)
    frozen=freeze(ROOT,config)
    key=os.environ.get('JURE_GLM_API_KEY') or getpass.getpass('GLM API key (hidden): ')
    try:result=run_case('C',ROOT,config,key)
    finally:del key
    assert file_sha(OLD)==OLD_SHA and code_manifest()==frozen['code_sha256']
    save(ROOT/'RECOVERY_BOUNDARY.json',{'trial_ended':True,'automatic_continuation':False,
        'scientific_case_stopped':result['completed'],'failure':result['failure'],
        'same_logical_critic_turn':True,'no_new_scientific_guidance':True,
        'next_action':'Compare old protocol and claim-source v1; no further Agent cycle.'})

if __name__=='__main__':main()
