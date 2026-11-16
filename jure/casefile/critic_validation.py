"""Reference checks for the additive critic-owned Case File sections."""
from .critic_models import CRITIC_COLLECTIONS


def register_critic_objects(case, register):
    for claim in case.mechanistic_claims:
        register(claim.claim_id, "mechanistic_claim")
    for name, (_, key, object_type) in CRITIC_COLLECTIONS.items():
        for record in getattr(case.critic_audits, name):
            register(getattr(record, key), object_type)
    # Recommendations are values embedded in stop/report records and may be
    # intentionally repeated in both. One ID must still denote one exact value.
    experiments = {r.experiment_id: r for r in case.critic_audits.recommended_experiments}
    for record in (*case.critic_audits.stop_records, *case.critic_audits.final_reports):
        for experiment in record.recommended_experiments:
            previous = experiments.get(experiment.experiment_id)
            if previous is None:
                register(experiment.experiment_id, "recommended_experiment")
                experiments[experiment.experiment_id] = experiment
            elif previous != experiment:
                raise ValueError("recommended experiment ID has inconsistent contents")


def validate_critic_references(case, reference, references, predictions, revision_owners):
    claims = {c.claim_id: c for c in case.mechanistic_claims}

    def refs(record, mapping):
        for field, kind in mapping.items():
            references(getattr(record, field), kind, type(record).__name__ + "." + field)

    def own_claims(hypothesis_id, identifiers):
        for identifier in identifiers:
            reference(identifier, "mechanistic_claim", "claim ownership")
            if claims[identifier].hypothesis_id != hypothesis_id:
                raise ValueError("claim must belong to the referenced hypothesis")

    for claim in claims.values():
        reference(claim.hypothesis_id, "hypothesis", "mechanistic claim")
        if claim.hypothesis_revision_id is not None and revision_owners.get(claim.hypothesis_revision_id) != claim.hypothesis_id:
            raise ValueError("claim must reference a revision of its own hypothesis")
        references(claim.derived_from_prediction_ids, "prediction", "mechanistic claim")
        for prediction_id in claim.derived_from_prediction_ids:
            prediction = predictions[prediction_id]
            if prediction.hypothesis_id != claim.hypothesis_id:
                raise ValueError("claim prediction must belong to its own hypothesis")
            if claim.hypothesis_revision_id is not None and prediction.hypothesis_revision_id != claim.hypothesis_revision_id:
                raise ValueError("claim prediction and hypothesis revision must agree")
    audits = case.critic_audits
    for audit in audits.hypothesis_audits:
        reference(audit.case_id, "case", "hypothesis audit")
        seen = set()
        for per_hypothesis in audit.per_hypothesis:
            reference(per_hypothesis.hypothesis_id, "hypothesis", "hypothesis audit")
            if per_hypothesis.hypothesis_id in seen:
                raise ValueError("duplicate hypothesis in hypothesis audit")
            seen.add(per_hypothesis.hypothesis_id)
    for audit in audits.evidence_audits:
        reference(audit.evidence_id, "evidence_record", "evidence audit")
        refs(audit, {"claim_ids": "mechanistic_claim"})
    for audit in audits.claim_audits:
        reference(audit.claim_id, "mechanistic_claim", "claim audit")
        refs(audit, {"evidence_ids": "evidence_record", "supporting_evidence_ids": "evidence_record",
                     "challenging_evidence_ids": "evidence_record", "gap_ids": "evidence_gap",
                     "contradiction_ids": "contradiction"})
        if set(audit.supporting_evidence_ids + audit.challenging_evidence_ids) - set(audit.evidence_ids):
            raise ValueError("supporting/challenging evidence must be included in claim audit evidence_ids")
    for synthesis in audits.hypothesis_syntheses:
        reference(synthesis.hypothesis_id, "hypothesis", "hypothesis synthesis")
        if synthesis.hypothesis_revision_id is not None and revision_owners.get(synthesis.hypothesis_revision_id) != synthesis.hypothesis_id:
            raise ValueError("synthesis must reference a revision of its own hypothesis")
        all_claims = synthesis.supported_claim_ids + synthesis.partial_claim_ids + synthesis.challenged_claim_ids + synthesis.insufficient_claim_ids
        references(all_claims, "mechanistic_claim", "hypothesis synthesis")
        own_claims(synthesis.hypothesis_id, all_claims)
        if synthesis.hypothesis_revision_id is not None and any(
            claims[c].hypothesis_revision_id not in {None, synthesis.hypothesis_revision_id} for c in all_claims
        ):
            raise ValueError("synthesis and claim hypothesis revisions must agree")
        refs(synthesis, {"critical_gaps": "evidence_gap", "contradictions": "contradiction"})
    related_mapping = {"related_hypothesis_ids": "hypothesis", "related_claim_ids": "mechanistic_claim",
                       "related_evidence_ids": "evidence_record", "related_gap_ids": "evidence_gap"}
    for decision in (*audits.routing_decisions, *audits.failure_attributions):
        refs(decision, related_mapping)
    for request in audits.revision_requests:
        refs(request, {"affected_hypothesis_ids": "hypothesis", "evidence_that_triggered_reframe": "evidence_record"})
    for request in audits.investigation_requests:
        refs(request, {"target_claim_ids": "mechanistic_claim", "target_gap_ids": "evidence_gap"})
    for change in audits.status_changes:
        reference(change.hypothesis_id, "hypothesis", "hypothesis status change")
        refs(change, {"claim_ids": "mechanistic_claim", "evidence_ids": "evidence_record", "gap_ids": "evidence_gap"})
        own_claims(change.hypothesis_id, change.claim_ids)
    for snapshot in audits.progress_snapshots:
        refs(snapshot, {"effective_evidence_ids": "evidence_record", "resolved_gap_ids": "evidence_gap",
                        "discriminating_question_ids": "evidence_question"})
    for stop in audits.stop_records:
        references(tuple(stop.final_hypothesis_states), "hypothesis", "stop hypothesis states")
        refs(stop, {"remaining_hypotheses": "hypothesis", "unresolved_critical_gaps": "evidence_gap",
                    "resolved_gaps": "evidence_gap", "key_supporting_evidence_ids": "evidence_record",
                    "key_challenging_evidence_ids": "evidence_record", "evidence_already_checked": "evidence_record"})
    for report in audits.final_reports:
        reference(report.case_id, "case", "critic final report")
        for final in report.final_hypotheses:
            reference(final.hypothesis_id, "hypothesis", "final hypothesis report")
            refs(final, {"key_supported_claims": "mechanistic_claim", "key_challenged_claims": "mechanistic_claim",
                         "critical_gaps": "evidence_gap", "key_evidence_ids": "evidence_record", "contradictions": "contradiction"})
            own_claims(final.hypothesis_id, final.key_supported_claims + final.key_challenged_claims)
    experiments = list(audits.recommended_experiments)
    for record in (*audits.stop_records, *audits.final_reports):
        experiments.extend(record.recommended_experiments)
    for experiment in experiments:
        refs(experiment, {"related_hypothesis_ids": "hypothesis", "related_claim_ids": "mechanistic_claim"})
