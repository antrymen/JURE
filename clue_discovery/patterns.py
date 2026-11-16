from dataclasses import dataclass
from itertools import combinations


@dataclass(frozen=True, order=True)
class JointPattern:
    genes: tuple[str, ...]
    states: tuple[int, ...]

    def __post_init__(self):
        if not self.genes or len(self.genes) != len(self.states):
            raise ValueError("genes and states must have equal nonzero length")
        if any(not isinstance(g, str) or not g for g in self.genes):
            raise ValueError("gene names must be nonempty strings")
        if len(set(self.genes)) != len(self.genes) or any(s not in (0, 1) for s in self.states):
            raise ValueError("genes must be unique and states binary")
        pairs = sorted(zip(self.genes, self.states))
        object.__setattr__(self, "genes", tuple(g for g, _ in pairs))
        object.__setattr__(self, "states", tuple(int(s) for _, s in pairs))

    @property
    def order(self):
        return len(self.genes)

    def canonicalize(self):
        return self

    def subpatterns(self, order=None):
        order = self.order - 1 if order is None else order
        if not 1 <= order < self.order:
            raise ValueError("subset order must be in [1, pattern.order)")
        return tuple(JointPattern(tuple(self.genes[i] for i in ix),
                                  tuple(self.states[i] for i in ix))
                     for ix in combinations(range(self.order), order))

    def to_string(self):
        return "".join(g + ("+" if s else "-") for g, s in zip(self.genes, self.states))


def merge_patterns(left, right):
    if left.order != right.order:
        return None
    merged = dict(zip(left.genes, left.states))
    for gene, state in zip(right.genes, right.states):
        if gene in merged and merged[gene] != state:
            return None
        merged[gene] = state
    if len(merged) != left.order + 1:
        return None
    return JointPattern(tuple(merged), tuple(merged.values()))
