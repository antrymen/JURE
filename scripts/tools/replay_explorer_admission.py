"""Replay saved outputs through production admission, with no external access.

Only temporary in-memory CaseStores are written. Original runs remain read-only.
No Critic/Investigator, evidence registry or provider is instantiated.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from jure.casefile import CaseStore, load_case
from jure.casefile.history import verify_history
from jure.agents.explorer.agent import MechanismExplorer
from jure.agents.explorer.backend import ExplorerBackend
from jure.agents.explorer.content_adapter import ContentExplorerBackend
from jure.agents.explorer.models import ExplorerConfig
from jure.agents.investigator.context import build_investigator_context
from jure.protocol.admission import POLICY_VERSION


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def snapshot(root):
    return {str(p): sha(p) for p in sorted(Path(root).rglob('*')) if p.is_file()}


class SavedProposal(ExplorerBackend):
    def __init__(self, payload): self.payload = payload
    def generate_initial(self, context, *, feedback=()): return self.payload
    def generate_reframe(self, context, *, feedback=()): raise RuntimeError('Initial-only offline replay')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--source',required=True)
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    source,output=Path(args.source),Path(args.output)
    if output.resolve().is_relative_to(source.resolve()):
        raise ValueError('Replay output must be outside the frozen input tree')
    output.mkdir(parents=True,exist_ok=False)
    before=snapshot(source)
    frozen=json.loads((source/'BENCHMARK_FROZEN.json').read_text())
    config=ExplorerConfig(**{**frozen['config']['explorer'], 'validation_policy':'three_layer','max_retries':0})
    rows=[]
    for path in sorted((source/'runs').glob('*/*/RESULT.json')):
        original=json.loads(path.read_text());slot,arm=original['slot'],original['arm']
        entry=next(x for x in frozen['initial_cases'] if x['slot']==slot)
        initial=load_case(entry['path'])
        raw_path=path.parent/'model_calls/call_0001_explorer/structured_output.json'
        raw=json.loads(raw_path.read_text())
        backend=ContentExplorerBackend(lambda request, raw=raw: raw) if arm=='deterministic_adapter' else SavedProposal(raw)
        with CaseStore() as store:
            store.import_case(initial)
            result=MechanismExplorer(backend,config).run(store,initial.metadata.case_id,
                capability_summary=frozen['capability_summary'])
            case=store.load_case(initial.metadata.case_id)
            verify_history(case)
            assert case.clue==initial.clue and not case.evidence_records and not case.critic_audits.hypothesis_audits
            assert result.attempts==1 and result.admission_checks
            decision=result.admission_checks[-1]['decision']
            if result.success:
                assert decision=='ADMIT_TO_INVESTIGATOR' and case.action_state.next_actor=='investigator'
                context=build_investigator_context(case)
                assert context['proposal_admission']['audit_flags']
            else:
                assert not case.hypotheses and not case.evidence_questions and not case.mechanistic_question
            row={'slot':slot,'arm':arm,'decision':decision,'offline_commit_success':result.success,
                 'hypotheses_in_temporary_store':len(case.hypotheses),'next_actor':case.action_state.next_actor,
                 'raw_sha256':sha(raw_path),'initial_sha256':sha(entry['path']),
                 'adapter_content_retained':backend.last_audit['content_retained'] if arm=='deterministic_adapter' and backend.last_audit else None,
                 'run_result':result.model_dump(mode='json')}
            rows.append(row)
    assert len(rows)==14
    adapter=[r for r in rows if r['arm']=='deterministic_adapter']
    legacy=[r for r in rows if r['arm']=='legacy_identifiers']
    assert {r['slot'] for r in adapter if r['offline_commit_success']}=={'E01','E02','E03','E04','E07'}
    assert not any(r['offline_commit_success'] for r in legacy)
    assert snapshot(source)==before
    result={'policy_version':POLICY_VERSION,'scope':'saved-output offline integration replay, not a new Agent benchmark',
            'source_files_unchanged':True,'source_file_count':len(before),'new_model_calls':0,'new_evidence_tool_calls':0,
            'critic_runs':0,'investigator_runs':0,'historical_case_writes':0,'temporary_case_commits':5,
            'adapter_admitted':5,'adapter_total':7,'legacy_admitted':0,'legacy_total':7,
            'rows':rows,'source_hashes':before,
            'runtime_hashes':{str(p):sha(p) for root in ('jure/agents','jure/protocol','jure/runtime','jure/llm') for p in sorted(Path(root).rglob('*.py'))}}
    (output/'REPLAY_RESULTS.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in {'rows','source_hashes','runtime_hashes'}},ensure_ascii=False))


if __name__=='__main__': main()
