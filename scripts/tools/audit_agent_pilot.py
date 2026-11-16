"""Verify artifacts and authorship without interpreting case biology."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from jure.casefile.store import load_case
from jure.casefile.history import verify_history
from jure.tools.real.registry import file_sha


def main():
    p=argparse.ArgumentParser();p.add_argument('--run',required=True);a=p.parse_args();root=Path(a.run)
    frozen=json.loads((root/'PILOT_RUNTIME_FROZEN.json').read_text());results=[]
    for letter in 'ABCD':
        directory=root/letter;path=directory/'case_file/case_file.json'
        if not (directory/'case_run_summary.json').exists():results.append({'case':letter,'finished':False});continue
        summary=json.loads((directory/'case_run_summary.json').read_text());case=load_case(path);verify_history(case)
        original=Path('outputs/pilot_preparation_v1_20260928/initial_cases')/letter/'case_file.json'
        initial=load_case(original);errors=[]
        if file_sha(original)!=frozen['initial_cases'][letter]:errors.append('Initial case changed')
        if case.clue!=initial.clue:errors.append('Clue changed')
        if case.investigation_history[:len(initial.investigation_history)]!=initial.investigation_history:errors.append('Initial history changed')
        for evidence in case.evidence_records:
            raw=Path(evidence.raw_result_reference)
            if not raw.exists() or file_sha(raw)!=evidence.provenance.artifact_sha256:errors.append('Evidence artifact hash mismatch: '+evidence.evidence_id);continue
            envelope=json.loads(raw.read_text())
            if envelope['source_mode']!='REAL' or envelope['context']['case_id']!=case.metadata.case_id:errors.append('Evidence source mode/case mismatch')
            if envelope['status'] not in ('OK','TRUNCATED','INSUFFICIENT_SUPPORT'):errors.append('Failed acquisition promoted to evidence')
        traces=[json.loads(line) for line in (directory/'tool_trace.jsonl').read_text().splitlines() if line]
        for trace in traces:
            ref=trace['result_reference'];envelope=json.loads(Path(ref['path']).read_text())
            if file_sha(ref['path'])!=ref['sha256']:errors.append('Trace artifact hash mismatch')
            if envelope['source_mode']!='REAL' or envelope['context']['case_id']!=case.metadata.case_id:errors.append('Trace source mismatch')
            if trace['actor'] not in ('investigator','critic'):errors.append('Unexpected acquisition actor')
        final_path=directory/'final_case_report.json'
        if summary['completed']:
            if case.action_state.current_phase!='stopped' or not case.critic_audits.final_reports:errors.append('No audited STOP')
            elif json.loads(final_path.read_text())!=case.critic_audits.final_reports[-1].model_dump(mode='json'):errors.append('Final report differs from committed Agent report')
        results.append({'case':letter,'finished':True,'completed':summary['completed'],'passed':not errors,
            'errors':errors,'hypotheses':len(case.hypotheses),'evidence_records':len(case.evidence_records),
            'tool_calls':len(traces),'claim_audits':len(case.critic_audits.claim_audits),'stop_reason':case.action_state.stop_reason})
    result={'scope':'artifact integrity, source provenance, immutable clue/history and committed report identity; no scientific adjudication',
        'all_four_completed':all(r.get('completed') for r in results),'all_finished_artifacts_passed':all(r.get('passed',True) for r in results),'cases':results}
    (root/'FINAL_ARTIFACT_AUDIT.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':main()
