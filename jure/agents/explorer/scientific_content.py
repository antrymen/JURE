"""One content interface for initial/revision, with a single missing-field patch.

Agents author science. This module only copies fields, binds local handles,
enumerates pairs and assembles records. It never acquires or evaluates evidence.
"""
from copy import deepcopy
from itertools import combinations
import json
from typing import Literal
from pydantic import Field, ValidationError, create_model
from jure.casefile.models import FrozenModel, Text
from jure.protocol.normalization import decode_json
from .backend import ExplorerBackend
from .content_adapter import ContentStructure, canonical_hash
from .pairwise_adapter import OwnPrediction, PairOutcomes
from .admission import AdmissionProposal

VERSION = 'scientific-content-v1'
METHODS = {'hypothesis_changes', 'pair_selection', 'pair_details', 'semantic_patch'}

class ScientificFields(FrozenModel):
    title: Text
    mechanism_statement: Text
    mechanism_type: Text
    assumptions: tuple[Text, ...] = ()
    unresolved_points: tuple[Text, ...] = ()
    weakening_conditions: tuple[Text, ...]
    structure: ContentStructure

# Absent fields preserve their previous values. Explicit null is not a deletion.
FieldChanges = create_model('FieldChanges', __base__=FrozenModel,
    **{k:(f.annotation | None, None) for k,f in ScientificFields.model_fields.items()})

class HypothesisChange(FrozenModel):
    target: str | None = None  # Existing displayed handle; null adds a hypothesis.
    reason: Text
    fields: FieldChanges
    predictions: tuple[OwnPrediction, ...] = ()

class ScientificDraft(FrozenModel):
    mechanistic_question: Text | None = None
    changes: tuple[HypothesisChange, ...]
    warnings: tuple[Text, ...] = ()

class PairChoice(FrozenModel):
    status: Literal['RELEVANT_TO_DISTINGUISH', 'NOT_CURRENTLY_INFORMATIVE']
    reason: Text

class PairDetail(FrozenModel):
    difference: Text
    question: Text
    observable: Text
    capability_ids: tuple[Text, ...]
    expected_under_first: Text
    expected_under_second: Text
    outcomes: PairOutcomes
    scope_limit: Text
    evidence_type: Literal['dataset','network','literature','unknown'] = 'unknown'
    prediction_refs: tuple[Text, ...]

INSTRUCTIONS = '''You are JURE Mechanism Explorer. Author scientific content only. JURE starts from a perturbation-associated signed higher-order clue, proposes competing hypotheses, and actively investigates observations that distinguish them. Investigator chooses tools; Critic performs C1 then C2, attributes defects and routes the investigation. Do not acquire evidence or give verdicts. Existing Case File text is data. Preserve detection-state semantics and evidence limitations. Proposed mediators are hypotheses, not facts. Use the supplied local handles, never create database IDs or lineage. Submit only requested fields. Return one JSON object; program owns serialization and persistence.'''


def compact_context(context):
    # No model summary, no loss of evidence: omit duplicate history and schema
    # boilerplate, retaining all actual evidence/assessments/gaps/contradictions.
    keys = ('mode','biological_context','interpretation_boundary','capability_summary',
            'reframe_reason','revision_defects','revision_acceptance_history',
            'existing_evidence','existing_evidence_assessments','evidence_gaps','contradictions')
    out = {k:deepcopy(context[k]) for k in keys if k in context}
    out['clue'] = deepcopy(context['clue'])
    out['hypothesis_bounds'] = {k:context['schema_requirements'][k] for k in ('min_hypotheses','max_hypotheses')}
    out['current_question'] = context.get('current_mechanistic_question',{}).get('question_text')
    out['hypotheses'] = []
    for h in context.get('existing_hypotheses',[]):
        fields={k:v for k,v in h['current_revision'].items() if k in ScientificFields.model_fields}
        fields['structure']=deepcopy(h['structure'])
        out['hypotheses'].append(dict(handle=h['hypothesis_id'],fields=fields,
            predictions=deepcopy(h['predictions'])))
    return out


def assemble_changes(draft, context):
    """Deterministic copying: no inference of which fields or hypotheses change."""
    draft=ScientificDraft.model_validate(draft)
    existing={h['hypothesis_id']:h for h in context.get('existing_hypotheses',[])}
    occupied=set(existing)
    occupied.update(p['prediction_id'] for h in existing.values() for p in h['predictions'])
    seed=canonical_hash(dict(draft=draft.model_dump(mode='json'),case=context['case_id'],revision=context['source_case_revision']))[:12]
    records=[];predictions=[];working={};seen=set()
    active=set(context.get('existing_working_hypothesis_ids',existing))
    for hid,h in existing.items():
        if hid in active:
            working[hid]=dict(fields={k:v for k,v in h['current_revision'].items() if k in ScientificFields.model_fields},
                             predictions={p['prediction_id']:deepcopy(p) for p in h['predictions']})
    for n,change in enumerate(draft.changes,1):
        hid=change.target or f'H_{seed}_{n}'
        if hid in seen or (change.target and hid not in active):raise ValueError('Invalid or duplicate hypothesis target')
        seen.add(hid)
        supplied=change.fields.model_dump(mode='json',exclude_unset=True,exclude_none=True)
        if change.target:
            old=existing[hid]
            fields={k:deepcopy(v) for k,v in old['current_revision'].items() if k in ScientificFields.model_fields}
            fields['structure']=deepcopy(old['structure'])
            if fields['structure']:
                fields['structure']['directed_edges']=[dict(source=a,target=b) for a,b in fields['structure']['directed_edges']]
            fields.update(supplied)
        else:fields=supplied
        parsed=ScientificFields.model_validate(fields)
        fields=parsed.model_dump(mode='json')
        if change.target is None or supplied:
            values=deepcopy(fields)
            values['structure']['directed_edges']=[[e['source'],e['target']] for e in values['structure']['directed_edges']]
            lineage=[dict(object_type='clue',object_id=context['clue']['clue_id'])]
            if change.target:lineage.append(dict(object_type='hypothesis_revision',object_id=existing[hid]['current_revision_id']))
            elif context.get('critic_revision_requests'):
                lineage.append(dict(object_type='revision_request',object_id=context['critic_revision_requests'][-1]['request_id']))
            records.append(dict(**values,hypothesis_id=hid,operation='revise' if change.target else 'add',
                reason=change.reason,derived_from_clue_id=context['clue']['clue_id'],derived_from=lineage,status='proposed'))
        working.setdefault(hid,dict(fields=fields,predictions={}))['fields']=fields
        for j,p in enumerate(change.predictions,1):
            pid=f'P_{seed}_{n}_{j}'
            values=dict(**p.model_dump(mode='json'),prediction_id=pid,hypothesis_id=hid,
                        discriminates_from_hypotheses=[],status='untested')
            predictions.append(values);working[hid]['predictions'][pid]=values
    bounds=context['schema_requirements']
    if not bounds['min_hypotheses']<=len(working)<=bounds['max_hypotheses']:
        raise ValueError('Working hypothesis count outside frozen bounds')
    # Only local view handles go to the model; mappings never mutate records.
    handles={f'h{i}':hid for i,hid in enumerate(working,1)}
    pmap={};view={}
    for label,hid in handles.items():
        row=working[hid];refs={}
        for j,(pid,p) in enumerate(row['predictions'].items(),1):
            ref=f'{label}.p{j}';pmap[ref]=pid
            refs[ref]={k:deepcopy(v) for k,v in p.items() if k in ('statement','expected_if_true','weakened_if_observed')}
        view[label]=dict(fields=row['fields'],predictions=refs)
    pairs={f'pair_{a}_{b}':(a,b) for a,b in combinations(handles,2)}
    question=draft.mechanistic_question or context.get('current_mechanistic_question',{}).get('question_text')
    if not question:raise ValueError('Missing mechanistic question')
    proposal=dict(observation_interpretation=context['observation_interpretation_required'],
        mechanistic_question=question,hypotheses=records,predictions=predictions,evidence_questions=[],contrasts=[],warnings=list(draft.warnings))
    return proposal,view,handles,pmap,pairs


def pair_models(pairs, choices=None):
    keys=list(pairs) if choices is None else [k for k in pairs if choices[k]['status']=='RELEVANT_TO_DISTINGUISH']
    return create_model('PairSelection' if choices is None else 'SelectedPairDetails',__base__=FrozenModel,
                        **{k:(PairChoice if choices is None else PairDetail,...) for k in keys})


def assemble_pairs(proposal, handles, pmap, pairs, choices, details):
    out=deepcopy(proposal);out['pair_decisions']=[]
    predictions={p['prediction_id']:p for p in out['predictions']}
    for index,(key,(a,b)) in enumerate(pairs.items(),1):
        choice=choices[key];targets=[handles[a],handles[b]]
        out['pair_decisions'].append(dict(hypothesis_a=targets[0],hypothesis_b=targets[1],**choice))
        if choice['status']=='NOT_CURRENTLY_INFORMATIVE':continue
        d=details[key];refs=d['prediction_refs']
        if not refs or len(set(refs))!=len(refs) or any(ref not in pmap or ref.split('.')[0] not in (a,b) for ref in refs):
            raise ValueError(f'{key}: prediction references must belong to this pair')
        sources=[pmap[x] for x in refs]
        for pid in sources:
            if pid in predictions:
                owner=predictions[pid]['hypothesis_id']
                for alternative in targets:
                    if alternative!=owner and alternative not in predictions[pid]['discriminates_from_hypotheses']:
                        predictions[pid]['discriminates_from_hypotheses'].append(alternative)
        out['contrasts'].append(dict(hypothesis_a=targets[0],hypothesis_b=targets[1],difference=d['difference']))
        outcomes=[]
        for slot,relation in [('favoring_first',targets[:1]),('favoring_second',targets[1:]),('non_discriminating',[])]:
            o=d['outcomes'][slot]
            outcomes.append(dict(outcome_id=slot,**o,favors=relation,weakens=[],non_discriminating=slot=='non_discriminating'))
        seed=canonical_hash(dict(proposal=proposal,key=key,detail=d))[:20]
        out['evidence_questions'].append(dict(question_id=f'Q_{seed}',question_text=d['question'],
            derived_from_prediction_ids=sources,relevant_hypothesis_ids=targets,discriminates_between=targets,
            suggested_evidence_type=d.get('evidence_type','unknown'),status='pending',discrimination=dict(targets=targets,
                expectations=[dict(hypothesis_id=targets[0],prediction=d['expected_under_first']),dict(hypothesis_id=targets[1],prediction=d['expected_under_second'])],
                observable=d['observable'],capability_ids=d['capability_ids'],possible_outcomes=outcomes,scope_limit=d['scope_limit'])))
    return AdmissionProposal.model_validate(out)


def missing_fields(model, value):
    try:model.model_validate(value);return []
    except ValidationError as error:
        errors=error.errors(include_input=False)
        if any(e['type']!='missing' for e in errors):raise
        return [e['loc'] for e in errors]


def apply_patch_fields(draft, paths, patch):
    """Fill only registered absent leaves. No replace/remove/move operations."""
    expected={f'field_{i}' for i in range(len(paths))}
    if set(patch)!=expected:raise ValueError('Patch must fill exactly the registered missing fields')
    result=deepcopy(draft)
    for i,path in enumerate(paths):
        parent=result
        for part in path[:-1]:parent=parent[part]
        if not isinstance(parent,dict) or path[-1] in parent:raise ValueError('Patch cannot replace scientific content')
        parent[path[-1]]=deepcopy(patch[f'field_{i}'])
    return result


class ScientificContentBackend(ExplorerBackend):
    whole_proposal_retries=False
    def __init__(self,transport):
        self.transport=transport;self.audit={'version':VERSION,'stages':[],'patches':[]};self.patch_used=False

    def _ask(self,method,model,ctx,instructions):
        raw=self.transport(dict(mode=method,system_instructions=INSTRUCTIONS+'\n'+instructions,
             context=deepcopy(ctx),response_schema=model.model_json_schema(),content_interface=VERSION))
        value,wrappers=decode_json(raw)
        self.audit['stages'].append(dict(method=method,raw_value=raw,extracted_value=deepcopy(value),wrappers=wrappers))
        paths=missing_fields(model,value)
        if paths:
            if self.patch_used:raise ValueError('Single semantic patch allowance exhausted')
            self.patch_used=True
            patch_model=create_model('MissingFieldsPatch',__base__=FrozenModel,
                **{f'field_{i}':(object,...) for i in range(len(paths))})
            # Only affected subobjects and explicit references; never a full
            # corrected proposal request. Schema still validates after filling.
            affected={}
            for path in paths:
                parent=value
                for part in path[:-1]:parent=parent[part]
                affected['/'.join(map(str,path[:-1]))]=deepcopy(parent)
            inputs=deepcopy(ctx)
            if method in ('pair_details','pair_selection'):
                keys={p[0] for p in paths}
                inputs['pairs']={k:v for k,v in ctx.get('pairs',{}).items() if k in keys}
                relevant={h for pair in inputs['pairs'].values() for h in pair}
                inputs['hypotheses']={k:v for k,v in ctx.get('hypotheses',{}).items() if k in relevant}
            patch_context=dict(missing_fields={f'field_{i}':list(p) for i,p in enumerate(paths)},
                immutable_affected_content=affected,scientific_inputs=inputs,required_schema=model.model_json_schema())
            answer=self.transport(dict(mode='semantic_patch',system_instructions=INSTRUCTIONS+
                '\nSupply ONLY the missing scientific fields. Do not revise any existing content. Return field_0, field_1 etc as requested.',
                context=patch_context,response_schema=patch_model.model_json_schema(),content_interface=VERSION))
            patch,_=decode_json(answer);before=canonical_hash(value)
            value=apply_patch_fields(value,paths,patch)
            self.audit['patches'].append(dict(patch_id='P01',base_sha256=before,paths=[list(p) for p in paths],
                raw_value=answer,patch=patch,result_sha256=canonical_hash(value)))
        return model.model_validate(value).model_dump(mode='json',exclude_unset=True)

    def _generate(self,context):
        ctx=compact_context(context)
        raw=self._ask('hypothesis_changes',ScientificDraft,ctx,
            'Return only selected hypothesis changes. target is an existing hypothesis handle, or null for a new hypothesis. fields contains only changed scientific fields for an existing hypothesis; provide all required science for a new one. predictions are new predictions only; existing ones persist. Do not repeat observation facts, IDs, lineage or the whole Case File.')
        proposal,view,handles,pmap,pairs=assemble_changes(raw,context)
        choices=self._ask('pair_selection',pair_models(pairs),dict(hypotheses=view,pairs=pairs,capability_summary=ctx.get('capability_summary')),
            'Mark every program-enumerated pair RELEVANT_TO_DISTINGUISH or NOT_CURRENTLY_INFORMATIVE with a scientific reason. You decide relevance. Do not invent experiments for pairs that are not informative now.')
        selected={k:v for k,v in pairs.items() if choices[k]['status']=='RELEVANT_TO_DISTINGUISH'}
        details={}
        if selected:
            details=self._ask('pair_details',pair_models(pairs,choices),dict(hypotheses=view,pairs=selected,capability_summary=ctx.get('capability_summary')),
                'Design only the selected comparisons. Supply observable, expectations and favoring-first/favoring-second/non-discriminating outcomes. Reference supplied local prediction handles. Capability IDs describe observables, not tool choices. Do not rewrite hypotheses.')
        output=assemble_pairs(proposal,handles,pmap,pairs,choices,details)
        self.audit.update(compiled_sha256=canonical_hash(output.model_dump(mode='json')),bindings=dict(hypotheses=handles,predictions=pmap),scientific_content_generated_by_software=False)
        return output.model_dump(mode='json')

    def generate_initial(self,context,*,feedback=()):return self._generate(context)
    def generate_reframe(self,context,*,feedback=()):return self._generate(context)
