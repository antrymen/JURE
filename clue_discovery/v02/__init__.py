"""Reference-guided v0.2 plus an explicit adapter to the untouched v0.1 baseline."""
from dataclasses import dataclass
from ..discovery import discover_clues
from .config import ReferenceConfig
from .populations import Population, split_reference
from .reference import FrozenCatalogue, ReferenceResult, fit_reference
from .testing import ShiftResult, test_perturbations

__version__ = '0.2.0'


@dataclass
class ReferenceGuidedResult:
    reference: ReferenceResult
    testing: ShiftResult

    def write(self, output_dir):
        self.reference.write(output_dir)
        return self.testing.write(output_dir)


def reference_guided(nt, perturbations, *, candidate_genes, config=None, strata=None):
    config = ReferenceConfig() if config is None else config
    discovery, validation, test = split_reference(nt, config, strata)
    result = fit_reference(discovery, validation, test, candidate_genes=candidate_genes, config=config)
    return ReferenceGuidedResult(result, test_perturbations(result.catalogue, test, perturbations))


def run_discovery(*, mode='reference_guided', **kwargs):
    if mode == 'reference_guided':
        return reference_guided(**kwargs)
    if mode == 'perturbation_emergent':
        if isinstance(kwargs.get('config'), ReferenceConfig):
            raise TypeError('perturbation_emergent uses the unchanged v0.1 DiscoveryConfig')
        result = discover_clues(**kwargs)
        result.metadata.update(mode=mode, baseline_version='0.1.0',
                               mode_caveat='Exploratory de novo channel; v0.1 does not establish absence of interaction in NT')
        return result
    raise ValueError('mode must be reference_guided or perturbation_emergent')


__all__ = ['ReferenceConfig', 'Population', 'split_reference', 'fit_reference', 'FrozenCatalogue',
           'test_perturbations', 'reference_guided', 'run_discovery', 'ReferenceGuidedResult']
