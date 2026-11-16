"""Compare execution artifacts only. Do not produce or revise biological verdicts."""
import json,hashlib
from collections import Counter
from pathlib import Path
ROOT=Path('outputs/case_c_claim_source_revision_test_20260930')
BASE=Path('outputs/case_c_second_cycle_20260929/run_004/C')
def read(p):return json.loads(p.read_text())
def lines(p):return [json.loads(x) for x in p.read_text().splitlines() if x]
def counts(xs,key):return dict(Counter(x[key] for x in xs))
def main():
 old=read(BASE/'case_file/case_file.json');new=read(ROOT/'C/case_file/case_file.json');summary=read(ROOT/'C/case_run_summary.json')
 oldtr=lines(BASE/'tool_trace.jsonl');newtr=lines(ROOT/'C/tool_trace_current.jsonl')
 oldids={e['evidence_id'] for e in old['evidence_records']};added=[e for e in new['evidence_records'] if e['evidence_id'] not in oldids]
 audits={k:v[len(old['critic_audits'][k]):] for k,v in new['critic_audits'].items() if isinstance(v,list)}
 events=new['investigation_history'][len(old['investigation_history']):]
 plans=[e['metadata']['query_plan'] for e in events if e['action']=='QUERY_PLAN_CREATED']
 calls=[read(p) for p in sorted((ROOT/'C/model_calls').glob('call_*/call.json'))]
 raw_responses=[]
 for p in sorted((ROOT/'C/model_calls').glob('call_*/structured_output.json')):
  raw_responses.append({'path':str(p),'output':read(p)})
 prices=read(Path('configs/glm_pricing_snapshot_20260928.json'));cost=0;known=0
 for c in calls:
  u=c.get('usage');model=c.get('requested_model');tiers=prices.get(model)
  if u is None or not isinstance(tiers,list):continue
  n=u.get('prompt_tokens',0);cache=min(n,u.get('prompt_tokens_details',{}).get('cached_tokens',0));tier=next(t for t in tiers if t['input_tokens_less_than'] is None or n<t['input_tokens_less_than'])
  cost+=((n-cache)*tier['input']+cache*tier['cached_input']+u.get('completion_tokens',0)*tier['output'])/1e6;known+=1
 def operations(traces):
  result=[]
  for t in traces:
   env=read(Path(t['result_reference']['path']));q=env['normalized_query'];result.append({'actor':t['actor'],'tool':t['tool_name'],'operation':q.get('operation'),'mode':q.get('mode'),'status':t['status'],'query_id':env['query_id'],'query':q,'error':env.get('error'),'result':env.get('result')})
  return result
 ops=operations(newtr)
 result={'baseline':{'model_calls':49,'tool_calls':len(oldtr),'tool_selection':counts(oldtr,'tool_name'),'evidence_records':len(old['evidence_records']),'source_types':counts(old['evidence_records'],'source_type'),'stop':old['action_state']},
  'new_only':{'model_calls':len(calls),'successful_model_calls':sum(c.get('status')=='success' for c in calls),'tool_calls':len(newtr),'tool_selection':counts(newtr,'tool_name'),'evidence_records':len(added),'source_types':counts(added,'source_type'),'query_plans':plans,'operations':ops,'audits':audits,'source_reviews':[e['metadata'] for e in events if e['action']=='SOURCE_REVIEW_COMPLETED'],'case_state':new['action_state'],'model_usage':summary['model'],'cost_estimate_cny':cost if known == len(calls) else None,'priced_calls':known,'usage_reported_calls':sum(c.get('usage') is not None for c in calls),'raw_uncommitted_plans':[r for r in raw_responses if 'call_0002_' in r['path']]},
  'trial_failure':summary['failure'],'raw_responses':raw_responses,'new_stage_results':read(ROOT/'C/stage_results.json')[len(read(BASE/'stage_results.json')):],
  'old_source_unchanged':hashlib.sha256((BASE/'case_file/case_file.json').read_bytes()).hexdigest()=='721cee2e6b782ac3c5ff0908c3e38a602589959479b0af2fc3051807fc0c016b',
  'comparison_limits':['Sequential continuation, not a matched-budget ablation. New run inherits old evidence and failure history.','Eight-tool allowance is an explicit revision-test allowance; historical costs are not reset.','No Day8 result inspected; no winner required.','Raw uncommitted responses are not Case File science.','Local price snapshot does not cover this model; cost is unavailable, not zero. Token usage is retained.']}
 (ROOT/'COMPARISON.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
 print(json.dumps({k:v for k,v in result['new_only'].items() if k not in ['query_plans','operations','audits','source_reviews']},ensure_ascii=False,indent=2))
 print('failure',summary['failure']);print('new audit counts',{k:len(v) for k,v in audits.items()});print('tools',[(o['actor'],o['tool'],o['operation'],o['mode'],o['status']) for o in ops])
if __name__=='__main__':main()
