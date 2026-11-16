"""Independent prioritization arm: five saved proposal contexts, no tools."""
import sys,json,hashlib,argparse,getpass
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from jure.runtime.pilot import code_manifest
from jure.runtime.backends import CheckedTransport
from jure.agents.investigator.backend import JSONInvestigatorBackend
from jure.agents.investigator.prioritization import PrioritizationResult
from jure.llm.glm import GLMConfig,GLMTransport

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')

def prepare(root):
    root.mkdir(parents=True,exist_ok=False)
    save(root/'SELECTION_RULES.json',{'inputs':5,'rule':'All historical prioritize_questions contexts; deduplicate complete hypothesis/queue JSON; SHA256(seed+context) order; no selection by output quality.','max_calls':5,'retries':0,'remaining_budget_from_explorer_arm':5})
    pool={}
    for p in sorted(Path('outputs/agent_pilot_v1_20260928').glob('run_*/[ABCD]/model_calls/call_*_investigator/request.json')):
        req=json.loads(json.loads(p.read_text())['messages'][1]['content'])
        if req.get('method')!='prioritize_questions':continue
        c=req['context']
        key=hashlib.sha256(json.dumps({k:c.get(k) for k in ('case_id','active_hypotheses','pending_questions')},sort_keys=True).encode()).hexdigest()
        pool.setdefault(key,{'request_path':str(p),'sha256':sha(p),'case_id':c['case_id'],'context':c})
    ordered=sorted(pool,key=lambda k:hashlib.sha256(('priority-smoke-v1:'+k).encode()).hexdigest())[:5]
    if len(ordered)!=5:raise ValueError('Need five distinct historical queue contexts')
    rows=[{'slot':f'I{i+1}',**pool[k]} for i,k in enumerate(ordered)]
    save(root/'PRIORITY_FROZEN.json',{'cases':rows,'code':code_manifest(),'script_sha256':sha(__file__),
        'provider':json.loads(Path('configs/agent_runtime_glm47_flash.json').read_text()),'max_model_calls':5})
    print(json.dumps([{'slot':r['slot'],'source':r['request_path']} for r in rows]),flush=True)

def run(root):
    f=json.loads((root/'PRIORITY_FROZEN.json').read_text())
    if f['code']!=code_manifest() or f['script_sha256']!=sha(__file__):raise ValueError('Frozen interface changed')
    key=getpass.getpass('GLM API key (hidden): ')
    provider=GLMTransport(config=GLMConfig(**{**f['provider'],'max_calls':5}),api_key=key,trace_dir=root/'model_calls');del key
    transport=CheckedTransport(provider,'investigator',schema_retries=0,protocol_v3=True)
    backend=JSONInvestigatorBackend(transport);rows=[]
    for item in f['cases']:
        assert sha(item['request_path'])==item['sha256']
        row={'slot':item['slot'],'pass':False}
        print(json.dumps({'event':'PRIORITY_STARTED','slot':item['slot']}),flush=True)
        try:
            result=PrioritizationResult.model_validate_json(backend.prioritize_questions(item['context']))
            row.update({'pass':True,'output':result.model_dump(mode='json')})
        except Exception as e:row['error']=f'{type(e).__name__}: {str(e)[:3000]}'
        rows.append(row);save(root/'PRIORITY_ROWS.json',rows);save(root/'USAGE.json',provider.summary())
        print(json.dumps({'event':'PRIORITY_COMPLETED','slot':item['slot'],'pass':row['pass']}),flush=True)
    summary={'passes':sum(r['pass'] for r in rows),'attempts':5,'model_calls':provider.calls,
        'usage':provider.summary(),'evidence_tool_calls':0,'critic_calls':0,'casefile_writes':0,
        'runtime_unchanged':code_manifest()==f['code'],'scope':'Independent existing-proposal prioritization interface, not a paired scientific investigation.'}
    save(root/'PRIORITY_SUMMARY.json',summary);print(json.dumps(summary),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['prepare','run']);p.add_argument('--output',required=True)
    a=p.parse_args();(prepare if a.action=='prepare' else run)(Path(a.output))
