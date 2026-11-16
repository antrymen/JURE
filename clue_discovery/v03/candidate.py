"""Canonical gene-set identity and bounded proposal provenance.

A candidate is an evaluation suggestion, not a detected biological interaction.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from typing import Iterable


def canonical_genes(genes: Iterable[str]) -> tuple[str, ...]:
    values = tuple(str(gene) for gene in genes)
    if not values or len(set(values)) != len(values):
        raise ValueError('candidate genes must be nonempty and unique')
    return tuple(sorted(values))


def candidate_id(genes: Iterable[str]) -> str:
    payload = json.dumps(canonical_genes(genes), separators=(',', ':'), ensure_ascii=False)
    return 'GS_' + hashlib.sha256(payload.encode()).hexdigest()[:24]


@dataclass
class Candidate:
    genes: tuple[str, ...]
    proposal_fold: str = ''
    proposal_sources: list[str] = field(default_factory=list)
    generation_parent_ids: list[str] = field(default_factory=list)
    provenance: list[dict] = field(default_factory=list)

    def __post_init__(self):
        self.genes = canonical_genes(self.genes)
        self.proposal_sources = sorted(set(self.proposal_sources))
        self.generation_parent_ids = sorted(set(self.generation_parent_ids))

    @property
    def candidate_id(self) -> str:
        return candidate_id(self.genes)

    @property
    def order(self) -> int:
        return len(self.genes)

    def add_provenance(self, source: str, *, parent_ids=(), **details):
        self.proposal_sources = sorted(set(self.proposal_sources) | {source})
        self.generation_parent_ids = sorted(set(self.generation_parent_ids) | set(parent_ids))
        record = {'proposal_type': source, 'generation_parent_ids': sorted(set(parent_ids)), **details}
        if record not in self.provenance:
            self.provenance.append(record)

    def merge(self, other: 'Candidate'):
        if self.genes != other.genes or self.proposal_fold != other.proposal_fold:
            raise ValueError('only identical candidates in the same fold can be merged')
        self.proposal_sources = sorted(set(self.proposal_sources) | set(other.proposal_sources))
        self.generation_parent_ids = sorted(set(self.generation_parent_ids) | set(other.generation_parent_ids))
        for record in other.provenance:
            if record not in self.provenance:
                self.provenance.append(record)
        return self

    def to_record(self) -> dict:
        return {'candidate_id': self.candidate_id, 'genes': list(self.genes), 'order': self.order,
                'proposal_sources': list(self.proposal_sources), 'proposal_fold': self.proposal_fold,
                'generation_parent_ids': list(self.generation_parent_ids),
                'provenance': list(self.provenance)}
