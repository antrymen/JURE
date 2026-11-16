"""Read-only frozen clue queries and revisioned Case File commands."""
from .contracts import Outcome, Status, ToolFailure
from .registry import digest
from jure.casefile.critic_models import CRITIC_COLLECTIONS

class CaseFileTool:
    def __init__(self,store): self.store=store
    def bind_registry(self,registry): self.registry=registry
    def execute(self,q,ctx):
        if q.case_id!=ctx.case_id: raise PermissionError('cross-case access')
        case=self.store.load_case(q.case_id).model_dump(mode='json')
        if q.operation=='append_record': return self.append(q,ctx)
        sections={'history':'investigation_history','get_evidence':'evidence_records','get_hypotheses':'hypotheses','get_audits':'critic_audits'}
        if q.operation=='read_case': result={'case':case}
        else:
            section=q.section if q.operation=='read_section' else sections[q.operation]
            if section not in case: raise ValueError('unknown case section')
            result={section:case[section]}
        return Outcome(result=result,record_ids=[q.case_id],provenance={'case_revision':case['metadata']['case_revision'],
            'snapshot_sha256':digest(case),'upstream_source_ids':[f'case:{q.case_id}']})

    def append(self,q,ctx):
        if q.expected_revision is None or q.record is None: raise ValueError('record and expected_revision required')
        actor='evidence_investigator' if ctx.actor=='investigator' else ctx.actor
        args={'actor':actor,'expected_revision':q.expected_revision}; record=dict(q.record)
        typed={'mechanistic_question':('explorer','add_mechanistic_question'),
            'prediction':('explorer','add_prediction'),'evidence_question':(('explorer','investigator'),'add_evidence_question'),
            'evidence_gap':('investigator','add_evidence_gap'),'evidence_record':('investigator','add_evidence_record')}
        if q.record_type in typed:
            role,method=typed[q.record_type]
            if ctx.actor not in ((role,) if isinstance(role,str) else role): raise PermissionError('write ownership')
            if q.record_type=='evidence_record': record=self.prepare_evidence(record,q.envelope_query_id,ctx)
            updated=getattr(self.store,method)(q.case_id,record,**args)
        elif q.record_type=='hypothesis':
            if ctx.actor!='explorer': raise PermissionError('write ownership')
            updated=self.store.add_hypothesis(q.case_id,**record,**args)
        elif q.record_type=='tool_action':
            if ctx.actor not in ('investigator','critic'): raise PermissionError('write ownership')
            env=self.registry.get_envelope(q.envelope_query_id)
            if env.context.case_id!=ctx.case_id or env.context.actor!=ctx.actor: raise PermissionError('trace ownership')
            updated=self.store.append_history_event(q.case_id,summary='Recorded tool acquisition',
                metadata={'query_id':env.query_id,'envelope_reference':self.registry.put_artifact(env.model_dump(mode='json'))},
                action='TOOL_ACQUISITION',**args)
        elif q.record_type in CRITIC_COLLECTIONS or q.record_type in ('claims','evidence_gaps','contradictions'):
            if ctx.actor!='critic': raise PermissionError('write ownership')
            updated=self.store.append_critic_records(q.case_id,**{q.record_type:[record]},**args)
        elif q.record_type=='action_state':
            if ctx.actor not in ('investigator','critic'): raise PermissionError('write ownership')
            updated=self.store.set_action_state(q.case_id,record,**args)
        else: raise ValueError('unsupported record_type')
        return Outcome(result={'case_id':q.case_id,'case_revision':updated.metadata.case_revision},
            record_ids=[q.case_id],provenance={'case_revision':updated.metadata.case_revision,'operation':'append_only_command'})

    def prepare_evidence(self,record,query_id,ctx):
        if not query_id: raise ValueError('EvidenceRecord requires an acquired envelope_query_id')
        env=self.registry.get_envelope(query_id)
        if env.context.case_id!=ctx.case_id: raise PermissionError('cross-case evidence')
        if self.registry.mode=='REAL' and env.source_mode!='REAL': raise PermissionError('mock evidence rejected')
        if env.status not in (Status.OK,Status.TRUNCATED,Status.INSUFFICIENT_SUPPORT): raise ValueError('failed tool result cannot be evidence')
        if env.tool_name not in ('data_experiment','knowledge_graph','gene_knowledge','literature'): raise ValueError('not an evidence source')
        if env.tool_name=='literature' and env.normalized_query.get('operation')!='retrieve':
            raise ValueError('search hits and unverified extraction are not EvidenceRecords; retrieve first')
        artifact=self.registry.put_artifact(env.model_dump(mode='json'))
        record['source_type']={'data_experiment':'dataset','knowledge_graph':'grn','gene_knowledge':'other','literature':'literature'}[env.tool_name]
        record['provenance']={'source_id':env.source_name,'tool':env.tool_name,'query':env.query_id,
            'parameters':{'evidence_envelope':env.model_dump(mode='json'),'source_class':env.source_type,
                'evidence_independence':env.independence,'source_mode':env.source_mode},'artifact_sha256':artifact['sha256']}
        record['raw_result_reference']=artifact['path'];record['fingerprint']=env.cache['cache_key']
        record['limitations']=list(dict.fromkeys(list(record.get('limitations',[]))+env.limitations))
        if env.status==Status.INSUFFICIENT_SUPPORT: record['support_quality']='insufficient'
        return record

class ClueQueryTool:
    def __init__(self,source,case_aliases=None):
        self.source=source; self.cases={c.case_id:c for c in source.cases}; self.aliases=case_aliases or {}
    def execute(self,q,ctx):
        ref=q.reference_id
        condition=q.condition
        selected=None
        if q.case_id:
            selected=self.cases.get(self.aliases.get(q.case_id,q.case_id))
            if not selected: return Outcome(Status.NO_RESULT,result={'matches':[]})
            ref=selected.reference_id; condition=selected.condition_id
        if q.genes:
            if len(q.genes)!=len(q.states) or len(set(q.genes))!=len(q.genes) or any(s not in (0,1) for s in q.states):
                raise ValueError('invalid signed state')
            query=dict(zip(q.genes,q.states))
            matches=[r.reference_id for r in self.source.references.values() if dict(zip(r.genes,r.states))==query]
            if len(matches)!=1: return Outcome(Status.NO_RESULT,result={'matches':matches})
            ref=matches[0]
        if q.operation in ('get_case_clue','get_condition_association'):
            values=[c.model_dump(mode='json') for c in self.cases.values() if (ref is None or c.reference_id==ref) and (condition is None or c.condition_id==condition)]
        elif q.operation=='get_reference_state':
            values=[r.model_dump(mode='json') for r in self.source.references.values() if r.reference_id==ref]
        elif q.operation=='get_landscape_context':
            values=[g.model_dump(mode='json') for g in self.source.groups.values() if ref is None or ref in g.reference_ids]
        elif q.operation=='get_related_states':
            groups=[g for g in self.source.groups.values() if ref in g.reference_ids]
            ids=set(r for g in groups for r in g.reference_ids)
            values=[self.source.references[r].model_dump(mode='json') for r in sorted(ids)]
        else:
            pool=self.source.landscape.signed_state_contrasts if q.operation=='get_signed_state_contrasts' else self.source.landscape.coresponse_relations
            values=[r.model_dump(mode='json') for r in pool if (ref is None or ref in (r.reference_a,r.reference_b)) and (condition is None or condition in r.shared_candidate_conditions)]
        truncated=len(values)>q.limit
        return Outcome(Status.TRUNCATED if truncated else Status.OK if values else Status.NO_RESULT,
            result={'matches':values[:q.limit],'total_matches':len(values),'returned':min(len(values),q.limit),
                'evidence_level':'DAY6_EXPLORATORY','day8_status':'NOT_PERFORMED'},
            record_ids=[ref] if ref else [],provenance={'verified_files':self.source.checked,
                'upstream_source_ids':['dataset:replogle_k562_essential_day6'],
                'scope':'frozen_reference_and_landscape_read_only'},
            limitations=['Response groups are not pathways. Association is not a mechanism. No evidence-level upgrade.'])
