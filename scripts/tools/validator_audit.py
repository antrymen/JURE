"""Offline responsibility audit. Never invoke Agents, providers or evidence tools.

Original outputs and Case Files are read-only. Admission is counterfactual,
not a CaseStore write, scientific acceptance or Critic verdict.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
from itertools import combinations
import json
from pathlib import Path
import re
import sys
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from pydantic import ValidationError
from jure.casefile.models import FrozenModel,Identifier,Text
from jure.casefile.store import load_case
from jure.agents.explorer.models import ExplorerOutput,EvidenceQuestionProposal,ExplorerConfig
from jure.agents.explorer.validation import validate_explorer_output,interpret_observation,_objects
from jure.agents.explorer.context import build_explorer_context
from jure.agents.explorer import content_adapter
from jure.protocol.contracts import HypothesisExpectation,PossibleOutcome
from jure.protocol.capabilities import CATALOG


POLICY={
 'version':'validator-responsibility-audit-v1',
 'machine':'JSON/field/type/enum correctness; globally unambiguous IDs; valid parent/lineage and cross references; exact immutable observation; registered capability IDs; contradictory structured outcome labels. Unknown values are rejected, never repaired.',
 'completeness':'Hypothesis bounds; prediction and weakening conditions per hypothesis; evidence question for each prediction; comparison/expectation/observable/outcome presence; contrast for every hypothesis pair; neutral and at least one directional outcome. These are structural checks, not judgments of biological truth.',
 'critic_flags':'Natural-language causality, unsupported named entities, observability, specificity, redundancy, scientific scope/encoding and prose verdict heuristics. Flags are retained for C1, never called evidence or proof of hallucination.',
 'existing_requirements_split':'Reassign responsibility without adding a requirement for reciprocal favoring branches.',
 'requested_reciprocal_branches':'Additionally, for each pair of targets in a question, require an explicit branch favoring one without favoring the other, and a reverse branch, plus a neutral branch. Weakening one is not automatically interpreted as favoring another. This is an additional completeness rule, not a retrospective old-rule failure.',
 'missing_vs_invalid_reference':'A question pointing at an unknown prediction is machine error; an existing prediction with no question is scientific incompleteness. Missing expectations for declared targets are incompleteness; references outside declared targets are machine errors.',
 'unavailable_capabilities':'Unknown ID is machine error. Known but unavailable measurement is a C1 capability-limit flag; whether an available proxy adequately tests a prediction belongs to C1.',
 'blocked_evaluation':'If syntax/type parsing fails, deeper structural evaluation is marked not evaluated. Original nested validation diagnostics are still classified. Nothing is silently completed.',
 'scope':'Exactly the 14 completed outputs, not the two interrupted calls. Enrichment-only engineering diagnosis, no new model calls or scientific adjudication.',
}


class AuditComparison(FrozenModel):
    """Same field types, with structure/comparison validators evaluated separately."""
    targets: tuple[Identifier,...]
    expectations: tuple[HypothesisExpectation,...]
    observable: Text
    capability_ids: tuple[Identifier,...]
    possible_outcomes: tuple[PossibleOutcome,...]
    scope_limit: Text


class AuditQuestion(EvidenceQuestionProposal):
    discrimination: AuditComparison|None=None


class AuditProposal(ExplorerOutput):
    evidence_questions: tuple[AuditQuestion,...]


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
def save(path,value):Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
def snapshot(root):return {str(p):sha(p) for p in sorted(Path(root).rglob('*')) if p.is_file()}


def classify_old(message):
    """Classify diagnostic text, never infer the mechanism's scientific validity."""
    if 'Explorer output failed validation within the retry limit' in message:
        return 'diagnostic_wrapper','BOUNDED_ATTEMPT_FAILED'
    if 'must label its directed edge' in message:return 'critic_flag','CAUSAL_LANGUAGE_TOO_STRONG'
    if 'unsupported named molecular specifics' in message:return 'critic_flag','UNSUPPORTED_NAMED_ENTITY'
    if 'not a testable discriminating prediction' in message:return 'critic_flag','OBSERVABILITY_UNCLEAR'
    if 'uses unavailable capability IDs' in message:return 'critic_flag','CAPABILITY_LIMIT'
    if 'redundant hypotheses' in message:return 'critic_flag','HYPOTHESIS_DISTINCTNESS_UNCLEAR'
    if 'substantive structural difference' in message:return 'critic_flag','CONTRAST_SPECIFICITY_UNCLEAR'
    if 'distinct conditional expectations' in message:return 'critic_flag','DISCRIMINATION_UNCLEAR'
    if 'mechanistic_question' in message:return 'critic_flag','QUESTION_SCOPE_UNCLEAR'
    if 'proof of a causal mechanism' in message:return 'critic_flag','CAUSAL_LANGUAGE_TOO_STRONG'
    if 'states cannot be relabeled' in message:return 'critic_flag','STATE_INTERPRETATION_UNCLEAR'
    if 'scores, rankings or final verdicts in text' in message:return 'critic_flag','UNAUTHORIZED_VERDICT_LANGUAGE'
    if 'Non-discriminating outcome cannot' in message or 'both favors and weakens' in message:
        return 'machine','CONTRADICTORY_OUTCOME_LABELS'
    if 'One expectation is required per target' in message:
        return 'inspect_payload','EXPECTATION_ALIGNMENT'  # absent and invalid are different
    if 'explicitly non-discriminating outcome' in message:return 'completeness','MISSING_NEUTRAL_OUTCOME'
    if 'conditionally discriminating outcome' in message:return 'completeness','MISSING_DIRECTIONAL_OUTCOME'
    if 'Missing hypothesis ID pairs' in message:return 'completeness','MISSING_PAIR_CONTRAST'
    if 'requires a derived evidence question' in message:return 'completeness','MISSING_QUESTION_FOR_PREDICTION'
    if 'requires at least one prediction' in message:return 'completeness','MISSING_PREDICTION'
    if 'weakening condition' in message or 'requires weakened_if_observed' in message:
        return 'completeness','MISSING_WEAKENING_CONDITION'
    if 'requires a discrimination specification' in message:return 'completeness','MISSING_COMPARISON'
    if 'at least one evidence question must discriminate' in message:return 'completeness','MISSING_COMPARISON'
    if 'Changed hypotheses need a reachable discriminating question' in message:return 'completeness','MISSING_QUESTION_COVERAGE'
    if any(s in message for s in ('valid array','valid tuple','Extra inputs','Field required','Input should','String should')):
        return 'machine','SCHEMA_TYPE_FIELD'
    if any(s in message for s in ('outside targets','invalid lineage','Duplicate comparison','Duplicate outcome','duplicate','collides','valid prediction lineage','omits the owner','source prediction owner','comparison does not follow','must reference an existing hypothesis','hypothesis contrast must identify','targets must be linked')):
        return 'machine','INVALID_REFERENCE'
    if 'observation_interpretation must exactly' in message:return 'machine','IMMUTABLE_OBSERVATION_MISMATCH'
    return 'unclassified','MANUAL_REVIEW_REQUIRED'


def project_without_repair(raw,context):
    """Observe the unchanged adapter's pre-validation argument, not a repaired proposal.

    Interception is local to this offline process and restored immediately.
    The payload is NOT accepted by ExplorerOutput and never reaches CaseStore.
    """
    captured={}
    class Captured(BaseException):pass
    class Capture:
        @staticmethod
        def model_validate(value):
            captured['payload']=deepcopy(value)
            raise Captured()
    with patch.object(content_adapter,'ExplorerOutput',Capture):
        try:content_adapter.compile_initial(raw,context)
        except Captured:pass
    if 'payload' not in captured:raise ValueError('Adapter did not produce a pre-validation payload')
    return captured['payload']


def evaluate_payload(payload,case,capabilities,bounds):
    findings=[]
    def add(layer,code,path,message,**extra):
        record=dict(layer=layer,code=code,path=path,message=message,**extra)
        if record not in findings:findings.append(record)
    try:proposal=AuditProposal.model_validate(payload)
    except ValidationError as error:
        for e in error.errors(include_url=False,include_input=False,include_context=False):
            add('machine','SCHEMA_TYPE_FIELD','.'.join(map(str,e['loc'])),e['msg'])
        return {'findings':findings,'structure_evaluated':False,'existing_split_eligible':False,'requested_split_eligible':False}
    hypotheses={h.hypothesis_id:h for h in proposal.hypotheses};objects=_objects(case)
    predictions={p.prediction_id:p for p in proposal.predictions};owners=set(hypotheses)
    ids=[h.hypothesis_id for h in proposal.hypotheses]+[p.prediction_id for p in proposal.predictions]+[q.question_id for q in proposal.evidence_questions]
    if len(set(ids))!=len(ids) or set(ids)&set(objects):add('machine','DUPLICATE_OBJECT_ID','objects','IDs collide or duplicate')
    if proposal.observation_interpretation.strip()!=interpret_observation(case):
        add('machine','IMMUTABLE_OBSERVATION_MISMATCH','observation_interpretation','Recorded observation is not preserved exactly')
    if not bounds['min_hypotheses']<=len(hypotheses)<=bounds['max_hypotheses']:
        add('completeness','HYPOTHESIS_COUNT','hypotheses','Configured competing-hypothesis count is not satisfied')
    for h in proposal.hypotheses:
        if h.operation!='add' or h.derived_from_clue_id!=case.clue.clue_id:
            add('machine','INVALID_LINEAGE',h.hypothesis_id,'Initial add/parent clue mismatch')
        for ref in h.derived_from:
            kind='evidence_record' if ref.object_type=='evidence' else ref.object_type
            if objects.get(ref.object_id)!=kind:add('machine','INVALID_LINEAGE',h.hypothesis_id,f'Invalid {kind} reference {ref.object_id}')
        if not h.weakening_conditions:add('completeness','MISSING_WEAKENING_CONDITION',h.hypothesis_id,'No weakening condition')
        if not any(p.hypothesis_id==h.hypothesis_id for p in proposal.predictions):
            add('completeness','MISSING_PREDICTION',h.hypothesis_id,'No prediction belongs to this hypothesis')
    expected_pairs={frozenset(pair) for pair in combinations(owners,2)};seen=set()
    for i,c in enumerate(proposal.contrasts):
        pair=frozenset((c.hypothesis_a,c.hypothesis_b))
        if len(pair)!=2 or pair-owners:add('machine','INVALID_REFERENCE',f'contrasts.{i}','Invalid contrast endpoints')
        elif pair in seen:add('machine','DUPLICATE_CONTRAST',f'contrasts.{i}','Duplicate contrast pair')
        else:seen.add(pair)
    for pair in sorted(expected_pairs-seen,key=lambda x:sorted(x)):
        add('completeness','MISSING_PAIR_CONTRAST','contrasts','Missing contrast for '+ ' vs '.join(sorted(pair)))
    for p in proposal.predictions:
        if p.hypothesis_id not in owners or set(p.discriminates_from_hypotheses)-owners or p.hypothesis_id in p.discriminates_from_hypotheses:
            add('machine','INVALID_REFERENCE',p.prediction_id,'Prediction has an invalid owner/alternative')
        if len(set(p.discriminates_from_hypotheses))!=len(p.discriminates_from_hypotheses):
            add('machine','DUPLICATE_REFERENCE',p.prediction_id,'Duplicate alternatives')
        if not p.discriminates_from_hypotheses:add('completeness','MISSING_ALTERNATIVE',p.prediction_id,'No comparison alternative')
    covered=set();question_coverage=set()
    known_caps={identifier for entries in CATALOG.values() for identifier,_ in entries}
    available={x['capability_id'] for x in capabilities['observables'] if x['availability']=='available'}
    for q in proposal.evidence_questions:
        path=q.question_id;refs=set(q.derived_from_prediction_ids);covered|=refs
        relevant=set(q.relevant_hypothesis_ids);comparators=set(q.discriminates_between)
        if not refs or refs-set(predictions):add('machine','INVALID_PREDICTION_PARENT',path,'Question has an empty/unknown prediction parent')
        if not relevant or relevant-owners or comparators-relevant:add('machine','INVALID_REFERENCE',path,'Question target references are inconsistent')
        if len(comparators)<2:add('completeness','MISSING_COMPARISON_TARGETS',path,'A comparison needs at least two targets')
        lineage_targets=set()
        for pid in refs&set(predictions):
            p=predictions[pid];lineage_targets|={p.hypothesis_id,*p.discriminates_from_hypotheses}
            if p.hypothesis_id not in relevant or p.hypothesis_id not in comparators:
                add('machine','PREDICTION_QUESTION_MISMATCH',path,'Question omits its prediction owner')
        if comparators-lineage_targets:add('machine','PREDICTION_QUESTION_MISMATCH',path,'Targets not represented by prediction lineage')
        spec=q.discrimination
        if spec is None:add('completeness','MISSING_COMPARISON',path,'No discrimination specification');continue
        targets=set(spec.targets);question_coverage|=targets
        if len(targets)<2:add('completeness','MISSING_COMPARISON_TARGETS',path,'Need at least two comparison targets')
        if targets-owners or targets-comparators or targets-relevant:
            add('machine','INVALID_REFERENCE',path,'Comparison targets not linked to question/hypotheses')
        if len(targets)!=len(spec.targets):add('machine','DUPLICATE_REFERENCE',path,'Duplicate comparison target')
        expected=[e.hypothesis_id for e in spec.expectations]
        if set(expected)-targets:add('machine','INVALID_REFERENCE',path,'Expectation references outside comparison')
        if len(set(expected))!=len(expected):add('machine','DUPLICATE_REFERENCE',path,'Duplicate expectation owner')
        for missing in sorted(targets-set(expected)):
            add('completeness','MISSING_TARGET_EXPECTATION',path,f'Missing expectation under {missing}')
        if len(spec.expectations)>=2 and len({e.prediction.strip() for e in spec.expectations})<2:
            add('critic_flag','DISCRIMINATION_UNCLEAR',path,'Expectations repeat verbatim; C1 must assess whether the proposed observable can discriminate')
        if not spec.capability_ids:add('completeness','MISSING_OBSERVABLE_MAPPING',path,'No capability mapping')
        if set(spec.capability_ids)-known_caps:add('machine','UNKNOWN_CAPABILITY_ID',path,'Unknown capability IDs: '+str(sorted(set(spec.capability_ids)-known_caps)))
        if set(spec.capability_ids)&known_caps-available:
            add('critic_flag','CAPABILITY_LIMIT',path,'Known capability is unavailable; C1 must assess executable prediction scope')
        if len(spec.possible_outcomes)<2:add('completeness','MISSING_OUTCOMES',path,'Fewer than two outcome branches')
        outcome_ids=[o.outcome_id for o in spec.possible_outcomes]
        if len(set(outcome_ids))!=len(outcome_ids):add('machine','DUPLICATE_OUTCOME_ID',path,'Duplicate outcome ID')
        for o in spec.possible_outcomes:
            a,b=set(o.favors),set(o.weakens)
            if (a|b)-targets:add('machine','INVALID_REFERENCE',path+'.'+o.outcome_id,'Outcome references outside its declared comparison')
            if a&b or o.non_discriminating and (a or b):
                add('machine','CONTRADICTORY_OUTCOME_LABELS',path+'.'+o.outcome_id,'Outcome contradicts its own explicit labels')
        if not any(o.non_discriminating for o in spec.possible_outcomes):
            add('completeness','MISSING_NEUTRAL_OUTCOME',path,'No explicitly non-discriminating outcome')
        if not any(o.favors or o.weakens for o in spec.possible_outcomes):
            add('completeness','MISSING_DIRECTIONAL_OUTCOME',path,'No directional outcome')
        for a,b in combinations(sorted(targets),2):
            for favored,other in ((a,b),(b,a)):
                if not any(not o.non_discriminating and favored in o.favors and other not in o.favors for o in spec.possible_outcomes):
                    add('additional_completeness','MISSING_RECIPROCAL_FAVOR_BRANCH',path,
                        f'No explicit outcome favors {favored} without also favoring {other}',target_pair=[a,b],missing_direction=[favored,other])
    for pid in sorted(set(predictions)-covered):add('completeness','MISSING_QUESTION_FOR_PREDICTION',pid,'Prediction has no derived question')
    for hid in sorted(owners-question_coverage):add('completeness','MISSING_QUESTION_COVERAGE',hid,'Hypothesis has no comparison question')
    # Re-run only the existing deterministic heuristics; no model judgment.
    replay=validate_explorer_output(proposal,case,config=ExplorerConfig(**bounds),capability_summary=capabilities)
    for message in replay:
        layer,code=classify_old(message)
        if layer=='critic_flag':
            extra={'requires_provenance_assessment':True} if code=='UNSUPPORTED_NAMED_ENTITY' else {}
            add(layer,code,'legacy_heuristic',message,**extra)
        elif layer=='unclassified':
            add('unclassified',code,'legacy_heuristic',message)
    hard=any(f['layer']=='machine' for f in findings)
    incomplete=any(f['layer']=='completeness' for f in findings)
    added=any(f['layer']=='additional_completeness' for f in findings)
    uncertain=any(f['layer']=='unclassified' for f in findings)
    return {'findings':findings,'structure_evaluated':True,
        'existing_split_eligible':not(hard or incomplete or uncertain),
        'requested_split_eligible':not(hard or incomplete or added or uncertain)}


def original_classifications(result,payload):
    """Every original rejection preserved; composites have leaf diagnostics."""
    leaves=[]
    try:ExplorerOutput.model_validate(payload)
    except ValidationError as error:
        for e in error.errors(include_url=False,include_input=False,include_context=False):
            layer,code=classify_old(e['msg'])
            if layer=='unclassified' and e['type']!='value_error':layer,code='machine','SCHEMA_TYPE_FIELD'
            leaves.append({'layer':layer,'code':code,'path':'.'.join(map(str,e['loc'])),'message':e['msg']})
    records=[]
    for i,message in enumerate(result['run_result']['validation_errors']):
        if 'validation errors for' in message or 'validation error for' in message:
            records.append({'index':i,'original_message':message,'classification':'composite','leaf_diagnostics':leaves})
        else:
            layer,code=classify_old(message)
            records.append({'index':i,'original_message':message,'classification':layer,'code':code})
    return records


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--source',required=True);parser.add_argument('--output',required=True)
    args=parser.parse_args();source=Path(args.source);output=Path(args.output)
    output.mkdir(parents=True,exist_ok=False)
    before=snapshot(source);frozen=json.loads((source/'BENCHMARK_FROZEN.json').read_text())
    save(output/'AUDIT_POLICY_FROZEN.json',{'policy':POLICY,'frozen_at':datetime.now(timezone.utc).isoformat(),
         'script_sha256':sha(__file__),'input_sha256':before,'runtime_modules_sha256':{str(p):sha(p) for base in ('jure/agents/explorer','jure/protocol','jure/casefile') for p in sorted(Path(base).glob('*.py'))}})
    results=[]
    for result_path in sorted((source/'runs').glob('*/*/RESULT.json')):
        old=json.loads(result_path.read_text());slot,arm=old['slot'],old['arm'];directory=result_path.parent
        entry=next(x for x in frozen['initial_cases'] if x['slot']==slot);case=load_case(entry['path'])
        raw_path=directory/'model_calls/call_0001_explorer/structured_output.json'
        if not raw_path.exists():raise ValueError('Completed output has no decodable raw JSON: handle explicitly, do not repair it')
        raw=json.loads(raw_path.read_text());payload=raw;projection='original full-object output'
        if arm=='deterministic_adapter':
            context=build_explorer_context(case,'initial',max_chars=frozen['config']['explorer']['max_context_chars'])
            context['schema_requirements'].update({k:frozen['config']['explorer'][k] for k in ('min_hypotheses','max_hypotheses')})
            context['capability_summary']=frozen['capability_summary']
            payload=project_without_repair(raw,context);projection='unchanged adapter pre-validation argument; never submitted'
            stored=directory/'compiled_proposal.json'
            if stored.exists() and ExplorerOutput.model_validate_json(stored.read_text()).model_dump(mode='json')!=ExplorerOutput.model_validate(payload).model_dump(mode='json'):
                raise ValueError('Projection differs from stored compiled candidate')
        assessment=evaluate_payload(payload,case,frozen['capability_summary'],frozen['config']['explorer'])
        assessment.update(slot=slot,arm=arm,case_id=entry['case_id'],original_submitted=old['proposal_submitted'],
            original_contract_pass=old['contract_pass'],raw_source=str(raw_path),raw_sha256=sha(raw_path),
            projection=projection,projection_sha256=digest(payload),original_rejections=original_classifications(old,payload),
            scientific_validity='NOT_ASSESSED; Critic has not run',actual_case_changed=False)
        save(output/f'{slot}_{arm}.json',assessment);results.append(assessment)
    if len(results)!=14:raise ValueError('Expected exactly the 14 completed outputs')
    arms={}
    for arm in frozen['config']['arms']:
        rows=[r for r in results if r['arm']==arm]
        arms[arm]={'count':len(rows),'actual_submitted':sum(r['original_submitted'] for r in rows),
            'machine_blocked':sum(any(f['layer']=='machine' for f in r['findings']) for r in rows),
            'existing_completeness_blocked_after_machine_pass':sum(not any(f['layer']=='machine' for f in r['findings']) and any(f['layer']=='completeness' for f in r['findings']) for r in rows),
            'existing_split_eligible':sum(r['existing_split_eligible'] for r in rows),
            'requested_split_eligible':sum(r['requested_split_eligible'] for r in rows),
            'additional_rule_blocks_previously_eligible':[r['slot'] for r in rows if r['existing_split_eligible'] and not r['requested_split_eligible']],
            'flagged_outputs':sum(any(f['layer']=='critic_flag' for f in r['findings']) for r in rows)}
    unchanged=snapshot(source)==before
    if not unchanged:raise ValueError('Original artifacts changed during read-only audit')
    summary={'policy':POLICY,'arms':arms,'results':[{k:r[k] for k in ('slot','arm','original_submitted','structure_evaluated','existing_split_eligible','requested_split_eligible')} for r in results],
        'original_artifacts_unchanged':unchanged,'new_model_calls':0,'new_tool_calls':0,'agent_runs':0,'case_writes':0,
        'unclassified_findings':[{'slot':r['slot'],'arm':r['arm'],**f} for r in results for f in r['findings'] if f['layer']=='unclassified'],
        'interpretation':'Counterfactual eligibility for C1, not actual submission or scientific validity; 7 enrichment-only input pairs; not a new benchmark.'}
    save(output/'SUMMARY.json',summary)
    print(json.dumps(summary,ensure_ascii=False))


if __name__=='__main__':main()
