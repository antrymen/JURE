"""Evidence-aware queue ranking computed from fresh Case File state each run."""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from pydantic import model_validator

from jure.casefile.models import FrozenModel, Identifier, Text

from .priority_policy import Ordinal, Redundancy, priority_class, priority_sort_key
from .query_plan import default_query_plan, question_evidence_type


class QuestionPriorityAssessment(FrozenModel):
    question_id: Identifier
    discriminative_value: Ordinal
    answerability: Ordinal
    directness_potential: Ordinal
    estimated_cost: Ordinal
    redundancy: Redundancy
    priority_class: Ordinal
    priority_reason: Text


class PrioritizationResult(FrozenModel):
    assessments: tuple[QuestionPriorityAssessment, ...] = ()
    selected_question_id: Identifier | None = None

    @model_validator(mode="after")
    def selected_is_assessed(self):
        ids = [item.question_id for item in self.assessments]
        if len(ids) != len(set(ids)):
            raise ValueError("Each question may be assessed only once")
        if self.selected_question_id is not None and self.selected_question_id not in ids:
            raise ValueError("Selected question must have an assessment")
        return self


def _required_available(tool, operation) -> bool:
    required = tool.get("required_inputs", {})
    fields = required.get(operation.operation, []) if isinstance(required, Mapping) else required
    return all(field in operation.inputs and operation.inputs[field] is not None for field in fields)


def compatible_tools(context, plan, operation=None):
    """Available tools with matching capability and concrete required inputs."""
    operations = (operation,) if operation is not None else plan.planned_operations
    if not operations:
        return []
    return [tool for tool in context.get("tool_capabilities", [])
            if tool.get("availability") == "available"
            and all(tool.get("tool_type") == (op.evidence_type or plan.evidence_type)
                    and op.operation in tool.get("capabilities", [])
                    and _required_available(tool, op) for op in operations)]


def prioritize_context(context: Mapping[str, Any]) -> PrioritizationResult:
    active_ids = {h["hypothesis_id"] for h in context.get("active_hypotheses", [])}
    evidence = context.get("existing_evidence", [])
    evidence_ids = {e["evidence_id"] for e in evidence}
    predictions = {p["prediction_id"]: p for p in context.get("predictions", [])}
    human_order = {qid: index for index, qid in enumerate(context.get("human_prioritized_question_ids", []))}
    questions = {q["question_id"]: q for q in context.get("pending_questions", [])}
    assessments = []
    new_verification = {}
    for qid, question in questions.items():
        contrasts = set(question.get("discriminates_between", [])) & active_ids
        for pid in question.get("derived_from_prediction_ids", []):
            prediction = predictions.get(pid, {})
            others = set(prediction.get("discriminates_from_hypotheses", [])) & active_ids
            if others:
                contrasts |= others | ({prediction.get("hypothesis_id")} & active_ids)
        generic = bool(re.search(r"associated with cancer|biologically important|gene function|co-mention",
                                 question["question_text"], re.I))
        discriminative = "high" if len(contrasts) >= 2 and not generic else (
            "medium" if not generic and set(question.get("relevant_hypothesis_ids", [])) & active_ids else "low")
        family = question_evidence_type(question)
        plan = default_query_plan(context, qid)
        tools_per_operation = [compatible_tools(context, plan, op) for op in plan.planned_operations]
        answerability = "high" if tools_per_operation and all(tools_per_operation) else "low"
        if answerability == "high" and family == "literature":
            # Tool availability establishes feasibility, not success of retrieval.
            # Targeted, experimentally specified claims can still be high answerability.
            answerability = "high" if question.get("investigation_depth") == "verification" or (
                any(op.operation in {"search_regulatory_relation", "search_perturbation_evidence"}
                    for op in plan.planned_operations)) else "medium"
        cost_order = {"low": 0, "medium": 1, "high": 2}
        cost = max((min((t.get("cost_class", "high") for t in group),
                        key=cost_order.__getitem__, default="high") for group in tools_per_operation),
                   key=cost_order.__getitem__, default="high")
        linked = [e for e in evidence if qid == e["question_id"] or qid in e.get("related_question_ids", [])]
        same_family = [e for e in linked if e["source_type"] == {"network": "grn"}.get(family, family)]
        redundancy = "high" if any(e.get("support_quality") not in {"insufficient"}
                                   and e.get("negative_evidence_type") != "not_found" for e in same_family) else (
            "partial" if linked else "none")
        new_verification[qid] = bool(question.get("investigation_depth") == "verification"
                                    and evidence_ids.intersection(question.get("derived_from_evidence_ids", [])))
        directness = "high" if family == "literature" and (question.get("investigation_depth") == "verification"
                                  or re.search(r"experiment|knockout|perturb|crispr", question["question_text"], re.I)) else (
            "medium" if family == "dataset" else "low")
        priority = priority_class(discriminative_value=discriminative, answerability=answerability,
                                  estimated_cost=cost, redundancy=redundancy)
        reasons = [f"{qid}: {discriminative} discriminative value",
                   f"{answerability} answerability with available {family} capabilities",
                   f"{cost} acquisition cost", f"{redundancy} redundancy"]
        if contrasts and not generic:
            reasons.append("tests contrasts among " + ", ".join(sorted(contrasts)))
        if new_verification[qid]:
            reasons.append("directly verifies a newly acquired observation rather than presuming its mechanism")
        if qid in human_order:
            reasons.append("explicit human priority override")
        assessments.append(QuestionPriorityAssessment(
            question_id=qid, discriminative_value=discriminative, answerability=answerability,
            directness_potential=directness, estimated_cost=cost, redundancy=redundancy,
            priority_class=priority, priority_reason="; ".join(reasons) + "."))
    assessments.sort(key=lambda item: priority_sort_key(item, manual_order=human_order.get(item.question_id),
                                                       verifies_new_evidence=new_verification[item.question_id]))
    return PrioritizationResult(assessments=tuple(assessments),
                                selected_question_id=assessments[0].question_id if assessments else None)


def reprioritize_pending_questions(case_file, registry=None) -> PrioritizationResult:
    """Pure re-evaluation; the agent persists reasons and status through CaseStore."""
    from .context import build_investigator_context
    return prioritize_context(build_investigator_context(case_file, registry=registry))
