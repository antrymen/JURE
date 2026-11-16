"""Additive, immutable scientific audit records for Mechanism Critic v0.1."""
from typing import Literal

from pydantic import AwareDatetime, Field, model_validator

from .models import Count, FrozenJSON, FrozenModel, Identifier, Text, new_id, utc_now

CriticStatus = Literal["supported", "partially_supported", "challenged", "insufficient"]
AuditDimension = Literal["pass", "fail", "warning"]
FailureType = Literal[
    "hypothesis_problem", "prediction_problem", "evidence_question_problem",
    "evidence_quality_problem", "evidence_missing", "evidence_conflict",
    "hypothesis_space_inadequate", "tool_limit", "no_problem",
]
RouteTarget = Literal["explorer", "investigator", "stop"]
StopType = Literal["evidence_sufficient", "evidence_limited", "capability_limited",
                   "revision_budget_exhausted", "tool_budget_exhausted", "stalled", "agent_budget_exhausted"]
StopReason = Literal["hypotheses_discriminated", "critical_evidence_unavailable",
                     "investigation_saturation", "budget_exhausted",
                     "hypothesis_space_unresolved", "tool_limit", "other", "revision_budget_exhausted",
                     "tool_budget_exhausted", "capability_limited", "stalled", "agent_budget_exhausted"]


class MechanisticClaim(FrozenModel):
    claim_id: Identifier = Field(default_factory=lambda: new_id("CLAIM"))
    hypothesis_id: Identifier
    hypothesis_revision_id: Identifier | None = None
    statement: Text
    claim_type: Text = "mechanistic"
    derived_from_prediction_ids: tuple[Identifier, ...] = ()
    required_evidence_types: tuple[Text, ...] = ()
    status: CriticStatus = "insufficient"
    critical: bool = True
    criticality_reason: Text = "Necessary to the hypothesis mechanism being audited."
    created_by: Literal["critic"] = "critic"
    created_at: AwareDatetime = Field(default_factory=utc_now)


class PerHypothesisAudit(FrozenModel):
    hypothesis_id: Identifier
    groundedness: AuditDimension = "pass"
    distinctness: AuditDimension = "pass"
    testability: AuditDimension = "pass"
    falsifiability: AuditDimension = "pass"
    discriminability: AuditDimension = "pass"
    scope: AuditDimension = "pass"
    issues: tuple[Text, ...] = ()
    required_revisions: tuple[Text, ...] = ()


class HypothesisAuditResult(FrozenModel):
    audit_id: Identifier = Field(default_factory=lambda: new_id("HA"))
    case_id: Identifier
    overall_status: Literal["pass", "revision_required"]
    per_hypothesis: tuple[PerHypothesisAudit, ...] = ()
    coverage_issues: tuple[Text, ...] = ()
    audit_summary: Text
    critic_round: Count = 0
    created_at: AwareDatetime = Field(default_factory=utc_now)


HypothesisAuditRecord = HypothesisAuditResult


class EvidenceAuditRecord(FrozenModel):
    evidence_audit_id: Identifier = Field(default_factory=lambda: new_id("EVA"))
    evidence_id: Identifier
    claim_ids: tuple[Identifier, ...] = ()
    relevance: Literal["relevant", "partial", "irrelevant", "unknown"] = "unknown"
    directness_assessment: Literal["direct", "indirect", "contextual", "unknown"] = "unknown"
    context_assessment: Literal["matched", "partial", "mismatched", "unknown"] = "unknown"
    source_quality_assessment: Literal["primary_experiment", "curated_database", "secondary_source", "unknown"] = "unknown"
    support_quality_assessment: Literal["sufficient", "limited", "insufficient", "unknown"] = "unknown"
    provenance_check: Literal["complete", "incomplete", "unknown"] = "unknown"
    overclaim_detected: bool = False
    contradiction_detected: bool = False
    issues: tuple[Text, ...] = ()
    critic_interpretation: Text
    mechanism_support: Text | None = None
    case_specific_support: Text | None = None
    context_transferability: Text | None = None
    critic_round: Count = 0
    created_at: AwareDatetime = Field(default_factory=utc_now)


class ClaimAuditRecord(FrozenModel):
    claim_audit_id: Identifier = Field(default_factory=lambda: new_id("CA"))
    claim_id: Identifier
    status: CriticStatus
    evidence_ids: tuple[Identifier, ...] = ()
    supporting_evidence_ids: tuple[Identifier, ...] = ()
    challenging_evidence_ids: tuple[Identifier, ...] = ()
    gap_ids: tuple[Identifier, ...] = ()
    contradiction_ids: tuple[Identifier, ...] = ()
    summary: Text
    critic_round: Count = 0
    created_at: AwareDatetime = Field(default_factory=utc_now)


ClaimEvidenceAudit = ClaimAuditRecord


class ClaimCoverageSummary(FrozenModel):
    total_claims: Count = 0
    critical_claims: Count = 0
    supported_claims: Count = 0
    partially_supported_claims: Count = 0
    challenged_claims: Count = 0
    insufficient_claims: Count = 0
    supported_critical_claims: Count = 0
    unresolved_critical_claims: Count = 0
    challenged_critical_claims: Count = 0


class HypothesisSynthesis(FrozenModel):
    synthesis_id: Identifier = Field(default_factory=lambda: new_id("SYN"))
    hypothesis_id: Identifier
    hypothesis_revision_id: Identifier | None = None
    status: CriticStatus
    supported_claim_ids: tuple[Identifier, ...] = ()
    partial_claim_ids: tuple[Identifier, ...] = ()
    challenged_claim_ids: tuple[Identifier, ...] = ()
    insufficient_claim_ids: tuple[Identifier, ...] = ()
    critical_gaps: tuple[Identifier, ...] = ()
    contradictions: tuple[Identifier, ...] = ()
    remaining_uncertainties: tuple[Text, ...] = ()
    summary: Text
    coverage: ClaimCoverageSummary = Field(default_factory=ClaimCoverageSummary)
    critic_round: Count = 0
    created_at: AwareDatetime = Field(default_factory=utc_now)


class FailureAttribution(FrozenModel):
    attribution_id: Identifier = Field(default_factory=lambda: new_id("FAIL"))
    reason_type: FailureType
    reason_summary: Text
    related_hypothesis_ids: tuple[Identifier, ...] = ()
    related_claim_ids: tuple[Identifier, ...] = ()
    related_evidence_ids: tuple[Identifier, ...] = ()
    related_gap_ids: tuple[Identifier, ...] = ()
    hypothesis_space_problem: bool = False
    critic_round: Count = 0


class RoutingDecision(FrozenModel):
    decision_id: Identifier = Field(default_factory=lambda: new_id("ROUTE"))
    from_actor: Literal["critic"] = "critic"
    route_to: RouteTarget
    reason_type: FailureType
    reason_summary: Text
    related_hypothesis_ids: tuple[Identifier, ...] = ()
    related_claim_ids: tuple[Identifier, ...] = ()
    related_evidence_ids: tuple[Identifier, ...] = ()
    related_gap_ids: tuple[Identifier, ...] = ()
    critic_round: Count = 0
    created_at: AwareDatetime = Field(default_factory=utc_now)


class RevisionRequest(FrozenModel):
    request_id: Identifier = Field(default_factory=lambda: new_id("RR"))
    reason: Text
    affected_hypothesis_ids: tuple[Identifier, ...] = ()
    issues: tuple[Text, ...] = ()
    required_changes: tuple[Text, ...] = ()
    evidence_that_triggered_reframe: tuple[Identifier, ...] = ()
    preserve_elements: tuple[Text, ...] = ()
    critic_round: Count = 0
    created_at: AwareDatetime = Field(default_factory=utc_now)


class InvestigationRequest(FrozenModel):
    request_id: Identifier = Field(default_factory=lambda: new_id("IR"))
    target_gap_ids: tuple[Identifier, ...] = ()
    target_claim_ids: tuple[Identifier, ...] = ()
    objective: Text
    why_needed: Text
    desired_evidence_characteristics: tuple[Text, ...] = ()
    critic_round: Count = 0
    created_at: AwareDatetime = Field(default_factory=utc_now)


class HypothesisStatusChange(FrozenModel):
    change_id: Identifier = Field(default_factory=lambda: new_id("HSC"))
    hypothesis_id: Identifier
    previous_status: Literal["proposed", "active", "modified", "challenged", "rejected", "retained",
                             "supported", "partially_supported", "insufficient"]
    new_status: CriticStatus
    claim_ids: tuple[Identifier, ...] = ()
    evidence_ids: tuple[Identifier, ...] = ()
    gap_ids: tuple[Identifier, ...] = ()
    reason: Text
    critic_round: Count
    timestamp: AwareDatetime = Field(default_factory=utc_now)


class InvestigationProgressSnapshot(FrozenModel):
    snapshot_id: Identifier = Field(default_factory=lambda: new_id("PROGRESS"))
    critic_round: Count
    new_evidence_count: Count = 0
    resolved_gap_count: Count = 0
    new_gap_count: Count = 0
    hypothesis_status_changes: Count = 0
    claim_status_changes: Count = 0
    new_discriminating_question_count: Count = 0
    contradiction_changes: Count = 0
    route: RouteTarget
    effective_evidence_ids: tuple[Identifier, ...] = ()
    resolved_gap_ids: tuple[Identifier, ...] = ()
    discriminating_question_ids: tuple[Identifier, ...] = ()
    investigation_stalled: bool = False
    created_at: AwareDatetime = Field(default_factory=utc_now)


class RecommendedExperiment(FrozenModel):
    experiment_id: Identifier = Field(default_factory=lambda: new_id("EXP"))
    objective: Text
    target_uncertainty: Text
    intervention: Text
    measurement: Text
    expected_discriminating_outcomes: FrozenJSON = Field(default_factory=FrozenJSON)
    related_hypothesis_ids: tuple[Identifier, ...] = ()
    related_claim_ids: tuple[Identifier, ...] = ()
    rationale: Text
    feasibility_notes: tuple[Text, ...] = ()


class SourceReview(FrozenModel):
    """Critic-authored source assessment; not an automatic scientific verdict."""
    target_id: Identifier
    source: Text
    evidence_need: Text
    status: Literal['SOURCE_EXHAUSTED', 'SOURCE_UNAVAILABLE', 'SOURCE_UNEXPLORED']
    rationale: Text


class StopRecord(FrozenModel):
    stop_id: Identifier = Field(default_factory=lambda: new_id("STOP"))
    stop_type: StopType
    stop_reason: StopReason
    final_hypothesis_states: FrozenJSON = Field(default_factory=FrozenJSON)
    remaining_hypotheses: tuple[Identifier, ...] = ()
    remaining_uncertainties: tuple[Text, ...] = ()
    unresolved_critical_gaps: tuple[Identifier, ...] = ()
    resolved_gaps: tuple[Identifier, ...] = ()
    key_supporting_evidence_ids: tuple[Identifier, ...] = ()
    key_challenging_evidence_ids: tuple[Identifier, ...] = ()
    why_current_tools_cannot_resolve: tuple[Text, ...] = ()
    evidence_already_checked: tuple[Identifier, ...] = ()
    source_reviews: tuple[SourceReview, ...] = ()
    recommended_experiments: tuple[RecommendedExperiment, ...] = ()
    critic_summary: Text
    critic_round: Count = 0
    created_at: AwareDatetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def four_statuses(self):
        if any(status not in {"supported", "partially_supported", "challenged", "insufficient"}
               for status in self.final_hypothesis_states.values()):
            raise ValueError("final hypothesis states must use the four critic statuses")
        return self


class FinalHypothesisReport(FrozenModel):
    hypothesis_id: Identifier
    status: CriticStatus
    mechanism_statement: Text
    key_supported_claims: tuple[Identifier, ...] = ()
    key_challenged_claims: tuple[Identifier, ...] = ()
    critical_gaps: tuple[Identifier, ...] = ()
    key_evidence_ids: tuple[Identifier, ...] = ()
    contradictions: tuple[Identifier, ...] = ()
    remaining_uncertainties: tuple[Text, ...] = ()


class CriticFinalReport(FrozenModel):
    report_id: Identifier = Field(default_factory=lambda: new_id("REPORT"))
    case_id: Identifier
    stop_type: StopType
    mechanistic_question: Text
    clue_summary: Text
    final_hypotheses: tuple[FinalHypothesisReport, ...] = ()
    observation: Text
    interpretation: Text
    uncertainty: tuple[Text, ...] = ()
    overall_case_summary: Text
    recommended_experiments: tuple[RecommendedExperiment, ...] = ()
    investigation_limitations: tuple[Text, ...] = ()
    created_at: AwareDatetime = Field(default_factory=utc_now)


class CriticAudits(FrozenModel):
    hypothesis_audits: tuple[HypothesisAuditResult, ...] = ()
    evidence_audits: tuple[EvidenceAuditRecord, ...] = ()
    claim_audits: tuple[ClaimAuditRecord, ...] = ()
    hypothesis_syntheses: tuple[HypothesisSynthesis, ...] = ()
    routing_decisions: tuple[RoutingDecision, ...] = ()
    stop_records: tuple[StopRecord, ...] = ()
    revision_requests: tuple[RevisionRequest, ...] = ()
    investigation_requests: tuple[InvestigationRequest, ...] = ()
    status_changes: tuple[HypothesisStatusChange, ...] = ()
    progress_snapshots: tuple[InvestigationProgressSnapshot, ...] = ()
    final_reports: tuple[CriticFinalReport, ...] = ()
    failure_attributions: tuple[FailureAttribution, ...] = ()
    recommended_experiments: tuple[RecommendedExperiment, ...] = ()


CRITIC_COLLECTIONS = {
    "hypothesis_audits": (HypothesisAuditResult, "audit_id", "hypothesis_audit"),
    "evidence_audits": (EvidenceAuditRecord, "evidence_audit_id", "evidence_audit"),
    "claim_audits": (ClaimAuditRecord, "claim_audit_id", "claim_audit"),
    "hypothesis_syntheses": (HypothesisSynthesis, "synthesis_id", "hypothesis_synthesis"),
    "routing_decisions": (RoutingDecision, "decision_id", "routing_decision"),
    "stop_records": (StopRecord, "stop_id", "stop_record"),
    "revision_requests": (RevisionRequest, "request_id", "revision_request"),
    "investigation_requests": (InvestigationRequest, "request_id", "investigation_request"),
    "status_changes": (HypothesisStatusChange, "change_id", "hypothesis_status_change"),
    "progress_snapshots": (InvestigationProgressSnapshot, "snapshot_id", "progress_snapshot"),
    "final_reports": (CriticFinalReport, "report_id", "final_report"),
    "failure_attributions": (FailureAttribution, "attribution_id", "failure_attribution"),
    "recommended_experiments": (RecommendedExperiment, "experiment_id", "recommended_experiment"),
}
