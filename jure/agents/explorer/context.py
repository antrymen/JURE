"""Bounded factual prompt views of the authoritative Shared Case File."""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from jure.casefile.models import CaseFile, INTERPRETATION_BOUNDARY

from .models import ExplorerMode, MechanismStructure


class ContextLimitError(ValueError):
    """The required factual context does not fit; no evidence was silently cut."""


def explorer_write_contract(config):
    """Shared interface constraints, without mechanisms or tool recommendations."""
    return {
        'validation_policy': config.validation_policy,
        'max_changed_hypotheses': config.max_hypotheses,
        'batch_semantics': 'Each add or revise counts as one change. Unchanged hypotheses remain stored; return only the selected changes, not the whole historical set. Contrast each changed hypothesis with every other non-rejected working hypothesis, including unchanged IDs. Adding a new ID does not remove an old hypothesis.',
        'lineage': 'Use typed IDs from the supplied lineage catalog. A Critic revision request is design provenance, not experimental evidence.',
        'new_objects': 'Predictions and evidence questions are append-only and need globally unused IDs; do not repeat existing objects.',
        'molecular_names': ('New named mediators may be proposed as unverified hypotheses, with assumptions and provenance/evidence needs. Do not present them as established facts. Critic flags are audit prompts, not evidence or verdicts.' if config.validation_policy == 'three_layer' else 'Explorer may use names supplied by typed clue facts or acquired EvidenceRecords. Names suggested only in a Critic audit/request are not acquired evidence. Hypothetical labeling does not provide a missing source.'),
        'audit_boundary': 'These interface constraints do not waive hypothesis quality checks or prescribe a scientific verdict, revision content, evidence tool, or route.',
    }


def _current_structure(case_file: CaseFile, hypothesis_id: str, revision_id: str) -> dict[str, Any] | None:
    """Recover only the matching current-revision annotation, never full history."""
    for event in reversed(case_file.investigation_history):
        if event.object_type != "hypothesis" or event.object_id != hypothesis_id:
            continue
        metadata = event.metadata
        if metadata.get("hypothesis_revision_id") != revision_id or "structure" not in metadata:
            continue
        try:
            return MechanismStructure.model_validate(metadata["structure"]).model_dump(mode="json")
        except (TypeError, ValueError, ValidationError):
            # External annotations are not a second authoritative state schema.
            # An invalid structure cannot be used as a semantic comparison fact.
            return None
    return None


def build_explorer_context(
    case_file: CaseFile,
    mode: ExplorerMode,
    *,
    reframe_reason: str | None = None,
    max_chars: int = 60_000,
) -> dict[str, Any]:
    """Return a detached, JSON-safe context, without raw payload or audit history.

    Initial exploration sees the clue's typed observations and source-stage
    statistics. Reframe also sees current mechanisms, predictions, assessments,
    evidence, gaps and contradictions; older revisions are included only when
    referenced by predictions or assessments. Exceeding ``max_chars`` raises an
    explicit error instead of silently omitting contrary evidence.
    """
    if mode not in ("initial", "reframe"):
        raise ValueError("mode must be 'initial' or 'reframe'")
    if type(max_chars) is not int or max_chars < 1:
        raise ValueError("max_chars must be a positive integer")
    if mode == "reframe" and (not isinstance(reframe_reason, str) or not reframe_reason.strip()):
        raise ValueError("reframe requires a nonempty reframe_reason")

    # Lazy import keeps the models/backend layer independent of semantic checks.
    from .validation import interpret_observation

    clue = case_file.clue
    context: dict[str, Any] = {
        "mode": mode,
        "case_id": case_file.metadata.case_id,
        "source_case_revision": case_file.metadata.case_revision,
        "clue": clue.model_dump(mode="json", exclude={"source_payload"}),
        "biological_context": {
            "source_dataset": case_file.metadata.source_dataset,
            "cell_context": case_file.metadata.cell_context,
            "perturbation": case_file.metadata.perturbation,
        },
        "interpretation_boundary": [INTERPRETATION_BOUNDARY, clue.interpretation_boundary],
        "observation_interpretation_required": interpret_observation(case_file),
        "schema_requirements": {
            "min_hypotheses": 2,
            "max_hypotheses": 4,
            "hypothesis_status": "proposed",
            "prediction_status": "untested",
            "evidence_question_status": "pending",
            "mechanism_classes": "free; choose structures suitable for this clue, not a fixed class list",
            "observation_interpretation": "Copy observation_interpretation_required exactly.",
            "mechanistic_question": (
                "Ask why this perturbation changes the joint state's prevalence, preserving biological "
                "context; do not presuppose one mechanism or ask generic gene function questions."
            ),
            "competition": (
                "Every pair of proposed hypotheses needs a concrete structural difference and a "
                "HypothesisContrast. Compare reframe proposals with relevant existing hypotheses too. "
                "Structure descriptors must match the mechanisms, not merely use different labels."
            ),
            "predictions": (
                "Every hypothesis has at least one testable prediction specifying expected and weakening "
                "observations, and at least one named alternative hypothesis it distinguishes. "
                "Biological importance, generic relatedness and merely finding literature are insufficient."
            ),
            "questions": (
                "Every evidence question has valid prediction lineage and hypothesis links; at least one "
                "question distinguishes two or more hypotheses. Suggest only an evidence type, not a tool."
            ),
            "factual_boundaries": (
                "States mean exactly the provided encoding, never inferred up/downregulation. Keep "
                "reference discovery, reference validation, legacy condition statistics and perturbation "
                "frequency shift separate. Do not invent stability or replication when absent. "
                "No statistic proves a causal mechanism. Do not assert unsupported named regulators, "
                "pathways or specific regulatory edges as evidence; keep general possibilities hypothetical."
            ),
            "forbidden_outputs": [
                "EvidenceRecord", "clue edits", "evidence assessments", "scores", "probabilities",
                "confidence", "hypothesis verdicts", "tool selection", "action routing",
            ],
        },
    }

    if mode == "initial":
        context['lineage_catalog'] = [
            {'object_id': case_file.metadata.case_id, 'object_type': 'case'},
            {'object_id': case_file.clue.clue_id, 'object_type': 'clue'},
        ]
        context['schema_requirements']['lineage'] = (
            'Copy exact object_id/object_type pairs from lineage_catalog. IDs nested inside clue '
            'provenance or source metadata are not independent Case File objects and cannot be '
            'relabeled as case, evidence or evidence_gap references.'
        )
    if mode == "reframe":
        context["schema_requirements"]["min_changed_hypotheses"] = 1
        context["schema_requirements"]["max_changed_hypotheses"] = 4
        context["reframe_reason"] = reframe_reason.strip()
        context["critic_revision_requests"] = [request.model_dump(mode="json")
            for request in case_file.critic_audits.revision_requests[-1:]]
        question = case_file.mechanistic_question
        context["current_mechanistic_question"] = (
            question.model_dump(mode="json", exclude={"revisions"}) if question is not None else None
        )
        referenced_revision_ids = {
            assessment.hypothesis_revision_id for assessment in case_file.evidence_assessments
        } | {
            prediction.hypothesis_revision_id
            for hypothesis in case_file.hypotheses for prediction in hypothesis.predictions
        }
        context["existing_hypotheses"] = [
            {
                "hypothesis_id": hypothesis.hypothesis_id,
                "current_revision_id": hypothesis.current_revision_id,
                "current_revision": hypothesis.current_revision.model_dump(mode="json"),
                "referenced_revisions": [
                    revision.model_dump(mode="json") for revision in hypothesis.revisions
                    if revision.revision_id != hypothesis.current_revision_id
                    and revision.revision_id in referenced_revision_ids
                ],
                "predictions": [prediction.model_dump(mode="json") for prediction in hypothesis.predictions],
                "structure": _current_structure(
                    case_file, hypothesis.hypothesis_id, hypothesis.current_revision_id,
                ),
            }
            for hypothesis in case_file.hypotheses
        ]
        context['existing_working_hypothesis_ids'] = [h.hypothesis_id for h in case_file.hypotheses
                                                     if h.current_revision.status != 'rejected']
        context["existing_evidence_questions"] = [q.model_dump(mode="json") for q in case_file.evidence_questions]
        context["existing_evidence"] = [e.model_dump(mode="json") for e in case_file.evidence_records]
        context["existing_evidence_assessments"] = [a.model_dump(mode="json") for a in case_file.evidence_assessments]
        context["evidence_gaps"] = [gap.model_dump(mode="json") for gap in case_file.evidence_gaps]
        context["contradictions"] = [c.model_dump(mode="json") for c in case_file.contradictions]
        context["schema_requirements"]["reframe"] = (
            "Use add for new IDs and revise for existing IDs. Every change needs a reason and typed "
            "lineage to existing hypotheses/revisions, evidence, gaps, contradictions, or a linked Critic revision request. Preserve "
            "historical revisions and their predictions. min_hypotheses applies to the resulting working "
            "hypothesis set, not the number changed in this response; a single addition or revision is "
            "allowed. Return between min_changed_hypotheses and max_changed_hypotheses changes. "
            "Do not make retained/rejected verdicts."
        )
        from .validation import _objects
        source_kinds = {'hypothesis', 'hypothesis_revision', 'evidence_record', 'evidence_gap',
                        'contradiction', 'evidence_assessment', 'revision_request'}
        context['lineage_catalog'] = [{'object_id': identifier, 'object_type': kind}
            for identifier, kind in _objects(case_file).items() if kind in source_kinds]

    encoded = json.dumps(context, ensure_ascii=False, allow_nan=False)
    if len(encoded) > max_chars:
        raise ContextLimitError(
            f"Explorer {mode} context requires {len(encoded)} characters, exceeding max_chars={max_chars}; "
            "no evidence was silently omitted"
        )
    return context
