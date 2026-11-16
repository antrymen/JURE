"""Read-only engineering evaluation shared by historical replay and smoke."""
from copy import deepcopy
import json,re
from itertools import combinations
from pydantic import ValidationError
from jure.protocol.normalization import normalize_output


def output_model(role, method, context):
    if role=='explorer':
        if method=='initial_content':
            from jure.agents.explorer.content_adapter import content_model
            return content_model(context)
        from jure.agents.explorer.admission import AdmissionProposal
        from jure.agents.explorer.models import ExplorerOutput
        return AdmissionProposal if context.get('write_contract',{}).get('validation_policy')=='three_layer' else ExplorerOutput
    if role=='investigator':
        from jure.agents.investigator.backend import _SCHEMAS
    else:
        from jure.agents.critic.backend import _SCHEMAS
        if method=='plan_rechecks':
            from jure.runtime.backends import RecheckPlan
            return RecheckPlan
    return _SCHEMAS[method]


def completeness_findings(value,role,method):
    findings=[]
    if role!='explorer': return findings
    content=method=='initial_content'
    hs=value.get('hypotheses',[])
    if len(hs)<2: findings.append('missing_competing_hypotheses')
    if not value.get('contrasts'): findings.append('missing_hypothesis_contrasts')
    if content:
        pairs={frozenset((c['hypothesis_a'],c['hypothesis_b'])) for c in value.get('contrasts',[])}
        for a,b in combinations(range(1,len(hs)+1),2):
            if frozenset((a,b)) not in pairs: findings.append(f'missing_contrast_{a}_{b}')
        for i,h in enumerate(hs):
            if not h.get('predictions'): findings.append(f'hypotheses[{i}].missing_predictions')
            for j,p in enumerate(h.get('predictions',[])):
                if not p.get('alternatives'): findings.append(f'hypotheses[{i}].predictions[{j}].missing_alternatives')
                outcomes=p.get('evidence_question',{}).get('possible_outcomes',[])
                if not any(o.get('non_discriminating') for o in outcomes): findings.append(f'hypotheses[{i}].predictions[{j}].missing_neutral_outcome')
    return findings


def reference_findings(value,role,method,context):
    errors=[]
    if role=='investigator' and method=='prioritize_questions':
        expected={q['question_id'] for q in context.get('pending_questions',[])}
        got=[a['question_id'] for a in value.get('assessments',[])]
        if set(got)!=expected or len(got)!=len(set(got)):errors.append('assessment_question_coverage_or_reference')
    if role=='critic' and method=='attribute_failure':
        from jure.agents.critic.references import validate_failure_references
        try:validate_failure_references(value,context)
        except ValueError as e:errors.append(str(e))
    if role=='explorer':
        if method=='initial_content':
            n=len(value['hypotheses']);known=set(range(1,n+1))
            for c in value['contrasts']:
                if c['hypothesis_a'] not in known or c['hypothesis_b'] not in known:errors.append('invalid_local_contrast_reference')
            for i,h in enumerate(value['hypotheses'],1):
                for p in h['predictions']:
                    alternatives=[a['hypothesis'] for a in p['alternatives']]
                    if i in alternatives:errors.append('self_alternative_reference')
                    if len(alternatives)!=len(set(alternatives)):errors.append('duplicate_alternative_reference')
                    targets={i}|set(alternatives)
                    if not targets<=known:errors.append('invalid_local_hypothesis_reference')
                    for o in p['evidence_question']['possible_outcomes']:
                        if not (set(o['favors'])|set(o['weakens']))<=targets:errors.append('invalid_local_outcome_reference')
                        if (set(o['favors'])&set(o['weakens']) or o['non_discriminating'] and (o['favors'] or o['weakens'])):
                            errors.append('contradictory_outcome_labels')
        else:
            catalog={r['object_id']:r['object_type'] for r in context.get('lineage_catalog',[])}
            clue=context.get('clue',{}).get('clue_id')
            for h in value.get('hypotheses',[]):
                if clue and h['derived_from_clue_id']!=clue:errors.append('invalid_parent_clue')
                for ref in h.get('derived_from',[]):
                    kind='evidence_record' if ref['object_type']=='evidence' else ref['object_type']
                    if catalog and catalog.get(ref['object_id'])!=kind:errors.append('invalid_typed_lineage')
            hs={h['hypothesis_id'] for h in value.get('hypotheses',[])}|{h['hypothesis_id'] for h in context.get('existing_hypotheses',[])}
            ps={p['prediction_id'] for p in value.get('predictions',[])}
            for p in value.get('predictions',[]):
                if p['hypothesis_id'] not in hs:errors.append('invalid_prediction_owner')
            for q in value.get('evidence_questions',[]):
                if not set(q['derived_from_prediction_ids'])<=ps:errors.append('invalid_question_prediction_reference')
    return errors


def evaluate(raw,role,method,context,*,normalize=True):
    model=output_model(role,method,context);audit=None
    try:
        if normalize:
            value,audit=normalize_output(raw,role=role,method=method,schema=model.model_json_schema(),context=context)
            parsed=model.model_validate(value)
        else:
            # Baseline includes the whole-response fence handling already in
            # the old GLM transport. Do not credit an existing feature as a gain.
            if isinstance(raw,str):
                match=re.fullmatch(r'```(?:json)?[ \t]*\r?\n(.*?)\r?\n```',raw.strip(),re.S)
                raw=match.group(1) if match else raw
            parsed=model.model_validate_json(raw) if isinstance(raw,str) else model.model_validate(raw)
        value=parsed.model_dump(mode='json')
        refs=reference_findings(value,role,method,context)
        return {'schema_pass':True,'technical_pass':not refs,'reference_errors':refs,
            'completeness_findings':completeness_findings(value,role,method),
            'normalized':value,'normalization_audit':audit,'errors':[]}
    except (ValueError,TypeError,KeyError) as e:
        return {'schema_pass':False,'technical_pass':False,'reference_errors':[],
            'completeness_findings':[], 'normalization_audit':audit,
            'errors':e.errors(include_input=False,include_context=False,include_url=False) if isinstance(e,ValidationError) else [{'type':type(e).__name__,'msg':str(e)}]}
