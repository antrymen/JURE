"""Immutable, typed investigation state for Shared Case File v0.1.

Models hold observations and recorded decisions; they perform no reasoning,
evidence retrieval, scoring, or routing. Cross-object checks live in validation.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterator, Mapping
from datetime import datetime, timezone
from typing import Annotated, Any, Literal
from uuid import uuid4

from pydantic import (
    AwareDatetime, BaseModel, ConfigDict, Field, FiniteFloat,
    StringConstraints, field_validator, model_validator,
)
from pydantic_core import core_schema


def new_id(prefix: str) -> str:
    """Return a stable-once-created identifier with a readable type prefix."""
    import re

    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.:-]*", prefix):
        raise ValueError("ID prefix must begin with a letter and contain ID characters")
    return f"{prefix}_{uuid4().hex}"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class FrozenJSON(Mapping[str, Any]):
    """A deeply immutable JSON object with detached reads and normal JSON output.

    Retaining canonical text, rather than nested mutable containers, also makes
    caller-owned input dictionaries safe to reuse after constructing a record.
    """

    __slots__ = ("_json",)

    def __init__(self, value: Mapping[str, Any] | FrozenJSON | None = None) -> None:
        if isinstance(value, FrozenJSON):
            encoded = value._json
        else:
            value = {} if value is None else value
            if not isinstance(value, Mapping):
                raise ValueError("FrozenJSON requires a JSON object")

            def check(item: Any) -> Any:
                if isinstance(item, Mapping):
                    if any(not isinstance(key, str) for key in item):
                        raise ValueError("JSON object keys must be strings")
                    return {key: check(child) for key, child in item.items()}
                if isinstance(item, (list, tuple)):
                    return [check(child) for child in item]
                if item is None or isinstance(item, (str, bool, int)):
                    return item
                if isinstance(item, float) and math.isfinite(item):
                    return item
                raise ValueError("Metadata must contain only finite JSON values")

            encoded = json.dumps(check(value), sort_keys=True, separators=(",", ":"),
                                 ensure_ascii=False, allow_nan=False)
        object.__setattr__(self, "_json", encoded)

    def __setattr__(self, name: str, value: Any) -> None:
        raise TypeError("FrozenJSON is immutable")

    def __delattr__(self, name: str) -> None:
        raise TypeError("FrozenJSON is immutable")

    def to_dict(self) -> dict[str, Any]:
        return json.loads(self._json)

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.to_dict())

    def __len__(self) -> int:
        return len(self.to_dict())

    def __repr__(self) -> str:
        return f"FrozenJSON({self._json})"

    def __copy__(self) -> FrozenJSON:
        return self

    def __deepcopy__(self, memo: dict[int, Any]) -> FrozenJSON:
        return self

    @classmethod
    def __get_pydantic_core_schema__(cls, source_type: Any, handler: Any) -> Any:
        return core_schema.no_info_plain_validator_function(
            lambda value: value if isinstance(value, cls) else cls(value),
            serialization=core_schema.plain_serializer_function_ser_schema(
                lambda value: value.to_dict(), return_schema=core_schema.dict_schema(),
            ),
        )

    @classmethod
    def __get_pydantic_json_schema__(cls, schema: Any, handler: Any) -> dict[str, Any]:
        return {"type": "object", "additionalProperties": True}


Identifier = Annotated[str, StringConstraints(pattern=r"^[A-Za-z][A-Za-z0-9_.:-]*$")]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Probability = Annotated[FiniteFloat, Field(ge=0, le=1)]
Count = Annotated[int, Field(ge=0, strict=True)]
Actor = Literal["explorer", "investigator", "evidence_investigator", "critic", "controller", "system", "human"]
HypothesisStatus = Literal["proposed", "active", "modified", "challenged", "rejected", "retained",
                           "supported", "partially_supported", "insufficient"]
PredictionStatus = Literal["untested", "queued", "partially_tested", "tested", "unresolved"]
QuestionStatus = Literal["pending", "selected", "in_progress", "answered", "partially_answered", "unresolved", "cancelled"]
ObjectType = Literal[
    "case", "clue", "mechanistic_question", "question_revision", "hypothesis",
    "hypothesis_revision", "prediction", "evidence_question", "evidence",
    "evidence_record", "evidence_assessment", "evidence_gap", "contradiction", "history_event",
    "mechanistic_claim", "hypothesis_audit", "evidence_audit", "claim_audit", "hypothesis_synthesis",
    "routing_decision", "stop_record", "revision_request", "investigation_request",
    "hypothesis_status_change", "progress_snapshot", "final_report", "failure_attribution",
    "recommended_experiment",
]


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", validate_default=True,
                              allow_inf_nan=False)


class CaseMetadata(FrozenModel):
    case_id: Identifier = Field(default_factory=lambda: new_id("CASE"))
    created_at: AwareDatetime = Field(default_factory=utc_now)
    updated_at: AwareDatetime = Field(default_factory=utc_now)
    schema_version: Literal["0.1.0", "0.1.1"] = "0.1.1"
    project: Literal["JURE"] = "JURE"
    case_revision: Annotated[int, Field(ge=1, strict=True)] = 1
    source_dataset: Text | None = None
    cell_context: Text | None = None
    perturbation: Text | None = None

    @model_validator(mode="after")
    def chronological(self) -> CaseMetadata:
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must not precede created_at")
        return self


class PatternRecord(FrozenModel):
    genes: tuple[Text, ...]
    states: tuple[Literal[0, 1], ...]
    order: Annotated[int, Field(ge=1, strict=True)]
    pattern_string: Text
    encoding: Text = "1 = detected expression; 0 = undetected expression (not inferred regulatory activity)"

    @field_validator("states", mode="before")
    @classmethod
    def binary_integers(cls, value: Any) -> Any:
        if not isinstance(value, (list, tuple)) or any(type(state) is not int for state in value):
            raise ValueError("pattern states must be binary integers, not floats or booleans")
        return value

    @model_validator(mode="after")
    def consistent_pattern(self) -> PatternRecord:
        if self.order != len(self.genes) or self.order != len(self.states):
            raise ValueError("pattern order must equal both genes and states lengths")
        if len(set(self.genes)) != len(self.genes):
            raise ValueError("pattern genes must be unique")
        displayed = "".join(gene + ("+" if state else "-") for gene, state in zip(self.genes, self.states))
        if self.pattern_string != displayed:
            raise ValueError("pattern_string must agree with ordered genes and states (+ detected, - undetected)")
        return self


class BootstrapSummary(FrozenModel):
    ci_low: FiniteFloat | None = None
    ci_high: FiniteFloat | None = None
    sign_stability: Probability | None = None

    @model_validator(mode="after")
    def ordered_interval(self) -> BootstrapSummary:
        if self.ci_low is not None and self.ci_high is not None and self.ci_low > self.ci_high:
            raise ValueError("bootstrap ci_low must not exceed ci_high")
        return self


class StatisticalEvidence(FrozenModel):
    mfi: FiniteFloat | None = None
    log2_enrichment: FiniteFloat | None = None
    p_value_null: Probability | None = None
    q_value_null: Probability | None = None
    expected_count: Annotated[FiniteFloat, Field(ge=0)] | None = None
    bootstrap: BootstrapSummary | None = None
    enrichment_bootstrap: BootstrapSummary | None = None


class ReferenceEvidence(FrozenModel):
    discovery: StatisticalEvidence | None = None
    validation: StatisticalEvidence | None = None


class ShiftEvidence(FrozenModel):
    control_frequency: Probability
    perturb_frequency: Probability
    delta_frequency: Annotated[FiniteFloat, Field(ge=-1, le=1)]
    control_count: Count
    perturb_count: Count
    p_value_shift: Probability | None = None
    q_value_shift: Probability | None = None
    support: Count | None = None
    status: Text = "unknown"
    bootstrap: BootstrapSummary | None = None

    @model_validator(mode="after")
    def consistent_statistics(self) -> ShiftEvidence:
        if not math.isclose(self.delta_frequency, self.perturb_frequency - self.control_frequency,
                            rel_tol=1e-6, abs_tol=1e-8):
            raise ValueError("delta_frequency must agree with perturb_frequency minus control_frequency")
        if self.support is not None and self.support != max(self.control_count, self.perturb_count):
            raise ValueError("support must equal max(control_count, perturb_count)")
        return self


class MatchedControlShiftEvidence(ShiftEvidence):
    """Day6 matched estimand; pooled counts are descriptive, not its numerator."""

    control_frequency_definition: Literal["perturbation_batch_weighted_nt_frequency"]
    control_count_scope: Literal["pooled_nt_descriptive_not_matched_frequency_numerator"]
    perturbation_n: Count
    pooled_nt_n: Count
    matched_nt_cells_pooled: Count
    matched_nt_effective_n: Annotated[FiniteFloat, Field(gt=0)]
    batch_support: tuple[FrozenJSON, ...]
    selected_family_holm_exploratory: Probability
    family_size: Count
    nominal_pointwise_delta_ci_low: FiniteFloat
    nominal_pointwise_delta_ci_high: FiniteFloat
    ci_method: Text
    statistical_method: Text
    inference_scope: Text
    nt_selection_adjusted: Literal[False]

    @model_validator(mode="after")
    def preserve_matched_semantics(self):
        if self.q_value_shift is not None or self.bootstrap is not None or self.support is not None:
            raise ValueError("matched Holm/pointwise evidence cannot populate q-value/bootstrap/legacy support")
        if not self.batch_support or self.perturbation_n <= 0 or self.pooled_nt_n <= 0:
            raise ValueError("matched shift requires nonempty batch support and denominators")
        batches = [b.to_dict() for b in self.batch_support]
        if len({b["batch"] for b in batches}) != len(batches):
            raise ValueError("duplicate batch")
        for b in batches:
            for group in ("nt", "perturbation"):
                n, hits = b[group + "_n"], b[group + "_hits"]
                if type(n) is not int or type(hits) is not int or not 0 <= hits <= n or n <= 0:
                    raise ValueError("invalid batch counts")
        if sum(b["perturbation_n"] for b in batches) != self.perturbation_n or sum(
            b["perturbation_hits"] for b in batches
        ) != self.perturb_count:
            raise ValueError("batch/perturbation totals disagree")
        matched = sum(b["perturbation_n"] / self.perturbation_n * b["nt_hits"] / b["nt_n"] for b in batches)
        effective = 1 / sum((b["perturbation_n"] / self.perturbation_n) ** 2 / b["nt_n"] for b in batches)
        if not math.isclose(matched, self.control_frequency, abs_tol=1e-12) or not math.isclose(
            self.perturb_count / self.perturbation_n, self.perturb_frequency, abs_tol=1e-12
        ) or not math.isclose(effective, self.matched_nt_effective_n, abs_tol=1e-8):
            raise ValueError("matched frequency/effective denominator inconsistent with counts")
        if self.matched_nt_cells_pooled != sum(b["nt_n"] for b in batches):
            raise ValueError("matched NT pooled denominator disagrees with batches")
        if not self.control_count <= self.pooled_nt_n or self.matched_nt_cells_pooled > self.pooled_nt_n:
            raise ValueError("invalid pooled NT counts")
        if self.nominal_pointwise_delta_ci_low > self.nominal_pointwise_delta_ci_high:
            raise ValueError("invalid nominal interval")
        return self


INTERPRETATION_BOUNDARY = (
    "This is an observed perturbation-associated higher-order expression pattern. "
    "It does not by itself establish a causal regulatory mechanism."
)


class ClueRecord(FrozenModel):
    clue_id: Identifier = Field(default_factory=lambda: new_id("CLUE"))
    perturbation: Text
    pattern: PatternRecord
    discovery_mode: Text
    source_schema_version: Text
    source_run_id: Text
    source_artifact: Text
    source_artifact_sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-fA-F]{64}$")] | None = None
    reference_id: Text | None = None
    catalogue_sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-fA-F]{64}$")] | None = None
    reference_evidence: ReferenceEvidence = Field(default_factory=ReferenceEvidence)
    legacy_control: StatisticalEvidence | None = None
    legacy_perturbation: StatisticalEvidence | None = None
    perturbation_shift: ShiftEvidence | MatchedControlShiftEvidence
    replication_status: Text = "not_available"
    interpretation_boundary: Text = INTERPRETATION_BOUNDARY
    source_payload: FrozenJSON = Field(default_factory=FrozenJSON)
    upstream_context: FrozenJSON | None = None

    @model_validator(mode="after")
    def distinct_statistical_populations(self) -> ClueRecord:
        if self.discovery_mode == "reference_guided" and (
            self.legacy_control is not None or self.legacy_perturbation is not None
        ):
            raise ValueError("reference_guided clues cannot contain legacy condition-specific MFI statistics")
        if self.discovery_mode == "perturbation_emergent" and (
            self.reference_evidence.discovery is not None or self.reference_evidence.validation is not None
        ):
            raise ValueError("perturbation_emergent clues cannot contain reference discovery/validation statistics")
        return self


class ObjectReference(FrozenModel):
    object_type: ObjectType
    object_id: Identifier


class QuestionRevision(FrozenModel):
    revision_id: Identifier = Field(default_factory=lambda: new_id("MQR"))
    previous_text: Text
    new_text: Text
    reason: Text
    timestamp: AwareDatetime = Field(default_factory=utc_now)
    actor: Actor = "explorer"


class MechanisticQuestion(FrozenModel):
    question_id: Identifier = Field(default_factory=lambda: new_id("MQ"))
    question_text: Text
    derived_from_clue_id: Identifier
    status: Literal["open", "reframed", "resolved"] = "open"
    revisions: tuple[QuestionRevision, ...] = ()


class HypothesisRevision(FrozenModel):
    revision_id: Identifier = Field(default_factory=lambda: new_id("HR"))
    title: Text
    mechanism_statement: Text
    mechanism_type: Text
    status: HypothesisStatus = "proposed"
    derived_from: tuple[ObjectReference, ...] = ()
    weakening_conditions: tuple[Text, ...] = ()
    assumptions: tuple[Text, ...] = ()
    unresolved_points: tuple[Text, ...] = ()
    supersedes_revision_id: Identifier | None = None
    reason: Text | None = None
    created_at: AwareDatetime = Field(default_factory=utc_now)
    created_by: Actor = "explorer"


class PredictionRecord(FrozenModel):
    prediction_id: Identifier = Field(default_factory=lambda: new_id("P"))
    hypothesis_id: Identifier
    hypothesis_revision_id: Identifier
    statement: Text
    expected_if_true: Text
    weakened_if_observed: Text
    discriminates_from_hypotheses: tuple[Identifier, ...] = ()
    status: PredictionStatus = "untested"


class HypothesisRecord(FrozenModel):
    hypothesis_id: Identifier = Field(default_factory=lambda: new_id("H"))
    current_revision_id: Identifier
    revisions: tuple[HypothesisRevision, ...]
    predictions: tuple[PredictionRecord, ...] = ()

    @property
    def status(self) -> HypothesisStatus:
        """Current verdict; previous verdicts remain in the append-only history."""
        return self.current_revision.status

    @property
    def current_revision(self) -> HypothesisRevision:
        for revision in self.revisions:
            if revision.revision_id == self.current_revision_id:
                return revision
        raise ValueError("current hypothesis revision is missing")


class EvidenceQuestion(FrozenModel):
    question_id: Identifier = Field(default_factory=lambda: new_id("Q"))
    question_text: Text
    derived_from_prediction_ids: tuple[Identifier, ...] = ()
    derived_from_question_ids: tuple[Identifier, ...] = ()
    derived_from_evidence_ids: tuple[Identifier, ...] = ()
    relevant_hypothesis_ids: tuple[Identifier, ...] = ()
    discriminates_between: tuple[Identifier, ...] = ()
    status: QuestionStatus = "pending"
    priority: Literal["high", "medium", "low", "unset"] = "unset"
    suggested_evidence_type: Literal["dataset", "network", "literature", "unknown"] = "unknown"
    investigation_depth: Literal["screening", "verification"] | None = None
    query_spec: FrozenJSON = Field(default_factory=FrozenJSON)
    created_by: Actor = "explorer"
    created_at: AwareDatetime = Field(default_factory=utc_now)


class Provenance(FrozenModel):
    source_id: Text
    source_uri: Text | None = None
    tool: Text | None = None
    query: Text | None = None
    parameters: FrozenJSON = Field(default_factory=FrozenJSON)
    artifact_sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-fA-F]{64}$")] | None = None


class EvidenceRecord(FrozenModel):
    evidence_id: Identifier = Field(default_factory=lambda: new_id("E"))
    question_id: Identifier
    related_question_ids: tuple[Identifier, ...] = ()
    claim_tested: Text
    result_summary: Text
    source_type: Literal["dataset", "grn", "literature", "other"]
    directness: Literal["direct", "indirect", "contextual", "unknown"] = "unknown"
    context_match: Literal["matched", "partial", "mismatched", "unknown"] = "unknown"
    source_quality: Literal["primary_experiment", "curated_database", "secondary_source", "unknown"] = "unknown"
    support_quality: Literal["sufficient", "limited", "insufficient", "unknown"] = "unknown"
    negative_evidence_type: Literal["explicit_null_result", "not_found", "not_applicable"] = "not_applicable"
    potential_conflict: bool = False
    fingerprint: Text | None = None
    limitations: tuple[Text, ...] = ()
    provenance: Provenance
    raw_result_reference: Text | None = None
    created_at: AwareDatetime = Field(default_factory=utc_now)
    created_by: Actor = "investigator"
    supersedes_evidence_id: Identifier | None = None

    @property
    def question_ids(self) -> tuple[str, ...]:
        """All linked questions, retaining the v0.1.0 primary question field."""
        return (self.question_id,) + tuple(q for q in self.related_question_ids if q != self.question_id)

    @property
    def primary_question_id(self) -> str:
        return self.question_id


class EvidenceAssessment(FrozenModel):
    assessment_id: Identifier = Field(default_factory=lambda: new_id("EA"))
    evidence_id: Identifier
    hypothesis_id: Identifier
    hypothesis_revision_id: Identifier
    prediction_id: Identifier | None = None
    relation: Literal["supports", "challenges", "neutral", "inconclusive"]
    rationale: Text
    assessed_by: Actor = "investigator"
    created_at: AwareDatetime = Field(default_factory=utc_now)


class EvidenceGap(FrozenModel):
    gap_id: Identifier = Field(default_factory=lambda: new_id("GAP"))
    description: Text
    related_hypotheses: tuple[Identifier, ...] = ()
    related_predictions: tuple[Identifier, ...] = ()
    related_question_ids: tuple[Identifier, ...] = ()
    related_claim_ids: tuple[Identifier, ...] = ()
    related_evidence_ids: tuple[Identifier, ...] = ()
    critical: bool = False
    criticality_reason: Text | None = None
    reason: Text | None = None
    resolvable_with_current_tools: bool | None = None
    status: Literal["open", "addressed", "unresolved"] = "open"


class ContradictionRecord(FrozenModel):
    contradiction_id: Identifier = Field(default_factory=lambda: new_id("C"))
    description: Text
    evidence_ids: tuple[Identifier, ...] = ()
    hypothesis_ids: tuple[Identifier, ...] = ()
    claim_ids: tuple[Identifier, ...] = ()
    context_difference: Text | None = None
    possible_explanations: tuple[Text, ...] = ()
    potential_context_dependency: bool = False
    critical: bool = False
    status: Literal["open", "resolved", "unresolved"] = "open"


class ActionState(FrozenModel):
    current_phase: Literal[
        "clue_ready", "exploration_needed", "evidence_needed",
        "evidence_in_progress", "critique_needed", "stopped",
    ] = "clue_ready"
    next_actor: Literal["explorer", "investigator", "evidence_investigator", "critic", "none"] = "none"
    selected_question_id: Identifier | None = None
    stop_reason: Text | None = None

    @model_validator(mode="after")
    def stopped_state_is_complete(self) -> ActionState:
        if self.current_phase == "stopped":
            if self.stop_reason is None:
                raise ValueError("stopped action state requires stop_reason")
            if self.next_actor != "none" or self.selected_question_id is not None:
                raise ValueError("stopped action state cannot select a next actor or question")
        elif self.stop_reason is not None:
            raise ValueError("stop_reason is only valid for a stopped action state")
        return self


class HistoryEvent(FrozenModel):
    event_id: Identifier = Field(default_factory=lambda: new_id("EV"))
    sequence: Annotated[int, Field(ge=1, strict=True)]
    case_revision: Annotated[int, Field(ge=1, strict=True)]
    timestamp: AwareDatetime = Field(default_factory=utc_now)
    actor: Actor
    action: Text
    object_type: ObjectType
    object_id: Identifier
    summary: Text
    metadata: FrozenJSON = Field(default_factory=FrozenJSON)
    changes: FrozenJSON = Field(default_factory=FrozenJSON)


# Imported here so additive schemas can reuse the immutable base definitions.
from .critic_models import CriticAudits, MechanisticClaim


class CaseFile(FrozenModel):
    metadata: CaseMetadata
    clue: ClueRecord
    mechanistic_question: MechanisticQuestion | None = None
    hypotheses: tuple[HypothesisRecord, ...] = ()
    evidence_questions: tuple[EvidenceQuestion, ...] = ()
    evidence_records: tuple[EvidenceRecord, ...] = ()
    evidence_assessments: tuple[EvidenceAssessment, ...] = ()
    evidence_gaps: tuple[EvidenceGap, ...] = ()
    contradictions: tuple[ContradictionRecord, ...] = ()
    mechanistic_claims: tuple[MechanisticClaim, ...] = ()
    critic_audits: CriticAudits = Field(default_factory=CriticAudits)
    action_state: ActionState = Field(default_factory=ActionState)
    investigation_history: tuple[HistoryEvent, ...] = ()
