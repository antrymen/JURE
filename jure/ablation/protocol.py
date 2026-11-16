"""Pure protocol logic; no model calls or historical report loading."""
from dataclasses import dataclass
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

MODEL = 'gpt-5.6-luna'
ARMS = ('full', 'without_critic', 'single')
class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')
class Hypothesis(Strict):
    id: str
    statement: str
    status: Literal['supported','partially_supported','insufficient','challenged']
class Claim(Strict):
    id: str
    hypothesis_id: str
    statement: str
    evidence_ids: list[str]
    limitation: str
class Evidence(Strict):
    id: str
    query_id: str
    source_locator: str
    finding: str
    context: str
class Gap(Strict):
    category: Literal['direct_experiment','context_transfer','alternative_explanation','causal_validation']
    description: str
class Prediction(Strict):
    hypothesis_id: str
    intervention: str
    observable_outcome: str
class FinalReport(Strict):
    case_id: str
    author: Literal['single','investigator','critic']
    hypotheses: list[Hypothesis]
    claims: list[Claim]
    evidence: list[Evidence]
    gaps: list[Gap]
    predictions: list[Prediction]
    stop_reason: str
    @model_validator(mode='after')
    def references(self):
        for records in [self.hypotheses,self.claims,self.evidence]:
            ids=[r.id for r in records]
            if len(set(ids))!=len(ids): raise ValueError('duplicate ID')
        hs={h.id for h in self.hypotheses}; es={e.id for e in self.evidence}
        for c in self.claims:
            if c.hypothesis_id not in hs or not set(c.evidence_ids)<=es:
                raise ValueError('dangling claim reference')
        if any(p.hypothesis_id not in hs for p in self.predictions):
            raise ValueError('dangling prediction reference')
        return self

@dataclass
class Budget:
    input_limit: int = 100000
    output_limit: int = 25000
    call_limit: int = 30
    tool_limit: int = 30
    input_tokens: int = 0
    output_tokens: int = 0
    calls: int = 0
    tool_calls: int = 0
    usage_complete: bool = True
    pending: bool = False
    def reserve(self, exact_input_tokens, max_output_tokens):
        if not self.usage_complete or self.pending: raise RuntimeError('usage unresolved')
        if min(exact_input_tokens,max_output_tokens)<0: raise ValueError('negative reservation')
        if (self.calls>=self.call_limit or self.input_tokens+exact_input_tokens>self.input_limit
            or self.output_tokens+max_output_tokens>self.output_limit):
            raise RuntimeError('budget exhausted')
        self.calls+=1;self.pending=True
    def settle(self, usage):
        if not self.pending: raise RuntimeError('no pending request')
        self.pending=False
        if not usage or any(type(usage.get(k)) is not int or usage[k]<0 for k in ('input_tokens','output_tokens')):
            self.usage_complete=False
            raise RuntimeError('usage missing; stop run, do not assume zero')
        self.input_tokens+=usage['input_tokens'];self.output_tokens+=usage['output_tokens']
        if self.input_tokens>self.input_limit or self.output_tokens>self.output_limit:
            raise RuntimeError('provider usage exceeded budget; invalidate run')
    def spend_tool(self):
        if self.tool_calls>=self.tool_limit: raise RuntimeError('tool budget exhausted')
        self.tool_calls+=1

class Controller:
    """Only explicit handoffs; no scientific verdicts implemented in host."""
    def __init__(self, arm):
        if arm not in ARMS: raise ValueError('unknown arm')
        self.arm=arm;self.actor='single' if arm=='single' else 'explorer'
        self.events=[];self.stopped=False
    def handoff(self,target,reason):
        if self.stopped: raise ValueError('run stopped')
        transitions={
            'full':{'explorer':{'critic'},'critic':{'explorer','investigator','STOP'},'investigator':{'critic'}},
            'without_critic':{'explorer':{'investigator'},'investigator':{'STOP'}},
            'single':{'single':{'STOP'}}}
        if target not in transitions[self.arm][self.actor]: raise ValueError('illegal handoff')
        if not reason.strip(): raise ValueError('handoff requires reason')
        event={'event_id':len(self.events)+1,'actor':self.actor,'target':target,'reason':reason,'type':'handoff_executed'}
        self.events.append(event)
        if target=='STOP':self.stopped=True
        else:self.actor=target
        return event
    def validate_report(self,report,executed_query_ids):
        r=FinalReport.model_validate(report)
        expected={'full':'critic','without_critic':'investigator','single':'single'}[self.arm]
        if self.actor!=expected or r.author!=expected:raise ValueError('wrong report author')
        if any(e.query_id not in executed_query_ids for e in r.evidence):raise ValueError('unknown tool query')
        return r

def whitelist(case,slot):
    c=case['clue'];p=c['pattern'];s=c['perturbation_shift']
    # Explicit nested whitelist: never include mechanistic_question, triage or historical roles.
    keys=('control_frequency','perturb_frequency','delta_frequency','control_count',
          'perturb_count','perturbation_n','pooled_nt_n','matched_nt_effective_n',
          'control_frequency_definition','control_count_scope','p_value_shift',
          'selected_family_holm_exploratory','family_size','statistical_method','inference_scope')
    return {'slot':slot,'dataset':'replogle_k562_essential_day6','cell_type':'K562',
            'perturbation':c['perturbation'],'reference_id':c['reference_id'],
            'state':dict(zip(p['genes'],p['states'])),
            'statistics':{k:s[k] for k in keys if k in s},
            'boundary':'Detection states, not repression; exploratory association, not a confirmed mechanism.'}
