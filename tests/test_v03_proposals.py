"""Proposal coverage, provenance, ownership and bounded-scale contracts."""
import itertools
import math
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from scipy import sparse

from clue_discovery.v03.candidate import Candidate, candidate_id
from clue_discovery.v03.dependency import DependencyGraphBuilder
from clue_discovery.v03.exploration import sample_exploration, unrank_combination
from clue_discovery.v03.hvg import HVG_METHOD, select_hvgs
from clue_discovery.v03.proposal import CandidateProposalEngine
import clue_discovery.v03.proposal as proposal_module


def identical_binary(n_genes):
    return np.repeat(np.tile([0, 1], 50)[:, None], n_genes, axis=1).astype(np.uint8)


def graph_fixture(n_genes=4, top_k=3, fold='A'):
    genes = tuple(chr(65+i) for i in range(n_genes))
    graph = DependencyGraphBuilder(top_k=top_k, min_abs_phi=.08, block_size=2).build(identical_binary(n_genes), genes, fold=fold)
    return genes, graph


def test_canonical_identity_and_provenance_merge():
    first = Candidate(('C', 'A', 'B'), 'A')
    second = Candidate(('B', 'A', 'C'), 'A')
    assert first.candidate_id == second.candidate_id == candidate_id(('A', 'B', 'C'))
    first.add_provenance('dependency', parent_ids=['parent1'], neighborhood_center='A')
    second.add_provenance('exploration', random_seed=42, sampling_probability=.01)
    first.merge(second)
    assert first.proposal_sources == ['dependency', 'exploration']
    assert first.generation_parent_ids == ['parent1']
    assert len(first.provenance) == 2
    with pytest.raises(ValueError):
        Candidate(('A', 'A'))


def test_fano_hvg_matches_sample_variance_dense_sparse_and_fold_ownership():
    rng = np.random.default_rng(87)
    counts = rng.poisson(np.linspace(.15, 2, 80), (150, 80))
    genes = tuple(f'G{i:03}' for i in range(80))
    before = select_hvgs(counts, genes, n_top=50, fold='A')
    sparse_result = select_hvgs(sparse.csr_matrix(counts), genes, n_top=50, fold='A')
    assert before.genes == sparse_result.genes
    assert before.table.selected.sum() == 50
    assert before.metadata['method'] == HVG_METHOD
    assert np.allclose(before.table.selection_metric, counts.var(axis=0, ddof=1)/counts.mean(axis=0))
    # An opposite-fold object has no route into this API or the selected result.
    opposite = counts[::-1].copy()
    opposite[:] = 0
    after = select_hvgs(counts, genes, n_top=50, fold='A')
    pd.testing.assert_frame_equal(before.table, after.table)
    assert set(before.table.fold) == {'A'}
    with pytest.raises(ValueError):
        select_hvgs(counts/2, genes, n_top=50)


def test_phi_blockwise_matches_correlation_and_streams_full_audit(tmp_path):
    rng = np.random.default_rng(42)
    binary = rng.binomial(1, .4, (127, 7)).astype(np.uint8)
    binary[:, -1] = 0
    genes = tuple(f'G{i}' for i in range(7))
    path = tmp_path/'all_pairs.csv'
    builder = DependencyGraphBuilder(top_k=2, min_abs_phi=.02, block_size=3)
    result = builder.build(binary, genes, audit_path=path)
    audit = pd.read_csv(path)
    assert len(audit) == math.comb(7, 2)
    correlations = np.corrcoef(binary[:, :-1], rowvar=False)
    for row in audit.itertuples():
        i, j = genes.index(row.gene_i), genes.index(row.gene_j)
        assert np.isclose(row.dependency_statistic, correlations[i, j] if j < 6 else 0)
    assert audit.selected_edge.sum() == len(result.edges)
    assert result.summary['n_pairs_examined'] == 21
    assert result.summary['max_neighborhood_size'] <= 3
    assert result.summary['constant_genes'] == ['G6']
    assert sum(map(len, result.summary['connected_components'])) == 7
    repeated = builder.build(sparse.csr_matrix(binary), genes)
    pd.testing.assert_frame_equal(result.edges, repeated.edges)
    assert result.neighborhoods == repeated.neighborhoods


def test_top_k_neighborhoods_remain_bounded_despite_incoming_hub():
    genes, graph = graph_fixture(20, top_k=3)
    assert max(graph.summary['node_degree'].values()) > 3
    assert all(len(members) <= 4 for members in graph.neighborhoods.values())
    assert all(len(graph.neighbors(gene)) <= 3 for gene in genes)
    assert graph.summary['n_edges'] <= len(genes)*3


def test_unranking_matches_small_exact_universe():
    for n in range(2, 12):
        for k in range(2, min(n, 4)+1):
            expected = list(itertools.combinations(range(n), k))
            actual = [unrank_combination(rank, n, k) for rank in range(len(expected))]
            assert actual == expected


def test_exploration_unique_reproducible_correct_inclusion_probability_at_1000():
    genes = tuple(f'G{i:04}' for i in range(1000))
    first, audit = sample_exploration(genes, 4, n_candidates=300, random_seed=19, fold='A')
    second, repeated = sample_exploration(genes[::-1], 4, n_candidates=300, random_seed=19, fold='A')
    assert [value.to_record() for value in first] == [value.to_record() for value in second]
    assert audit == repeated
    assert len({value.genes for value in first}) == 300
    assert audit['inclusion_probability'] == 300/math.comb(1000, 4)
    assert all(value.provenance[0]['n_sample'] == 300 for value in first)
    changed, _ = sample_exploration(genes, 4, n_candidates=300, random_seed=19, proposal_round=1)
    assert [value.genes for value in changed] != [value.genes for value in first]


def test_overlapping_neighborhoods_deduplicate_and_collect_actual_parent_lineage():
    genes, graph = graph_fixture()
    engine = CandidateProposalEngine(genes, graph, candidate_mode='dependency_only')
    pairs = engine.propose(2)
    triples = engine.propose(3, parents=pairs.candidates)
    assert len(triples.candidates) == 4
    for candidate in triples.candidates:
        expected = {candidate_id(pair) for pair in itertools.combinations(candidate.genes, 2)}
        assert set(candidate.generation_parent_ids) == expected
        assert {record['neighborhood_center'] for record in candidate.provenance} == set(genes)
    # Only the explicitly qualified triple supplies L4 lineage.
    parent = triples.candidates[0]
    quads = engine.propose(4, parents=[parent.to_record()])
    assert len(quads.candidates) == 1
    assert quads.candidates[0].generation_parent_ids == [parent.candidate_id]
    assert engine.propose(4, parents=[]).candidates == ()
    with pytest.raises(ValueError, match='explicit qualified'):
        engine.propose(4)


def test_lineage_uses_only_supplied_compatible_pair_not_all_possible_parents():
    genes, graph = graph_fixture()
    parent = Candidate(('A', 'B'), 'A')
    engine = CandidateProposalEngine(genes, graph, candidate_mode='dependency_only')
    triples = engine.propose(3, parents=[parent])
    assert {candidate.genes for candidate in triples.candidates} == {('A', 'B', 'C'), ('A', 'B', 'D')}
    assert all(candidate.generation_parent_ids == [parent.candidate_id] for candidate in triples.candidates)


def test_fixed_quotas_preserve_exploration_and_report_capped_unknown_remaining():
    genes, graph = graph_fixture(8)
    engine = CandidateProposalEngine(genes, graph, max_pair_candidates=6,
        exploration_fraction=.5, max_exploration_candidates_per_order=20, random_seed=9)
    batch = engine.propose(2)
    assert len(batch.candidates) <= 6
    assert batch.audit['status'] == 'budget_exhausted'
    assert batch.audit['dependency_quota'] == 3
    assert batch.audit['dependency_unique_observed'] == 4
    assert batch.audit['exploration']['n_sample'] == 3
    assert sum('exploration' in value.proposal_sources for value in batch.candidates) == 3
    assert batch.audit['exact_remaining_unknown']
    assert batch.audit['remaining'] is None
    assert len(batch.budget_pruned_candidates) == 1
    again = CandidateProposalEngine(genes, graph, max_pair_candidates=6,
        exploration_fraction=.5, max_exploration_candidates_per_order=20, random_seed=9).propose(2)
    assert [value.to_record() for value in batch.candidates] == [value.to_record() for value in again.candidates]


def test_cross_source_duplicates_keep_both_sources_without_re_evaluation():
    genes, graph = graph_fixture(3)
    engine = CandidateProposalEngine(genes, graph, max_pair_candidates=20,
        max_triplet_candidates=20, exploration_fraction=.5, max_exploration_candidates_per_order=20)
    pairs = engine.propose(2)
    assert len(pairs.candidates) == 3
    assert all(value.proposal_sources == ['dependency', 'exploration'] for value in pairs.candidates)
    triples = engine.propose(3, parents=pairs.candidates)
    assert len(triples.candidates) == 1
    assert triples.audit['both_source_candidates'] == 1
    assert not triples.audit['budget_exhausted']


def test_pure_three_way_is_absent_from_graph_but_has_exploration_path():
    states = np.asarray(list(itertools.product([0, 1], repeat=3)))
    repeats = np.where(states.sum(axis=1) % 2 == 0, 60, 20)
    binary = np.repeat(states, repeats, axis=0)
    genes = ('A', 'B', 'C')
    graph = DependencyGraphBuilder(top_k=2, min_abs_phi=.08).build(binary, genes)
    assert len(graph.edges) == 0  # Each bivariate marginal is exactly uniform.
    guided = CandidateProposalEngine(genes, graph, candidate_mode='dependency_only')
    assert guided.propose(2).candidates == ()
    assert guided.propose(3).candidates == ()
    exploratory = CandidateProposalEngine(genes, graph, candidate_mode='exploration_only',
        max_triplet_candidates=1, max_exploration_candidates_per_order=1)
    batch = exploratory.propose(3)
    assert [candidate.genes for candidate in batch.candidates] == [genes]
    assert batch.audit['exploration']['inclusion_probability'] == 1.
    assert not batch.audit['budget_exhausted']


@pytest.mark.parametrize('n_genes', [500, 1000])
def test_large_pool_never_enumerates_global_triples_or_quads(monkeypatch, n_genes):
    genes = tuple(f'G{i:04}' for i in range(n_genes))
    rng = np.random.default_rng(47)
    binary = rng.binomial(1, .5, (30, n_genes)).astype(np.uint8)
    graph = DependencyGraphBuilder(top_k=3, min_abs_phi=.08, block_size=64).build(binary, genes)
    original = itertools.combinations
    calls = []
    def bounded_combinations(values, k):
        values = tuple(values)
        calls.append((len(values), k))
        if k >= 3:
            assert len(values) <= 4, 'global higher-order enumeration detected'
        return original(values, k)
    monkeypatch.setattr(proposal_module, 'itertools', SimpleNamespace(combinations=bounded_combinations))
    engine = CandidateProposalEngine(genes, graph, max_pair_candidates=40,
        max_triplet_candidates=30, max_quad_candidates=12,
        exploration_fraction=.2, max_exploration_candidates_per_order=10)
    pairs = engine.propose(2)
    triples = engine.propose(3, parents=pairs.candidates)
    quads = engine.propose(4, parents=triples.candidates[:3])
    assert len(pairs.candidates) <= 40
    assert len(triples.candidates) <= 30
    assert len(quads.candidates) <= 12
    assert all(not batch.audit['global_higher_order_enumeration'] for batch in (pairs, triples, quads))
    assert graph.summary['max_neighborhood_size'] <= 4
    assert calls


def test_opposite_fold_graph_and_parents_are_rejected():
    genes, graph_b = graph_fixture(fold='B')
    with pytest.raises(ValueError, match='discovery fold'):
        CandidateProposalEngine(genes, graph_b, fold='A')
    _, graph_a = graph_fixture(fold='A')
    engine = CandidateProposalEngine(genes, graph_a, fold='A')
    with pytest.raises(ValueError, match='discovery fold'):
        engine.propose(3, parents=[Candidate(('A', 'B'), 'B')])
