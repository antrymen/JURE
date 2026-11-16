"""Question identity, bounded follow-ups, and explicit recovery of abandoned work."""
import json
import re
from datetime import timedelta

from jure.casefile import EvidenceQuestion, new_id, utc_now

ACTOR = "evidence_investigator"
SELECTABLE = {"pending", "partially_answered", "unresolved"}


def record_event(store, case, action, run_id, *, object_type="case", object_id=None, **metadata):
    return store.append_history_event(
        case.metadata.case_id, actor=ACTOR, expected_revision=case.metadata.case_revision,
        summary=action, action=action, object_type=object_type,
        object_id=object_id or case.metadata.case_id,
        metadata={"investigator_event": action, "run_id": run_id, **metadata},
    )


def question_fingerprint(question):
    """Conservative relation identity: preserve context and explicit query filters."""
    spec = question.query_spec.to_dict()
    if spec:
        return json.dumps(spec, sort_keys=True, ensure_ascii=False)
    text = question.question_text.lower().strip().rstrip("?.")
    text = text.replace("→", "->")
    patterns = (
        r"(?:does|can)\s+(\w+)\s+(?:regulate|regulates|control)\s+(\w+)(.*)",
        r"(?:is there evidence for|is there evidence that|evidence for)\s+(\w+)\s*->\s*(\w+)(.*)",
    )
    for pattern in patterns:
        match = re.fullmatch(pattern, text)
        if match:
            return "regulation:" + ":".join(match.groups())
    return re.sub(r"\s+", " ", text)


def deduplicate_evidence_questions(questions):
    """Return (newer, original) IDs; never delete an existing question."""
    seen, duplicates = {}, []
    for question in questions:
        if question.status == "cancelled":
            continue
        key = question_fingerprint(question)
        if key in seen:
            duplicates.append((question.question_id, seen[key]))
        else:
            seen[key] = question.question_id
    return tuple(duplicates)


def make_network_followups(question, evidence, candidates, *, limit):
    """Only verify an acquired architecture; do not invent another hypothesis."""
    output = []
    for candidate in candidates[:limit]:
        regulator = candidate["regulator"]
        targets = candidate["targets"]
        output.append(EvidenceQuestion(
            question_id=new_id("Q"),
            question_text=f"Is there direct experimental evidence that {regulator} regulates "
                          f"{', '.join(targets)} in the relevant context?",
            derived_from_prediction_ids=question.derived_from_prediction_ids,
            relevant_hypothesis_ids=question.relevant_hypothesis_ids,
            discriminates_between=question.discriminates_between,
            suggested_evidence_type="literature", investigation_depth="verification",
            derived_from_question_ids=(question.question_id,),
            derived_from_evidence_ids=(evidence.evidence_id,), created_by=ACTOR,
            query_spec={"evidence_type": "literature", "operation": "search_claim",
                        "inputs": {"claim": f"{regulator} regulates {', '.join(targets)}",
                                   "context": candidate.get("context")}},
        ))
    return tuple(output)


def recover_stale_in_progress_questions(store, case_id, *, stale_after_seconds=3600, now=None):
    """Explicit host recovery. Recent work is left alone; all changes are audited.

    Investigator stages question transitions outside the authoritative store, so
    its own interrupted calls normally leave questions pending. This also recovers
    old/manual in-progress entries. Run start times act as conservative leases.
    """
    if stale_after_seconds < 0:
        raise ValueError("stale_after_seconds cannot be negative")
    case = store.load_case(case_id)
    cutoff = (now or utc_now()) - timedelta(seconds=stale_after_seconds)
    recovered = []
    with store.atomic(case_id, expected_revision=case.metadata.case_revision):
        for question in case.evidence_questions:
            if question.status not in {"selected", "in_progress"}:
                continue
            touched = [e.timestamp for e in case.investigation_history
                       if e.object_id == question.question_id or e.action == "INVESTIGATOR_STARTED"]
            if max(touched, default=question.created_at) > cutoff:
                continue
            case = store.update_evidence_question_status(
                case_id, question.question_id, "pending", actor=ACTOR,
                expected_revision=case.metadata.case_revision)
            case = record_event(store, case, "STALE_QUESTION_RECOVERED", new_id("RECOVERY"),
                                object_type="evidence_question", object_id=question.question_id,
                                previous_status=question.status, reason="abandoned run or stale lease")
            recovered.append(question.question_id)
    return tuple(recovered)


def manually_prioritize_question(store, case_id, question_id):
    case = store.load_case(case_id)
    return store.manually_prioritize_question(case_id, question_id,
                                             expected_revision=case.metadata.case_revision)


def manually_cancel_question(store, case_id, question_id):
    case = store.load_case(case_id)
    return store.manually_cancel_question(case_id, question_id,
                                         expected_revision=case.metadata.case_revision)


def manually_add_evidence_question(store, case_id, question):
    case = store.load_case(case_id)
    return store.manually_add_evidence_question(case_id, question,
                                               expected_revision=case.metadata.case_revision)
