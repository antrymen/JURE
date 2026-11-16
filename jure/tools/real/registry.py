"""One registry for role-scoped acquisition, budgets, cache, artifacts and traces."""
from __future__ import annotations
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import resource
import sqlite3
import sys
import threading
import time
import uuid
from pydantic import ValidationError
from .contracts import (VERSION, CACHE_SCHEMA, QUERY_SEMANTICS, CallContext,
    EvidenceEnvelope, Status, Outcome, ToolFailure, now)


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)

def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()

def file_sha(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for part in iter(lambda:f.read(1024*1024),b''): h.update(part)
    return h.hexdigest()

@dataclass
class ToolSpec:
    name: str
    description: str
    input_model: type
    backend: object
    allowed_agents: tuple
    data_source: str
    source_version: str
    source_type: str
    availability: str
    dataset_id: str | None = None
    limitations: list = field(default_factory=list)
    examples: list = field(default_factory=list)
    when_to_use: str = ''
    when_not_to_use: str = ''
    implementation_sha256: str = ''

    def card(self):
        return dict(tool_name=self.name,tool_version=VERSION,implementation_sha256=self.implementation_sha256,description=self.description,
            input_schema=self.input_model.model_json_schema(),output_schema=EvidenceEnvelope.model_json_schema(),
            allowed_agents=self.allowed_agents,data_source=self.data_source,source_version=self.source_version,
            source_type=self.source_type,dataset_id=self.dataset_id,availability=self.availability,
            provenance_policy='Source identifiers, original retrieval time, hashes and query retained; no inference added.',
            error_policy='Structured status; no mock fallback; no failure upgraded to evidence.',
            when_to_use=self.when_to_use,when_not_to_use=self.when_not_to_use,
            example_queries=self.examples,limitations=self.limitations)

class ToolRegistry:
    """Host binds the role. Model-generated arguments cannot choose actor or mode.

    Registry lock serializes counters and source requests in this process. SQLite
    BEGIN IMMEDIATE additionally protects budgets across host processes.
    """
    def __init__(self, root, *, run_id, mode='REAL', budgets=None, disabled_tools=()):
        if mode not in ('REAL','TEST'): raise ValueError('mode must be REAL or TEST')
        self.root=Path(root); self.root.mkdir(parents=True,exist_ok=True)
        self.run_id=run_id; self.mode=mode; self.disabled=set(disabled_tools); self.specs={}; self.lock=threading.RLock()
        self.budgets={'total':120,'literature':30,'knowledge_graph':20,'data_experiment':40,**(budgets or {})}
        self.db=sqlite3.connect(self.root/'tool_state.sqlite',isolation_level=None,check_same_thread=False)
        self.db.row_factory=sqlite3.Row
        self.db.executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS cache(key TEXT PRIMARY KEY, mode TEXT NOT NULL, envelope TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS traces(query_id TEXT PRIMARY KEY,run_id TEXT,case_id TEXT,actor TEXT,tool TEXT,payload TEXT,envelope TEXT);
        CREATE TABLE IF NOT EXISTS counters(run_id TEXT,case_id TEXT,tool TEXT,n INTEGER,PRIMARY KEY(run_id,case_id,tool));
        ''')

    def register(self,spec):
        if spec.name in self.specs: raise ValueError('duplicate tool')
        if self.mode=='REAL' and getattr(spec.backend,'source_mode','REAL')!='REAL': raise ValueError('test backend cannot enter real registry')
        spec.implementation_sha256=digest({str(p):file_sha(p) for root in (Path(__file__).parent,Path(__file__).parents[2]/'integrations') for p in sorted(root.glob('*.py'))})
        self.specs[spec.name]=spec
        if hasattr(spec.backend,'bind_registry'): spec.backend.bind_registry(self)

    def snapshot(self,path=None):
        result=dict(registry_version=VERSION,run_id=self.run_id,mode=self.mode,timestamp=now(),
            cache_schema=CACHE_SCHEMA,query_semantics=QUERY_SEMANTICS,budgets=self.budgets,
            disabled_tools=sorted(self.disabled),tools=[s.card() for s in self.specs.values()],
            execution_policy='No prescribed tool order; role selects queries. No Agent execution in validation.')
        result['snapshot_sha256']=digest(result)
        if path: Path(path).write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n')
        return result

    def bind(self,actor,case_id,*,stage,purpose='INVESTIGATION'):
        return ToolClient(self,actor,case_id,stage,purpose)

    def put_artifact(self,payload):
        body=canonical(payload); checksum=hashlib.sha256(body.encode()).hexdigest()
        path=self.root/'artifacts'/f'{checksum}.json'; path.parent.mkdir(parents=True,exist_ok=True)
        if not path.exists(): path.write_text(body)
        return {'path':str(path.resolve()),'sha256':checksum,'bytes':len(body.encode())}

    def get_envelope(self,query_id):
        row=self.db.execute('SELECT envelope FROM traces WHERE query_id=?',(query_id,)).fetchone()
        if not row: raise ValueError('unknown tool query ID')
        return EvidenceEnvelope.model_validate_json(row[0])

    def _spend(self,case_id,tool):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            counts={r['tool']:r['n'] for r in self.db.execute('SELECT tool,n FROM counters WHERE run_id=? AND case_id=?',(self.run_id,case_id))}
            if sum(counts.values())>=self.budgets['total'] or counts.get(tool,0)>=self.budgets.get(tool,self.budgets['total']):
                self.db.execute('ROLLBACK'); return False
            self.db.execute('INSERT INTO counters VALUES(?,?,?,1) ON CONFLICT(run_id,case_id,tool) DO UPDATE SET n=n+1',(self.run_id,case_id,tool))
            self.db.execute('COMMIT'); return True
        except BaseException:
            self.db.execute('ROLLBACK'); raise

    def execute(self,tool_name,query,context):
        # A validated trusted host context is required, including for invalid calls.
        context=CallContext.model_validate(context)
        with self.lock:
            return self._execute(tool_name,query,context)

    def _execute(self,tool_name,query,ctx):
        started=now(); clock=time.monotonic(); cpu=time.process_time(); qid='TQ_'+uuid.uuid4().hex
        spec=self.specs.get(tool_name); normalized={}; cache_key=None; cached=None
        source_executed=False; duplicate_of=None
        try:
            if spec is None: raise ToolFailure(Status.INVALID_QUERY,'UNKNOWN_TOOL','Unknown tool')
            if ctx.actor not in spec.allowed_agents: raise ToolFailure(Status.INVALID_QUERY,'ROLE_DENIED','Role cannot call this tool')
            parsed=spec.input_model.model_validate(query)
            if hasattr(spec.backend,'normalize'): parsed=spec.backend.normalize(parsed)
            normalized=parsed.model_dump(mode='json')
            if tool_name in self.disabled: raise ToolFailure(Status.UNAVAILABLE,'TOOL_DISABLED','Tool disabled in this run')
            if not self._spend(ctx.case_id,tool_name): raise ToolFailure(Status.BUDGET_EXHAUSTED,'BUDGET_EXHAUSTED','Per-case tool budget exhausted')
            # Case reads are mutable and writes have effects. Never cache either.
            cacheable=tool_name not in ('case_file','tn_query')
            cache_key=digest(dict(tool=tool_name,version=VERSION,implementation=spec.implementation_sha256,source_version=spec.source_version,
                dataset=spec.dataset_id,cache_schema=CACHE_SCHEMA,semantics=QUERY_SEMANTICS,mode=self.mode,query=normalized))
            row=self.db.execute('SELECT envelope FROM cache WHERE key=? AND mode=?',(cache_key,self.mode)).fetchone() if cacheable else None
            prior=EvidenceEnvelope.model_validate_json(row[0]) if row else None
            duplicate_of=prior.query_id if prior else None
            if prior and not ctx.force_requery:
                cached=prior
                outcome=Outcome(prior.status,prior.result,prior.source_record_ids,prior.provenance,prior.warnings,prior.limitations,prior.error)
            else:
                source_executed=True
                outcome=spec.backend.execute(parsed,ctx)
                if not isinstance(outcome,Outcome): raise TypeError('backend must return Outcome')
                canonical(outcome.result)  # Reject NaN/non-JSON payloads inside the traced failure boundary.
        except ToolFailure as e:
            outcome=Outcome(e.status,error={'code':e.code,'message':e.message,'details':e.details},provenance=e.details)
        except ValidationError as e:
            outcome=Outcome(Status.INVALID_QUERY,error={'code':'SCHEMA_VALIDATION','message':'Query schema validation failed','fields':[list(x['loc']) for x in e.errors()]})
        except PermissionError:
            outcome=Outcome(Status.INVALID_QUERY,error={'code':'ROLE_DENIED','message':'Operation not permitted for bound role'})
        except (ValueError,KeyError) as e:
            # No untrusted exception contents/credentials are copied into traces.
            outcome=Outcome(Status.INVALID_QUERY,error={'code':type(e).__name__,'message':'Invalid identity, revision, record or parameters'})
        except Exception as e:
            outcome=Outcome(Status.SOURCE_ERROR,error={'code':type(e).__name__,'message':'Backend failed; no replacement evidence generated'})
        source_type=spec.source_type if spec else 'BACKGROUND_SOURCE'
        upstream=outcome.provenance.get('upstream_source_ids',outcome.record_ids)
        envelope=EvidenceEnvelope(tool_name=tool_name,query_id=qid,raw_query=query if isinstance(query,dict) else {'invalid_raw_input':query},normalized_query=normalized,
            status=outcome.status,result=outcome.result,source_type=source_type,
            source_name=spec.data_source if spec else 'unknown',source_version=spec.source_version if spec else 'unknown',
            source_record_ids=outcome.record_ids,dataset_id=spec.dataset_id if spec else None,
            timestamp=cached.timestamp if cached else now(),parameters=normalized,
            provenance={**outcome.provenance,'tool_code_version':VERSION,'source_executed':source_executed},
            warnings=outcome.warnings,limitations=list(dict.fromkeys((spec.limitations if spec else [])+outcome.limitations)),
            error=outcome.error,context=ctx,source_mode=self.mode,
            cache=dict(cache_hit=bool(cached),cache_key=cache_key,cache_record_id=cache_key,cache_schema_version=CACHE_SCHEMA,duplicate_of=duplicate_of,
                original_query_id=cached.query_id if cached else None,force_requery=ctx.force_requery,
                requery_reason=ctx.requery_reason,original_timestamp=cached.timestamp if cached else None),
            independence=dict(upstream_source_ids=upstream,independent_confirmation=False,
                reason='Re-query verifies acquisition; shared datasets/publications do not become independent evidence.'))
        payload=envelope.model_dump(mode='json')
        artifact=self.put_artifact(payload)
        elapsed=time.monotonic()-clock
        trace=dict(query_id=qid,run_id=self.run_id,case_id=ctx.case_id,actor=ctx.actor,stage=ctx.stage,
            parent_question_id=ctx.parent_question_id,purpose=ctx.purpose,tool_name=tool_name,
            tool_version=VERSION,query=normalized,implementation_sha256=spec.implementation_sha256 if spec else None,started_at=started,completed_at=now(),latency_seconds=elapsed,
            cpu_seconds=time.process_time()-cpu,peak_rss_native_units=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            peak_rss_unit='bytes' if sys.platform=='darwin' else 'KiB',
            status=envelope.status.value,cache_hit=bool(cached),source_executed=source_executed,
            error=envelope.error,source_version=envelope.source_version,source_type=source_type,
            result_reference=artifact,cache_key=cache_key,expected_information_gain=ctx.expected_information_gain,
            observed_impact='UNKNOWN',tokens=0,llm_cost=0,source_cost=None)
        self.db.execute('INSERT INTO traces VALUES(?,?,?,?,?,?,?)',(qid,self.run_id,ctx.case_id,ctx.actor,tool_name,canonical(trace),canonical(payload)))
        if not cached and cache_key and tool_name not in ('case_file','tn_query') and outcome.status in (Status.OK,Status.NO_RESULT,Status.TRUNCATED):
            self.db.execute('INSERT OR REPLACE INTO cache VALUES(?,?,?)',(cache_key,self.mode,canonical(payload)))
        return envelope

    def export_traces(self,path):
        rows=self.db.execute('SELECT payload FROM traces WHERE run_id=? ORDER BY rowid',(self.run_id,)).fetchall()
        Path(path).write_text(''.join(r[0]+'\n' for r in rows))
        return len(rows)

    def gap_for(self,envelope):
        if envelope.status in (Status.OK,Status.TRUNCATED): raise ValueError('successful acquisition does not itself establish a gap')
        return dict(description=f'{envelope.tool_name}: {envelope.status.value}',reason=envelope.error['code'] if envelope.error else envelope.status.value,
            related_question_ids=[envelope.context.parent_question_id] if envelope.context.parent_question_id else [],
            resolvable_with_current_tools=None,status='open')

class ToolClient:
    def __init__(self,registry,actor,case_id,stage,purpose):
        self.registry=registry; self.context=CallContext(actor=actor,case_id=case_id,stage=stage,purpose=purpose)
    def cards(self):
        return [s.card() for s in self.registry.specs.values() if self.context.actor in s.allowed_agents]
    def call(self,tool,query,*,parent_question_id=None,force_requery=False,requery_reason=None,expected_information_gain=None):
        ctx=self.context.model_copy(update=dict(parent_question_id=parent_question_id,force_requery=force_requery,
            requery_reason=requery_reason,expected_information_gain=expected_information_gain))
        return self.registry.execute(tool,query,CallContext.model_validate(ctx.model_dump()))
    def read_artifact(self,reference):
        path=Path(reference['path']).resolve()
        if path.parent!=(self.registry.root/'artifacts').resolve():raise PermissionError('Artifact outside this run')
        if file_sha(path)!=reference['sha256']:raise ValueError('Artifact hash mismatch')
        return json.loads(path.read_text())
    def compact(self,envelope):
        """Machine-facing result references large payloads; never silently loses the source."""
        artifact=self.registry.put_artifact(envelope.model_dump(mode='json'))
        body=envelope.model_dump(mode='json')
        if len(canonical(body['result']))>16000:
            body['result']={'artifact_reference':artifact,'summary':'Payload exceeds inline limit; read the hashed artifact for full results.'}
        return body
