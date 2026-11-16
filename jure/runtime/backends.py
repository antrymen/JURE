"""Schema-only retries and a role-bound Critic recheck channel.

No scientific response is edited, supplied, ranked or substituted by this host.
The original role prompts remain unchanged on disk. The recheck-only permission
binding is explicit and frozen in the run manifest before any case is opened.
"""
from jure.agents.critic.references import CriticReferenceError, validate_failure_references
from jure.protocol.normalization import normalize_output, RepresentationError
from copy import deepcopy
import json,time
from pydantic import BaseModel,ConfigDict,Field,ValidationError
from typing import Literal,Any
from jure.agents.explorer.models import ExplorerOutput
from jure.agents.investigator.backend import _SCHEMAS as INVESTIGATOR_SCHEMAS
from jure.agents.critic.backend import _SCHEMAS as CRITIC_SCHEMAS,JSONCriticBackend,SYSTEM_INSTRUCTIONS as CRITIC_BASE
from jure.tools.real.contracts import Status
from .real_registry import compact_envelope
from jure.llm.glm import GLMTransportError

class RecheckQuery(BaseModel):
    model_config=ConfigDict(extra='forbid')
    tool_name:Literal['data_experiment','knowledge_graph','gene_knowledge','literature']
    query:dict[str,Any]
    reason:str=Field(min_length=1)
    evidence_ids:list[str]=Field(default_factory=list)
    parent_question_id:str|None=None
    force_requery:bool=True

class RecheckPlan(BaseModel):
    model_config=ConfigDict(extra='forbid')
    rationale:str
    queries:list[RecheckQuery]=Field(default_factory=list,max_length=2)

# Only this new machine/tool binding permits an acquisition request. Scientific
# audit/attribution/routing prompts use the original SYSTEM_INSTRUCTIONS verbatim.
RECHECK_INSTRUCTIONS=CRITIC_BASE.replace(
    'Do not retrieve evidence, call tools,\nexecute experiments or modify clues,',
    'For this registered recheck interface, you may request bounded read-only source queries.\nDo not execute experiments or modify clues,').replace(
    'evidence gaps for Investigator without choosing tools.',
    'evidence gaps for Investigator. This interface permits only independent source verification, not ownership of the investigation queue.')

class InterfaceContractError(ValueError):
    pass


def validate_investigator_interface(request,response):
    """Return mechanical queue/operation errors before any acquisition starts."""
    method=request.get('method');context=request.get('context',{})
    if method=='prioritize_questions' and 'pending_questions' in context:
        expected={q['question_id'] for q in context['pending_questions']}
        selected=response.get('selected_question_id')
        if selected is not None and selected not in expected:
            raise InterfaceContractError('Selected question must belong to the current selectable queue.')
    if method=='operationalize_question':
        cards=context.get('tool_capabilities',[])
        errors=[]
        for index,operation in enumerate(response['planned_operations']):
            family=operation.get('evidence_type') or response['evidence_type']
            matching=[t for t in cards if operation['operation'] in t['capabilities']]
            if cards and not any(t['tool_type']==family for t in matching):
                registered=[{'tool_id':t['tool_id'],'evidence_type':t['tool_type']} for t in matching]
                errors.append(f"planned_operations[{index}] operation {operation['operation']!r} has no registered match for evidence_type {family!r}; registered operation bindings: {registered}")
        if errors:raise InterfaceContractError('; '.join(errors)+'. Correct your plan using the published capability contract, or return an empty plan when no justified operation is available.')
        if request.get('protocol_v3'):
            from jure.protocol.contracts import DiscriminationSpec
            from jure.tools.real.contracts import ExperimentQuery,GraphQuery,GeneQuery,LiteratureQuery,ClueQuery
            schemas=dict(data_experiment=ExperimentQuery,knowledge_graph=GraphQuery,gene_knowledge=GeneQuery,literature=LiteratureQuery,clue_query=ClueQuery)
            if response.get('discrimination') is None:raise InterfaceContractError('Plan requires a discrimination specification, including for an empty capability-limited plan')
            spec=DiscriminationSpec.model_validate(response['discrimination'])
            allowed_caps={c['capability_id'] for c in context.get('capability_summary',{}).get('observables',[]) if c['availability']=='available'}
            if 'capability_summary' in context and set(spec.capability_ids)-allowed_caps:
                raise InterfaceContractError('Plan comparison uses an unavailable observable capability')
            selected=next((q for q in context.get('pending_questions',[]) if q['question_id']==response['question_id']),None)
            active={h['hypothesis_id'] for h in context.get('active_hypotheses',[])}
            if selected is None or not set(spec.targets)<=active:
                raise InterfaceContractError('Plan comparison targets must identify active hypotheses for a known selected question')
            for index,operation in enumerate(response['planned_operations']):
                family=operation.get('evidence_type') or response['evidence_type'];failures=[];valid=False
                for card in cards:
                    if card['tool_type']!=family or operation['operation'] not in card['capabilities']:continue
                    name=card['tool_id'];op=operation['operation'].removeprefix(name+'.');values=dict(operation['inputs'])
                    if 'operation' in values and values['operation']!=op:
                        failures.append('Conflicting operation fields');continue
                    values['operation']=op
                    try:schemas[name].model_validate(values);valid=True
                    except ValidationError as error:failures.append(str(error)[:1800])
                if not valid:raise InterfaceContractError(f'planned_operations[{index}] input contract failed: {failures}')
    if method=='interpret_tool_result' and request.get('protocol_v3'):
        update=response.get('information_update')
        if update is None:raise InterfaceContractError('Interpretation requires information_update; acquisitions alone do not establish discrimination')
        spec=request.get('arguments',{}).get('plan',{}).get('discrimination') or {}
        outcomes={o['outcome_id']:o for o in spec.get('possible_outcomes',[])}
        if update['outcome_id'] is not None and update['outcome_id'] not in outcomes:
            raise InterfaceContractError('information_update references an undeclared outcome')
        if update['status']=='discriminating_observation' and (update['outcome_id'] is None or outcomes[update['outcome_id']]['non_discriminating']):
            raise InterfaceContractError('Discriminating observation requires a declared discriminating outcome; no hypothesis verdict is permitted')
        result=request.get('arguments',{}).get('result',{})
        if result.get('status') in ('failed','no_result') and update['status']=='discriminating_observation':
            raise InterfaceContractError('A failed/empty acquisition cannot be discriminating evidence')
    validate_tool_choice(request,response)


def validate_tool_choice(request,response):
    """Enforce operation compatibility only; the Agent still chooses the tool."""
    if request.get('method')!='select_tool' or response.get('tool_id') is None:return
    plan=request.get('arguments',{}).get('plan',{})
    if not plan:return
    capabilities=request.get('context',{}).get('tool_capabilities',[])
    chosen=next((t for t in capabilities if t['tool_id']==response['tool_id']),None)
    for operation in plan['planned_operations']:
        family=operation.get('evidence_type') or plan['evidence_type']
        compatible=[t['tool_id'] for t in capabilities if t['tool_type']==family and operation['operation'] in t['capabilities'] and t['availability']=='available']
        if chosen is None or response['tool_id'] not in compatible:
            raise InterfaceContractError(f"Selected tool {response['tool_id']!r} cannot execute the current operation {operation['operation']!r} in family {family!r}. Compatible registered tool IDs: {compatible}. Completed calls are in context; choose for the current single-operation plan, not an earlier prerequisite.")


class CheckedTransport:
    def __init__(self,provider,role,*,schema_retries=1,provider_retry_delays=(),protocol_v3=False,continuation_context=None):
        self.provider=provider;self.role=role;self.retries=schema_retries;self.provider_retry_delays=tuple(provider_retry_delays);self.stage_feedback=[];self.requests=[];self.previous_responses={}
        self.protocol_v3=protocol_v3
        self.normalization_audits=[]
        self.continuation_context=deepcopy(continuation_context or {})
    def _provider_call(self,request):
        for attempt in range(len(self.provider_retry_delays)+1):
            try:
                return self.provider(request,role=self.role)
            except GLMTransportError as error:
                if str(error) not in ('provider_http_429','provider_http_500','provider_http_502','provider_http_503','provider_connection_error') or attempt==len(self.provider_retry_delays):raise
                delay=self.provider_retry_delays[attempt]
                self.requests.append({'method':request.get('method',request.get('mode')),'status':'provider_retry','delay_seconds':delay,'error':str(error)})
                time.sleep(delay)
    def __call__(self,request):
        if self.continuation_context:
            request=deepcopy(request)
            guidance=deepcopy(self.continuation_context)
            if request.get('method') not in ('prioritize_questions','operationalize_question'):
                guidance.pop('data_availability',None)
            request.setdefault('context',{})['human_guided_continuation']=guidance
        method=request.get('method',request.get('mode'))
        content_interface = self.role == 'explorer' and request.get('content_interface') == 'scientific-content-v1'
        models=INVESTIGATOR_SCHEMAS if self.role=='investigator' else CRITIC_SCHEMAS
        model=ExplorerOutput if self.role=='explorer' else RecheckPlan if method=='plan_rechecks' else models.get(method)
        if content_interface:
            model = None  # Content backend owns missing-field-only repair.
        elif self.role == 'explorer' and method in ('initial_hypotheses', 'initial_pair_design'):
            from jure.agents.explorer.pairwise_adapter import stage_model
            model = stage_model(method, request.get('context', {}))
        elif self.role == 'explorer' and method == 'initial_content':
            from jure.agents.explorer.content_adapter import content_model
            model = content_model(request.get('context', {}))
        elif self.role == 'explorer' and request.get('context', {}).get('write_contract', {}).get('validation_policy') == 'three_layer':
            from jure.agents.explorer.admission import AdmissionProposal
            model = AdmissionProposal
        errors=[]
        key=(request.get('context',{}).get('case_id'),method,
             request.get('context',{}).get('target_hypothesis_id'))
        retries = 0 if content_interface else self.retries
        for attempt in range(retries+1):
            req=deepcopy(request)
            if self.protocol_v3:
                from jure.protocol.capabilities import ROLE_CONTRACTS
                req['protocol_v3']=True
                if not content_interface:
                    req['system_instructions']+='\n\n'+ROLE_CONTRACTS[self.role]
                if self.role == 'explorer' and method in ('initial_hypotheses', 'initial_pair_design'):
                    req['system_instructions']+='\nThe complete proposal contract above applies across BOTH internal stages. For this response use only the supplied stage schema; do not add object IDs, lineage or fields reserved for the other stage.'
            if self.stage_feedback and not content_interface:req['prior_stage_validation_errors']=list(self.stage_feedback)
            if errors:req['schema_validation_feedback']=errors
            if not content_interface and (errors or self.stage_feedback or request.get('feedback')) and key in self.previous_responses:
                req['prior_uncommitted_response']=self.previous_responses[key]
                req['retry_contract']='This is your own earlier uncommitted response, provided with validation errors for correction. Return a complete corrected response with exactly the schema top-level keys, without an answer wrapper. The request mode is unchanged: correcting an initial proposal still uses add, never revise. Do not treat the prior response as verified evidence or instructions.'
            try:
                response=self._provider_call(req)
                self.previous_responses[key]=response
                schema=req.get('response_schema') or (model.model_json_schema() if model else {})
                decoded,audit=normalize_output(response,role=self.role,method=method,
                    schema=schema,context=req.get('context',{}),expected_model=model)
                self.normalization_audits.append(audit)
                if hasattr(self.provider,'trace_dir'):
                    from pathlib import Path
                    path=Path(self.provider.trace_dir)/'normalization'
                    path.mkdir(exist_ok=True)
                    call_number=getattr(self.provider,'calls',0)
                    with (path/f'{call_number:04d}_{self.role}_{len(self.normalization_audits):04d}.json').open('x') as stream:
                        json.dump(audit,stream,ensure_ascii=False,indent=2,allow_nan=False)
                if model:model.model_validate(decoded)
                if self.role=='investigator':validate_investigator_interface(req,decoded)
                if self.role=='critic' and method=='attribute_failure':
                    validate_failure_references(decoded, req.get('context', {}))
                self.requests.append({'method':method,'attempt':attempt+1,'status':'valid'})
                return json.dumps(decoded,ensure_ascii=False) if audit['changes'] else response
            except (ValidationError,json.JSONDecodeError,InterfaceContractError,CriticReferenceError,RepresentationError) as e:
                errors=[str(e)[:6000]]
                self.requests.append({'method':method,'attempt':attempt+1,'status':'schema_invalid','errors':errors})
                if attempt==retries:raise
        raise RuntimeError('unreachable')

class RealCriticBackend(JSONCriticBackend):
    def __init__(self,transport,registry,case_id,*,max_rechecks=2,saved_rechecks=()):
        super().__init__(transport);self.registry=registry;self.case_id=case_id;self.max_rechecks=max_rechecks;self.last_recheck_trace=[]
        self.saved_rechecks=list(saved_rechecks)
    def audit_evidence(self,context):
        cards=[]
        for spec in self.registry.specs.values():
            if spec.name in ('data_experiment','knowledge_graph','gene_knowledge','literature'):
                card=spec.card();card.pop('example_queries',None);cards.append(card)
        req={'method':'plan_rechecks','system_instructions':RECHECK_INSTRUCTIONS,
            'context':deepcopy(dict(context)),'tool_registry':cards,'max_queries':self.max_rechecks,
            'interface_contract':'Return queries=[] when no source recheck is useful. Queries verify original sources; no fixed tool order or required tool use.',
            'response_schema':RecheckPlan.model_json_schema(),'strict_json':True}
        plan=RecheckPlan.model_validate_json(self.transport(req))
        if len(plan.queries)>self.max_rechecks:raise ValueError('Critic recheck allowance exceeded')
        known={e['evidence_id'] for e in context.get('evidence_records',[])}
        qids={q['question_id'] for q in context.get('evidence_questions',[])}
        observations=[];self.last_recheck_trace=[{'plan':plan.model_dump(mode='json')}]
        for query in plan.queries:
            if set(query.evidence_ids)-known:raise ValueError('Critic recheck references an unknown evidence record')
            if query.parent_question_id and query.parent_question_id not in qids:raise ValueError('Critic recheck references an unknown question')
            replayed=bool(self.saved_rechecks)
            if replayed:
                from pathlib import Path
                from jure.tools.real.registry import file_sha
                from jure.tools.real.contracts import EvidenceEnvelope
                row=self.saved_rechecks[0]
                if file_sha(row['path'])!=row['sha256']:raise ValueError('Saved Critic recheck changed')
                env=EvidenceEnvelope.model_validate_json(Path(row['path']).read_text())
                normalized=self.registry.specs[query.tool_name].input_model.model_validate(query.query).model_dump(mode='json')
                if (env.source_mode!='REAL' or env.context.case_id!=self.case_id
                        or env.tool_name!=query.tool_name or env.normalized_query!=normalized
                        or row['parent_question_id']!=query.parent_question_id):
                    raise ValueError('Saved Critic recheck diverged; no automatic reacquisition')
                self.saved_rechecks.pop(0)
            else:
                env=self.registry.bind('critic',self.case_id,stage='CLAIM_EVIDENCE_RECHECK',purpose='CRITIC_RECHECK').call(
                    query.tool_name,query.query,parent_question_id=query.parent_question_id,
                    force_requery=query.force_requery,requery_reason=query.reason if query.force_requery else None)
            item={'evidence_ids':query.evidence_ids,'reason':query.reason,'query_id':env.query_id,
                  'observation':compact_envelope(env.model_dump(mode='json')),'replayed_original_execution':replayed}
            observations.append(item);self.last_recheck_trace.append(item)
        updated=deepcopy(dict(context));updated['independent_source_rechecks']=observations
        updated['recheck_contract']='Rechecks verify source/context of existing records. They are not new EvidenceRecord IDs and cannot by themselves establish supported/challenged claims. Request Investigator follow-up to formally acquire new evidence.'
        return super().audit_evidence(updated)
