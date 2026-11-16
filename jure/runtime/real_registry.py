"""Existing Investigator dispatch API backed exclusively by real envelopes."""
from copy import deepcopy
from datetime import datetime
import json
from types import SimpleNamespace
from jure.tools.evidence.base import ToolExecutionResult,ToolMetadata
from jure.tools.real.contracts import Status
from jure.tools.real.registry import digest
from jure.casefile.models import EvidenceRecord,Provenance,new_id
from jure.agents.investigator.evidence_normalizer import NormalizedEvidence,NETWORK_LIMITATION,DATASET_LIMITATION

FAMILIES={'data_experiment':'dataset','knowledge_graph':'network','literature':'literature','gene_knowledge':'other','clue_query':'other'}

class RealInvestigatorRegistry:
    native_envelopes=True
    def __init__(self,registry,case_id):
        if registry.mode!='REAL':raise ValueError('Production adapter requires REAL registry')
        self.registry=registry;self.case_id=case_id;self.question_id=None;self.stage='INVESTIGATION';self.last_envelope=None;self.recent=[]
    def set_context(self,*,question_id,stage):self.question_id=question_id;self.stage=stage
    def metadata_snapshot(self):
        rows=[]
        for name,family in FAMILIES.items():
            s=self.registry.specs[name];schema=s.input_model.model_json_schema();op=schema['properties']['operation']
            canonical=op.get('enum',[op.get('const')]);operations=canonical+[name+'.'+o for o in canonical];required=[x for x in schema.get('required',[]) if x!='operation']
            rows.append(dict(tool_id=name,tool_type=family,version='0.1.0',capabilities=operations,
                required_inputs={o:required for o in operations},cost_class='medium' if name in ('literature','gene_knowledge') else 'low',
                availability='unavailable' if name in self.registry.disabled or s.availability in ('UNAVAILABLE','NOT_IMPLEMENTED') else 'available',
                description=s.description,input_schema=schema,limitations=s.limitations,
                output_contract='EvidenceEnvelope. Search hits are not evidence; select and retrieve relevant PMIDs in an Agent-authored subsequent plan.',
                when_to_use=s.when_to_use,when_not_to_use=s.when_not_to_use))
        return rows
    def get_tool(self,name):
        row=next((r for r in self.metadata_snapshot() if r['tool_id']==name),None)
        if row is None:return None
        keys=ToolMetadata.model_fields
        return SimpleNamespace(metadata=ToolMetadata.model_validate({k:v for k,v in row.items() if k in keys}))
    def get_tools_for_evidence_type(self,family):
        return tuple(self.get_tool(r['tool_id']) for r in self.metadata_snapshot() if r['tool_type']==family)
    def execute(self,tool_id,operation,inputs):
        if operation.startswith(tool_id+'.'):
            operation=operation[len(tool_id)+1:]
        query=dict(inputs)
        if 'operation' in query and query['operation']!=operation:raise ValueError('Conflicting operation fields')
        query['operation']=operation
        env=self.registry.bind('investigator',self.case_id,stage=self.stage).call(tool_id,query,parent_question_id=self.question_id)
        self.last_envelope=env
        status={Status.OK:'success',Status.TRUNCATED:'success',Status.NO_RESULT:'no_result',Status.INSUFFICIENT_SUPPORT:'insufficient_data'}.get(env.status,'failed')
        payload=env.model_dump(mode='json')
        # Complete raw acquisition is persisted by the real registry. Transport
        # carries the result and essential provenance, not a repeated file manifest.
        compact=compact_envelope(payload)
        self.recent.append(compact)
        return ToolExecutionResult(status=status,tool_id=tool_id,tool_version=env.tool_version,operation=operation,
            parameters=inputs,payload={'evidence_envelope':compact},warnings=tuple(env.warnings),
            failure_reason=None if status=='success' else env.status.value,
            started_at=datetime.fromisoformat(env.timestamp),completed_at=datetime.now().astimezone())
    def context_snapshot(self):
        return deepcopy(self.recent[-12:])
    def normalize_result(self,question,result,raw,case,config,run_id,family):
        env=self.registry.get_envelope(result.payload['evidence_envelope']['query_id'])
        if env.source_mode!='REAL' or env.context.case_id!=case.metadata.case_id:raise ValueError('Cross-case or test evidence rejected')
        if env.status not in (Status.OK,Status.TRUNCATED,Status.INSUFFICIENT_SUPPORT):
            return NormalizedEvidence(gap=f'{env.tool_name}: {env.status.value}; no observation sufficient to answer the question was obtained.')
        if env.tool_name=='literature' and env.normalized_query['operation']!='retrieve':
            # Search results remain available in ToolResult for the Investigator
            # to choose retrieval. No automatic paper selection or record creation.
            return NormalizedEvidence(question_status='partially_answered',gap='Search located candidate references; paper retrieval and claim/context inspection remain necessary.')
        artifact=self.registry.put_artifact(env.model_dump(mode='json'))
        payload=compact_envelope(env.model_dump(mode='json'))
        items=env.result.get('articles',[]) if env.tool_name=='literature' else [env.result]
        records=[]
        for item in items:
            source_type={'data_experiment':'dataset','knowledge_graph':'grn','literature':'literature'}.get(env.tool_name,'other')
            details={'actor':'evidence_investigator','run_id':run_id,'question_id':question.question_id,
                'execution_status':result.status,'query_parameters':env.normalized_query,'query_id':env.query_id,
                'source_mode':'REAL','source_class':env.source_type,'source_version':env.source_version,
                'source_record_ids':env.source_record_ids,'source_independence':env.independence,
                'tool_result':item,'envelope_reference':artifact,'envelope_metadata':{k:v for k,v in payload.items() if k!='result'}}
            if source_type=='dataset':details['dataset']={'dataset_id':env.dataset_id,'statistics_location':'provenance.parameters.tool_result','support_evaluation':env.status.value}
            if source_type=='literature':details['literature']={'pmid':item['pmid'],'retrieval_scope':'ABSTRACT_ONLY','experimental_design_assessed':False}
            if source_type=='grn':details['query_answer_complete']=False
            limitations=list(env.limitations)
            if source_type=='grn':limitations.append(NETWORK_LIMITATION)
            if source_type=='dataset':limitations.append(DATASET_LIMITATION)
            summary=(f"Retrieved PubMed {item['pmid']}: {item['title']}. Abstract is available for claim-level audit; experimental design/context not classified by the retrieval tool."
                if source_type=='literature' else f"{env.tool_name} returned {env.status.value} for the recorded query. The measured/curated result is in provenance.tool_result; no mechanistic conclusion is assigned.")
            records.append(EvidenceRecord(question_id=question.question_id,claim_tested=question.question_text,
                result_summary=summary,source_type=source_type,directness='indirect' if source_type=='dataset' else 'contextual',
                context_match='matched' if source_type=='dataset' else 'unknown',
                source_quality='primary_experiment' if source_type=='dataset' else 'curated_database' if source_type in ('grn','other') else 'unknown',
                support_quality='insufficient' if env.status==Status.INSUFFICIENT_SUPPORT else 'sufficient' if source_type=='dataset' else 'limited',
                fingerprint=digest({'query':env.cache['cache_key'],'record':item.get('pmid') if source_type=='literature' else None}),
                limitations=tuple(dict.fromkeys(limitations)),provenance=Provenance(source_id=env.source_name,
                    source_uri=item['source_url'] if source_type=='literature' else None,tool=env.tool_name,query=env.query_id,
                    parameters=details,artifact_sha256=artifact['sha256']),raw_result_reference=artifact['path'],created_by='evidence_investigator'))
        return NormalizedEvidence(records=records,question_status='partially_answered',
            gap='Acquisition completed; the broader mechanistic prediction still requires claim-level interpretation and discriminating evidence.')

def compact_envelope(env):
    env=deepcopy(env)
    p=env.get('provenance',{})
    for key in ('verified_files','store_manifest'):
        if key in p:p[key]={'manifest_sha256':digest(p[key]),'full_provenance_location':'original envelope artifact'}
    return env
