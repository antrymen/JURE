from dataclasses import replace
import json

import numpy as np
import pytest

from clue_discovery.v02.populations import Population
from clue_discovery.v03.artifacts import digest
from clue_discovery.v03.hvg import select_hvgs
from clue_discovery.v04.config import ScalableConfig
from clue_discovery.v04_validation.experiment import run_experiment
from real_nt_v04_holm.run import run_reference, compress_csvs, verify_frozen_engine


def test_real_adapter_matches_accepted_policy_and_preserves_locked_states(tmp_path,monkeypatch):
    states=np.array([[int(x) for x in f'{i:03b}'] for i in range(8)],dtype=np.uint8)
    matrix=np.repeat(states,np.where(states.sum(1)%2,70,330),axis=0)
    populations={f:Population(matrix,('A','B','C'),tuple(f'{f}{i}' for i in range(len(matrix)))) for f in ('A','B')}
    cfg=replace(ScalableConfig(),hvg_pool_size=3,max_order=3,fingerprint_bands=4,n_null_simulations=99,n_bootstrap=40)
    baseline=run_experiment(populations['A'],populations['B'],cfg,tmp_path/'accepted')
    selections={f:select_hvgs(p.matrix,p.gene_names,n_top=3,fold=f) for f,p in populations.items()}
    from real_nt_v04_holm import run
    original=run.discover
    seen=[]
    def checked(*args,**kwargs):
        assert kwargs['selection'] is selections[kwargs['fold']]
        seen.append(kwargs['fold'])
        return original(*args,**kwargs)
    monkeypatch.setattr(run,'discover',checked)
    summary=run_reference(populations,selections,{'real_data_used':False,'unit_fixture':True},cfg,tmp_path/'real_adapter')
    assert seen==['A','B']
    expected={r['reference_id'] for r in baseline.corrected_states if r['arm']=='holm_025' and r['qualified']}
    root=tmp_path/'real_adapter'
    catalogue=json.loads((root/'holm_reference_catalogue_frozen.json').read_text())
    assert digest(catalogue['payload'])==catalogue['sha256']
    assert {r['reference_id'] for r in catalogue['payload']['records']}==expected
    assert summary['holm_qualified_states']==len(expected)>0
    for r in catalogue['payload']['records']:
        expected_count=int((matrix==r['states']).all(axis=1).sum())*2
        assert r['nt_support']==expected_count
        assert r['nt_n_cells']==2*len(matrix)
        assert r['nt_frequency']==expected_count/(2*len(matrix))
        assert r['bidirectionally_qualified']
        assert not r['eligible_for_agent_investigation']
        assert not r['state_level_FDR_controlled']
    barrier=json.loads((root/'both_discoveries_and_families_frozen_before_validation.json').read_text())
    compress_csvs(root)
    assert all((root/p).exists() for p in barrier)
    assert (root/'holm_reference_patterns.csv').exists()
    assert (root/'corrected_gene_sets.csv.gz').exists()
    with pytest.raises(FileExistsError):
        run_reference(populations,selections,{},cfg,root)


def test_previously_accepted_sources_unchanged():
    verify_frozen_engine()
