"""Prepare clean inputs and preflight status. Does not execute LLMs."""
import json,hashlib,os
from pathlib import Path
from jure.ablation.protocol import whitelist,FinalReport,ARMS,MODEL
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'outputs/result4_agent_ablation/02_implementation'
def sha(b):return hashlib.sha256(b).hexdigest()
def main():
 OUT.mkdir(parents=True,exist_ok=True)
 manifest=json.loads((ROOT/'outputs/result4_agent_ablation/01_audit/case_manifest.json').read_text())
 inputs=[]
 for c in manifest['cases']:
  src=Path(c['input_path']);raw=src.read_bytes()
  if sha(raw)!=c['input_sha256']:raise ValueError('input changed: '+c['slot'])
  clean=whitelist(json.loads(raw),c['slot']);clean['case_id']=c['case_id']
  body=json.dumps(clean,ensure_ascii=False,sort_keys=True,indent=2)+'\n'
  dest=OUT/'clean_inputs'/f"{c['slot']}.json";dest.parent.mkdir(exist_ok=True);dest.write_text(body)
  inputs.append({'slot':c['slot'],'path':str(dest),'sha256':sha(body.encode()),'source_sha256':sha(raw)})
 (OUT/'input_manifest.json').write_text(json.dumps(inputs,indent=2)+'\n')
 (OUT/'final_report.schema.json').write_text(json.dumps(FinalReport.model_json_schema(),indent=2)+'\n')
 runs=[{'run_id':f'{slot}__{arm}__r1','slot':slot,'arm':arm,'model':MODEL,'status':'NOT_STARTED'} for slot in ('M01_03','M02','M03') for arm in ARMS]
 (OUT/'pilot_plan.json').write_text(json.dumps(runs,indent=2)+'\n')
 status={'model':MODEL,'api_key_present':bool(os.getenv('OPENAI_API_KEY')),'pilot_started':False,
 'blocking_items':['provider access and actual usage not verified','provider-side exact input counting and max output enforcement not integrated','frozen literature query snapshot not implemented','tool bridge and end-to-end runner not yet implemented'],
 'offline_completed':['15 hashed whitelist inputs','9-run pilot plan','role-neutral report schema','arm routing and shared budget primitives']}
 (OUT/'preflight.json').write_text(json.dumps(status,indent=2)+'\n');print(json.dumps(status,indent=2))
if __name__=='__main__':main()
