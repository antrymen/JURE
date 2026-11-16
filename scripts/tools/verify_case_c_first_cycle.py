import json
from pathlib import Path
from collections import Counter
from datetime import datetime
from jure.casefile import load_case
from jure.casefile.history import verify_history,agent_round_counts
from jure.runtime.pilot import code_manifest,save
from jure.tools.real.registry import file_sha
b=Path('outputs/case_c_eif2b5_single_cycle_20260929');r=b/'run_006/C';case=load_case(r/'case_file/case_file.json');verify_history(case)
s=json.loads((r/'case_run_summary.json').read_text());initial=load_case(b/'initial_case/case_file.json')
rounds={x:agent_round_counts(case,x) for x in ('explorer','investigator','critic')};assert all(v['completed']==1 for v in rounds.values())
prep=json.loads((b/'PREPARATION_VERIFICATION.json').read_text());assert all(file_sha(Path('outputs/pilot_preparation_v1_20260928/initial_cases')/x/'case_file.json')==sha for x,sha in prep['original_initial_case_hashes'].items())
assert case.clue==initial.clue and file_sha(b/'initial_case/case_file.json')==prep['new_case_sha256']
frozen=json.loads((r.parent/'PILOT_RUNTIME_FROZEN.json').read_text());assert code_manifest()==frozen['code_sha256']
trace=[json.loads(x) for x in (r/'tool_trace.jsonl').read_text().splitlines()];assert len(trace)==len({x['query_id'] for x in trace})==6
for row in trace:
 ref=row['result_reference'];assert file_sha(ref['path'])==ref['sha256'];assert json.loads(Path(ref['path']).read_text())['source_mode']=='REAL'
calls=[json.loads(p.read_text()) for p in b.glob('**/model_calls/call_*/call.json')];assert len(calls)==s['cumulative_model_calls']==26
assert all(x['status']=='success' and x['usage'] for x in calls)
p=sum(x['usage']['prompt_tokens'] for x in calls);o=sum(x['usage']['completion_tokens'] for x in calls);cached=sum(x['usage'].get('prompt_tokens_details',{}).get('cached_tokens',0) for x in calls)
price=(p*.8+o*2.8-cached*.57)/1e6
replay=json.loads((r/'saved_prefix_replay.json').read_text());assert replay['remaining_responses']==replay['remaining_tools']==0
assert s['c2_entered'] and s['claim_audits']==4 and s['critic_routes']==['investigator']
assert s['failure']=='controller_transition_limit_reached; no scientific STOP was fabricated'
assert case.action_state.current_phase=='evidence_needed'
v={'single_cycle_completed':True,'investigation_completed':False,'pause_reason':'USER_AUTHORIZED_ONE_CYCLE_COMPLETE','authoritative_case_path':str(r/'case_file/case_file.json'),'case_sha256':file_sha(r/'case_file/case_file.json'),'history_verified':True,'initial_clue_unchanged':True,'original_pilot_initials_unchanged':True,'runtime_code_unchanged_during_run':True,'round_counts':rounds,'c1_status':case.critic_audits.hypothesis_audits[-1].overall_status,'c2_claim_audits':s['claim_audits'],'route':'investigator','second_cycle_started':False,'scientific_stop':False,'tool_calls':6,'tool_actor_counts':dict(Counter(x['actor'] for x in trace)),'tool_status_counts':dict(Counter(x['status'] for x in trace)),'all_tool_sources_real_and_hash_verified':True,'evidence_records':len(case.evidence_records),'model_calls':26,'model_call_budget':40,'tool_call_budget':8,'provider':'glm-5.3-flash','prompt_tokens':p,'completion_tokens':o,'cached_tokens':cached,'estimated_rmb':price,'pricing_source':'outputs/cost_control_20260928/official_pricing.md; saved snapshot, not actual invoice','paid_replay_consumed':True,'first_call_started_at':min(x['started_at'] for x in calls),'last_call_completed_at':max(x['completed_at'] for x in calls),'provider_elapsed_seconds':sum(x['elapsed_seconds'] for x in calls)}
save(b/'VERIFICATION.json',v)
print(json.dumps(v,ensure_ascii=False,indent=2))
