"""Bounded run configuration and portable Investigator audit artifacts."""
from typing import Literal

from pydantic import Field

from jure.casefile.models import FrozenModel, FrozenJSON, Identifier, QuestionStatus


class InvestigatorConfig(FrozenModel):
    source_aware_planning: bool = False
    protocol_v3: bool = False
    max_questions_per_run: int = Field(default=1, ge=1, strict=True)
    max_tool_calls_per_run: int = Field(default=3, ge=1, strict=True)
    min_conditional_support: int = Field(default=20, ge=1, strict=True)
    max_new_followup_questions: int = Field(default=2, ge=0, strict=True)
    allow_followup_questions: bool = True
    allow_counter_evidence_search: bool = True
    priority_policy: Literal["rule_based_v0.1"] = "rule_based_v0.1"


class InvestigatorRunResult(FrozenModel):
    run_id: Identifier
    case_id: Identifier
    success: bool = False
    selected_question_id: Identifier | None = None
    selected_question_ids: tuple[Identifier, ...] = ()
    priority_assessment: tuple[FrozenJSON, ...] = ()
    query_plan_id: Identifier | None = None
    query_plans: tuple[FrozenJSON, ...] = ()
    tool_calls: tuple[FrozenJSON, ...] = ()
    created_evidence_ids: tuple[Identifier, ...] = ()
    linked_evidence_ids: tuple[Identifier, ...] = ()
    created_gap_ids: tuple[Identifier, ...] = ()
    created_followup_question_ids: tuple[Identifier, ...] = ()
    question_final_status: QuestionStatus | None = None
    question_final_statuses: FrozenJSON = Field(default_factory=FrozenJSON)
    recommended_next_actor: Literal["investigator", "critic", "none"] = "critic"
    warnings: tuple[str, ...] = ()
    validation_errors: tuple[str, ...] = ()
    source_case_revision: int
    committed_case_revision: int | None = None
    artifact_path: str | None = None
