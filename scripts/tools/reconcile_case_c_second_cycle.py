"""One bounded Critic semantic patch for its own inconsistent C1/attribution.

No Explorer changes, evidence queries, fabricated judgments or budget refund.
The Critic may retain a blocking C1 decision or classify its warnings as nonblocking.
"""
import getpass
import json
from pathlib import Path
import sys
from typing import Literal
from pydantic import BaseModel, ConfigDict

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from jure.llm.glm import GLMConfig, GLMTransport
from jure.agents.critic.backend import SYSTEM_INSTRUCTIONS
from jure.agents.critic.validation import validate_hypothesis_audit
from jure.casefile import load_case
from jure.casefile.critic_models import HypothesisAuditResult, FailureAttribution
from jure.runtime.pilot import save
from jure.tools.real.registry import file_sha


class ReviewPatch(BaseModel):
    model_config=ConfigDict(extra='forbid')
    c1_overall_status: Literal['pass','revision_required']
    c1_audit_summary: str
    attribution_reason_type: Literal['hypothesis_problem','prediction_problem','evidence_question_problem','evidence_quality_problem','hypothesis_space_inadequate','evidence_missing','evidence_conflict','tool_limit','no_problem']
    attribution_hypothesis_space_problem: bool
    attribution_reason_summary: str
    reconciliation_reason: str


def main():
    base=Path('outputs/case_c_second_cycle_20260929')
    source=base/'run_002/C'
    target=base/'critic_reconciliation'
    target.mkdir(exist_ok=False)
    audit_path=source/'model_calls/call_0009_critic/structured_output.json'
    failure_path=source/'model_calls/call_0010_critic/structured_output.json'
    audit=json.loads(audit_path.read_text());failure=json.loads(failure_path.read_text())
    summary=json.loads((source/'case_run_summary.json').read_text())
    assert summary['cumulative_model_calls']==38 and not summary['completed']
    assert audit['overall_status']=='revision_required' and failure['reason_type']=='evidence_missing'
    cfg=GLMConfig.model_validate_json(Path('configs/agent_runtime_glm53_flash.json').read_text()).model_copy(update={'max_calls':1})
    key=getpass.getpass('GLM API key (hidden): ')
    provider=GLMTransport(config=cfg,api_key=key,trace_dir=target/'model_calls')
    del key
    payload={
        'method':'reconcile_c1_attribution',
        'system_instructions':SYSTEM_INSTRUCTIONS+'\nThis is a narrowly scoped semantic repair of your own two inconsistent outputs. Return only the requested decision/summary patch; no hypothesis rewrite, no new evidence, no tool selection.',
        'context':{
            'previous_c1':audit,'previous_failure_attribution':failure,
            'conflict':'C1 says revision_required, but attribution says no hypothesis-space problem remains and the problem is evidence_missing. These cannot both describe a C1-blocking design defect under this protocol.',
            'decision_boundary':'Decide whether the already listed issues are genuinely blocking hypothesis/prediction design defects or nonblocking evidence/capability limitations. Both outcomes are allowed. If genuine design defects remain, retain the blocking C1 verdict and explain the matching design attribution. If these are only limitations and acquisition gaps, return pass for C1 and leave scientific evidence sufficiency to a subsequent C2. Passing C1 never means any hypothesis is supported. Do not choose pass just to complete the workflow, and do not invent new requirements.',
            'immutable_content':'All per-hypothesis entries, coverage entries, hypotheses, predictions, questions, evidence and references remain unchanged. Only the explicit fields in this patch may change. The previous full audit/attribution remain preserved as failed historical outputs.',
            'repair_scope':'Same uncommitted second full Critic round, exactly one repair call. This is not an extra Explorer revision or an additional completed Critic round.',
        },
        'response_schema':ReviewPatch.model_json_schema(),
    }
    patch=ReviewPatch.model_validate_json(provider(payload,role='critic'))
    save(target/'patch.json',patch.model_dump())
    save(target/'model_usage.json',provider.summary())
    assert provider.calls==1
    revised_audit={**audit,'overall_status':patch.c1_overall_status,'audit_summary':patch.c1_audit_summary}
    revised_failure={**failure,'reason_type':patch.attribution_reason_type,
        'hypothesis_space_problem':patch.attribution_hypothesis_space_problem,
        'reason_summary':patch.attribution_reason_summary}
    case=load_case(source/'case_file/case_file.json')
    validate_hypothesis_audit(case,HypothesisAuditResult.model_validate(revised_audit))
    alias_map={'hypothesis_ids':'related_hypothesis_ids','mechanistic_claim_ids':'related_claim_ids','evidence_record_ids':'related_evidence_ids','evidence_gap_ids':'related_gap_ids'}
    for old,new in alias_map.items():
        if old in revised_failure:
            assert new not in revised_failure or revised_failure[new]==revised_failure[old]
            revised_failure[new]=revised_failure.pop(old)
    route_annotation=revised_failure.pop('route_to',None)
    save(target/'REPRESENTATION_BINDINGS.json',{'aliases':alias_map,'route_to_annotation':route_annotation,'routing_decision_still_required':True})
    FailureAttribution.model_validate(revised_failure)
    if revised_audit['overall_status']!='pass':
        assert revised_failure['reason_type'] in {'hypothesis_problem','prediction_problem','hypothesis_space_inadequate'}, 'Critic patch remains inconsistent; no automatic verdict correction'
    paths=[]
    for method,obj in [('audit_hypotheses',revised_audit),('attribute_failure',revised_failure)]:
        path=target/(method+'_patched_response.json')
        save(path,{'content':json.dumps(obj,ensure_ascii=False),'author':'critic',
            'patch_source':str(target/'patch.json'),'patch_sha256':file_sha(target/'patch.json'),
            'original_source':str(audit_path if method=='audit_hypotheses' else failure_path),
            'not_a_new_generation':True})
        if method=='audit_hypotheses' or revised_audit['overall_status']!='pass':
            paths.append({'path':str(path),'sha256':file_sha(path),'role':'critic','method':method})
    # Checkpoint content is unchanged; this ledger charges the separate patch.
    checkpoint=target/'C';checkpoint.mkdir()
    import shutil
    shutil.copytree(source/'case_file',checkpoint/'case_file')
    shutil.copyfile(source.parent/'PILOT_RUNTIME_FROZEN.json',target/'PILOT_RUNTIME_FROZEN.json')
    for name in ('stage_results.json','tool_trace.jsonl'):
        shutil.copyfile(source/name,checkpoint/name)
    save(checkpoint/'case_run_summary.json',{**summary,'cumulative_model_calls':39,
        'checkpoint_only':True,'predecessor':{'directory':str(source),
            'case_sha256':file_sha(source/'case_file/case_file.json')},
        'additional_paid_reconciliation':{'calls':1,'directory':str(target)}})
    config=json.loads(Path('configs/agent_case_c_second_cycle.json').read_text())
    config.update(protocol_id='jure_case_c_critic_semantic_reconciliation',
        resume_sources={'C':{'directory':str(checkpoint),
            'case_sha256':file_sha(checkpoint/'case_file/case_file.json')}},
        saved_investigator_prefix={'responses':paths,'tools':[],'envelopes':[]},
        engineering_recovery={'reason':'Critic-authored local patch reconciles its C1 verdict and failure attribution; no host verdict substitution.',
            'inherited_model_calls':39,'original_outputs_preserved':True,
            'scientific_patch_author':'critic','patch_manifest':str(target/'patch.json'),
            'same_logical_transition':5,'new_scientific_revision_allowance':0})
    save('configs/agent_case_c_second_cycle_reconciliation.json',config)
    save(target/'RECONCILIATION_PROVENANCE.json',{
        'original_c1_sha256':file_sha(audit_path),'original_attribution_sha256':file_sha(failure_path),
        'patch_sha256':file_sha(target/'patch.json'),'author':'critic',
        'case_file_unchanged':file_sha(checkpoint/'case_file/case_file.json')==file_sha(source/'case_file/case_file.json'),
        'new_model_calls':1,'cumulative_model_calls':39,'new_tool_calls':0,
        'c1_status':patch.c1_overall_status,'not_yet_committed':True,
        'c2_will_be_required_if_pass':True,
    })
    print(json.dumps({'patch_status':patch.c1_overall_status,'calls':1,
        'remaining_cumulative_model_calls':17,'config':'configs/agent_case_c_second_cycle_reconciliation.json'}))


if __name__=='__main__':main()
