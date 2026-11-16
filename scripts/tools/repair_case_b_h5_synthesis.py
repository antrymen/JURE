"""One local Critic content patch for a missing H5 synthesis, not a new audit."""
import getpass
import json
import shutil
import sys
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, ConfigDict

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from jure.agents.critic.backend import SYSTEM_INSTRUCTIONS
from jure.agents.critic.result import CriticConfig
from jure.agents.critic.validation import validate_synthesis
from jure.casefile.critic_models import HypothesisSynthesis, MechanisticClaim, ClaimAuditRecord
from jure.llm.glm import GLMConfig, GLMTransport
from jure.protocol.normalization import normalize_output
from jure.runtime.pilot import save
from jure.tools.real.registry import file_sha


class SynthesisContent(BaseModel):
    model_config = ConfigDict(extra='forbid')
    status: Literal['supported', 'partially_supported', 'challenged', 'insufficient']
    summary: str
    remaining_uncertainties: list[str]
    critical_gaps: list[str]


def main():
    base = Path('outputs/agent_pilot_v1_20260928')
    source = base / 'run_047_case_b_budget_extension/B'
    out = base / 'case_b_h5_synthesis_patch_20260929'
    out.mkdir(exist_ok=False)
    failed = source / 'model_calls/call_0007_critic'
    request = json.loads((failed / 'request.json').read_text())
    context = json.loads(next(m['content'] for m in request['messages'] if m['role'] == 'user'))['context']
    target = context['target_hypothesis_id']
    assert target == 'H_5846edf4eac8_1' and context['critic_round'] == 4
    claims = [c for c in context['claims'] if c['hypothesis_id'] == target]
    ids = {c['claim_id'] for c in claims}
    audits = [a for a in context['claim_audits'] if a['claim_id'] in ids]
    evidence_ids = {eid for a in audits for eid in a['evidence_ids']}
    cfg = GLMConfig.model_validate_json(Path('configs/agent_runtime_glm53_flash.json').read_text()).model_copy(update={'max_calls': 1})
    key = getpass.getpass('GLM API key (hidden): ')
    provider = GLMTransport(config=cfg, api_key=key, trace_dir=out / 'model_calls')
    del key
    response = provider({
        'method': 'patch_missing_h5_synthesis',
        'system_instructions': SYSTEM_INSTRUCTIONS + '\nProvide only the missing scientific content for the requested H5 synthesis. Software binds identifiers and computes descriptive coverage from your existing claim audit. Do not rerun C1/C2, change prior claim verdicts, synthesize other hypotheses, or issue a final route/STOP here.',
        'context': {
            'actual_critic_round': 4,
            'target_hypothesis_id': target,
            'target_hypothesis': next(h for h in context['hypotheses'] if h['hypothesis_id'] == target),
            'hypothesis_audit': context['hypothesis_audit'],
            'target_claims': claims, 'already_completed_claim_audits': audits,
            'evidence_records': [e for e in context['evidence_records'] if e['evidence_id'] in evidence_ids],
            'evidence_audits': [e for e in context['evidence_audits'] if e['evidence_id'] in evidence_ids],
            'evidence_gaps': context['evidence_gaps'],
            'contradictions': context['contradictions'],
            'previous_wrong_scope_answer': json.loads((failed / 'structured_output.json').read_text()),
            'repair_scope': 'Your previous answer was a whole-case review instead of the requested single-hypothesis synthesis. Only the H5 synthesis is missing. You author its status, scientific summary, uncertainty and relevant critical-gap references; no host verdict will be substituted.',
        },
        'response_schema': SynthesisContent.model_json_schema(),
    }, role='critic')
    save(out / 'model_usage.json', provider.summary())
    content = SynthesisContent.model_validate_json(response)
    save(out / 'patch.json', content.model_dump())
    structured = {**content.model_dump(), 'hypothesis_id': target,
                  'synthesis_id': 'SYN_B_C4_H5_local_content_patch', 'critic_round': 4}
    normalized, audit = normalize_output(structured, role='critic', method='synthesize_hypothesis',
        schema=HypothesisSynthesis.model_json_schema(), context=context)
    model = HypothesisSynthesis.model_validate(normalized)
    validate_synthesis(model, [MechanisticClaim.model_validate(c) for c in context['claims']],
        [ClaimAuditRecord.model_validate(a) for a in context['claim_audits']], CriticConfig())
    assert set(model.critical_gaps) <= {g['gap_id'] for g in context['evidence_gaps']}
    path = out / 'h5_synthesis_response.json'
    save(path, {'content': json.dumps(normalized, ensure_ascii=False), 'author': 'critic',
        'patch_source': str(out / 'patch.json'), 'patch_sha256': file_sha(out / 'patch.json'),
        'original_wrong_scope_response': str(failed / 'response.json')})
    checkpoint = out / 'B'; checkpoint.mkdir()
    shutil.copytree(source / 'case_file', checkpoint / 'case_file')
    for name in ('stage_results.json', 'tool_trace.jsonl'):
        shutil.copyfile(source / name, checkpoint / name)
    summary = json.loads((source / 'case_run_summary.json').read_text())
    assert summary['cumulative_model_calls'] == 105
    save(checkpoint / 'case_run_summary.json', {**summary, 'cumulative_model_calls': 106,
        'checkpoint_only': True, 'predecessor': {'directory': str(source), 'case_sha256': file_sha(source / 'case_file/case_file.json')},
        'missing_h5_patch_calls': 1})
    shutil.copyfile(source.parent / 'PILOT_RUNTIME_FROZEN.json', out / 'PILOT_RUNTIME_FROZEN.json')
    config = json.loads(Path('configs/agent_pilot_case_b_budget_claim_binding_recovery.json').read_text())
    config.update(protocol_id='jure_case_b_budget_extension_h5_patch',
        resume_sources={'B': {'directory': str(checkpoint), 'case_sha256': file_sha(checkpoint / 'case_file/case_file.json')}})
    for index in range(1, 8):
        call = source / f'model_calls/call_{index:04d}_critic'
        meta = json.loads((call / 'call.json').read_text())
        p = path if index == 7 else call / 'response.json'
        config['saved_investigator_prefix']['responses'].append({
            'path': str(p), 'sha256': file_sha(p), 'role': 'critic', 'method': meta['operation']})
    assert not (source / 'tool_trace_current.jsonl').read_text().strip()
    config['max_transitions'] = 14
    config['engineering_recovery'] = {'same_logical_transition': 14, 'inherited_model_calls': 106,
        'inherited_tool_calls': 21, 'reason': 'Critic authors missing H5 scientific content only. Existing C1/C2 and H1-H4 syntheses replay exactly. Finish this committed audit boundary before allocating remaining calls to round 5.',
        'controller_boundary_after_current_critic': True, 'no_budget_reset': True}
    save('configs/agent_pilot_case_b_budget_h5_recovery.json', config)
    save(out / 'PATCH_PROVENANCE.json', {'scientific_author': 'critic', 'only_missing_hypothesis': target,
        'existing_audits_and_other_syntheses_unchanged': True, 'normalization_audit': audit,
        'new_model_calls': 1, 'cumulative_model_calls': 106, 'new_tool_calls': 0})
    print(json.dumps({'config': 'configs/agent_pilot_case_b_budget_h5_recovery.json', 'remaining_model_calls': 24,
                      'pause_at_committed_C4_boundary': True}))


if __name__ == '__main__':
    main()
