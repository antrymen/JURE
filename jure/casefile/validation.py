"""Structural integrity checks, independent of any scientific decision policy."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .models import CaseFile
from .critic_validation import register_critic_objects, validate_critic_references


def validate_case(value: CaseFile | Mapping[str, Any]) -> CaseFile:
    """Parse a case and reject dangling, ambiguous, or inconsistent references.

    Model instances are parsed again so Pydantic's unchecked ``model_copy`` and
    ``model_construct`` helpers cannot bypass checks at a persistence boundary.
    These checks validate recorded state, not whether a mechanism is plausible.
    """
    if isinstance(value, CaseFile):
        value = value.model_dump(mode="json")
    case = CaseFile.model_validate(value)
    objects: dict[str, str] = {}

    def register(identifier: str, object_type: str) -> None:
        if identifier in objects:
            raise ValueError(f"duplicate object ID {identifier!r}: {objects[identifier]} and {object_type}")
        objects[identifier] = object_type

    register(case.metadata.case_id, "case")
    register(case.clue.clue_id, "clue")
    question = case.mechanistic_question
    if question:
        register(question.question_id, "mechanistic_question")
        for revision in question.revisions:
            register(revision.revision_id, "question_revision")
    predictions = {}
    revision_owners = {}
    for hypothesis in case.hypotheses:
        register(hypothesis.hypothesis_id, "hypothesis")
        for revision in hypothesis.revisions:
            register(revision.revision_id, "hypothesis_revision")
            revision_owners[revision.revision_id] = hypothesis.hypothesis_id
        for prediction in hypothesis.predictions:
            register(prediction.prediction_id, "prediction")
            predictions[prediction.prediction_id] = prediction
    for records, key, object_type in (
        (case.evidence_questions, "question_id", "evidence_question"),
        (case.evidence_records, "evidence_id", "evidence_record"),
        (case.evidence_assessments, "assessment_id", "evidence_assessment"),
        (case.evidence_gaps, "gap_id", "evidence_gap"),
        (case.contradictions, "contradiction_id", "contradiction"),
        (case.investigation_history, "event_id", "history_event"),
    ):
        for record in records:
            register(getattr(record, key), object_type)
    register_critic_objects(case, register)

    def reference(identifier: str, object_type: str, context: str) -> None:
        expected = "evidence_record" if object_type == "evidence" else object_type
        actual = objects.get(identifier)
        if actual != expected:
            raise ValueError(f"{context}: dangling or wrong-type {object_type} reference {identifier!r}")

    def references(identifiers: tuple[str, ...], object_type: str, context: str) -> None:
        if len(identifiers) != len(set(identifiers)):
            raise ValueError(f"{context}: duplicate references")
        for identifier in identifiers:
            reference(identifier, object_type, context)

    if case.metadata.perturbation is not None and case.metadata.perturbation != case.clue.perturbation:
        raise ValueError("metadata perturbation must agree with the immutable clue")
    if question:
        reference(question.derived_from_clue_id, "clue", "mechanistic question")
        for previous, revised in zip(question.revisions, question.revisions[1:]):
            if revised.previous_text != previous.new_text:
                raise ValueError("mechanistic question revision chain is discontinuous")
        if question.revisions and question.revisions[-1].new_text != question.question_text:
            raise ValueError("mechanistic question text must match its latest revision")

    for hypothesis in case.hypotheses:
        if not hypothesis.revisions:
            raise ValueError(f"hypothesis {hypothesis.hypothesis_id} must have a revision")
        if hypothesis.current_revision_id != hypothesis.revisions[-1].revision_id:
            raise ValueError("current_revision_id must identify the latest hypothesis revision")
        previous_id = None
        for revision in hypothesis.revisions:
            if revision.supersedes_revision_id != previous_id:
                raise ValueError("hypothesis revision chain must supersede its immediate predecessor")
            for source in revision.derived_from:
                reference(source.object_id, source.object_type, "hypothesis derived_from")
            previous_id = revision.revision_id
        for prediction in hypothesis.predictions:
            if prediction.hypothesis_id != hypothesis.hypothesis_id:
                raise ValueError("prediction hypothesis_id must match its containing hypothesis")
            if revision_owners.get(prediction.hypothesis_revision_id) != hypothesis.hypothesis_id:
                raise ValueError("prediction must reference a revision of its own hypothesis")
            references(prediction.discriminates_from_hypotheses, "hypothesis", "prediction discrimination")

    evidence_questions = {q.question_id: q for q in case.evidence_questions}
    for evidence_question in case.evidence_questions:
        references(evidence_question.derived_from_prediction_ids, "prediction", "evidence question")
        references(evidence_question.relevant_hypothesis_ids, "hypothesis", "evidence question")
        references(evidence_question.discriminates_between, "hypothesis", "evidence question discrimination")
        references(evidence_question.derived_from_question_ids, "evidence_question", "follow-up lineage")
        references(evidence_question.derived_from_evidence_ids, "evidence_record", "follow-up lineage")
        if evidence_question.created_by == "evidence_investigator" and (
                not evidence_question.derived_from_question_ids or not evidence_question.derived_from_evidence_ids):
            raise ValueError("investigator follow-up requires question and evidence lineage")

    visiting, visited = set(), set()

    def visit_question(identifier):
        if identifier in visiting:
            raise ValueError("evidence question lineage cannot contain cycles")
        if identifier in visited:
            return
        visiting.add(identifier)
        for parent in evidence_questions[identifier].derived_from_question_ids:
            visit_question(parent)
        visiting.remove(identifier)
        visited.add(identifier)

    for identifier in evidence_questions:
        visit_question(identifier)

    prior_evidence = {}
    for evidence in case.evidence_records:
        reference(evidence.question_id, "evidence_question", "evidence record")
        references(evidence.related_question_ids, "evidence_question", "evidence record")
        if evidence.supersedes_evidence_id is not None:
            previous = prior_evidence.get(evidence.supersedes_evidence_id)
            if previous is None:
                raise ValueError("supersedes_evidence_id must reference earlier evidence (no cycles)")
            if previous.question_id != evidence.question_id:
                raise ValueError("replacement evidence must address the same evidence question")
        prior_evidence[evidence.evidence_id] = evidence

    for assessment in case.evidence_assessments:
        reference(assessment.evidence_id, "evidence_record", "evidence assessment")
        reference(assessment.hypothesis_id, "hypothesis", "evidence assessment")
        if revision_owners.get(assessment.hypothesis_revision_id) != assessment.hypothesis_id:
            raise ValueError("assessment must reference a revision of its own hypothesis")
        if assessment.prediction_id is not None:
            reference(assessment.prediction_id, "prediction", "evidence assessment")
            prediction = predictions[assessment.prediction_id]
            if (prediction.hypothesis_id != assessment.hypothesis_id
                    or prediction.hypothesis_revision_id != assessment.hypothesis_revision_id):
                raise ValueError("assessment prediction and hypothesis revision must agree")

    for gap in case.evidence_gaps:
        references(gap.related_hypotheses, "hypothesis", "evidence gap")
        references(gap.related_predictions, "prediction", "evidence gap")
        references(gap.related_question_ids, "evidence_question", "evidence gap")
        references(gap.related_claim_ids, "mechanistic_claim", "evidence gap")
        references(gap.related_evidence_ids, "evidence_record", "evidence gap")
    for contradiction in case.contradictions:
        references(contradiction.evidence_ids, "evidence_record", "contradiction")
        references(contradiction.hypothesis_ids, "hypothesis", "contradiction")
        references(contradiction.claim_ids, "mechanistic_claim", "contradiction")

    validate_critic_references(case, reference, references, predictions, revision_owners)

    selected = case.action_state.selected_question_id
    if selected is not None:
        reference(selected, "evidence_question", "action state")
        if evidence_questions[selected].status not in {"selected", "in_progress", "partially_answered"}:
            raise ValueError("action state selected question must have an active status")

    if len(case.investigation_history) != case.metadata.case_revision:
        raise ValueError("history length must equal case_revision")
    for sequence, event in enumerate(case.investigation_history, start=1):
        if event.sequence != sequence or event.case_revision != sequence:
            raise ValueError("history sequence and case_revision must be contiguous from 1")
        # Nothing is deleted from the supported write API; historical records
        # continue to point at the preserved object or revision they describe.
        reference(event.object_id, event.object_type, "history event")
    return case
