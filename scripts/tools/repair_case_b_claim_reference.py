"""Ask Critic for one explicit primary-claim lineage patch; preserve all prose."""
import getpass
import json
import shutil
import sys
from pathlib import Path
from pydantic import BaseModel, ConfigDict, Field

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from jure.casefile import load_case
from jure.agents.critic.backend import SYSTEM_INSTRUCTIONS, ClaimDecompositionResult
from jure.agents.critic.validation import normalize_claims
from jure.llm.glm import GLMConfig, GLMTransport
from jure.runtime.pilot import save
from jure.tools.real.registry import file_sha


class ReferencePatch(BaseModel):
    model_config=ConfigDict(extra='forbid')
    derived_from_prediction_ids: list[str] = Field(min_length=1)
    reason: str


def main():
    base=Path('outputs/agent_pilot_v1_20260928')
    source=base/'run_038_case_b_final_audit/B'
    target=base/'case_b_claim_reference_patch_20260929';target.mkdir(exist_ok=False)
    path=source/'model_calls/call_0001_critic/structured_output.json'
    original=json.loads(path.read_text())
    case=load_case(source/'case_file/case_file.json')
    summary=json.loads((source/'case_run_summary.json').read_text())
    assert summary['cumulative_model_calls']==67
    claims=ClaimDecompositionResult.model_validate(original).claims
    owners={p.prediction_id:h.hypothesis_id for h in case.hypotheses for p in h.predictions
        if p.hypothesis_revision_id==h.current_revision_id}
    bad=[c for c in claims if any(owners.get(p)!=c.hypothesis_id for p in c.derived_from_prediction_ids)]
    assert len(bad)==1 and bad[0].claim_id=='C_cross_hypothesis_discrimination_unresolved'
    claim=bad[0]
    hypothesis=next(h for h in case.hypotheses if h.hypothesis_id==claim.hypothesis_id)
    cfg=GLMConfig.model_validate_json(Path('configs/agent_runtime_glm53_flash.json').read_text()).model_copy(update={'max_calls':1})
    key=getpass.getpass('GLM API key (hidden): ')
    provider=GLMTransport(config=cfg,api_key=key,trace_dir=target/'model_calls');del key
    answer=provider({
        'method':'repair_primary_claim_prediction_references',
        'system_instructions':SYSTEM_INSTRUCTIONS+'\nReturn only the requested local reference patch for your own claim. Do not rewrite its statement, criticality, evidence interpretation, or any other claim.',
        'context':{
            'claim':claim.model_dump(mode='json'),
            'primary_hypothesis':hypothesis.model_dump(mode='json'),
            'prediction_owner_catalog':owners,
            'problem':'This claim is stored under primary hypothesis H1 but its derived_from_prediction_ids also include predictions owned by other hypotheses. The field records the primary hypothesis prediction lineage, not every alternative mentioned in a comparison.',
            'instruction':'Select the current H1 prediction IDs that ground your existing claim as an H1 comparison. Keep the cross-hypothesis statement and its interpretation exactly unchanged; the broader comparison remains visible in the statement and the other six claims. Return only your corrected derived_from_prediction_ids and your reason. Do not claim that this mechanical repair supports H1.',
        },'response_schema':ReferencePatch.model_json_schema()},role='critic')
    patch=ReferencePatch.model_validate_json(answer)
    save(target/'patch.json',patch.model_dump());save(target/'model_usage.json',provider.summary())
    assert all(owners.get(p)==claim.hypothesis_id for p in patch.derived_from_prediction_ids)
    revised=json.loads(json.dumps(original))
    row=next(c for c in revised['claims'] if c['claim_id']==claim.claim_id)
    row['derived_from_prediction_ids']=patch.derived_from_prediction_ids
    normalized=normalize_claims(case,ClaimDecompositionResult.model_validate(revised).claims)
    assert len(normalized)==7
    response_path=target/'decompose_claims_patched_response.json'
    save(response_path,{'content':json.dumps(revised,ensure_ascii=False),'author':'critic',
        'original_source':str(path),'original_sha256':file_sha(path),
        'patch_source':str(target/'patch.json'),'patch_sha256':file_sha(target/'patch.json')})
    checkpoint=target/'B';checkpoint.mkdir()
    shutil.copytree(source/'case_file',checkpoint/'case_file')
    for name in ('stage_results.json','tool_trace.jsonl'):
        shutil.copyfile(source/name,checkpoint/name)
    save(checkpoint/'case_run_summary.json',{**summary,'cumulative_model_calls':68,
        'checkpoint_only':True,'predecessor':{'directory':str(source),'case_sha256':file_sha(source/'case_file/case_file.json')},
        'additional_paid_reference_patch':{'calls':1,'directory':str(target)}})
    shutil.copyfile(source.parent/'PILOT_RUNTIME_FROZEN.json',target/'PILOT_RUNTIME_FROZEN.json')
    config=json.loads(Path('configs/agent_pilot_case_b_critic_reconciliation.json').read_text())
    config.update(protocol_id='jure_case_b_claim_reference_recovery',
        resume_sources={'B':{'directory':str(checkpoint),'case_sha256':file_sha(checkpoint/'case_file/case_file.json')}})
    config['saved_investigator_prefix']['responses'].append({'path':str(response_path),
        'sha256':file_sha(response_path),'role':'critic','method':'decompose_claims'})
    config['engineering_recovery']={'reason':'Critic-authored patch changes one primary-claim reference list only.',
        'inherited_model_calls':68,'all_scientific_prose_unchanged':True,
        'original_outputs_preserved':True,'same_logical_transition':12,'new_scientific_revision_allowance':0}
    save('configs/agent_pilot_case_b_claim_reference_recovery.json',config)
    save(target/'PATCH_PROVENANCE.json',{'author':'critic','changed_claim_id':claim.claim_id,
        'changed_field':'derived_from_prediction_ids','old_value':list(claim.derived_from_prediction_ids),
        'new_value':patch.derived_from_prediction_ids,'original_sha256':file_sha(path),
        'patch_sha256':file_sha(target/'patch.json'),'all_claim_prose_and_criticality_unchanged':True,
        'all_seven_claims_validate':True,'new_model_calls':1,'cumulative_model_calls':68,
        'new_tool_calls':0,'not_yet_committed':True})
    print(json.dumps({'patched_claim':claim.claim_id,'all_claims_validate':True,
        'remaining_model_calls':12,'config':'configs/agent_pilot_case_b_claim_reference_recovery.json'}))


if __name__=='__main__':main()
