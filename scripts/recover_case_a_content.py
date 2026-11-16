"""Offline replay of two paid answers. Never calls a model or evidence tool.

Earliest answer passing the same admission/store checks becomes the recovery
checkpoint. Both original answers and all failed calls remain recorded.
"""
import hashlib,json
from pathlib import Path
from jure.casefile import CaseStore
from jure.casefile.store import load_case
from jure.casefile.history import verify_history
from jure.agents.explorer.agent import MechanismExplorer
from jure.agents.explorer.models import ExplorerConfig
from jure.protocol.normalization import decode_json
from jure.runtime.pilot import freeze,save

PREVIOUS=Path('outputs/agent_pilot_v1_20260928/run_022_glm53_flash_case_a_extension')
ROOT=Path('outputs/agent_pilot_v1_20260928/run_023_content_recovery')

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def main():
    ROOT.mkdir(exist_ok=False)
    cfg=json.loads(Path('configs/agent_pilot_glm53_flash_case_a_extension.json').read_text())
    cfg['policy']='Offline recovery using only saved Explorer answers; earliest valid answer selected deterministically. No new model/evidence calls or budget reset.'
    freeze(ROOT,cfg)
    source_path=PREVIOUS/'A/case_file/case_file.json';before=sha(source_path);source=load_case(source_path)
    summary=json.loads((PREVIOUS/'A/case_run_summary.json').read_text());results=[];chosen=None
    for number in (1,2):
        folder=PREVIOUS/f'A/model_calls/call_{number:04d}_explorer';rawfile=folder/'response.json'
        raw=json.loads(rawfile.read_text())['content'];value,changes=decode_json(raw)
        request=json.loads(json.loads((folder/'request.json').read_text())['messages'][1]['content'])
        target=ROOT/f'offline_answer_{number}';target.mkdir()
        class SavedResponse:
            whole_proposal_retries=False
            audit={'version':'saved-content-recovery-v1','raw_response_path':str(rawfile),
                   'raw_response_sha256':sha(rawfile),'extraction':changes,'new_model_calls':0}
            def generate_initial(self,*a,**k):raise ValueError('Cannot restart Case A')
            def generate_reframe(self,*a,**k):return value
        with CaseStore(target/'case_store.sqlite') as store:
            store.import_case(source)
            result=MechanismExplorer(SavedResponse(),ExplorerConfig(**cfg['explorer'])).run(store,source.metadata.case_id,
                mode='reframe',reframe_reason=source.critic_audits.revision_requests[-1].reason,
                capability_summary=request['context']['capability_summary'],artifact_dir=target/'explorer')
            final=store.load_case(source.metadata.case_id);verify_history(final)
            unchanged=final.clue==source.clue and final.evidence_records==source.evidence_records
            if result.success:
                for h in value['hypotheses']:
                    got=next(x for x in final.hypotheses if x.hypothesis_id==h['hypothesis_id']).current_revision
                    unchanged &= all(json.loads(got.model_dump_json())[k]==h[k] for k in ('title','mechanism_statement','mechanism_type','assumptions','unresolved_points','weakening_conditions'))
                for p in value['predictions']:
                    got=next(x for h in final.hypotheses for x in h.predictions if x.prediction_id==p['prediction_id'])
                    unchanged &= all(json.loads(got.model_dump_json())[k]==v for k,v in p.items())
                for q in value['evidence_questions']:
                    got=next(x for x in final.evidence_questions if x.question_id==q['question_id'])
                    payload=json.loads(got.model_dump_json())
                    unchanged &= all((payload['query_spec']['discrimination'] if k=='discrimination' else payload[k])==v for k,v in q.items())
            row=dict(answer=number,success=result.success,scientific_content_unchanged=bool(unchanged),validation_errors=list(result.validation_errors),raw_response_path=str(rawfile),raw_response_sha256=sha(rawfile),new_model_calls=0)
            results.append(row);save(target/'REPLAY_RESULT.json',row);store.export_case(source.metadata.case_id,target/'case_file')
            if result.success and unchanged and chosen is None:chosen=(final,result,row)
    if chosen is None:raise ValueError('No saved answer passed; no continuation launched')
    final,result,row=chosen;directory=ROOT/'A';directory.mkdir()
    with CaseStore(directory/'case_store.sqlite') as store:
        store.import_case(final);store.export_case(final.metadata.case_id,directory/'case_file')
    stages=json.loads((PREVIOUS/'A/stage_results.json').read_text())
    stages.append(dict(role='explorer',transition=13,attempt=2,execution_kind='OFFLINE_SAVED_OUTPUT_RECOVERY',**result.model_dump(mode='json')))
    save(directory/'stage_results.json',stages)
    (directory/'tool_trace.jsonl').write_text((PREVIOUS/'A/tool_trace.jsonl').read_text())
    save(directory/'offline_recovery.json',{**row,'predecessor':str(source_path),'predecessor_sha256':before,
        'selection_rule':'earliest paid answer passing admission and atomic persistence; no scientific ranking',
        'all_replays':results,'cumulative_model_calls':summary['cumulative_model_calls'],'cumulative_tool_calls':summary['tool_calls']})
    save(directory/'case_run_summary.json',dict(cumulative_model_calls=summary['cumulative_model_calls'],model={'calls':0},
        tool_calls=summary['tool_calls'],next_actor=final.action_state.next_actor,completed=False,
        evidence_records=len(final.evidence_records),hypotheses=len(final.hypotheses),new_model_calls=0,offline_recovery=True))
    assert sha(source_path)==before
    save(ROOT/'OFFLINE_ACCEPTANCE.json',{'answers':results,'selected_answer':row['answer'],'all_pass':all(x['success'] and x['scientific_content_unchanged'] for x in results),'source_unchanged':True,'new_model_calls':0})
    cfg['case_execution_policy']='scientific_content_recovery'
    cfg['protocol_id']='jure_scientific_content_case_a_continuation'
    cfg['resume_sources']={'A':{'directory':str(directory),'case_sha256':sha(directory/'case_file/case_file.json')}}
    cfg['policy']='User-authorized content interface simplification; continue Investigator then Critic from a validated saved Explorer answer. Preserve cumulative 53/80 model calls, 10/18 tools and transitions 13/15. B/C/D paused.'
    cfg.pop('provider_switch',None)
    save('configs/agent_pilot_scientific_content_case_a.json',cfg)
    print(json.dumps({'selected_answer':row['answer'],'offline_answers':results,'next_actor':final.action_state.next_actor,'new_model_calls':0},ensure_ascii=False))

if __name__=='__main__':main()
