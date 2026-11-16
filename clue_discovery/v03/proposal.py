"""Bounded dependency/exploration proposals with explicit candidate accounting."""
from __future__ import annotations

from dataclasses import dataclass
import itertools
import json
import math

import pandas as pd

from .candidate import Candidate, canonical_genes, candidate_id
from .exploration import sample_exploration


@dataclass
class ProposalBatch:
    candidates: tuple[Candidate, ...]
    audit: dict
    budget_pruned_candidates: tuple[Candidate, ...] = ()

    def to_frame(self) -> pd.DataFrame:
        columns = ['candidate_id', 'genes', 'order', 'proposal_sources', 'proposal_fold',
                   'generation_parent_ids', 'provenance']
        records = [candidate.to_record() for candidate in self.candidates]
        return pd.DataFrame(records, columns=columns)


def _parent(value, *, fold):
    if isinstance(value, Candidate):
        if value.proposal_fold != str(fold):
            raise ValueError('parents must belong to the current discovery fold')
        return value
    if isinstance(value, dict):
        genes = value['genes']
        if isinstance(genes, str):
            genes = json.loads(genes)
        candidate = Candidate(tuple(genes), str(value.get('proposal_fold', fold)))
        if candidate.proposal_fold != str(fold):
            raise ValueError('parents must belong to the current discovery fold')
        if value.get('candidate_id', candidate.candidate_id) != candidate.candidate_id:
            raise ValueError('parent ID does not match canonical genes')
        return candidate
    return Candidate(tuple(value), str(fold))


class CandidateProposalEngine:
    """Propose candidates without testing data or making significance claims.

    Exploration has a fixed reserved quota, never filled adaptively after seeing
    a result. Dependency generation is lazy and stops at the first extra unique
    candidate past its own quota. Only consumed/retained paths are documented.
    The remaining guided universe is explicitly unknown after truncation.
    """
    def __init__(self, genes, graph=None, *, candidate_mode='hybrid', random_seed=20260927,
                 exploration_fraction=.2, max_exploration_candidates_per_order=300,
                 max_pair_candidates=4000, max_triplet_candidates=4000,
                 max_quad_candidates=1000, proposal_round=0, fold='A'):
        self.genes = canonical_genes(genes)
        if candidate_mode not in {'dependency_only', 'exploration_only', 'hybrid'}:
            raise ValueError('invalid candidate_mode')
        if not 0 <= exploration_fraction <= 1:
            raise ValueError('exploration_fraction must be between zero and one')
        for value in (random_seed, max_exploration_candidates_per_order,
                      max_pair_candidates, max_triplet_candidates, max_quad_candidates,
                      proposal_round):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError('candidate budgets, seed and round must be nonnegative integers')
        if graph is not None and set(graph.nodes) != set(self.genes):
            raise ValueError('proposal graph nodes must exactly match this discovery HVG pool')
        if graph is not None and str(graph.summary.get('fold', fold)) != str(fold):
            raise ValueError('proposal graph must belong to this discovery fold')
        self.graph, self.candidate_mode, self.random_seed = graph, candidate_mode, random_seed
        self.exploration_fraction = float(exploration_fraction)
        self.max_exploration = max_exploration_candidates_per_order
        self.budgets = {2: max_pair_candidates, 3: max_triplet_candidates, 4: max_quad_candidates}
        self.proposal_round, self.fold = proposal_round, str(fold)
        self._history = {}
        self._neighborhood_sets = ({gene: set(values) for gene, values in graph.neighborhoods.items()}
                                   if graph is not None else {})
        self._gene_centers = {gene: set() for gene in self.genes}
        for center, members in self._neighborhood_sets.items():
            for gene in members:
                self._gene_centers[gene].add(center)

    def _routes(self, genes, parents):
        """Complete actual local generation paths for an already retained tuple."""
        if self.graph is None:
            return
        order = len(genes)
        if order == 2:
            for center in genes:
                if set(genes).issubset(self._neighborhood_sets[center]):
                    yield {'neighborhood_center': center, 'generation_parent_ids': [],
                           'proposal_path': 'selected_dependency_edge'}
        elif order == 3:
            parent_ids = sorted(parents[pair].candidate_id for pair in itertools.combinations(genes, 2) if pair in parents)
            if not parent_ids:
                return
            centers = set.intersection(*(self._gene_centers[gene] for gene in genes))
            for center in sorted(centers):
                yield {'neighborhood_center': center, 'generation_parent_ids': parent_ids,
                       'proposal_path': 'compatible_pair_in_bounded_neighborhood'}
        elif order == 4:
            for parent_genes in itertools.combinations(genes, 3):
                if parent_genes not in parents:
                    continue
                added = next(gene for gene in genes if gene not in parent_genes)
                for center in parent_genes:
                    if added in self.graph.neighbors(center):
                        yield {'neighborhood_center': center,
                               'generation_parent_ids': [parents[parent_genes].candidate_id],
                               'added_gene': added,
                               'proposal_path': 'qualified_triplet_outbound_neighbor_extension'}

    def _dependency_candidates(self, order, parents):
        if self.graph is None:
            return
        if order == 2:
            rows = self.graph.edges.sort_values(['dependency_strength', 'gene_i', 'gene_j'], ascending=[False, True, True])
            for row in rows.itertuples(index=False):
                candidate = Candidate((row.gene_i, row.gene_j), self.fold)
                candidate.add_provenance('dependency', dependency_method='binary_phi',
                    dependency_statistic=float(row.dependency_statistic),
                    dependency_strength=float(row.dependency_strength),
                    proposal_path='selected_dependency_edge')
                yield candidate
        elif order == 3:
            # Enumerate only bounded neighborhoods; never combinations(self.genes,3).
            for center in sorted(self._neighborhood_sets):
                members = tuple(sorted(self._neighborhood_sets[center]))
                for genes in itertools.combinations(members, 3):
                    parent_ids = sorted(parents[pair].candidate_id for pair in itertools.combinations(genes, 2) if pair in parents)
                    if parent_ids:
                        candidate = Candidate(genes, self.fold)
                        candidate.add_provenance('dependency', parent_ids=parent_ids,
                            neighborhood_center=center, proposal_path='compatible_pair_in_bounded_neighborhood')
                        yield candidate
        elif order == 4:
            for parent_genes, parent in sorted(parents.items()):
                for center in parent_genes:
                    for neighbor in self.graph.neighbors(center):
                        if neighbor not in parent_genes:
                            candidate = Candidate(parent_genes + (neighbor,), self.fold)
                            candidate.add_provenance('dependency', parent_ids=[parent.candidate_id],
                                neighborhood_center=center, added_gene=neighbor,
                                proposal_path='qualified_triplet_outbound_neighbor_extension')
                            yield candidate

    def propose(self, order, *, parents=None) -> ProposalBatch:
        if order not in self.budgets:
            raise ValueError('v0.3 proposal orders are 2, 3 and 4')
        if parents is None:
            if order == 4:
                raise ValueError('order 4 requires explicit qualified L3 parents (empty is allowed)')
            parents = self._history.get(order-1, ())
        parent_records = [_parent(value, fold=self.fold) for value in parents]
        if any(value.order != order-1 or not set(value.genes).issubset(self.genes) for value in parent_records):
            raise ValueError('parents must have order k-1 and belong to this HVG pool')
        parent_map = {value.genes: value for value in parent_records}
        budget = self.budgets[order]
        exploration_quota = 0
        if self.candidate_mode == 'exploration_only':
            exploration_quota = min(budget, self.max_exploration)
        elif self.candidate_mode == 'hybrid':
            exploration_quota = min(self.max_exploration, int(math.ceil(budget*self.exploration_fraction)))
        exploration, exploration_audit = sample_exploration(self.genes, order,
            n_candidates=exploration_quota, random_seed=self.random_seed,
            proposal_round=self.proposal_round, fold=self.fold)
        guided_budget = (0 if self.candidate_mode == 'exploration_only' else budget-exploration_quota)
        selected = {candidate.genes: candidate for candidate in exploration}
        guided_seen, rejected = set(), []
        overflow_candidate = None
        consumed_paths, exhausted = 0, False
        if self.candidate_mode != 'exploration_only':
            for candidate in self._dependency_candidates(order, parent_map):
                consumed_paths += 1
                if candidate.genes not in guided_seen:
                    guided_seen.add(candidate.genes)
                    if len(guided_seen) > guided_budget:
                        overflow_candidate = candidate
                        if candidate.genes not in selected:
                            rejected.append(candidate)
                        exhausted = True
                        break
                if candidate.genes in selected:
                    selected[candidate.genes].merge(candidate)
                else:
                    selected[candidate.genes] = candidate
            # Complete provenance for retained guided tuples using only their
            # bounded local witnesses, without generating any additional tuple.
            for candidate in selected.values():
                if 'dependency' in candidate.proposal_sources:
                    for route in self._routes(candidate.genes, parent_map):
                        parent_ids = route.pop('generation_parent_ids')
                        candidate.add_provenance('dependency', parent_ids=parent_ids, **route)
        candidates = tuple(selected[genes] for genes in sorted(selected))
        self._history[order] = candidates
        generated = len(set(selected) | {candidate.genes for candidate in rejected})
        remaining_lower = len({candidate.genes for candidate in rejected}-set(selected))
        audit = {'order': order, 'fold': self.fold, 'candidate_mode': self.candidate_mode,
                 'status': 'budget_exhausted' if exhausted else 'complete',
                 'budget_exhausted': exhausted, 'budget': budget,
                 'generated': generated, 'evaluated': 0, 'proposed': len(candidates),
                 'pruned': len(rejected), 'pruned_budget': len(rejected),
                 'remaining': None if exhausted else 0,
                 'remaining_lower_bound': remaining_lower,
                 'exact_remaining_unknown': exhausted,
                 'generated_count_is_lower_bound': exhausted,
                 'dependency_unique_observed': len(guided_seen),
                 'dependency_quota': guided_budget, 'dependency_paths_consumed': consumed_paths,
                 'dependency_remaining_lower_bound': 1 if exhausted else 0,
                 'exploration_quota': exploration_quota, 'exploration': exploration_audit,
                 'budget_pruned_candidate_ids': [value.candidate_id for value in rejected],
                 'dependency_overflow_candidate_id': (overflow_candidate.candidate_id if overflow_candidate else None),
                 'dependency_overflow_already_selected_by_exploration': bool(overflow_candidate and overflow_candidate.genes in selected),
                 'dependency_only_candidates': sum(value.proposal_sources == ['dependency'] for value in candidates),
                 'exploration_only_candidates': sum(value.proposal_sources == ['exploration'] for value in candidates),
                 'both_source_candidates': sum(set(value.proposal_sources) == {'dependency', 'exploration'} for value in candidates),
                 'source_budget_policy': 'fixed_reserved_quotas_no_adaptive_refill',
                 'provenance_scope': 'consumed_paths_plus_retained_local_generation_witnesses',
                 'full_global_order_universe': math.comb(len(self.genes), order) if order <= len(self.genes) else 0,
                 'global_higher_order_enumeration': False,
                 'sampling_only_does_not_imply_global_coverage': True}
        return ProposalBatch(candidates, audit, tuple(rejected))
