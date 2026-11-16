"""One Investigator local content patch; preserve its plan, evidence and paid prefix."""
import getpass
import json
from pathlib import Path
import shutil
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from jure.agents.investigator.backend import SYSTEM_INSTRUCTIONS, ToolInterpretation
from jure.protocol.contracts import InformationUpdate
from jure.llm.glm import GLMConfig, GLMTransport
from jure.runtime.pilot import save
from jure.tools.real.registry import file_sha

def main():
    base=Path('outputs/case_c_eif2b5_single_cycle_20260929')
    source=base/'run_002/C'; target=base/'information_update_patch'
    target.mkdir(exist_ok=False)
    call=source/'model_calls/call_0006_investigator'
    old=json.loads((call/'structured_output.json').read_text())
    assert old['information_update'] is None
    req=json.loads(next(m['content'] for m in json.loads((call/'request.json').read_text())['messages'] if m['role']=='user'))
    cfg=GLMConfig.model_validate_json(Path('configs/agent_runtime_glm53_flash.json').read_text()).model_copy(update={'max_calls':1})
    key=getpass.getpass('GLM API key (hidden): ')
    provider=GLMTransport(config=cfg,api_key=key,trace_dir=target/'model_calls');del key
    answer=provider({'method':'patch_missing_information_update',
        'system_instructions':SYSTEM_INSTRUCTIONS+'\nComplete only your missing information_update. Return the InformationUpdate object itself. Do not change existing interpretation, queries, outcomes, genes, thresholds or hypotheses. This is a local patch of your own prior response, not a new investigation.',
        'context':{'previous_interpretation':old,'original_arguments':req['arguments'],
            'selected_question_id':req['context']['selected_question_id'],
            'discrimination_goal':req['context']['discrimination_goal']},
        'response_schema':InformationUpdate.model_json_schema()},role='investigator')
    patch=InformationUpdate.model_validate_json(answer)
    save(target/'patch.json',patch.model_dump(mode='json'))
    new={**old,'information_update':patch.model_dump(mode='json')};ToolInterpretation.model_validate(new)
    response=target/'interpretation_response.json'
    save(response,{'content':json.dumps(new,ensure_ascii=False),'author':'investigator',
        'raw_source':str(call/'structured_output.json'),'raw_sha256':file_sha(call/'structured_output.json'),
        'patch_source':str(target/'patch.json'),'patch_sha256':file_sha(target/'patch.json')})
    summary=json.loads((source/'case_run_summary.json').read_text());assert summary['cumulative_model_calls']==11
    checkpoint=target/'C';checkpoint.mkdir();shutil.copytree(source/'case_file',checkpoint/'case_file')
    for name in ('stage_results.json','tool_trace.jsonl'):shutil.copyfile(source/name,checkpoint/name)
    save(checkpoint/'case_run_summary.json',{**summary,'cumulative_model_calls':12,'checkpoint_only':True,
        'local_patch_calls':1,'local_patch_directory':str(target)})
    shutil.copyfile(source.parent/'PILOT_RUNTIME_FROZEN.json',target/'PILOT_RUNTIME_FROZEN.json')
    config=json.loads(Path('configs/agent_case_c_eif2b5_conditional_binding.json').read_text())
    config['resume_sources']={'C':{'directory':str(checkpoint),'case_sha256':file_sha(checkpoint/'case_file/case_file.json')}}
    prefix=config['saved_investigator_prefix']
    for d in sorted((source/'model_calls').glob('call_*')):
        record=json.loads((d/'call.json').read_text());p=response if d==call else d/'response.json'
        prefix['responses'].append({'path':str(p),'sha256':file_sha(p),'role':'investigator','method':record['operation']})
    raw={json.loads(p.read_text())['payload']['evidence_envelope']['query_id']:p
         for p in (source/'02_investigator_attempt1/raw_evidence').glob('*.json')}
    for line in (source/'tool_trace.jsonl').read_text().splitlines():
        row=json.loads(line);p=raw[row['query_id']]
        prefix['tools'].append({'path':str(p),'sha256':file_sha(p),'question_id':row['parent_question_id']})
        prefix['envelopes'].append({'path':row['result_reference']['path'],'sha256':row['result_reference']['sha256']})
    config['engineering_recovery']={'same_logical_transition':2,'inherited_model_calls':12,
        'inherited_tool_calls':3,'no_budget_reset':True,'scientific_rounds_added':0,
        'reason':'Investigator-authored missing information_update only; exact replay of prior queries and responses.'}
    save('configs/agent_case_c_eif2b5_update_patch.json',config)
    save(target/'PATCH_PROVENANCE.json',{'author':'investigator','paid_calls':1,'tool_calls':0,
        'case_unchanged':file_sha(checkpoint/'case_file/case_file.json')==file_sha(source/'case_file/case_file.json'),
        'existing_interpretation_unchanged':{**new,'information_update':None}==old,
        'cumulative_model_calls':12,'prefix_response_count':len(prefix['responses']),
        'prefix_tool_count':len(prefix['tools'])})
    print('Local patch saved; original scientific text and evidence preserved; cumulative calls12/40.')

if __name__=='__main__':main()
