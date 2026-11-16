"""Apply normalized observations through the existing CaseStore commands."""
from jure.casefile import ContradictionRecord, EvidenceAssessment, EvidenceGap, EvidenceQuestion

from .queue import ACTOR, deduplicate_evidence_questions, make_network_followups, record_event
from .validation import validate_investigator_action


class InvestigationRecorder:
    def __init__(self, store, case, config, run_id):
        self.store, self.case, self.config, self.run_id = store, case, config, run_id
        self.evidence_ids, self.linked_ids, self.gap_ids, self.followup_ids = [], [], [], []

    def call(self, method, *args, **kwargs):
        self.case = getattr(self.store, method)(
            self.case.metadata.case_id, *args, actor=ACTOR,
            expected_revision=self.case.metadata.case_revision, **kwargs)
        return self.case

    def event(self, action, **kwargs):
        self.case = record_event(self.store, self.case, action, self.run_id, **kwargs)

    def consume_critic_request(self):
        """Investigator owns queue changes; Critic supplies only gaps and objectives."""
        if not self.case.critic_audits.investigation_requests:
            return
        request = self.case.critic_audits.investigation_requests[-1]
        if any(e.action == "CRITIC_REQUEST_CONSUMED" and e.metadata.get("request_id") == request.request_id
               for e in self.case.investigation_history):
            return
        for claim in self.case.mechanistic_claims:
            if claim.claim_id not in request.target_claim_ids:
                continue
            linked = [q for q in self.case.evidence_questions
                      if set(q.derived_from_prediction_ids).intersection(claim.derived_from_prediction_ids)]
            selectable = [q for q in linked if q.status in {"pending", "partially_answered", "unresolved"}]
            if selectable:
                for question in selectable:
                    if question.priority != "high":
                        self.call("update_evidence_question_priority", question.question_id, "high")
                continue
            if not self.config.allow_followup_questions or len(self.followup_ids) >= self.config.max_new_followup_questions:
                continue
            if linked and all(q.status == "cancelled" for q in linked):
                continue  # Preserve explicit cancellation rather than recreating its work.
            text = f"What direct, context-matched experimental evidence supports or challenges this prediction: {claim.statement}?"
            if any(q.question_text == text for q in self.case.evidence_questions):
                continue
            hypotheses = tuple(dict.fromkeys(h for q in linked for h in q.relevant_hypothesis_ids)) or (claim.hypothesis_id,)
            contrasts = tuple(dict.fromkeys(h for q in linked for h in q.discriminates_between))
            linked_ids = {q.question_id for q in linked}
            evidence_ids = tuple(e.evidence_id for e in self.case.evidence_records
                                 if linked_ids.intersection(e.question_ids))
            if not linked or not evidence_ids:
                continue  # A follow-up requires actual question and evidence lineage.
            question = EvidenceQuestion(question_text=text, created_by=ACTOR, priority="high",
                derived_from_prediction_ids=claim.derived_from_prediction_ids,
                derived_from_question_ids=tuple(q.question_id for q in linked),
                derived_from_evidence_ids=evidence_ids,
                relevant_hypothesis_ids=hypotheses, discriminates_between=contrasts,
                investigation_depth="verification")
            self.call("add_evidence_question", question)
            self.followup_ids.append(question.question_id)
            self.event("FOLLOWUP_QUESTION_CREATED", object_type="evidence_question", object_id=question.question_id,
                       critic_request_id=request.request_id, claim_id=claim.claim_id)
        self.event("CRITIC_REQUEST_CONSUMED", request_id=request.request_id)

    def status(self, question_id, status):
        old = next(q.status for q in self.case.evidence_questions if q.question_id == question_id)
        self.call("update_evidence_question_status", question_id, status)
        self.event("QUESTION_STATUS_UPDATED", object_type="evidence_question", object_id=question_id,
                   previous_status=old, status=status)
        if status == "answered":
            answered = {q.question_id for q in self.case.evidence_questions if q.status == "answered"}
            for gap in self.case.evidence_gaps:
                if (gap.status != "addressed" and question_id in gap.related_question_ids
                        and set(gap.related_question_ids) <= answered):
                    self.call("update_evidence_gap_status", gap.gap_id, "addressed")
                    self.event("EVIDENCE_GAP_UPDATED", object_type="evidence_gap", object_id=gap.gap_id,
                               previous_status=gap.status, status="addressed", question_id=question_id)

    def gap(self, question, description):
        if any(g.description == description and question.question_id in g.related_question_ids
               for g in self.case.evidence_gaps):
            return
        gap = EvidenceGap(description=description, related_question_ids=(question.question_id,),
                          related_hypotheses=question.relevant_hypothesis_ids,
                          related_predictions=question.derived_from_prediction_ids)
        self.call("add_evidence_gap", gap)
        self.gap_ids.append(gap.gap_id)
        self.event("EVIDENCE_GAP_CREATED", object_type="evidence_gap", object_id=gap.gap_id,
                   question_id=question.question_id)

    def _assess(self, question, evidence):
        """Record local consistency; an observation never decides a verdict."""
        primaries = {h.hypothesis_id for h in self.case.hypotheses for p in h.predictions
                     if p.prediction_id in question.derived_from_prediction_ids}
        literature = evidence.provenance.parameters.get("literature", {})
        for hypothesis in self.case.hypotheses:
            if hypothesis.hypothesis_id not in question.relevant_hypothesis_ids:
                continue
            relation = "neutral"
            if hypothesis.hypothesis_id in primaries:
                if evidence.source_type == "grn" and evidence.provenance.parameters.get("query_answer_complete"):
                    relation = "supports"
                elif (evidence.source_type == "literature" and evidence.directness == "direct"
                      and evidence.context_match != "mismatched"):
                    if evidence.negative_evidence_type == "explicit_null_result":
                        if literature.get("sufficient_power"):
                            relation = "challenges"
                    elif literature.get("relation_effect") == "supports":
                        relation = "supports"
                    elif literature.get("relation_effect") == "challenges":
                        relation = "challenges"
            if evidence.support_quality == "insufficient" or evidence.negative_evidence_type == "not_found":
                relation = "inconclusive"
            prediction = next((p.prediction_id for p in hypothesis.predictions
                               if p.prediction_id in question.derived_from_prediction_ids), None)
            if any(a.evidence_id == evidence.evidence_id and a.hypothesis_id == hypothesis.hypothesis_id
                   and a.prediction_id == prediction and a.relation == relation for a in self.case.evidence_assessments):
                continue
            self.call("add_evidence_assessment", EvidenceAssessment(
                evidence_id=evidence.evidence_id, hypothesis_id=hypothesis.hypothesis_id,
                hypothesis_revision_id=hypothesis.current_revision_id, prediction_id=prediction,
                relation=relation,
                rationale=(f"The acquired observation is {relation} with respect to the specific queried "
                           "prediction component. This is an evidence relation, not a hypothesis verdict."),
                assessed_by=ACTOR))

    def record(self, question, normalized):
        recorded = []
        for proposed in normalized.records:
            validate_investigator_action(self.case, evidence=proposed)
            existing = next((e for e in self.case.evidence_records
                             if proposed.fingerprint and e.fingerprint == proposed.fingerprint), None)
            if existing:
                if question.question_id not in existing.question_ids:
                    self.call("link_evidence_to_question", existing.evidence_id, question.question_id)
                    self.linked_ids.append(existing.evidence_id)
                    self.event("EVIDENCE_LINKED", object_type="evidence_record", object_id=existing.evidence_id,
                               question_id=question.question_id)
                evidence = next(e for e in self.case.evidence_records if e.evidence_id == existing.evidence_id)
            else:
                self.call("add_evidence_record", proposed)
                evidence = next(e for e in self.case.evidence_records if e.evidence_id == proposed.evidence_id)
                self.evidence_ids.append(evidence.evidence_id)
                self.event("EVIDENCE_RECORDED", object_type="evidence_record", object_id=evidence.evidence_id,
                           question_id=question.question_id, raw_result_reference=evidence.raw_result_reference)
            recorded.append(evidence)
            self._assess(question, evidence)
        # Opposing results remain distinct, including conflicts with prior runs.
        conflicts = set()
        for new in recorded:
            details = new.provenance.parameters.get("literature", {})
            if not details or new.directness != "direct":
                continue
            for old in self.case.evidence_records:
                prior = old.provenance.parameters.get("literature", {})
                if old.evidence_id == new.evidence_id or old.directness != "direct" or not prior:
                    continue
                same_relation = all(details.get(k) == prior.get(k) for k in
                                    ("perturbed_entity", "measured_entity", "biological_context"))
                opposing = (new.negative_evidence_type == "explicit_null_result") != (old.negative_evidence_type == "explicit_null_result")
                if same_relation and opposing:
                    conflicts.add(tuple(sorted((old.evidence_id, new.evidence_id))))
        if normalized.potential_conflict and len(recorded) > 1:
            conflicts.add(tuple(sorted(e.evidence_id for e in recorded)))
        for ids in sorted(conflicts):
            if any(set(c.evidence_ids) == set(ids) for c in self.case.contradictions):
                continue
            contradiction = ContradictionRecord(
                description="Potentially conflicting observations require critique; Investigator has not adjudicated them.",
                evidence_ids=ids, hypothesis_ids=question.relevant_hypothesis_ids)
            self.call("add_contradiction", contradiction)
            self.event("POTENTIAL_CONTRADICTION_RECORDED", object_type="contradiction",
                       object_id=contradiction.contradiction_id)
        if normalized.gap:
            self.gap(question, normalized.gap)
        remaining = self.config.max_new_followup_questions - len(self.followup_ids)
        if self.config.allow_followup_questions and recorded and remaining > 0:
            for followup in make_network_followups(question, recorded[0], normalized.followup_candidates, limit=remaining):
                followup = followup.model_copy(update={"derived_from_evidence_ids": tuple(e.evidence_id for e in recorded)})
                self.call("add_evidence_question", followup)
                self.followup_ids.append(followup.question_id)
                self.event("FOLLOWUP_QUESTION_CREATED", object_type="evidence_question", object_id=followup.question_id,
                           derived_from_question_ids=list(followup.derived_from_question_ids),
                           derived_from_evidence_ids=list(followup.derived_from_evidence_ids))
                self.gap(followup, "Candidate network architecture requires direct experimental verification.")
                for duplicate, original in deduplicate_evidence_questions(self.case.evidence_questions):
                    if duplicate == followup.question_id:
                        self.status(duplicate, "cancelled")
                        self.event("DUPLICATE_QUESTION_CANCELLED", object_type="evidence_question",
                                   object_id=duplicate, reason=f"duplicate_of:{original}")
        return recorded
