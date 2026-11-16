"""Ask the real Critic only for omitted old-evidence audit entries; preserve its new audit."""
import getpass,json,shutil,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from pydantic import BaseModel,ConfigDict
from jure.casefile.critic_models import EvidenceAuditRecord
from jure.agents.critic.backend import SYSTEM_INSTRUCTIONS
from jure.llm.glm import GLMConfig,GLMTransport
from jure.runtime.pilot import save
from jure.tools.real.registry import file_sha
class Patch(BaseModel):
 model_config=ConfigDict(extra='forbid')
 evidence_audits:list[EvidenceAuditRecord]
b=Path('outputs/case_c_second_cycle_20260929');s=b/'run_003/C';t=b/'audit_coverage_patch';t.mkdir(exist_ok=False)
p=s/'model_calls/call_0003_critic/structured_output.json';old=json.loads(p.read_text());case=json.loads((s/'case_file/case_file.json').read_text())
seen={x['evidence_id'] for x in old['evidence_audits']};missing=[x for x in case['evidence_records'] if x['evidence_id'] not in seen];assert len(missing)==3
cfg=GLMConfig.model_validate_json(Path('configs/agent_runtime_glm53_flash.json').read_text()).model_copy(update={'max_calls':1})
key=getpass.getpass('GLM API key (hidden): ');provider=GLMTransport(config=cfg,api_key=key,trace_dir=t/'model_calls');del key
patch=Patch.model_validate_json(provider({'method':'patch_missing_evidence_audits','system_instructions':SYSTEM_INSTRUCTIONS+'\nReturn only the omitted evidence_audits for the THREE supplied records. This is the same uncommitted second Critic round. Do not rewrite claims, judgments, gaps, hypotheses, routing or the four existing evidence audits. Evaluate the supplied records yourself; the program will append only your missing entries.','context':{'current_critic_round':2,'your_current_evidence_audit':old,'missing_evidence_records':missing,'current_claims':json.loads((s/'model_calls/call_0001_critic/structured_output.json').read_text()),'prior_round_evidence_audits':[x for x in case['critic_audits']['evidence_audits'] if x['evidence_id'] in {m['evidence_id'] for m in missing}],'scope':'Prior evidence remains relevant: your own current claims explicitly cite these three records. Complete their per-record review, not a new full scientific round.'},'response_schema':Patch.model_json_schema()},role='critic'))
assert len(patch.evidence_audits)==3 and {x.evidence_id for x in patch.evidence_audits}=={x['evidence_id'] for x in missing}
save(t/'patch.json',patch.model_dump(mode='json'));new={**old,'evidence_audits':old['evidence_audits']+[x.model_dump(mode='json') for x in patch.evidence_audits]}
r=t/'audit_response.json';save(r,{'content':json.dumps(new,ensure_ascii=False),'author':'critic','raw_source':str(p),'patch_source':str(t/'patch.json')})
checkpoint=t/'C';checkpoint.mkdir();shutil.copytree(s/'case_file',checkpoint/'case_file')
for n in ('stage_results.json','tool_trace.jsonl'):shutil.copyfile(s/n,checkpoint/n)
shutil.copyfile(s.parent/'PILOT_RUNTIME_FROZEN.json',t/'PILOT_RUNTIME_FROZEN.json')
summary=json.loads((s/'case_run_summary.json').read_text());assert summary['cumulative_model_calls']==42
save(checkpoint/'case_run_summary.json',{**summary,'cumulative_model_calls':43,'checkpoint_only':True,'local_critic_patch_calls':1})
c=json.loads(Path('configs/agent_case_c_second_cycle_reconciliation.json').read_text());c['resume_sources']={'C':{'directory':str(checkpoint),'case_sha256':file_sha(checkpoint/'case_file/case_file.json')}}
for d in sorted((s/'model_calls').glob('call_*')):
 m=json.loads((d/'call.json').read_text());f=r if m['operation']=='audit_evidence' else d/'response.json';c['saved_investigator_prefix']['responses'].append({'path':str(f),'sha256':file_sha(f),'role':'critic','method':m['operation']})
c['saved_critic_rechecks']=[]
for line in (s/'tool_trace.jsonl').read_text().splitlines():
 row=json.loads(line)
 if row['actor']=='critic' and '/case_c_second_cycle_20260929/run_003/' in row['result_reference']['path']:
  c['saved_critic_rechecks'].append({**{k:row['result_reference'][k] for k in ('path','sha256')},'parent_question_id':row['parent_question_id']})
assert len(c['saved_critic_rechecks'])==2
c['engineering_recovery'].update(inherited_model_calls=43,inherited_tool_calls=12,reason='Critic-authored missing three prior-evidence audits only; previous current audit preserved; two source rechecks replayed.')
save('configs/agent_case_c_second_cycle_coverage.json',c)
save(t/'PROVENANCE.json',{'author':'critic','new_model_calls':1,'new_tools':0,'cumulative_model_calls':43,'original_claims_gaps_audits_unchanged':True,'missing_evidence_ids':[x['evidence_id'] for x in missing]})
print('Missing three audits appended by Critic; cumulative 43/56 calls; rechecks reused.')
