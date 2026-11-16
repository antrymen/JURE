"""Resume an interrupted stage from immutable paid responses/acquisitions.

A strict ordered prefix, not a similarity cache. No model/tool budget refund.
Once the prefix is consumed, normal live execution and original limits apply.
"""
import json
from pathlib import Path
from .real_registry import RealInvestigatorRegistry
from jure.tools.real.contracts import EvidenceEnvelope
from jure.tools.real.registry import file_sha
from jure.tools.evidence.base import ToolExecutionResult

class SavedPrefixProvider:
    def __init__(self,provider,manifest):
        self.provider=provider;self.remaining=list(manifest['responses']);self.replayed=[]
    def __getattr__(self,name):return getattr(self.provider,name)
    def __call__(self,request,*,role):
        if not self.remaining:return self.provider(request,role=role)
        row=self.remaining[0]
        if role!=row.get('role','investigator') or request.get('method',request.get('mode'))!=row['method']:
            raise ValueError('Saved response prefix diverged; no paid fallback')
        p=Path(row['path'])
        if file_sha(p)!=row['sha256']:raise ValueError('Saved response changed')
        self.remaining.pop(0);self.replayed.append(row)
        # The original bytes are re-normalized under the new interface.
        return json.loads(p.read_text())['content']

class HistoricalEnvelopeRegistry:
    def __init__(self,registry,envelopes):self.registry=registry;self.envelopes=envelopes
    def __getattr__(self,name):return getattr(self.registry,name)
    def get_envelope(self,query_id):
        if query_id in self.envelopes:return self.envelopes[query_id]
        return self.registry.get_envelope(query_id)

class SavedPrefixBinding(RealInvestigatorRegistry):
    def __init__(self,registry,case_id,manifest):
        envelopes={}
        for row in manifest['envelopes']:
            if file_sha(row['path'])!=row['sha256']:raise ValueError('Saved evidence changed')
            env=EvidenceEnvelope.model_validate_json(Path(row['path']).read_text())
            if env.source_mode!='REAL' or env.context.case_id!=case_id:raise ValueError('Invalid saved evidence source')
            envelopes[env.query_id]=env
        super().__init__(HistoricalEnvelopeRegistry(registry,envelopes),case_id)
        self.remaining=list(manifest['tools']);self.replayed=[]
    def execute(self,tool_id,operation,inputs):
        if not self.remaining:return super().execute(tool_id,operation,inputs)
        row=self.remaining[0]
        if file_sha(row['path'])!=row['sha256']:raise ValueError('Saved raw tool result changed')
        result=ToolExecutionResult.model_validate_json(Path(row['path']).read_text())
        if (result.tool_id!=tool_id or result.operation!=operation.removeprefix(tool_id+'.')
                or result.parameters.to_dict()!=inputs or row['question_id']!=self.question_id):
            raise ValueError('Saved tool prefix diverged; no acquisition fallback')
        self.remaining.pop(0);self.replayed.append(row)
        self.recent.append(result.payload.to_dict()['evidence_envelope'])
        return result
