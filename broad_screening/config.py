from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Config:
    version: str = 'broad_screening_v01'
    seed: int = 20260927
    bootstrap_repetitions: int = 50
    bootstrap_enabled: bool = True
    stable_core_enabled: bool = True
    clustering_cut: float = 0.30
    sensitivity_cuts: tuple = (0.20, 0.40, 0.50)
    stable_core_pair_probability: float = 0.80
    stable_core_min_size: int = 2
    high_effect_pp: float = 20.0
    high_target_support_cells: int = 300
    sample_size_context_cells: int = 150
    strong_module_activity_pp: float = 10.0
    module_specificity_min: float = 0.50
    context_pearson_min: float = 0.80
    context_spearman_min: float = 0.70
    context_shared_candidates_min: int = 5
    contrast_pearson_max: float = -0.50
    robustness_jaccard_min: float = 0.50
    robustness_centroid_min: float = 0.80
    robustness_core_recovery_min: float = 0.70
    top_pairs: int = 50
    main_cards: int = 4
    dpi: int = 300

    def validate(self):
        if self.bootstrap_enabled and self.bootstrap_repetitions < 2:
            raise ValueError('Use at least two bootstrap replicates or explicitly disable bootstrap')
        if not 0 < self.clustering_cut < 2:
            raise ValueError('clustering_cut must be between 0 and 2')
        if not 0 < self.stable_core_pair_probability <= 1:
            raise ValueError('core probability must be in (0,1]')
        if self.stable_core_min_size < 2:
            raise ValueError('Singletons cannot establish pairwise core stability')
        return self

    def to_dict(self):
        return asdict(self)
