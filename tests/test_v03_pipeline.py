from dataclasses import replace
import json

import numpy as np
import pytest

from clue_discovery.v02.populations import Population
from clue_discovery.v03.artifacts import ArtifactStore
from clue_discovery.v03.bottom_up import discover
from clue_discovery.v03.catalogue import FrozenReferenceCatalogue
from clue_discovery.v03.config import ScalableConfig
from clue_discovery.v03.multiple_testing import MultipleTestingAudit
from clue_discovery.v03.pipeline import fit_twofold
from clue_discovery.v03.validation import validate_locked


def population(prefix, *, uniform=False):
    states = np.array([[int(x) for x in f'{i:03b}'] for i in range(8)])
    counts = np.full(8, 100) if uniform else np.where(states.sum(1) % 2, 190, 10)
    return Population(np.repeat(states, counts, axis=0), ('A', 'B', 'C'),
                      tuple(f'{prefix}{i}' for i in range(int(counts.sum()))))


def config(**kwargs):
    return replace(ScalableConfig(hvg_pool_size=3, max_order=3, candidate_mode='exploration_only',
        n_bootstrap=40, n_null_simulations=99), **kwargs)


def test_complete_lock_barrier_and_catalogue(tmp_path, monkeypatch):
    from clue_discovery.v03 import pipeline
    # Parallel development may add source files; this test concerns the lock barrier.
    monkeypatch.setattr(pipeline, 'code_hashes', lambda: {'test_source': 'constant'})
    observed = []
    original = pipeline.validate_locked
    def checking(*args, **kwargs):
        assert (tmp_path/'both_discoveries_frozen_before_validation.json').exists()
        assert (tmp_path/'discovery_A_frozen.json').exists()
        assert (tmp_path/'discovery_B_frozen.json').exists()
        observed.append(kwargs['source_fold'])
        return original(*args, **kwargs)
    monkeypatch.setattr(pipeline, 'validate_locked', checking)
    result = fit_twofold(population('a'), population('b'), config(), tmp_path)
    assert observed == ['A', 'B']
    triples = [r for r in result.cross_summary if r['order'] == 3]
    assert triples and all(r['bidirectionally_rediscovered'] for r in triples)
    assert result.manifest['both_discoveries_frozen_before_validation']
    assert all(r['catalogue_tier'] == 'exploratory' for r in result.catalogue.records)
    stored = FrozenReferenceCatalogue.load(tmp_path/'frozen_reference_catalogue.json')
    records = stored.records
    records[0]['genes'] = ['tampered']
    assert stored.records[0]['genes'] != ['tampered']
    with pytest.raises(FileExistsError):
        fit_twofold(population('a'), population('b'), config(), tmp_path)


def test_validation_null_failure_does_not_crash_or_search(tmp_path):
    store, audit = ArtifactStore(tmp_path), MultipleTestingAudit()
    d = discover(population('a'), config(), store, audit, fold='A')
    before = json.loads((tmp_path/'discovery_A_frozen.json').read_text())
    rows, sets = validate_locked(population('b', uniform=True), d.locked, config(), store, audit,
                                 source_fold='A', validation_fold='B')
    assert rows and not any(r['cross_fold_replicated'] for r in rows)
    assert all(0 <= r['p_mfi'] <= 1 for r in sets)
    assert all(not r['candidate_search_performed'] and not r['calibration_training_performed'] for r in sets)
    assert json.loads((tmp_path/'discovery_A_frozen.json').read_text()) == before
    assert len(sets) == len({r['candidate_id'] for r in d.locked})


def test_ablation_never_formal_replication(tmp_path):
    store, audit, cfg = ArtifactStore(tmp_path), MultipleTestingAudit(), config(bootstrap='off')
    d = discover(population('a'), cfg, store, audit, fold='A')
    rows, _ = validate_locked(population('b'), d.locked, cfg, store, audit,
                             source_fold='A', validation_fold='B')
    assert rows and any(r['evaluation_passed_under_config'] for r in rows)
    assert not any(r['cross_fold_replicated'] for r in rows)


def test_ids_guard_and_explicit_budget(tmp_path, monkeypatch):
    from clue_discovery.v03 import pipeline
    monkeypatch.setattr(pipeline, 'code_hashes', lambda: {})
    with pytest.raises(ValueError, match='overlap'):
        fit_twofold(population('a'), population('a'), config(), tmp_path/'bad')
    result = fit_twofold(population('a'), population('b'), config(max_bootstrap_gene_sets=1, max_order=4), tmp_path/'limited')
    assert result.manifest['status'] == 'budget_exhausted'
    assert 'candidate_budget_exhaustion' in result.manifest['limitations']
    assert not any(r['catalogue_tier'] == 'primary' for r in result.catalogue.records)
    families = json.loads((tmp_path/'limited/multiple_testing_manifest.json').read_text())
    assert all(len(f['unique_member_ids']) == len(set(f['unique_member_ids'])) for f in families['families'])
    assert not families['global_search_fdr_controlled']


def test_config_rejects_nonfunctional_options():
    with pytest.raises(ValueError):
        config(n_bootstrap=1)
    with pytest.raises(ValueError):
        config(gain_epsilon=0)
