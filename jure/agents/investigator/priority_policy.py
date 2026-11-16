"""Explainable ordinal rules. No information-gain or weighted-score fiction."""
from __future__ import annotations

from typing import Literal

Ordinal = Literal["high", "medium", "low"]
Redundancy = Literal["none", "partial", "high"]


def priority_class(*, discriminative_value: Ordinal, answerability: Ordinal,
                   estimated_cost: Ordinal, redundancy: Redundancy) -> Ordinal:
    if discriminative_value == "low" or answerability == "low":
        result = "low"
    elif discriminative_value == "high" and answerability == "high" and estimated_cost != "high":
        result = "high"
    elif discriminative_value == "high" and answerability == "medium" and estimated_cost == "low":
        result = "high"
    else:
        result = "medium"
    if redundancy == "high":
        return {"high": "medium", "medium": "low", "low": "low"}[result]
    return result


def priority_sort_key(assessment, *, manual_order: int | None = None,
                      verifies_new_evidence: bool = False):
    """Lexicographic policy; tie-breaking never uses queue creation order."""
    ordinal = {"high": 0, "medium": 1, "low": 2}
    return (0 if manual_order is not None else 1,
            manual_order if manual_order is not None else 0,
            ordinal[assessment.priority_class],
            ordinal[assessment.discriminative_value],
            0 if verifies_new_evidence else 1,
            ordinal[assessment.answerability],
            ordinal[assessment.directness_potential],
            {"low": 0, "medium": 1, "high": 2}[assessment.estimated_cost],
            {"none": 0, "partial": 1, "high": 2}[assessment.redundancy],
            assessment.question_id)
