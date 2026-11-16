from dataclasses import replace
import json

import numpy as np
import pytest

from clue_discovery.v02.populations import Population
from clue_discovery.v03.dependency import DependencyGraphBuilder
from clue_discovery.v04.config import ScalableConfig
from clue_discovery.v04.fingerprint import screen_triplets
from clue_discovery.v04.pipeline import fit_twofold
from clue_discovery.v04.priority import rank_shortlist
from clue_discovery.v04.proposal import CandidateProposalEngine


def cfg(**kwargs):
    return replace(ScalableConfig(), **kwargs)


@pytest.mark.parametrize('size', [100, 500, 1000])
def test_direct_parity_path_without_graph_or_truth_input(size):
    rng = np.random.default_rng(37)
    matrix = rng.integers(0, 2, (256, size), dtype=np.uint8)
    # Late positions/names, both parity orientations, no identity-based injection.
    matrix[:, -1] = matrix[:, -3] ^ matrix[:, -2] ^ (size == 500)
    genes = tuple(f'G{i:04}' for i in range(size))
    config = cfg(fingerprint_bands=8, fingerprint_score_candidates=64)
    candidates, audit = screen_triplets(matrix, genes, config, fold='A', quota=8)
    assert genes[-3:] in {c.genes for c in candidates}
    assert all(c.proposal_sources == ['higher_order_fingerprint'] for c in candidates)
    assert all(not c.generation_parent_ids for c in candidates)
    assert audit['pairs_queried_per_band'] == size*(size-1)//2
    assert not audit['global_triplet_enumeration']
    assert audit['candidates_scored'] <= 64
    assert not audit['truth_used'] and not audit['opposite_fold_used']


def test_column_order_reproducibility_and_sign_orientation():
    rng = np.random.default_rng(18)
    matrix = rng.integers(0, 2, (120, 15), dtype=np.uint8)
    genes = tuple(f'G{i:02}' for i in range(15))
    config = cfg(fingerprint_bands=4)
    c1, a1 = screen_triplets(matrix, genes, config, fold='A', quota=20)
    c2, a2 = screen_triplets(matrix[:, ::-1], genes[::-1], config, fold='A', quota=20)
    assert [c.to_record() for c in c1] == [c.to_record() for c in c2]
    assert a1['bands'] == a2['bands']
    _, other = screen_triplets(matrix, genes, config, fold='B', quota=20)
    assert a1['seed'] != other['seed']


def test_dense_collision_caps_are_explicit_and_bounded():
    matrix = np.tile(np.arange(60) % 2, (40, 1)).T.astype(np.uint8)
    # All zeros collide; this deliberately stresses buckets rather than biology.
    matrix[:] = 0
    config = cfg(fingerprint_bands=3, fingerprint_bucket_cap=3,
                 fingerprint_hits_per_band=7, fingerprint_score_candidates=5)
    candidates, audit = screen_triplets(matrix, tuple(f'G{i}' for i in range(40)), config,
                                        fold='A', quota=2)
    assert audit['budget_exhausted']
    assert all(b['bucket_entries_dropped'] == 37 for b in audit['bands'])
    assert all(b['retained_collisions'] <= 7 for b in audit['bands'])
    assert len(candidates) <= 2 and audit['candidates_scored'] <= 5
    assert all(np.isfinite(r['fingerprint_score']) for r in audit['screened_records'])


def test_merged_channels_obey_total_quota_and_deduplicate():
    rng = np.random.default_rng(6)
    matrix = rng.integers(0, 2, (256, 8), dtype=np.uint8)
    genes = tuple(f'G{i}' for i in range(8))
    config = cfg(max_triplet_candidates=12, fingerprint_bands=4,
                 max_exploration_candidates_per_order=10)
    graph = DependencyGraphBuilder().build(matrix, genes, fold='A')
    engine = CandidateProposalEngine(genes, graph, matrix, config, fold='A', random_seed=1)
    pairs = engine.propose(2)
    triples = engine.propose(3, parents=pairs.candidates)
    assert len(triples.candidates) <= 12
    assert len({c.candidate_id for c in triples.candidates}) == len(triples.candidates)
    assert triples.audit['higher_order_fingerprint_quota'] == 6
    retained = {c.candidate_id for c in triples.candidates}
    assert not retained.intersection(c.candidate_id for c in triples.budget_pruned_candidates)
    assert any('higher_order_fingerprint' in c.proposal_sources for c in triples.candidates)
    assert cfg(triplet_screen='off').fingerprint_quota == 0
    assert cfg(candidate_mode='dependency_only').fingerprint_quota == 0


def test_priority_is_discovery_evidence_not_alphabet_or_validation():
    def record(name, gain, p=.001, quality='good'):
        return dict(candidate_id=name, genes=[name], estimability_status=quality,
                    set_level_gain=gain, p_gain=p, min_state_count=30)
    weak, strong = record('AAA', .001), record('ZZZ', .1)
    sparse = record('SPARSE', 10, quality='sparse_boundary')
    before = rank_shortlist([(weak, []), (sparse, []), (strong, [])], seed=9)
    assert [r['candidate_id'] for r, _ in before] == ['ZZZ', 'AAA', 'SPARSE']
    for r in [weak, strong, sparse]:
        r['validation_gain'] = 100 if r is weak else 0
        r['cross_fold_replicated'] = r is weak
    after = rank_shortlist([(weak, []), (strong, []), (sparse, [])], seed=9)
    assert [r['candidate_id'] for r, _ in before] == [r['candidate_id'] for r, _ in after]
    assert strong['bootstrap_priority_rank'] == 1


def two_modules(prefix):
    rng = np.random.default_rng(71 if prefix == 'A' else 73)
    n = 6000
    matrix = rng.integers(0, 2, (n, 6), dtype=np.uint8)
    for offset, strength in [(0, .2), (3, .65)]:
        flip = rng.random(n) < (1-strength)/2
        matrix[:, offset+2] = matrix[:, offset] ^ matrix[:, offset+1] ^ flip
    return Population(matrix, ('AAA', 'AAB', 'AAC', 'ZZX', 'ZZY', 'ZZZ'),
                      tuple(f'{prefix}{i}' for i in range(n)))


def test_full_pipeline_spends_tight_calibration_and_bootstrap_on_stronger_late_gene_set(tmp_path):
    config = cfg(hvg_pool_size=6, max_order=3, max_triplet_candidates=40,
        fingerprint_bands=16, max_gain_calibration_gene_sets=1,
        max_bootstrap_gene_sets=1, n_bootstrap=80, n_null_simulations=99)
    result = fit_twofold(two_modules('A'), two_modules('B'), config, tmp_path)
    for discovery in result.discoveries.values():
        triple = next(r for r in discovery.records if tuple(r['genes']) == ('ZZX', 'ZZY', 'ZZZ'))
        assert triple['gain_calibration_priority_rank'] == 1
        assert triple['bootstrap_priority_rank'] == 1
        assert triple['bootstrap_status'] == 'complete'
        assert triple['keep']
    assert any(tuple(r['genes']) == ('ZZX', 'ZZY', 'ZZZ') and r['bidirectionally_rediscovered']
               for r in result.cross_summary)
    assert result.manifest['both_discoveries_frozen_before_validation']
    assert not result.manifest['formal_global_fdr_control']
    assert all(r['catalogue_tier'] == 'exploratory' for r in result.catalogue.records)
    with pytest.raises(FileExistsError):
        fit_twofold(two_modules('A'), two_modules('B'), config, tmp_path)


def test_statistically_qualified_fingerprint_needs_no_dependency_source(tmp_path):
    folds = {}
    for fold in ('A', 'B'):
        population = two_modules(fold)
        folds[fold] = Population(population.matrix[:, 3:], population.gene_names[3:], population.cell_ids)
    config = cfg(hvg_pool_size=3, max_order=3, fingerprint_bands=8,
                 n_bootstrap=80, n_null_simulations=99)
    result = fit_twofold(folds['A'], folds['B'], config, tmp_path)
    assert result.manifest['status'] == 'complete'
    assert all(d.graph_summary['n_edges'] == 0 for d in result.discoveries.values())
    assert result.catalogue.records
    assert all(r['catalogue_tier'] == 'primary' for r in result.catalogue.records)
    assert all('higher_order_fingerprint_source' in r['quality_flags'] for r in result.catalogue.records)
    assert all('exploration_only' not in r['quality_flags'] for r in result.catalogue.records)
    assert all(not r['global_search_fdr_controlled'] for r in result.catalogue.records)


@pytest.mark.parametrize('kwargs', [dict(fingerprint_bits=17), dict(fingerprint_bands=0),
    dict(fingerprint_bands=128, fingerprint_hits_per_band=100000),
    dict(fingerprint_bucket_cap=True), dict(bootstrap_priority='validation_gain')])
def test_invalid_resource_and_ranking_options_rejected(kwargs):
    with pytest.raises(ValueError):
        cfg(**kwargs)
