"""Evidence Investigator v0.1: acquisition without hypothesis verdicts."""
from .agent import EvidenceInvestigator
from .backend import InvestigatorBackend, JSONInvestigatorBackend, MockInvestigatorBackend
from .context import build_investigator_context
from .prioritization import QuestionPriorityAssessment, reprioritize_pending_questions
from .query_plan import QueryPlan
from .queue import (deduplicate_evidence_questions, recover_stale_in_progress_questions,
                    manually_prioritize_question, manually_cancel_question, manually_add_evidence_question)
from .result import InvestigatorConfig, InvestigatorRunResult

__all__ = ["EvidenceInvestigator", "InvestigatorBackend", "JSONInvestigatorBackend", "MockInvestigatorBackend",
           "InvestigatorConfig", "InvestigatorRunResult", "QueryPlan", "QuestionPriorityAssessment",
           "build_investigator_context", "reprioritize_pending_questions", "deduplicate_evidence_questions",
           "recover_stale_in_progress_questions", "manually_prioritize_question", "manually_cancel_question",
           "manually_add_evidence_question"]
