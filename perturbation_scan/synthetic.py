"""Frozen fixtures for implementation checks, not confirmatory calibration."""
import argparse
import itertools
import json
from pathlib import Path
import numpy as np
from clue_discovery.v03.artifacts import write_json
from clue_discovery.v03.data import file_hash
from .scan import Counts,scan


def make_fixture(kind,seed):
    rng=np.random.default_rng(seed)
    states=np.array(list(itertools.product((0,1),repeat=3)),dtype=int)
    patterns=[dict(reference_id=f'R{i}',genes=['A','B','C'],states=s.tolist(),
        pattern=' '.join(g+('+' if x else '-') for g,x in zip('ABC',s))) for i,s in enumerate(states)]
    gt=[];gb=[];ns=[];hits=[]
    for t in range(4): # NT + three targets
        for b in range(3):
            n=700 if t==0 else (300 if b==t-1 else 100)
            p=[.1,.5,.9][b] if kind=='batch_heterogeneous_null' else .5
            x=rng.binomial(1,p,(n,3))
            if kind=='pairwise_only_null':
                x[:,1]=np.where(rng.random(n)<.85,x[:,0],1-x[:,0])
            if kind.startswith('depletion'):
                x[:,:]=rng.binomial(1,.8,(n,3))
            if t==1:
                if kind.startswith('enrichment'):
                    f=.5 if kind.endswith('strong') else .2
                    x[rng.random(n)<f]=1
                if kind.startswith('depletion'):
                    f=1. if kind.endswith('strong') else .4
                    x[(x==1).all(1)&(rng.random(n)<f),0]=0
            gt.append(t);gb.append(b);ns.append(n)
            hits.append([(x==s).all(1).sum() for s in states])
    return Counts(('T1','T2','T3'),('b0','b1','b2'),np.array(gt),np.array(gb),
                  np.array(ns),np.array(hits),patterns,3)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output-dir',required=True)
    args=parser.parse_args();out=Path(args.output_dir)
    if out.exists() and any(out.iterdir()):raise FileExistsError('refuse overwrite')
    kinds=['balanced_null','batch_heterogeneous_null','pairwise_only_null',
           'enrichment_strong','enrichment_medium','depletion_strong','depletion_medium']
    cases=[]
    for j,kind in enumerate(kinds):
        for repeat in range(8):
            name=f'{kind}_{repeat}';seed=2026092800+j*100+repeat
            root=out/'fixtures'/name;make_fixture(kind,seed).save(root)
            cases.append(dict(name=name,kind=kind,seed=seed,hashes={p.name:file_hash(p) for p in sorted(root.iterdir())}))
    write_json(out/'FIXTURES_FROZEN_BEFORE_SCAN.json',dict(cases=cases,
        role='implementation_checks_not_selection_calibration_or_general_power_estimate'))
    results=[]
    for case in cases:
        root=out/'fixtures'/case['name']
        assert all(file_hash(root/name)==h for name,h in case['hashes'].items())
        summary=scan(Counts.load(root),out/'runs'/case['name'])
        with np.load(out/'runs'/case['name']/'statistics.npz') as d:
            recovered=bool(d['candidate'][0,7])
        results.append(dict(name=case['name'],kind=case['kind'],**summary,true_111_shift_recovered=recovered))
    report={k:dict(cases=8,total_candidates=sum(r['exploratory_candidates'] for r in results if r['kind']==k),
                   runs_with_candidates=sum(r['exploratory_candidates']>0 for r in results if r['kind']==k),
                   true_111_shift_recovered=sum(r['true_111_shift_recovered'] for r in results if r['kind']==k)) for k in kinds}
    write_json(out/'RESULTS.json',dict(by_kind=report,cases=results,confirmatory_calibration=False))
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()
