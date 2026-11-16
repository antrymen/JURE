"""Retrieved documents and verified experiment-level claims are separate types."""
from abc import abstractmethod
import re
from typing import Literal

from pydantic import Field, model_validator

from jure.casefile.models import FrozenModel, Text

from .base import EvidenceTool


class RetrievedItem(FrozenModel):
    paper_id: Text
    title: Text
    year: int | None = Field(default=None, ge=1600, le=3000)
    source_excerpt_or_summary: Text
    source_reference: Text
    source: Text = "synthetic"
    claim_location: Text | None = None
    biological_context: Text | None = None
    cell_type_or_model: Text | None = None


class VerifiedEvidenceCandidate(FrozenModel):
    paper_id: Text
    title: Text
    year: int | None = Field(default=None, ge=1600, le=3000)
    claim_tested: Text
    experiment_identifier: Text
    experiment_type: Text | None = None
    perturbed_entity: Text | None = None
    measured_entity: Text | None = None
    observed_effect: Text | None = None
    biological_context: Text | None = None
    cell_type_or_model: Text | None = None
    directness: Literal["direct", "indirect", "contextual", "unknown"]
    source_excerpt_or_summary: Text
    source_reference: Text
    source: Text = "synthetic"
    claim_location: Text | None = None
    limitations: tuple[Text, ...] = ()
    source_quality: Literal["primary_experiment", "curated_database", "secondary_source", "unknown"] = "unknown"
    support_quality: Literal["sufficient", "limited", "insufficient", "unknown"] = "unknown"
    negative_evidence_type: Literal["explicit_null_result", "not_found", "not_applicable"] = "not_applicable"
    sufficient_power: bool = False
    relation_effect: Literal["supports", "challenges", "neutral"] = "neutral"

    @model_validator(mode="after")
    def direct_requires_experiment(self):
        if self.directness == "direct":
            if not all((self.experiment_type, self.perturbed_entity,
                        self.measured_entity, self.observed_effect)):
                raise ValueError("direct evidence requires an experiment, manipulated and measured entities, and an effect")
            if self.source_quality != "primary_experiment":
                raise ValueError("direct evidence requires primary experimental content")
            if re.search(r"co[\s-]?mention|association|review|retriev|rag summary", self.experiment_type, re.I):
                raise ValueError("co-mention or retrieval cannot establish direct evidence")
        if self.negative_evidence_type == "not_found" and self.relation_effect != "neutral":
            raise ValueError("absence of retrieved evidence cannot challenge a hypothesis")
        if (self.negative_evidence_type == "explicit_null_result"
                and self.relation_effect == "challenges" and not self.sufficient_power):
            raise ValueError("challenging null evidence must report sufficient power")
        return self


class LiteratureEvidenceTool(EvidenceTool):
    @abstractmethod
    def search_claim(self, claim, context=None): ...

    @abstractmethod
    def search_regulatory_relation(self, source_gene, target_gene, context=None): ...

    @abstractmethod
    def search_perturbation_evidence(self, perturbed_gene, measured_gene, context=None): ...

    def validate_payload(self, operation, payload):
        super().validate_payload(operation, payload)
        for field in ("retrieved_items", "verified_candidates", "query", "provenance", "warnings", "has_results"):
            if field not in payload:
                raise ValueError(f"literature response missing {field}")
        if any(not isinstance(payload[field], list) for field in ("retrieved_items", "verified_candidates")):
            raise ValueError("literature result collections must be lists")
        if bool(payload["retrieved_items"] or payload["verified_candidates"]) != payload["has_results"]:
            raise ValueError("has_results conflicts with literature results")
        for item in payload["retrieved_items"]:
            RetrievedItem.model_validate(item)
        for candidate in payload["verified_candidates"]:
            VerifiedEvidenceCandidate.model_validate(candidate)
