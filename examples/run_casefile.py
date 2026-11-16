"""Offline synthetic Case File persistence example; does not invoke agents."""
import argparse
from pathlib import Path
from jure.casefile.models import ClueRecord, PatternRecord, ShiftEvidence
from jure.casefile.store import CaseStore

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',default='runs/casefile')
    args=p.parse_args();root=Path(args.output).resolve()
    if root.exists():p.error('Output already exists; choose a new directory.')
    root.mkdir(parents=True)
    clue=ClueRecord(clue_id='SYN_CLUE',perturbation='SYN_KO',discovery_mode='reference_guided',
        source_schema_version='0.2.0',source_run_id='synthetic',source_artifact='synthetic_example',
        reference_id='SYN_REF',catalogue_sha256='a'*64,
        pattern=PatternRecord(genes=('A','B','C'),states=(1,0,1),order=3,pattern_string='A+B-C+'),
        perturbation_shift=ShiftEvidence(control_frequency=.1,perturb_frequency=.2,delta_frequency=.1,
            control_count=10,perturb_count=20),source_payload={'synthetic':True})
    with CaseStore(root/'cases.sqlite') as store:
        case=store.create_case_from_clue(clue,case_id='SYN_CASE')
        (root/'case_file.json').write_text(case.model_dump_json(indent=2))
    print('Synthetic Case File saved:',root)
if __name__=='__main__':main()
