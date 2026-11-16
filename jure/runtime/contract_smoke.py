"""Frozen five-input contract smoke; no evidence registry or Critic execution."""
import argparse,getpass,json,hashlib
from copy import deepcopy
from pathlib import Path
from jure.casefile import CaseStore,load_case
from jure.agents.explorer.agent import MechanismExplorer
from jure.agents.explorer.models import ExplorerConfig
from jure.agents.explorer.content_adapter import ContentExplorerBackend
from jure.agents.investigator.backend import JSONInvestigatorBackend
from jure.agents.investigator.prioritization import PrioritizationResult
from jure.agents.investigator.context import build_investigator_context
from jure.runtime.backends import CheckedTransport
from jure.runtime.pilot import code_manifest
from jure.runtime.contract_review import evaluate
from jure.llm.glm import GLMTransport,GLMConfig


def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,v):
    Path(p).parent.mkdir(parents=True,exist_ok=True)
    Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')


def prepare(root):
    config=json.loads(Path('configs/contract_stabilization_v1.json').read_text())
    root.mkdir(parents=True,exist_ok=False)
    # Freeze selector before inspecting input facts. No outcome-dependent choice.
    save(root/'SELECTION_RULES.json',config)
    paths=sorted(Path('outputs/explorer_contract_benchmark_v1_20260928/initial_cases').glob('*/case_file.json'))
    pool=[(p,load_case(p)) for p in paths];used=set();selected=[]
    predicates={
        'enrichment':lambda c:c.clue.perturbation_shift.delta_frequency>0,
        'depletion':lambda c:c.clue.perturbation_shift.delta_frequency<0,
        'stable-core':lambda c:c.clue.upstream_context.to_dict()['stable_core_context']['status']=='stable_core',
        'signed-state contrast':lambda c:bool(c.clue.upstream_context.to_dict()['signed_state_contrast_context']),
        'gene-disjoint context':lambda c:any(r['relation_type']=='GENE_DISJOINT_CORESPONSE' for r in c.clue.upstream_context.to_dict()['condition_specific_relations']),
    }
    for label,predicate in predicates.items():
        eligible=sorted(((p,c) for p,c in pool if c.clue.clue_id not in used and predicate(c)),
            key=lambda pc:(hashlib.sha256((config['version']+':'+pc[1].clue.clue_id).encode()).hexdigest(),pc[1].clue.clue_id))
        if not eligible:raise ValueError('Missing smoke stratum '+label)
        p,c=eligible[0];used.add(c.clue.clue_id)
        selected.append({'slot':f'S{len(selected)+1}','type':label,'path':str(p),'sha256':sha(p),'case_id':c.metadata.case_id,'perturbation':c.clue.perturbation})
    previous=Path('outputs/agent_pilot_v1_20260928/run_019_glm47_admission_v2_a/A/model_calls/call_0001_investigator/request.json')
    context=json.loads(json.loads(previous.read_text())['messages'][1]['content'])['context']
    save(root/'SMOKE_FROZEN.json',{'config':config,'cases':selected,'code':code_manifest(),
        'script_sha256':sha(__file__),'protocol_document_sha256':sha('docs/tools/SCIENTIFIC_PROTOCOL_FROZEN_V1.md'),
        'capability_source':str(previous),'capability_source_sha256':sha(previous),
        'tool_cards':context['tool_capabilities'],'capability_summary':context['capability_summary'],
        'provider_config':json.loads(Path(config['model_config']).read_text()),
        'pilot_checkpoints':{str(p):sha(p) for p in Path('outputs/agent_pilot_v1_20260928').glob('run_*/[ABCD]/case_file/case_file.json')}})
    print(json.dumps(selected,ensure_ascii=False),flush=True)


class CapabilityCardsOnly:
    protocol_v3=True
    def __init__(self,cards):self.cards=cards
    def metadata_snapshot(self):return deepcopy(self.cards)
    # No get_tool, execute, call or real registry exists on this object.


def run(root):
    frozen=json.loads((root/'SMOKE_FROZEN.json').read_text())
    if code_manifest()!=frozen['code'] or sha(__file__)!=frozen['script_sha256']:raise ValueError('Frozen runtime changed')
    if (root/'model_calls').exists():raise FileExistsError('No retry/resume into an existing smoke run')
    key=getpass.getpass('GLM API key (hidden): ')
    provider=GLMTransport(config=GLMConfig(**{**frozen['provider_config'],'max_calls':10}),api_key=key,trace_dir=root/'model_calls')
    del key
    rows=[]
    registry=CapabilityCardsOnly(frozen['tool_cards'])
    for entry in frozen['cases']:
        if sha(entry['path'])!=entry['sha256']:raise ValueError('Smoke input changed')
        print(json.dumps({'event':'SMOKE_EXPLORER_STARTED','slot':entry['slot'],'type':entry['type']},ensure_ascii=False),flush=True)
        config=ExplorerConfig(protocol_v3=True,validation_policy='three_layer',min_hypotheses=3,max_hypotheses=4,
            max_retries=0,max_context_chars=750000,round_budget_basis='completed')
        backend=ContentExplorerBackend(CheckedTransport(provider,'explorer',schema_retries=0,protocol_v3=True))
        with CaseStore() as store:
            initial=load_case(entry['path']);store.import_case(initial)
            start=provider.calls
            result=MechanismExplorer(backend,config).run(store,initial.metadata.case_id,
                capability_summary=frozen['capability_summary'],artifact_dir=root/entry['slot']/'explorer')
            case=store.load_case(initial.metadata.case_id)
            row={**entry,'explorer_success':result.success,'explorer_result':result.model_dump(mode='json'),
                'explorer_calls':provider.calls-start,'investigator_success':False,'investigator_status':'SKIPPED_NO_COMPLETE_PROPOSAL'}
            if backend.last_compiled:
                save(root/entry['slot']/'compiled_proposal.json',backend.last_compiled.model_dump(mode='json'))
                save(root/entry['slot']/'adapter_audit.json',backend.last_audit)
            if result.success:
                # Only prioritization backend; no EvidenceInvestigator or tools.
                context=build_investigator_context(case,registry=registry)
                ib=JSONInvestigatorBackend(CheckedTransport(provider,'investigator',schema_retries=0,protocol_v3=True))
                try:
                    output=PrioritizationResult.model_validate_json(ib.prioritize_questions(context))
                    save(root/entry['slot']/'investigator_priority.json',output.model_dump(mode='json'))
                    row.update(investigator_success=True,investigator_status='SCHEMA_AND_REFERENCES_PASS')
                except Exception as e:row.update(investigator_status='FAILED',investigator_error=f'{type(e).__name__}: {str(e)[:2500]}')
            assert not case.evidence_records and not case.critic_audits.hypothesis_audits
        rows.append(row);save(root/'SMOKE_ROWS.json',rows)
        save(root/'USAGE.json',provider.summary())
        print(json.dumps({'event':'SMOKE_SLOT_COMPLETED','slot':entry['slot'],'explorer':row['explorer_success'],'investigator':row['investigator_status'],'model_calls':provider.calls}),flush=True)
    completed=sum(r['explorer_success'] for r in rows);ips=sum(r['investigator_success'] for r in rows)
    errors=[];tech={'explorer':0,'investigator':0}
    for p in sorted((root/'model_calls').glob('call_*/request.json')):
        role=p.parent.name.rsplit('_',1)[-1]
        req=json.loads(json.loads(p.read_text())['messages'][1]['content'])
        response=p.parent/'response.json'
        if not response.exists():continue
        raw=json.loads(response.read_text())
        if raw.get('finish_reason')!='stop':continue
        review=evaluate(raw['content'],role,req.get('method',req.get('mode')),req['context'])
        tech[role]+=int(review['technical_pass'])
        if not review['technical_pass']:errors.append({'path':str(p),'errors':review['errors']+review['reference_errors']})
    accepted=provider.calls==10 and sum(tech.values())>=9 and min(tech.values())>=4 and completed>=4 and ips>=4
    assert code_manifest()==frozen['code'] and sha(__file__)==frozen['script_sha256']
    assert all(sha(p)==h for p,h in frozen['pilot_checkpoints'].items())
    result={'accepted':accepted,'model_calls':provider.calls,'technical_passes':tech,'complete_explorer_proposals':completed,
        'investigator_priority_passes':ips,'errors':errors,'usage':provider.summary(),'evidence_tool_calls':0,'critic_calls':0,
        'pilot_checkpoints_unchanged':True,'runtime_unchanged':True,'case_a_launched':False,
        'scope':'Contract communication only; no scientific validity or discrimination claim.'}
    save(root/'SMOKE_SUMMARY.json',result);print(json.dumps(result,ensure_ascii=False),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['prepare','run']);p.add_argument('--output',required=True)
    a=p.parse_args();(prepare if a.action=='prepare' else run)(Path(a.output))
