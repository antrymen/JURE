"""Engineering-only checks, separate from scientific-content heuristics."""
from .validation import _objects


def reference_errors(output, case, capability_summary):
    errors=[]
    def fail(category,message):errors.append({'category':category,'message':message})
    objects=_objects(case)
    owners={h.hypothesis_id:h for h in output.hypotheses}
    predictions={p.prediction_id:p for p in output.predictions}
    identifiers=[h.hypothesis_id for h in output.hypotheses]+[p.prediction_id for p in output.predictions]+[q.question_id for q in output.evidence_questions]
    if len(set(identifiers))!=len(identifiers) or set(identifiers)&set(objects):
        fail('invalid_hypothesis_reference','New IDs duplicate each other or existing objects')
    for h in output.hypotheses:
        if h.operation!='add' or h.derived_from_clue_id!=case.clue.clue_id:
            fail('invalid_lineage','Initial add/clue ownership mismatch')
        for ref in h.derived_from:
            if objects.get(ref.object_id)!=ref.object_type:
                fail('invalid_lineage',f'{h.hypothesis_id}: invalid {ref.object_type} reference {ref.object_id}')
    for p in output.predictions:
        if p.hypothesis_id not in owners or set(p.discriminates_from_hypotheses)-set(owners) or p.hypothesis_id in p.discriminates_from_hypotheses:
            fail('invalid_hypothesis_reference',f'Prediction {p.prediction_id} has invalid hypothesis links')
    available={x['capability_id'] for x in capability_summary['observables'] if x['availability']=='available'}
    covered=set()
    for q in output.evidence_questions:
        sources=set(q.derived_from_prediction_ids);covered|=sources
        if not sources or sources-set(predictions):
            fail('prediction_question_mismatch',f'Question {q.question_id} has missing prediction links')
        relevant=set(q.relevant_hypothesis_ids);targets=set(q.discriminates_between)
        if not relevant or relevant-set(owners) or targets-relevant:
            fail('invalid_hypothesis_reference',f'Question {q.question_id} has invalid target links')
        supported=set()
        for pid in sources&set(predictions):
            p=predictions[pid];supported|={p.hypothesis_id,*p.discriminates_from_hypotheses}
            if p.hypothesis_id not in relevant or (targets and p.hypothesis_id not in targets):
                fail('prediction_question_mismatch',f'Question {q.question_id} omits its prediction owner')
        if targets-supported:
            fail('prediction_question_mismatch',f'Question {q.question_id} targets exceed prediction comparison')
        if q.discrimination is None:
            fail('json_schema',f'Question {q.question_id} has no comparison')
        else:
            if set(q.discrimination.targets)-targets:
                fail('invalid_hypothesis_reference',f'Question {q.question_id} comparison targets are not linked')
            if set(q.discrimination.capability_ids)-available:
                fail('capability_mismatch',f'Question {q.question_id} has unavailable capability IDs')
    if set(predictions)-covered:fail('prediction_question_mismatch','Predictions without derived questions')
    for contrast in output.contrasts:
        if contrast.hypothesis_a not in owners or contrast.hypothesis_b not in owners or contrast.hypothesis_a==contrast.hypothesis_b:
            fail('invalid_hypothesis_reference','Contrast has invalid hypothesis positions')
    return errors


def classify_validation_error(error):
    text=str(error)
    if hasattr(error,'category'):return error.category
    if 'available_observables' in text or 'unavailable capability' in text:return 'capability_mismatch'
    if any(x in text for x in ('outside targets','One expectation','Duplicate comparison target','hypothesis position')):
        return 'invalid_hypothesis_reference'
    if any(x in text for x in ('distinct conditional expectations','Non-discriminating outcome','conditionally discriminating outcome','both favors and weakens')):
        return 'scientific_content_guard'
    return 'json_schema'
