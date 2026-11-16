"""Continue the same Case C logical I→C turn with immutable paid prefix."""
import getpass
import json
import os
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))

from jure.casefile import load_case
from jure.casefile.history import verify_history
from jure.runtime.pilot import code_manifest, freeze, run_case, save
from jure.tools.real.registry import file_sha

PARENT=Path('outputs/case_c_claim_source_revision_test_20260930')
PREVIOUS=PARENT/'C'
ROOT=PARENT/'recovery_001'
OLD=Path('outputs/case_c_second_cycle_20260929/run_004/C/case_file/case_file.json')
OLD_SHA='721cee2e6b782ac3c5ff0908c3e38a602589959479b0af2fc3051807fc0c016b'


def manifest():
    calls=sorted((PREVIOUS/'model_calls').glob('call_*/call.json'))
    assert len(calls)==5
    responses=[]
    for call in calls:
        record=json.loads(call.read_text())
        assert record['role']=='investigator' and record['finish_reason']=='stop'
        path=call.with_name('response.json')
        assert path.is_file()
        responses.append({'path':str(path),'sha256':file_sha(path),
                          'role':'investigator','method':record['operation']})
    tool=PREVIOUS/'06_investigator_attempt1/raw_evidence/37d6ed7280a83e8141ee843cfcf7a6fc88c4595bce899897b608678fd8f5b2be.json'
    trace=json.loads((PREVIOUS/'tool_trace_current.jsonl').read_text())
    envelope=Path(trace['result_reference']['path'])
    assert file_sha(envelope)==trace['result_reference']['sha256']
    assert json.loads(tool.read_text())['status']=='success'
    return {'responses':responses,
            'tools':[{'path':str(tool),'sha256':file_sha(tool),'question_id':trace['parent_question_id']}],
            'envelopes':[{'path':str(envelope),'sha256':file_sha(envelope)}]}


def main():
    assert file_sha(OLD)==OLD_SHA
    old_config=json.loads((PARENT/'protocol.json').read_text())
    previous=json.loads((PREVIOUS/'case_run_summary.json').read_text())
    assert previous['failure']=='investigator failed bounded validation attempts'
    assert previous['cumulative_model_calls']==54 and previous['tool_calls']==13
    case_path=PREVIOUS/'case_file/case_file.json'
    case=load_case(case_path);verify_history(case)
    assert case.action_state.next_actor=='investigator' and len(case.evidence_records)==7
    config=dict(old_config)
    config['case_execution_policy']='case_c_claim_source_v1_same_turn_engineering_recovery'
    config['resume_sources']={'C':{'directory':str(PREVIOUS),'case_sha256':file_sha(case_path)}}
    config['saved_investigator_prefix']=manifest()
    config['technical_continuation']='replay_exact_paid_prefix_after_receiver_fix'
    config['recovery_authorization']='User requested receiver repair and completion of the previously interrupted I→C turn.'
    assert config['provider_max_calls_per_case']==79 and config['registry_budgets']['total']==20
    assert config['max_transitions']==7 and config['schema_retries']==config['failed_stage_retries']==0
    ROOT.mkdir(parents=True,exist_ok=False)
    save(ROOT/'protocol.json',config)
    frozen=freeze(ROOT,config)
    key=os.environ.get('JURE_GLM_API_KEY') or getpass.getpass('GLM API key (hidden): ')
    try:
        result=run_case('C',ROOT,config,key)
    finally:
        del key
    assert file_sha(OLD)==OLD_SHA
    assert code_manifest()==frozen['code_sha256']
    save(ROOT/'RECOVERY_BOUNDARY.json',{
        'trial_ended':True,'automatic_continuation':False,
        'scientific_case_stopped':result['completed'],'failure':result['failure'],
        'same_logical_investigator_then_critic':True,
        'no_new_scientific_guidance':True,
        'next_action':'Compare old protocol and claim-source v1; do not start another Agent cycle.'})


if __name__=='__main__':main()
