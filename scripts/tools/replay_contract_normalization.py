"""Freeze and replay every historical final response; no providers or tools."""
import sys,json,hashlib
from pathlib import Path
from collections import Counter
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from jure.runtime.contract_review import evaluate
from jure.runtime.pilot import code_manifest

def categories(review):
    result=set()
    if review.get('completeness_findings'):result.add('scientific_structure_incomplete')
    if review.get('reference_errors'):result.add('machine_reference_or_object_consistency')
    for error in review.get('errors',[]):
        kind=error.get('type','');message=error.get('msg','')
        if 'expectation is required per target' in message:
            result.add('scientific_structure_incomplete')
        elif kind in {'JSONDecodeError','json_invalid','RepresentationError'}:
            result.add('machine_json')
        else:result.add('machine_schema_or_object_consistency')
    return sorted(result)

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    import argparse
    ap=argparse.ArgumentParser();ap.add_argument('--output',required=True);args=ap.parse_args()
    out=Path(args.output);out.mkdir(parents=True,exist_ok=False)
    paths=sorted(list(Path('outputs/agent_pilot_v1_20260928').glob('run_*/[ABCD]/model_calls/call_*/request.json'))+
        list(Path('outputs/explorer_contract_benchmark_v1_20260928/runs').glob('*/*/model_calls/call_*/request.json')))
    sources={str(p):sha(p) for req in paths for p in req.parent.glob('*.json')}
    (out/'REPLAY_FROZEN.json').write_text(json.dumps({'sources':sources,'code':code_manifest(),'new_model_calls':0},indent=2)+'\n')
    rows=[]
    for index,path in enumerate(paths):
        role=path.parent.name.rsplit('_',1)[-1]
        request=json.loads(json.loads(path.read_text())['messages'][1]['content'])
        method=request.get('method',request.get('mode'))
        response=path.parent/'response.json';call=path.parent/'call.json'
        if not response.exists():
            rows.append({'source':str(path),'role':role,'method':method,'excluded':'no_final_content'});continue
        payload=json.loads(response.read_text())
        if payload.get('finish_reason')!='stop':
            rows.append({'source':str(path),'role':role,'method':method,'excluded':'incomplete_final_content'});continue
        raw=payload['content'];context=request.get('context',{})
        before=evaluate(raw,role,method,context,normalize=False)
        after=evaluate(raw,role,method,context)
        artifact={'source':str(path),'role':role,'method':method,'before':before,'after':after}
        (out/f'{index:04d}_{role}.json').write_text(json.dumps(artifact,ensure_ascii=False,indent=2)+'\n')
        rows.append({'source':str(path),'role':role,'method':method,
            'before_pass':before['technical_pass'],'after_pass':after['technical_pass'],
            'schema_before':before['schema_pass'],'schema_after':after['schema_pass'],
            'remaining_errors':after['errors']+after['reference_errors'],
            'completeness_findings':after['completeness_findings'],
            'remaining_categories':categories(after),
            'rules':[c['rule'] for c in (after['normalization_audit'] or {}).get('changes',[])]})
    included=[r for r in rows if 'excluded' not in r]
    groups={}
    for role in ('explorer','investigator','critic'):
        group=[r for r in included if r['role']==role]
        groups[role]={'completed_outputs':len(group),'technical_failures_before':sum(not r['before_pass'] for r in group),
            'technical_failures_after':sum(not r['after_pass'] for r in group),
            'schema_failures_before':sum(not r['schema_before'] for r in group),
            'schema_failures_after':sum(not r['schema_after'] for r in group),
            'complete_schema_with_scientific_structure_gaps':sum(r['after_pass'] and bool(r['completeness_findings']) for r in group)}
    assert all(sha(Path(p))==h for p,h in sources.items())
    summary={'total_requests':len(rows),'complete_outputs':len(included),'excluded':dict(Counter(r['excluded'] for r in rows if 'excluded' in r)),
        'groups':groups,'rule_counts':dict(Counter(x for r in included for x in r['rules'])),
        'remaining_category_counts':dict(Counter(x for r in included for x in r['remaining_categories'])),
        'baseline':'Previous production whole-JSON-fence handling included; no new credit for existing fence normalization.',
        'new_model_calls':0,'evidence_tool_calls':0,'casefile_writes':0,'source_hashes_unchanged':True,
        'limitation':'Mixed historical interface versions. Mechanical replay only, not new agent execution; completeness screen is structural, not scientific validity.',
        'rows':rows}
    (out/'REPLAY_SUMMARY.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in summary.items() if k!='rows'},ensure_ascii=False))

if __name__=='__main__':main()
