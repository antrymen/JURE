"""Configurable operational limits and the portable audit-run result."""
from pydantic import Field
from typing import Literal
from jure.casefile.models import FrozenModel, Identifier, Text


class CriticConfig(FrozenModel):
    # Explicit revision opt-in preserves historical run semantics and budgets.
    source_aware_stopping: bool = False
    protocol_v3: bool = False
    max_revision_acceptance_attempts: int = Field(default=2, ge=1, strict=True)
    # Operational defaults, not scientifically optimized parameters.
    max_critic_rounds: int = Field(default=6, ge=1, strict=True)
    max_investigator_rounds: int = Field(default=8, ge=1, strict=True)
    max_explorer_reframes: int = Field(default=2, ge=0, strict=True)
    max_total_tool_calls: int = Field(default=30, ge=0, strict=True)
    max_consecutive_stalled_rounds: int = Field(default=2, ge=1, strict=True)
    # Preserve legacy configurations; new repair runs explicitly use completed.
    round_budget_basis: Literal['started', 'completed'] = 'started'
    allow_evidence_sufficient_stop: bool = True
    allow_evidence_limited_stop: bool = True
    require_hypothesis_audit_before_evidence_audit: bool = True
    require_critical_claim_resolution_for_supported: bool = True
    max_context_chars: int = Field(default=250_000, ge=1, strict=True)
    max_response_chars: int = Field(default=250_000, ge=1, strict=True)


class CriticRunResult(FrozenModel):
    run_id: Identifier
    case_id: Identifier
    critic_round: int = Field(ge=1, strict=True)
    success: bool = False
    hypothesis_audit_id: Identifier | None = None
    claim_audit_ids: tuple[Identifier, ...] = ()
    hypothesis_synthesis_ids: tuple[Identifier, ...] = ()
    created_gap_ids: tuple[Identifier, ...] = ()
    created_contradiction_ids: tuple[Identifier, ...] = ()
    status_changes: tuple[Identifier, ...] = ()
    routing_decision_id: Identifier | None = None
    stop_record_id: Identifier | None = None
    final_report_id: Identifier | None = None
    warnings: tuple[Text, ...] = ()
    validation_errors: tuple[Text, ...] = ()
    source_case_revision: int = Field(ge=1, strict=True)
    committed_case_revision: int | None = None
    artifact_path: str | None = None
