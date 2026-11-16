"""Production tool contracts. These are acquisition results, never Agent verdicts."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

VERSION = '0.1.0'
CACHE_SCHEMA = 'jure-tool-cache-v1'
QUERY_SEMANTICS = 'signed-detection-v1'
ROLES = ('explorer', 'investigator', 'critic')

def now():
    return datetime.now(timezone.utc).isoformat()

class Status(str, Enum):
    OK='OK'; NO_RESULT='NO_RESULT'; NOT_EVALUABLE='NOT_EVALUABLE'
    UNAVAILABLE='UNAVAILABLE'; SOURCE_ERROR='SOURCE_ERROR'; INVALID_QUERY='INVALID_QUERY'
    INSUFFICIENT_SUPPORT='INSUFFICIENT_SUPPORT'; BUDGET_EXHAUSTED='BUDGET_EXHAUSTED'
    AMBIGUOUS_ENTITY='AMBIGUOUS_ENTITY'; TRUNCATED='TRUNCATED'; NOT_IMPLEMENTED='NOT_IMPLEMENTED'

class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)

class CallContext(StrictModel):
    case_id: str = Field(min_length=1)
    actor: Literal['explorer','investigator','critic']
    stage: str = Field(min_length=1)
    parent_question_id: str | None = None
    purpose: Literal['INVESTIGATION','CRITIC_RECHECK','TOOL_VALIDATION']
    force_requery: bool = False
    requery_reason: str | None = None
    expected_information_gain: str | None = None
    @model_validator(mode='after')
    def check(self):
        if self.force_requery and not (self.requery_reason or '').strip():
            raise ValueError('force_requery requires a reason')
        if self.purpose == 'CRITIC_RECHECK' and self.actor != 'critic':
            raise ValueError('CRITIC_RECHECK requires critic')
        return self

class EvidenceEnvelope(StrictModel):
    schema_version: str = '0.1'
    tool_name: str
    tool_version: str = VERSION
    query_id: str
    raw_query: dict[str, Any]
    normalized_query: dict[str, Any]
    status: Status
    result: dict[str, Any] = Field(default_factory=dict)
    source_type: str
    source_name: str
    source_version: str
    source_record_ids: list[str] = Field(default_factory=list)
    dataset_id: str | None = None
    timestamp: str
    parameters: dict[str, Any]
    provenance: dict[str, Any]
    warnings: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    error: dict[str, Any] | None = None
    context: CallContext
    source_mode: Literal['REAL','TEST']
    cache: dict[str, Any] = Field(default_factory=dict)
    directness: str = 'UNKNOWN'
    independence: dict[str, Any] = Field(default_factory=dict)

class CaseQuery(StrictModel):
    operation: Literal['read_case','read_section','append_record','history','get_evidence','get_hypotheses','get_audits']
    case_id: str
    section: str | None = None
    record_type: str | None = None
    record: dict[str, Any] | None = None
    expected_revision: int | None = Field(default=None, ge=1)
    envelope_query_id: str | None = None

class ClueQuery(StrictModel):
    operation: Literal['get_case_clue','get_reference_state','get_condition_association','get_landscape_context','get_related_states','get_signed_state_contrasts','get_co_response_context']
    case_id: str | None = None
    condition: str | None = None
    reference_id: str | None = None
    genes: list[str] = Field(default_factory=list, max_length=10)
    states: list[int] = Field(default_factory=list, max_length=10)
    limit: int = Field(default=20, ge=1, le=100)

class ExperimentQuery(StrictModel):
    operation: Literal['query'] = 'query'
    mode: Literal['MARGINAL','PAIRWISE','JOINT_STATE','CONDITIONAL','CONDITION_COMPARISON','STATE_CONTRAST']
    condition: str
    state: dict[str,int] = Field(min_length=1, max_length=12)
    conditioning_states: dict[str,int] = Field(default_factory=dict, max_length=12)
    contrast_state: dict[str,int] | None = None
    condition_b: str | None = None
    dataset_id: str = 'replogle_k562_essential_day6'
    min_condition_cells: int = Field(default=100, ge=1)
    min_nt_per_batch: int = Field(default=20, ge=1)
    min_effective_nt: int = Field(default=100, ge=1)
    min_events: int = Field(default=10, ge=1)
    @model_validator(mode='after')
    def check(self):
        for state in [self.state,self.conditioning_states,self.contrast_state or {}]:
            if any(not k.strip() or type(v) is not int or v not in (0,1) for k,v in state.items()):
                raise ValueError('states must map unique gene symbols to integer 0 or 1')
        if self.mode=='MARGINAL' and len(self.state)!=1: raise ValueError('MARGINAL requires one gene')
        if self.mode=='PAIRWISE' and len(self.state)!=2: raise ValueError('PAIRWISE requires two genes')
        if self.mode=='CONDITIONAL':
            if not self.conditioning_states or set(self.state)&set(self.conditioning_states):
                raise ValueError('CONDITIONAL requires disjoint query and conditioning genes')
        elif self.conditioning_states: raise ValueError('conditioning_states only for CONDITIONAL')
        if self.mode=='STATE_CONTRAST':
            if not self.contrast_state or set(self.state)!=set(self.contrast_state) or self.state==self.contrast_state:
                raise ValueError('STATE_CONTRAST requires same genes and different signs')
        elif self.contrast_state: raise ValueError('contrast_state only for STATE_CONTRAST')
        if self.condition_b and self.mode!='CONDITION_COMPARISON': raise ValueError('condition_b only for CONDITION_COMPARISON')
        return self

class GraphQuery(StrictModel):
    operation: Literal['query_entity','query_edge','find_paths','local_subgraph']
    entity: str
    target: str | None = None
    max_hops: int = Field(default=2, ge=1, le=3)
    max_nodes: int = Field(default=30, ge=1, le=100)
    max_edges: int = Field(default=60, ge=1, le=200)
    max_paths: int = Field(default=10, ge=1, le=30)
    relation_types: list[str] = Field(default_factory=list, max_length=30)
    entity_types: list[str] = Field(default_factory=list, max_length=20)

class GeneQuery(StrictModel):
    operation: Literal['get_gene_info','query_gene_sets','query_pathways','query_functional_context']
    gene: str = Field(min_length=1, max_length=80)
    species: Literal['Homo sapiens'] = 'Homo sapiens'
    limit: int = Field(default=20, ge=1, le=50)

class LiteratureQuery(StrictModel):
    operation: Literal['search','retrieve','extract_evidence']
    entities: list[str] = Field(default_factory=list, max_length=10)
    relation: str | None = None
    process: str | None = None
    cell_type: str | None = None
    perturbation: str | None = None
    keywords: list[str] = Field(default_factory=list, max_length=10)
    pmids: list[str] = Field(default_factory=list, max_length=10)
    limit: int = Field(default=5, ge=1, le=20)
    claim: str | None = None
    passages: list[dict[str,Any]] = Field(default_factory=list, max_length=10)
    @model_validator(mode='after')
    def check(self):
        if self.operation=='search' and not self.entities and not self.keywords: raise ValueError('search requires entities or keywords')
        if self.operation!='search' and (not self.pmids or any(not p.isdigit() for p in self.pmids)): raise ValueError('valid PMIDs required')
        return self

class TNQuery(StrictModel):
    operation: Literal['query'] = 'query'
    query: dict[str,Any]

@dataclass
class Outcome:
    status: Status = Status.OK
    result: dict = field(default_factory=dict)
    record_ids: list = field(default_factory=list)
    provenance: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)
    limitations: list = field(default_factory=list)
    error: dict | None = None

class ToolFailure(Exception):
    def __init__(self, status, code, message, details=None):
        self.status=Status(status); self.code=code; self.message=message; self.details=details or {}
        super().__init__(message)
