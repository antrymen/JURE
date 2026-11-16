"""Versioned representation normalization, without scientific completion.

No fuzzy matching, prose rewriting, status inference, dropped fields or guessed
cross-type links. Every change is reversible from its raw/normalized audit pair.
"""
from copy import deepcopy
import hashlib
import json
import re

VERSION = 'representation-v2'
PRIORITY_FIELDS = {'discriminative_value', 'answerability', 'directness_potential',
                   'estimated_cost', 'priority_class'}
GENERATED_IDS = {'audit_id','evidence_audit_id','claim_audit_id','attribution_id',
                 'synthesis_id','claim_id','gap_id','contradiction_id'}
REFERENCE_FIELDS = {
    'hypothesis_id':'hypothesis', 'relevant_hypothesis_ids':'hypothesis',
    'related_hypothesis_ids':'hypothesis', 'discriminates_between':'hypothesis',
    'discriminates_from_hypotheses':'hypothesis', 'hypothesis_a':'hypothesis',
    'hypothesis_b':'hypothesis', 'targets':'hypothesis', 'favors':'hypothesis', 'weakens':'hypothesis',
    'question_id':'question', 'selected_question_id':'question',
    'prediction_id':'prediction', 'derived_from_prediction_ids':'prediction',
    'evidence_id':'evidence', 'evidence_ids':'evidence', 'related_evidence_ids':'evidence',
    'supporting_evidence_ids':'evidence','challenging_evidence_ids':'evidence',
    'claim_id':'claim','claim_ids':'claim','related_claim_ids':'claim',
    'gap_id':'gap','gap_ids':'gap','related_gap_ids':'gap',
}


class RepresentationError(ValueError):
    pass


def _pairs(pairs):
    result={}
    for k,v in pairs:
        if k in result: raise RepresentationError(f'Duplicate JSON key: {k}')
        result[k]=v
    return result


def decode_json(raw, *, array_item_model=None):
    changes=[]
    if isinstance(raw, dict): return deepcopy(raw),changes
    if not isinstance(raw,str) or len(raw)>1_000_000:
        raise RepresentationError('Expected a bounded JSON object')
    text=raw.strip()
    blocks=list(re.finditer(r'```(?:json)?\s*\n(.*?)\n```|<proposal>\s*(.*?)\s*</proposal>',text,re.I|re.S))
    if len(blocks)>1:
        raise RepresentationError('Multiple structured output blocks')
    match=blocks[0] if blocks else None
    if match:
        prefix,suffix=text[:match.start()],text[match.end():]
        if any(c in prefix+suffix for c in '{}[]'):
            raise RepresentationError('Ambiguous content outside structured output')
        payload=match[1] if match[1] is not None else match[2]
        changes.append(dict(path='$',rule='whole_json_fence' if match.start()==0 and match.end()==len(text) else 'explicit_structured_block',raw_value=raw,normalized_value=payload))
        text=payload
    def parse(t):
        return json.loads(t,object_pairs_hook=_pairs,
            parse_constant=lambda x: (_ for _ in ()).throw(RepresentationError('Non-finite JSON number')))
    try:
        value=parse(text)
    except json.JSONDecodeError as error:
        # A complete leading object is the payload; preserve surrounding prose
        # in the reversible audit. Do not guess broken JSON or choose between
        # multiple possible payloads. No model call is needed for extraction.
        if error.msg != 'Extra data':
            raise
        candidate = text[:error.pos].rstrip()
        suffix = text[error.pos:]
        if not text.startswith('{') or any(c in suffix for c in '{}[]'):
            raise
        value = parse(candidate)
        if not isinstance(value, dict):
            raise RepresentationError('Expected a JSON object before footer')
        changes.append(dict(path='$', rule='complete_json_with_trailing_text',
                            raw_value=raw, normalized_value=candidate))
    if isinstance(value,str):
        decoded=parse(value)
        changes.append(dict(path='$',rule='json_string_envelope',raw_value=value,normalized_value=decoded))
        value=decoded
    if isinstance(value,list) and array_item_model is not None:
        valid=[]
        for item in value:
            if not isinstance(item,dict):
                raise RepresentationError('Array wrapper contains a non-object item')
            try:
                array_item_model.model_validate(item)
            except ValueError:
                if (set(item) not in ({'answer'}, {'message'})
                        or not all(isinstance(v,str) for v in item.values())):
                    raise RepresentationError('Array wrapper contains an unrecognized object') from None
            else:
                valid.append(item)
        if len(valid)!=1:
            raise RepresentationError('Array wrapper must contain exactly one valid response')
        selected=valid[0]
        changes.append(dict(path='$',rule='unique_typed_object_in_array',
                            raw_value=deepcopy(value),normalized_value=deepcopy(selected)))
        value=selected
    if not isinstance(value,dict): raise RepresentationError('Expected a JSON object')
    return value,changes


def _key(value):
    return re.sub(r'[\s_-]+','_',value.strip().casefold())


def normalize_output(raw, *, role, method, schema, context=None, expected_model=None):
    context=context or {}
    value,changes=decode_json(raw,array_item_model=expected_model if role=='investigator' and method=='select_tool' else None)
    def record(path,rule,old,new):
        if old!=new:
            changes.append(dict(path=path,rule=rule,raw_value=deepcopy(old),normalized_value=deepcopy(new)))
        return new
    root=schema
    def deref(node):
        if '$ref' in node:
            return root['$defs'][node['$ref'].split('/')[-1]]
        return node
    properties=deref(root).get('properties',{})
    if role=='critic' and method=='synthesize_hypothesis':
        target=context.get('target_hypothesis_id')
        claims={c['claim_id']:c for c in context.get('claims',[]) if c['hypothesis_id']==target}
        states={a['claim_id']:a['status'] for a in context.get('claim_audits',[]) if a['claim_id'] in claims}
        if target and claims and set(states)==set(claims) and value.get('hypothesis_id')==target:
            critical={cid for cid,c in claims.items() if c['critical']}
            counts=dict(total_claims=len(claims),critical_claims=len(critical),
                supported_claims=sum(s=='supported' for s in states.values()),
                partially_supported_claims=sum(s=='partially_supported' for s in states.values()),
                challenged_claims=sum(s=='challenged' for s in states.values()),
                insufficient_claims=sum(s=='insufficient' for s in states.values()),
                supported_critical_claims=sum(states[cid]=='supported' for cid in critical),
                unresolved_critical_claims=sum(states[cid]!='supported' for cid in critical),
                challenged_critical_claims=sum(states[cid]=='challenged' for cid in critical))
            value['coverage']=record('$.coverage','counts_from_existing_claim_audits',value.get('coverage'),counts)
            for status,field in [('supported','supported_claim_ids'),('partially_supported','partial_claim_ids'),('challenged','challenged_claim_ids'),('insufficient','insufficient_claim_ids')]:
                value[field]=record('$.'+field,'index_existing_claim_audit_statuses',value.get(field),[cid for cid,s in states.items() if s==status])
    if role=='critic' and method=='audit_evidence':
        known={e['evidence_id'] for e in context.get('evidence_records',[])}
        for i,a in enumerate(value.get('claim_audits',[])):
            refs=list(dict.fromkeys(a.get('evidence_ids',[])+a.get('supporting_evidence_ids',[])+a.get('challenging_evidence_ids',[])))
            if set(refs)<=known:
                a['evidence_ids']=record(f'$.claim_audits[{i}].evidence_ids','index_explicit_polarity_references',a.get('evidence_ids'),refs)
    if role=='critic' and method=='plan_rechecks':
        # A source recheck already identifies its evidence and exact query.
        # Bind an omitted dispatch name only from that evidence's recorded tool;
        # never infer a new scientific query or select between sources.
        from jure.tools.real.contracts import ExperimentQuery,GraphQuery,GeneQuery,LiteratureQuery
        tools={'data_experiment':ExperimentQuery,'knowledge_graph':GraphQuery,
               'gene_knowledge':GeneQuery,'literature':LiteratureQuery}
        evidence={e['evidence_id']:e for e in context.get('evidence_records',[])}
        for i,q in enumerate(value.get('queries',[])):
            if not isinstance(q,dict) or 'tool_name' in q:continue
            refs=q.get('evidence_ids',[])
            if not refs or any(e not in evidence for e in refs):continue
            names={evidence[e].get('provenance',{}).get('tool') for e in refs}
            if len(names)!=1:continue
            name=next(iter(names))
            if name not in tools:continue
            try:tools[name].model_validate(q.get('query',{}))
            except ValueError:continue
            q['tool_name']=record(f'$.queries[{i}].tool_name','existing_evidence_source_tool_binding',None,name)
    if len(value)==1:
        name=next(iter(value))
        if name in {'output','result','response','proposal','answer'} and name not in properties and isinstance(value[name],dict):
            value=record('$','single_object_envelope',value,value[name])
    ids={kind:set() for kind in set(REFERENCE_FIELDS.values())}
    collections={'hypothesis':('hypotheses','active_hypotheses','existing_hypotheses'),
        'question':('evidence_questions','pending_questions','existing_evidence_questions'),
        'evidence':('evidence_records','existing_evidence'), 'claim':('claims',),
        'prediction':('predictions',), 'gap':('evidence_gaps',)}
    id_keys={'hypothesis':'hypothesis_id','question':'question_id','prediction':'prediction_id',
             'evidence':'evidence_id','claim':'claim_id','gap':'gap_id'}
    for kind,names in collections.items():
        for name in names:
            rows=context.get(name,())
            if isinstance(rows,dict):rows=rows.values()
            for row in rows:
                if not isinstance(row,dict):continue
                if isinstance(row.get(id_keys[kind]),str):ids[kind].add(row[id_keys[kind]])
                if kind=='hypothesis':
                    predictions=row.get('predictions',())
                    if isinstance(predictions,dict):predictions=predictions.values()
                    ids['prediction'].update(p['prediction_id'] for p in predictions
                        if isinstance(p,dict) and isinstance(p.get('prediction_id'),str))
    # Declared IDs are authoritative for references within this output. Never
    # create an object merely because a reference mentions it.
    for kind,names in collections.items():
        for name in names:
            for row in value.get(name,[]) if isinstance(value.get(name),list) else []:
                if isinstance(row,dict) and isinstance(row.get(id_keys[kind]),str): ids[kind].add(row[id_keys[kind]])
    seed=hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    def walk(v,node,path,field=None):
        node=deref(node)
        if field=='directed_edges' and re.search(r'\.directed_edges\[\d+\]$',path):
            pair=None
            if isinstance(v,str) and len(re.findall(r'->|→',v))==1:
                parts=re.split(r'->|→',v)
                if all(p.strip() for p in parts): pair=[p.strip() for p in parts]
            elif isinstance(v,dict) and set(v)=={'source','target'}:
                pair=[v['source'],v['target']]
            elif isinstance(v,list) and len(v)==2: pair=v
            if pair is not None:
                if node.get('type')=='array' and len(node.get('prefixItems',[]))==2:
                    v=record(path,'explicit_edge_pair_representation',v,pair)
                elif node.get('type')=='object' and set(node.get('properties',{}))=={'source','target'}:
                    v=record(path,'explicit_edge_pair_representation',v,dict(zip(('source','target'),pair)))
        if 'anyOf' in node:
            branches=[deref(n) for n in node['anyOf'] if n.get('type')!='null']
            if v is None: return v
            if len(branches)==1: return walk(v,branches[0],path,field)
        if isinstance(v,str):
            choices=node.get('enum', [node['const']] if 'const' in node else [])
            if role=='explorer' and method in ('initial_content', 'initial_pair_design') and field=='available_observables':
                # Both forms refer to the same registered capability. Resolve
                # the entire authoritative namespace, never guess a tool.
                from jure.agents.explorer.content_adapter import OBSERVABLES
                names=[name for name,cid in OBSERVABLES.items()
                       if cid.casefold()==v.strip().casefold() and name in choices]
                if len(names)==1:
                    v=record(path,'registered_capability_id_to_display_name',v,names[0])
            matches=[x for x in choices if isinstance(x,str) and _key(x)==_key(v)]
            if v not in choices and len(matches)==1:
                v=record(path,'enum_spelling',v,matches[0])
            if (role=='investigator' and method=='prioritize_questions' and field in PRIORITY_FIELDS
                    and set(choices)=={'high','medium','low'} and _key(v)=='medium_high'):
                v=record(path,'declared_priority_alias_medium_high_to_high',v,'high')
            if node.get('type')=='boolean' and v.strip().casefold() in {'true','false'}:
                return record(path,'boolean_literal',v,v.strip().casefold()=='true')
            if node.get('type')=='integer' and re.fullmatch(r'-?(0|[1-9]\d*)',v.strip()):
                return record(path,'integer_literal',v,int(v))
            kind=REFERENCE_FIELDS.get(field)
            if kind and v not in ids[kind]:
                matches=[s for s in ids[kind] if s.casefold()==v.strip().casefold()]
                if len(matches)==1: v=record(path,'unique_typed_reference_spelling',v,matches[0])
            return v
        if isinstance(v,list):
            return [walk(x,node.get('prefixItems',[{}]*len(v))[i] if 'prefixItems' in node and i<len(node['prefixItems'])
                else node.get('items',{}),f'{path}[{i}]',field) for i,x in enumerate(v)]
        if isinstance(v,dict):
            props=node.get('properties',{})
            result=deepcopy(v)
            if 'case_id' in props and 'case_id' not in result and context.get('case_id'):
                result['case_id']=record(path+'.case_id','authoritative_case_binding',None,context['case_id'])
            if ('derived_from_clue_id' in props and 'derived_from_clue_id' not in result
                    and role=='explorer' and context.get('clue',{}).get('clue_id')):
                result['derived_from_clue_id']=record(path+'.derived_from_clue_id','authoritative_parent_clue_binding',None,context['clue']['clue_id'])
            # IDs of genuinely new Critic records have no scientific meaning.
            # References to existing records are never generated here.
            for name in GENERATED_IDS & set(props) - set(result):
                defines_record=(name=='claim_id' and 'statement' in props or
                    name=='gap_id' and 'description' in props or
                    name=='contradiction_id' and 'description' in props or
                    name in {'audit_id','evidence_audit_id','claim_audit_id','attribution_id','synthesis_id'})
                if role=='critic' and defines_record:
                    new='N_'+hashlib.sha256(f'{context.get("case_id")}|{method}|{seed}|{path}|{name}'.encode()).hexdigest()[:24]
                    result[name]=record(path+'.'+name,'deterministic_new_record_id',None,new)
            for k,x in list(result.items()):
                if k in props: result[k]=walk(x,props[k],path+'.'+k,k)
            return result
        return v
    normalized=walk(value,root,'$')
    return normalized,{'version':VERSION,'role':role,'method':method,'changes':changes,
        'raw_value':deepcopy(raw),'normalized_value':deepcopy(normalized),
        'scientific_content_generated':False}
