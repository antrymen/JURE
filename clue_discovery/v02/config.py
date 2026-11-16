"""Separate v0.2 configuration; the v0.1 defaults and implementation stay intact."""
from dataclasses import asdict, dataclass, fields
import math
from ..config import DiscoveryConfig


@dataclass(frozen=True)
class ReferenceConfig(DiscoveryConfig):
    max_order: int = 7  # computational ceiling, never a required achieved order
    min_occupancy: float = 0.9
    min_observed_state_count: int = 3
    split_fractions: tuple[float, float, float] = (0.5, 0.25, 0.25)
    shift_fdr_scope: str = "all_perturbations"
    max_tests: int = 1_000_000

    def __post_init__(self):
        base = {f.name: getattr(self, f.name) for f in fields(DiscoveryConfig)}
        base['max_order'] = 3
        DiscoveryConfig(**base)  # reuse validation, without changing its order restriction
        if isinstance(self.max_order, bool) or not isinstance(self.max_order, int) or not 2 <= self.max_order <= 7:
            raise ValueError('max_order must be an integer from 2 to 7')
        if not math.isfinite(self.min_occupancy) or not 0 < self.min_occupancy <= 1:
            raise ValueError('min_occupancy must lie in (0, 1]')
        for key in ('min_observed_state_count', 'max_tests'):
            value = getattr(self, key)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f'{key} must be a positive integer')
        fractions = tuple(self.split_fractions)
        if len(fractions) != 3 or any(not math.isfinite(x) or x <= 0 for x in fractions) or not math.isclose(sum(fractions), 1):
            raise ValueError('split_fractions must contain three positive fractions summing to one')
        object.__setattr__(self, 'split_fractions', fractions)
        if self.shift_fdr_scope not in ('all_perturbations', 'per_perturbation'):
            raise ValueError('unknown shift_fdr_scope')


def config_dict(config):
    return asdict(config)
