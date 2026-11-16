"""Offline three-stage example; no API calls or real data required."""
import argparse
from pathlib import Path
from clue_discovery.integration.synthetic import make_fixture
from clue_discovery.run import run_pipeline

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',default='runs/synthetic')
    p.add_argument('--negative',action='store_true')
    args=p.parse_args();root=Path(args.output).resolve()
    if root.exists():p.error('Output already exists; choose a new directory.')
    cfg=make_fixture(root/'input',negative=args.negative)
    result=run_pipeline('full',cfg,root/'analysis')
    print(result['status'],result['summary'])
    print('Outputs:',root/'analysis')
if __name__=='__main__':main()
