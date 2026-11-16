"""Shared structured investigation state for JURE, version 0.1.1."""
from .adapters import clue_from_v01, clue_from_v02
from .models import (
    ActionState, BootstrapSummary, CaseFile, CaseMetadata, ClueRecord,
    ContradictionRecord, EvidenceAssessment, EvidenceGap, EvidenceQuestion,
    EvidenceRecord, FrozenJSON, HistoryEvent, HypothesisRecord,
    HypothesisRevision, MechanisticQuestion, ObjectReference, PatternRecord,
    PredictionRecord, Provenance, QuestionRevision, ReferenceEvidence,
    ShiftEvidence, MatchedControlShiftEvidence, StatisticalEvidence, new_id, utc_now,
)
from .schema import case_json_schema
from .store import CaseStore, IntegrityError, RevisionConflict, create_case_from_clue, load_case, save_case
from .validation import validate_case
from .selected_adapter import clue_from_selected_case, initialize_selected_case
from .critic_models import (
    ClaimAuditRecord, ClaimCoverageSummary, ClaimEvidenceAudit, CriticAudits,
    CriticFinalReport, CriticStatus, EvidenceAuditRecord, FailureAttribution,
    FinalHypothesisReport, HypothesisAuditRecord, HypothesisAuditResult,
    HypothesisStatusChange, HypothesisSynthesis, InvestigationProgressSnapshot,
    InvestigationRequest, MechanisticClaim, PerHypothesisAudit,
    RecommendedExperiment, RevisionRequest, RoutingDecision, StopRecord,
)

__all__ = [
    "ActionState", "BootstrapSummary", "CaseFile", "CaseMetadata", "CaseStore", "ClueRecord",
    "ContradictionRecord", "EvidenceAssessment", "EvidenceGap", "EvidenceQuestion", "EvidenceRecord",
    "FrozenJSON", "HistoryEvent", "HypothesisRecord", "HypothesisRevision", "IntegrityError",
    "MechanisticQuestion", "ObjectReference", "PatternRecord", "PredictionRecord", "Provenance",
    "QuestionRevision", "ReferenceEvidence", "RevisionConflict", "ShiftEvidence", "MatchedControlShiftEvidence", "StatisticalEvidence",
    "case_json_schema", "clue_from_v01", "clue_from_v02", "create_case_from_clue", "load_case",
    "new_id", "save_case", "utc_now", "validate_case", "clue_from_selected_case", "initialize_selected_case",
    "ClaimAuditRecord", "ClaimCoverageSummary", "ClaimEvidenceAudit", "CriticAudits",
    "CriticFinalReport", "CriticStatus", "EvidenceAuditRecord", "FailureAttribution",
    "FinalHypothesisReport", "HypothesisAuditRecord", "HypothesisAuditResult",
    "HypothesisStatusChange", "HypothesisSynthesis", "InvestigationProgressSnapshot",
    "InvestigationRequest", "MechanisticClaim", "PerHypothesisAudit",
    "RecommendedExperiment", "RevisionRequest", "RoutingDecision", "StopRecord",
]
