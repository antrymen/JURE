"""Three reserved proposal channels, merged by canonical identity."""
from ..v03.proposal import CandidateProposalEngine as LegacyEngine, ProposalBatch
from .fingerprint import screen_triplets


class CandidateProposalEngine:
    def __init__(self, genes, graph, binary, config, *, fold, random_seed):
        self.genes, self.binary, self.config, self.fold = tuple(genes), binary, config, fold
        self.quota = config.fingerprint_quota
        self.base = LegacyEngine(genes, graph, candidate_mode=config.candidate_mode,
            random_seed=random_seed, exploration_fraction=config.exploration_fraction,
            max_exploration_candidates_per_order=min(config.max_exploration_candidates_per_order,
                config.max_exploration_candidates//(config.max_order-1)),
            max_pair_candidates=config.max_pair_candidates,
            max_triplet_candidates=config.max_triplet_candidates-self.quota,
            max_quad_candidates=config.max_quad_candidates, fold=fold)
        self.fingerprint_audit = None

    def propose(self, order, *, parents=None):
        base = self.base.propose(order, parents=parents)
        if order != 3 or not self.quota:
            return base
        added, audit = screen_triplets(self.binary, self.genes, self.config,
                                       fold=self.fold, quota=self.quota)
        self.fingerprint_audit = audit
        selected = {candidate.genes: candidate for candidate in base.candidates}
        for candidate in added:
            if candidate.genes in selected:
                selected[candidate.genes].merge(candidate)
            else:
                selected[candidate.genes] = candidate
        candidates = tuple(selected[genes] for genes in sorted(selected))
        # A formerly rejected guided tuple may now be retained by the new channel.
        rejected = tuple(c for c in base.budget_pruned_candidates if c.genes not in selected)
        exhausted = base.audit['budget_exhausted'] or audit['budget_exhausted']
        merged = dict(base.audit, budget=self.config.max_triplet_candidates,
            status='budget_exhausted' if exhausted else 'complete', budget_exhausted=exhausted,
            proposed=len(candidates), generated=len({c.genes for c in candidates+rejected}),
            generated_count_is_lower_bound=True, exact_remaining_unknown=True, remaining=None,
            pruned=len(rejected), pruned_budget=len(rejected),
            remaining_lower_bound=len(rejected),
            budget_pruned_candidate_ids=[c.candidate_id for c in rejected],
            higher_order_fingerprint_quota=self.quota,
            higher_order_fingerprint_candidates=len(added),
            higher_order_fingerprint_audit={k: v for k, v in audit.items()
                                           if k not in ('bands', 'screened_records')},
            source_budget_policy='reserved_fingerprint_plus_legacy_quotas_no_refill',
            generated_scope='retained_union_plus_observed_guided_rejections; fingerprint_screen_counts_separate')
        for name, sources in [('dependency_only_candidates', ['dependency']),
                              ('exploration_only_candidates', ['exploration']),
                              ('both_source_candidates', ['dependency', 'exploration'])]:
            merged[name] = sum(c.proposal_sources == sources for c in candidates)
        self.base._history[order] = candidates
        assert len(candidates) <= self.config.max_triplet_candidates
        return ProposalBatch(candidates, merged, rejected)
