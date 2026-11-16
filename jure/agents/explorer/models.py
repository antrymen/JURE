"""Transient Explorer proposals, configuration and run artifacts.

The authoritative investigation state remains :mod:`jure.casefile`.  These
models describe an untrusted backend response until the Explorer validates and
commits it through the existing Case Store API.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from jure.casefile.models import FrozenModel, Identifier, ObjectReference, Text
from jure.protocol.contracts import DiscriminationSpec


ExplorerMode = Literal["initial", "reframe"]


class ExplorerConfig(FrozenModel):
    min_hypotheses: Annotated[int, Field(ge=2, le=16, strict=True)] = 2
    max_hypotheses: Annotated[int, Field(ge=2, le=16, strict=True)] = 4
    max_retries: Annotated[int, Field(ge=0, le=5, strict=True)] = 2
    max_context_chars: Annotated[int, Field(ge=1, le=1_000_000, strict=True)] = 60_000
    max_response_chars: Annotated[int, Field(ge=1, le=1_000_000, strict=True)] = 60_000
    round_budget_basis: Literal['started', 'completed'] = 'started'
    protocol_v3: bool = False
    validation_policy: Literal["legacy", "three_layer"] = "legacy"

    @model_validator(mode="after")
    def ordered_hypothesis_limits(self) -> ExplorerConfig:
        if self.validation_policy == "three_layer" and not self.protocol_v3:
            raise ValueError("three_layer admission requires protocol_v3")
        if self.min_hypotheses > self.max_hypotheses:
            raise ValueError("min_hypotheses must not exceed max_hypotheses")
        return self


class MechanismStructure(FrozenModel):
    """Inspectable structure for redundancy checks, not a fixed class taxonomy."""

    causal_structure: Text
    directness: Literal["direct", "indirect", "mixed", "unspecified"]
    cell_state_explanation: Annotated[bool, Field(strict=True)]
    conditional_dependence: Annotated[bool, Field(strict=True)]
    directed_edges: tuple[tuple[Text, Text], ...] = ()
    distinguishing_features: tuple[Text, ...] = ()


class HypothesisProposal(FrozenModel):
    hypothesis_id: Identifier
    operation: Literal["add", "revise"] = "add"
    title: Text
    mechanism_statement: Text
    mechanism_type: Text
    assumptions: tuple[Text, ...] = ()
    unresolved_points: tuple[Text, ...] = ()
    weakening_conditions: tuple[Text, ...] = ()
    derived_from_clue_id: Identifier
    derived_from: tuple[ObjectReference, ...] = ()
    status: Literal["proposed"] = "proposed"
    reason: Text | None = None
    structure: MechanismStructure


class PredictionProposal(FrozenModel):
    prediction_id: Identifier
    hypothesis_id: Identifier
    statement: Text
    expected_if_true: Text
    weakened_if_observed: Text
    discriminates_from_hypotheses: tuple[Identifier, ...] = ()
    status: Literal["untested"] = "untested"


class LegacyDiscriminationSpec(DiscriminationSpec):
    @model_validator(mode="after")
    def distinct_expectations(self):
        if len({x.prediction.strip() for x in self.expectations}) < 2:
            raise ValueError("A comparison needs distinct conditional expectations")
        return self


class EvidenceQuestionProposal(FrozenModel):
    question_id: Identifier
    question_text: Text
    derived_from_prediction_ids: tuple[Identifier, ...] = ()
    relevant_hypothesis_ids: tuple[Identifier, ...] = ()
    discriminates_between: tuple[Identifier, ...] = ()
    suggested_evidence_type: Literal["dataset", "network", "literature", "unknown"] = "unknown"
    status: Literal["pending"] = "pending"
    discrimination: LegacyDiscriminationSpec | None = None


class HypothesisContrast(FrozenModel):
    hypothesis_a: Identifier
    hypothesis_b: Identifier
    difference: Text


class PairDecision(FrozenModel):
    hypothesis_a: Identifier
    hypothesis_b: Identifier
    status: Literal['RELEVANT_TO_DISTINGUISH', 'NOT_CURRENTLY_INFORMATIVE']
    reason: Text


class ExplorerOutput(FrozenModel):
    observation_interpretation: Text
    mechanistic_question: Text
    hypotheses: tuple[HypothesisProposal, ...]
    predictions: tuple[PredictionProposal, ...]
    evidence_questions: tuple[EvidenceQuestionProposal, ...]
    contrasts: tuple[HypothesisContrast, ...]
    warnings: tuple[Text, ...] = ()
    pair_decisions: tuple[PairDecision, ...] = ()


class ExplorerRunResult(FrozenModel):
    run_id: Identifier
    case_id: Identifier
    mode: ExplorerMode
    success: bool
    observation_interpretation: str = ""
    mechanistic_question_id: Identifier | None = None
    created_hypothesis_ids: tuple[Identifier, ...] = ()
    created_prediction_ids: tuple[Identifier, ...] = ()
    created_evidence_question_ids: tuple[Identifier, ...] = ()
    revised_hypothesis_ids: tuple[Identifier, ...] = ()
    warnings: tuple[Text, ...] = ()
    validation_errors: tuple[Text, ...] = ()
    admission_checks: tuple[dict, ...] = ()
    attempts: Annotated[int, Field(ge=0, strict=True)] = 0
    source_case_revision: Annotated[int, Field(ge=1, strict=True)]
    committed_case_revision: Annotated[int, Field(ge=1, strict=True)] | None = None
    artifact_path: str | None = None
