"""Enforce IDs, tool capabilities, budgets, and protected Case File state."""
from collections.abc import Mapping
import json

from jure.casefile import EvidenceRecord, validate_case
from .evidence_normalizer import NETWORK_LIMITATION
from .queue import SELECTABLE


def parse_backend_output(model, response):
    if hasattr(response, "model_dump"):
        response = response.model_dump(mode="json")
    if isinstance(response, Mapping):
        response = json.dumps(dict(response), allow_nan=False)
    if not isinstance(response, str) or len(response) > 200_000:
        raise ValueError("backend must return a bounded structured JSON object")
    return model.model_validate_json(response)


def validate_investigator_action(case, *, question_id=None, plan=None, tool=None,
                                 tool_calls=0, max_tool_calls=3, evidence=None,
                                 before=None, operation=None):
    if question_id is not None:
        questions = {q.question_id: q for q in case.evidence_questions}
        if question_id not in questions:
            raise ValueError("selected question does not exist")
        if questions[question_id].status not in SELECTABLE | {"selected", "in_progress"}:
            raise ValueError("question status cannot be investigated")
    if plan is not None and plan.question_id != question_id:
        raise ValueError("QueryPlan must point to the selected question")
    if plan is not None and question_id is not None:
        specification = questions[question_id].query_spec.to_dict()
        expected = specification.get("planned_operations")
        if not expected and specification.get("operation"):
            expected = [{"operation": specification["operation"], "inputs": specification.get("inputs", {}),
                         "evidence_type": specification.get("evidence_type")}]
        # A typed biological query is an input contract, not a suggestion that a
        # backend can silently simplify by dropping the conditioning population.
        if expected and operation is None:
            if len(plan.planned_operations) != len(expected):
                raise ValueError("QueryPlan changed the explicit query specification")
            for actual, required in zip(plan.planned_operations, expected):
                if (actual.operation != required["operation"]
                    or any(actual.inputs.get(key) != value for key, value in required.get("inputs", {}).items())
                    or (required.get("evidence_type") and
                        (actual.evidence_type or plan.evidence_type) != required["evidence_type"])):
                    raise ValueError("QueryPlan changed an explicit operation, target, context or filter")
    if tool is not None:
        if tool.metadata.availability != "available":
            raise ValueError("selected tool is unavailable")
        if operation is not None and operation.operation not in tool.metadata.capabilities:
            raise ValueError("selected tool cannot execute the planned operation")
        family = operation.evidence_type if operation is not None else None
        if plan is not None and tool.metadata.tool_type != (family or plan.evidence_type):
            raise ValueError("selected tool family does not match query plan")
        if tool_calls >= max_tool_calls:
            raise ValueError("tool call budget reached")
    if evidence is not None:
        evidence = EvidenceRecord.model_validate(evidence.model_dump(mode="json"))
        if evidence.question_id not in {q.question_id for q in case.evidence_questions}:
            raise ValueError("evidence must link to an existing question")
        if not evidence.provenance.parameters or not evidence.raw_result_reference:
            raise ValueError("evidence requires full provenance and raw artifact")
        parameters = evidence.provenance.parameters
        if parameters.get("execution_status") in {"no_result", "failed"} and evidence.negative_evidence_type == "explicit_null_result":
            raise ValueError("unresolved acquisition is not negative experimental evidence")
    if before is not None:
        validate_case(case)
        for key in ("clue", "mechanistic_question", "hypotheses"):
            if getattr(before, key) != getattr(case, key):
                raise ValueError(f"Investigator modified protected field: {key}")
        if case.investigation_history[:len(before.investigation_history)] != before.investigation_history:
            raise ValueError("Investigator rewrote history")
        if case.action_state.current_phase == "stopped":
            raise ValueError("Investigator cannot stop the case")
    return True
