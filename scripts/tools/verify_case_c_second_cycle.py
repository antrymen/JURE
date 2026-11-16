"""Read-only verification of the two-cycle record and bounded follow-up ledger."""
import json,sys
from pathlib import Path
from collections import Counter
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from jure.casefile import load_case
from jure.casefile.history import verify_history,agent_round_counts
from jure.runtime.pilot import code_manifest,save
from jure.tools.real.registry import file_sha
b=Path('outputs/case_c_second_cycle_20260929');r=b/'run_004/C';old=Path('outputs/case_c_eif2b5_single_cycle_20260929');anchor=old/'run_006/C/case_file/case_file.json'
c=load_case(r/'case_file/case_file.json');a=load_case(anchor);verify_history(c)
cfg=json.loads(Path('configs/agent_case_c_second_cycle.json').read_text());assert file_sha(anchor)==cfg['continuation_anchor']['case_sha256']
assert c.clue==a.clue and c.investigation_history[:len(a.investigation_history)]==a.investigation_history
rounds={x:agent_round_counts(c,x) for x in ('explorer','investigator','critic')};assert [rounds[x]['completed'] for x in rounds]==[1,2,2]
assert c.action_state.current_phase=='stopped' and c.action_state.next_actor=='none'
assert [x.critic_round for x in c.critic_audits.hypothesis_audits]==[1,2]
assert len([x for x in c.critic_audits.claim_audits if x.critic_round==2])==4
frozen=json.loads((r.parent/'PILOT_RUNTIME_FROZEN.json').read_text());assert code_manifest()==frozen['code_sha256']
prep=json.loads((old/'PREPARATION_VERIFICATION.json').read_text());assert all(file_sha(Path('outputs/pilot_preparation_v1_20260928/initial_cases')/k/'case_file.json')==v for k,v in prep['original_initial_case_hashes'].items())
rows=[json.loads(x) for x in (r/'tool_trace.jsonl').read_text().splitlines()];assert len(rows)==len({x['query_id'] for x in rows})==12
for row in rows:
 ref=row['result_reference'];assert file_sha(ref['path'])==ref['sha256'];assert json.loads(Path(ref['path']).read_text())['source_mode']=='REAL'
new=[x for x in rows if '/case_c_second_cycle_20260929/' in x['result_reference']['path']];assert len(new)==6
calls=[json.loads(p.read_text()) for p in b.glob('**/model_calls/call_*/call.json')];previous=[json.loads(p.read_text()) for p in old.glob('**/model_calls/call_*/call.json')]
s=json.loads((r/'case_run_summary.json').read_text());assert len(calls)==23 and len(calls)+len(previous)==s['cumulative_model_calls']==49
assert all(x['status']=='success' and x['usage'] for x in calls+previous)
def usage(cs):
 p=sum(x['usage']['prompt_tokens'] for x in cs);o=sum(x['usage']['completion_tokens'] for x in cs);cache=sum(x['usage'].get('prompt_tokens_details',{}).get('cached_tokens',0) for x in cs)
 return {'calls':len(cs),'prompt_tokens':p,'completion_tokens':o,'cached_tokens':cache,'estimated_rmb':(p*.8+o*2.8-cache*.57)/1e6}
replay=json.loads((r/'saved_prefix_replay.json').read_text());assert replay['remaining_responses']==replay['remaining_tools']==0
v={'second_cycle_completed':True,'third_cycle_started':False,'case_stopped':True,'winner_selected':False,'stop_reason_as_recorded':s['stop_reason'],'stop_exhaustiveness_verified':False,'human_guided':True,'directions_executed':{'literature':False,'knowledge_graph':False,'reverse_conditioning':False,'new_EIF2B_family_conditions':False,'pairwise_structure':True},'history_verified':True,'original_first_cycle_unchanged':True,'original_pilot_initials_unchanged':True,'runtime_unchanged_during_second_cycle':True,'round_counts':rounds,'second_cycle_c1':'pass','second_cycle_claim_audits':4,'new_tool_calls':6,'new_tool_actor_counts':dict(Counter(x['actor'] for x in new)),'new_tool_status_counts':dict(Counter(x['status'] for x in new)),'cumulative_tool_calls':12,'all_tools_real_hash_verified':True,'new_evidence_records':4,'cumulative_evidence_records':7,'hypothesis_states':s['hypothesis_states'],'claim_status_counts':s['claim_status_counts'],'new_usage':usage(calls),'cumulative_usage':usage(calls+previous),'cumulative_model_call_cap':56,'cumulative_tool_cap':12,'pricing_source':'outputs/cost_control_20260928/official_pricing.md; saved snapshot estimate, not invoice','authoritative_case_path':str(r/'case_file/case_file.json'),'case_sha256':file_sha(r/'case_file/case_file.json'),'first_new_call_started_at':min(x['started_at'] for x in calls),'last_call_completed_at':max(x['completed_at'] for x in calls),'provider_elapsed_seconds':sum(x['elapsed_seconds'] for x in calls),'verification_limitations':['Critic STOP and H2 status are recorded Agent judgments, not independently established scientific conclusions.','Human guidance and available-gene inventory were supplied; no literature or reverse-conditional query was chosen.','Full availability inventory was included only in Investigator planning calls, not Critic recheck planning.']}
save(b/'VERIFICATION.json',v);print(json.dumps(v,ensure_ascii=False,indent=2))
