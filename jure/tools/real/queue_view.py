"""Projection of the existing flexible queue schema; does not change Case File."""
import json

def evidence_queue_view(case,registry):
    data=case.model_dump(mode='json')
    traces=[json.loads(r[0]) for r in registry.db.execute('SELECT payload FROM traces WHERE run_id=? AND case_id=?',(registry.run_id,case.metadata.case_id))]
    result=[]
    for q in data['evidence_questions']:
        extra=q['query_spec'].get('tool_layer_v01',{})
        ids=[e['evidence_id'] for e in data['evidence_records'] if q['question_id'] in [e['question_id'],*e['related_question_ids']]]
        calls=[t for t in traces if t.get('parent_question_id')==q['question_id']]
        gaps=[g for g in data['evidence_gaps'] if q['question_id'] in g['related_question_ids'] and g['status']!='addressed']
        result.append(dict(question_id=q['question_id'],question=q['question_text'],hypothesis_ids=q['relevant_hypothesis_ids'],
            claim_ids=extra.get('claim_ids',[]),why_needed=extra.get('why_needed'),
            discriminating_prediction=q['derived_from_prediction_ids'],candidate_tools=extra.get('candidate_tools',[]),
            selected_tool=extra.get('selected_tool'),status=q['status'],tool_call_ids=[c['query_id'] for c in calls],
            evidence_ids=ids,remaining_gap=[g['gap_id'] for g in gaps]))
    return result
