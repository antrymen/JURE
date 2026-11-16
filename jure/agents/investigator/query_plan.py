"""Typed, internal acquisition plans; never evidence or Case File mutations."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Literal, Mapping

from pydantic import AwareDatetime, Field

from jure.casefile.models import FrozenJSON, FrozenModel, Identifier, Text, utc_now
from jure.protocol.contracts import DiscriminationSpec

EvidenceType = Literal["dataset", "network", "literature", "other"]


class PlannedOperation(FrozenModel):
    operation: Identifier
    inputs: FrozenJSON = Field(default_factory=FrozenJSON)
    evidence_type: EvidenceType | None = None
    # Free scientific prose, not another ID/reference contract. Persisted with the plan.
    evidence_planning: FrozenJSON = Field(default_factory=FrozenJSON)


class QueryPlan(FrozenModel):
    plan_id: Identifier
    question_id: Identifier
    objective: Text
    evidence_type: EvidenceType
    candidate_tool_types: tuple[EvidenceType, ...]
    required_inputs: FrozenJSON = Field(default_factory=FrozenJSON)
    planned_operations: tuple[PlannedOperation, ...] = ()
    expected_output: Text
    failure_conditions: tuple[Text, ...] = ()
    created_at: AwareDatetime = Field(default_factory=utc_now)
    discrimination: DiscriminationSpec | None = None


OPERATIONS = {
    "dataset": {"joint_frequency", "conditional_frequency", "compare_conditional_frequency",
                "compare_pattern_between_conditions", "get_support"},
    "network": {"query_edge", "query_shared_regulators", "query_paths"},
    "literature": {"search_claim", "search_regulatory_relation", "search_perturbation_evidence"},
}


def question_evidence_type(question: Mapping[str, Any]) -> EvidenceType:
    """Resolve explicit operational intent before the Explorer's family hint."""
    spec = question.get("query_spec", {})
    if spec.get("evidence_type") in {"dataset", "network", "literature", "other"}:
        return spec["evidence_type"]
    for family, operations in OPERATIONS.items():
        if spec.get("operation") in operations:
            return family
    text = question["question_text"].lower()
    if any(term in text for term in ("experiment", "knockout", "knockdown", "crispr", "literature")):
        return "literature"
    if any(term in text for term in ("conditional", "dataset", "frequency", "state alter", "support count")):
        return "dataset"
    if any(term in text for term in ("shared regulator", "shared upstream", "network", "regulatory edge")):
        return "network"
    hint = question.get("suggested_evidence_type")
    return hint if hint in {"dataset", "network", "literature"} else "other"


def _relations(text: str) -> list[tuple[str, str]]:
    entity = r"([A-Za-z][A-Za-z0-9_.-]*?)"
    expressions = (rf"(?=\b{entity}\s*(?:→|->)\s*{entity}(?=\s|[?.,;]|→|->|$))",
                   rf"\b{entity}\s+(?:regulates?|controls?)\s+{entity}(?=\s|[?.,;]|$)")
    return list(dict.fromkeys((match.group(1), match.group(2)) for expression in expressions
                              for match in re.finditer(expression, text, flags=re.IGNORECASE)))


def default_query_plan(context: Mapping[str, Any], question_id: str) -> QueryPlan:
    """Conservative deterministic mock operationalizer.

    Explicit query specifications preserve every filter. Conceptual questions
    without an implemented operation remain unanswerable; choosing arbitrary
    clue genes would silently substitute a different scientific question.
    """
    questions = context.get("pending_questions", [])
    question = next((q for q in questions if q["question_id"] == question_id), None)
    if question is None:
        raise ValueError(f"unknown selectable question {question_id}")
    spec = question.get("query_spec", {})
    family = question_evidence_type(question)
    text = question["question_text"]
    fan_out = bool(re.search(
        r"\bregulates?\s+[A-Za-z][A-Za-z0-9_.-]*\s*(?:[,/]|\band\s+[A-Za-z])", text, re.I))
    cell_context = context.get("biological_context", {}).get("cell_context")
    operations: list[PlannedOperation] = []
    failure_conditions = ["No result does not establish absence of the tested relation.",
                          "Unavailable sources and insufficient support leave the question unresolved."]
    if spec.get("planned_operations"):
        operations = [PlannedOperation.model_validate(item) for item in spec["planned_operations"]]
    elif spec.get("operation"):
        operations = [PlannedOperation(operation=spec["operation"], inputs=spec.get("inputs", {}),
                                       evidence_type=family)]
    elif family == "network":
        if re.search(r"shared (?:upstream )?regulator|common (?:upstream )?regulator", text, re.I):
            genes = context.get("clue_genes", [])
            # A shared-regulator query has an explicit target set: named genes,
            # or all clue genes only when the question actually names all of them.
            named = [g for g in genes if re.search(rf"(?<![A-Za-z0-9_]){re.escape(g)}(?![A-Za-z0-9_])", text)]
            if len(named) >= 2:
                operations = [PlannedOperation(operation="query_shared_regulators",
                    inputs={"target_genes": named, "context": cell_context}, evidence_type=family)]
        elif not fan_out and (relations := _relations(text)):
            operations = [PlannedOperation(operation="query_edge", evidence_type=family,
                inputs={"source_gene": source, "target_gene": target, "context": cell_context})
                for source, target in relations]
    elif family == "dataset":
        # These are the supported two-state comparisons, not composition matching,
        # adjustment for confounding, causal effects, or arbitrary joint-state tests.
        patterns = (
            r"\bDoes\s+([A-Za-z][A-Za-z0-9_.-]*)\s+state\s+alter\s+([A-Za-z][A-Za-z0-9_.-]*)\s+response",
            r"\bconditional\s+relationship\s+between\s+([A-Za-z][A-Za-z0-9_.-]*)\s+and\s+([A-Za-z][A-Za-z0-9_.-]*)",
        )
        match = next((match for pattern in patterns if (match := re.search(pattern, text, re.I))), None)
        if match and not re.search(r"adjust|match|composition|confound|joint state", text, re.I):
            operations = [PlannedOperation(operation="compare_conditional_frequency", evidence_type=family,
                inputs={"target_gene": match.group(2), "conditioning_gene": match.group(1), "target_state": 1})]
    elif family == "literature":
        relations = _relations(text)
        # A fan-out phrase cannot be reduced to its first measured entity.
        if relations and not fan_out:
            operations = [PlannedOperation(operation="search_regulatory_relation", evidence_type=family,
                inputs={"source_gene": source, "target_gene": target, "context": cell_context})
                for source, target in relations]
        elif fan_out or re.search(r"experiment|literature|perturbation", text, re.I):
            operations = [PlannedOperation(operation="search_claim", evidence_type=family,
                inputs={"claim": text, "context": cell_context})]
    if not operations:
        failure_conditions.append("The question requires an explicit supported operation and its scientific inputs.")
    required_inputs = spec.get("required_inputs", spec.get("inputs", operations[0].inputs if len(operations) == 1 else {}))
    material = {"case": context.get("case_id"), "revision": context.get("source_case_revision"),
                "question": question_id, "operations": [o.model_dump(mode="json") for o in operations]}
    plan_id = "PLAN_" + hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()[:24]
    return QueryPlan(plan_id=plan_id, question_id=question_id, objective=text, evidence_type=family,
                     candidate_tool_types=tuple(dict.fromkeys([family] + [o.evidence_type for o in operations if o.evidence_type])),
                     required_inputs=required_inputs, planned_operations=tuple(operations),
                     expected_output="Traceable observations with source provenance, limitations and support where applicable.",
                     failure_conditions=tuple(failure_conditions),
                     created_at=context.get("context_timestamp") or utc_now())
