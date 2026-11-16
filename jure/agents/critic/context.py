"""Stage-scoped JSON views; no tool handle, store, raw output, or full history."""
from __future__ import annotations
import json
from jure.agents.explorer.context import _current_structure


def active_claims(case):
    revisions = {h.hypothesis_id: h.current_revision_id for h in case.hypotheses
                 if h.current_revision.status != 'rejected'}
    return tuple(c for c in case.mechanistic_claims
                 if c.hypothesis_id in revisions and
                 (c.hypothesis_revision_id is None or c.hypothesis_revision_id == revisions[c.hypothesis_id]))


def build_critic_context(case_file, audit_stage, *, max_chars=250_000, **extra):
    aliases = {'C1': 'hypothesis', 'hypothesis_audit': 'hypothesis',
               'C2': 'evidence', 'evidence_audit': 'evidence', 'final_audit': 'final'}
    stage = aliases.get(audit_stage, audit_stage)
    if stage not in {'hypothesis', 'evidence', 'final'}:
        raise ValueError('audit_stage must be hypothesis, evidence, or final')
    case = case_file
    hypotheses = [h for h in case.hypotheses if h.current_revision.status != 'rejected']
    predictions = [p for h in hypotheses for p in h.predictions
                   if p.hypothesis_revision_id == h.current_revision_id]
    pids = {p.prediction_id for p in predictions}
    hids = {h.hypothesis_id for h in hypotheses}
    questions = [q for q in case.evidence_questions if pids.intersection(q.derived_from_prediction_ids)
                 or (not q.derived_from_prediction_ids and hids.intersection(q.relevant_hypothesis_ids))]
    # Follow-up lineage is valid without repeating prediction IDs.
    while True:
        qids = {q.question_id for q in questions}
        lineage_eids = {e.evidence_id for e in case.evidence_records if qids.intersection(e.question_ids)}
        added = [q for q in case.evidence_questions if q.question_id not in qids
                 and (qids.intersection(q.derived_from_question_ids)
                      or lineage_eids.intersection(q.derived_from_evidence_ids))]
        if not added:
            break
        questions.extend(added)
    context = {
        'audit_stage': stage, 'case_id': case.metadata.case_id,
        'source_case_revision': case.metadata.case_revision,
        'clue': case.clue.model_dump(mode='json', exclude={'source_payload'}),
        'mechanistic_question': case.mechanistic_question.model_dump(mode='json', exclude={'revisions'})
            if case.mechanistic_question else None,
        'biological_context': {'source_dataset': case.metadata.source_dataset,
                               'cell_context': case.metadata.cell_context,
                               'perturbation': case.metadata.perturbation},
        'hypotheses': [{'hypothesis_id': h.hypothesis_id, 'current_revision_id': h.current_revision_id,
                        'current_revision': h.current_revision.model_dump(mode='json'),
                        'predictions': [p.model_dump(mode='json') for p in predictions if p.hypothesis_id == h.hypothesis_id],
                        'structure': _current_structure(case, h.hypothesis_id, h.current_revision_id)}
                       for h in hypotheses],
        'predictions': [p.model_dump(mode='json') for p in predictions],
        'evidence_questions': [q.model_dump(mode='json') for q in questions],
    }
    # C1 reviews hypothesis design with the acquired evidence available,
    # but this context construction never performs C2 or assigns claim verdicts.
    claims = active_claims(case)
    cids = {c.claim_id for c in claims}
    qids = {q.question_id for q in questions}
    assessments = [a for a in case.evidence_assessments if a.prediction_id in pids or
                   any(a.hypothesis_id == h.hypothesis_id and a.hypothesis_revision_id == h.current_revision_id
                       for h in hypotheses)]
    eids = {a.evidence_id for a in assessments}
    eids.update(e.evidence_id for e in case.evidence_records if qids.intersection(e.question_ids))
    gaps = [g for g in case.evidence_gaps if cids.intersection(g.related_claim_ids) or
            pids.intersection(g.related_predictions) or
            (not g.related_predictions and not g.related_claim_ids and
             any(h.hypothesis_id in g.related_hypotheses for h in hypotheses))]
    contradictions = [c for c in case.contradictions if cids.intersection(c.claim_ids) or
                      eids.intersection(c.evidence_ids)]
    # Keep opposing records needed to interpret a relevant contradiction.
    eids.update(eid for c in contradictions for eid in c.evidence_ids)
    evidence = [e for e in case.evidence_records if e.evidence_id in eids]
    context.update(
        claims=[c.model_dump(mode='json') for c in claims],
        evidence_records=[e.model_dump(mode='json') for e in evidence],
        evidence_assessments=[a.model_dump(mode='json') for a in assessments],
        evidence_audits=[a.model_dump(mode='json') for a in case.critic_audits.evidence_audits
                         if a.evidence_id in eids],
        evidence_gaps=[g.model_dump(mode='json') for g in gaps],
        contradictions=[c.model_dump(mode='json') for c in contradictions],
        provenance_summaries=[{'evidence_id': e.evidence_id, **e.provenance.model_dump(mode='json'),
                               'raw_result_reference': e.raw_result_reference} for e in evidence],
    )
    from jure.protocol.admission import latest_admission
    admission = latest_admission(case)
    if admission is not None:
        context['proposal_admission'] = dict(admission.metadata)
        context['proposal_admission']['event_id'] = admission.event_id
        context['proposal_admission']['contract'] = (
            'Machine and completeness admission is not scientific acceptance. The attached flags '
            'are fallible lexical/structural prompts, not evidence or established defects. '
            'C1 must independently assess specificity, testability, competing alternatives, '
            'observability, causal wording and unsupported assumptions. New named mediators '
            'may be hypotheses; assess their provenance needs and do not treat them as known facts. '
            'Do not use the presence/absence or count of flags as an automatic pass/fail rule.')
    context.update(extra)
    from jure.protocol.source_review import source_review_targets, source_acquisition_history
    context['source_review_targets'] = source_review_targets(case)
    context['source_acquisition_history'] = source_acquisition_history(case)
    context['protocol_corrections']=[dict(e.metadata) for e in case.investigation_history
        if e.actor=='controller' and e.metadata.get('controller_event')=='REVISION_REQUIREMENT_WITHDRAWN']
    from .references import reference_catalog
    context["reference_catalog"] = reference_catalog(context)
    result = json.loads(json.dumps(context, ensure_ascii=False, allow_nan=False))
    if len(json.dumps(result, ensure_ascii=False)) > max_chars:
        raise ValueError('Critic stage context exceeds max_context_chars; no evidence was silently omitted')
    return result
