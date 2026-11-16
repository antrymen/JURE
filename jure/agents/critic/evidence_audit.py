"""Claim-scoped evidence interpretation without modifying evidence or provenance.

The deterministic mock is deliberately conservative. Links establish lineage;
they do not by themselves establish semantic relevance or causal support.
"""
from __future__ import annotations

import re
from jure.casefile.models import ContradictionRecord, EvidenceGap, FrozenModel
from jure.casefile.critic_models import ClaimAuditRecord, EvidenceAuditRecord
from .claim_decomposition import explicit_edges
from .hypothesis_audit import audit_time, stable_id


class EvidenceAuditResult(FrozenModel):
    evidence_audits: tuple[EvidenceAuditRecord, ...] = ()
    claim_audits: tuple[ClaimAuditRecord, ...] = ()
    evidence_gaps: tuple[EvidenceGap, ...] = ()
    contradictions: tuple[ContradictionRecord, ...] = ()


_GENERIC = re.compile(r"co.mention|contextual (?:search|association|information)|mentions? relevant entities|experiment was not verified", re.I)
_CAUSAL_ASSERTION = re.compile(r"causally|(?:prove[sd]?|establish(?:es|ed)?|demonstrat(?:es|ed)?|therefore|thus).{0,35}(?:caus|directly regulat)|directly regulates|因果证明|因此.*调控", re.I)
_STOP_WORDS = frozenset("the a an of for to in on and or is are be should would could may with from as this that evidence proposed relevant biological context mechanism prediction experiment experimental supports support tested result study observation matched direct different".split())


def _tokens(text):
    return {x.casefold() for x in re.findall(r"[\w]+", text) if x.casefold() not in _STOP_WORDS}


def _details(evidence):
    return evidence.get("provenance", {}).get("parameters", {}).get("literature", {})


def _linked(context, claim, evidence):
    pids = set(claim.get("derived_from_prediction_ids", ()))
    qids = {evidence.get("question_id"), *evidence.get("related_question_ids", ())}
    questions = {q["question_id"]: q for q in context.get("evidence_questions", ())}
    records = {e["evidence_id"]: e for e in context.get("evidence_records", ())}
    seen = set()
    # Investigator verification follow-ups may preserve lineage via a parent
    # question or seed evidence rather than repeat the prediction IDs.
    while qids:
        qid = qids.pop()
        if qid in seen:
            continue
        seen.add(qid)
        question = questions.get(qid, {})
        if pids.intersection(question.get("derived_from_prediction_ids", ())):
            return True
        qids.update(question.get("derived_from_question_ids", ()))
        for eid in question.get("derived_from_evidence_ids", ()):
            ancestor = records.get(eid, {})
            qids.update((ancestor.get("question_id"), *ancestor.get("related_question_ids", ())))
    return any(a.get("evidence_id") == evidence["evidence_id"]
               and a.get("hypothesis_id") == claim["hypothesis_id"]
               and a.get("prediction_id") in pids
               and (not claim.get("hypothesis_revision_id") or
                    a.get("hypothesis_revision_id") == claim["hypothesis_revision_id"])
               for a in context.get("evidence_assessments", ()))


def claim_evidence_relevance(context, claim, evidence):
    if not _linked(context, claim, evidence):
        return "irrelevant"
    details = _details(evidence)
    pair = (str(details.get("perturbed_entity", "")).casefold(), str(details.get("measured_entity", "")).casefold())
    edges = {(a.casefold(), b.casefold()) for a, b in explicit_edges(claim["statement"])}
    if edges and all(pair):
        return "relevant" if pair in edges else "irrelevant"
    tested = evidence.get("claim_tested", "")
    summary = evidence.get("result_summary", "")
    if _GENERIC.search(tested + " " + summary):
        return "partial"
    test_edges = {(a.casefold(), b.casefold()) for a, b in explicit_edges(tested)}
    if edges and test_edges:
        return "relevant" if edges.intersection(test_edges) else "irrelevant"
    claim_tokens, evidence_tokens = _tokens(claim["statement"]), _tokens(tested + " " + summary)
    # Exact claim text is strongest lexical evidence. An explicit lineage link
    # still must share the tested entities or meaningful mechanism vocabulary.
    genes = context.get("clue", {}).get("pattern", {}).get("genes", ())
    required_genes = {g.casefold() for g in genes if re.search(r"(?<!\w)" + re.escape(g) + r"(?!\w)", claim["statement"], re.I)}
    observed_genes = {g.casefold() for g in genes if re.search(r"(?<!\w)" + re.escape(g) + r"(?!\w)", tested + " " + summary, re.I)}
    if required_genes and not required_genes.intersection(observed_genes):
        return "irrelevant"
    if all(pair) and len(required_genes) > 1 and pair[1] in required_genes and not edges:
        # A single component experiment does not establish the full fan-out or
        # joint-state architecture even if claim_tested repeats a broad query.
        return "partial"
    if tested.strip().casefold() == claim["statement"].strip().casefold():
        return "relevant"
    if required_genes and required_genes <= observed_genes:
        return "relevant"
    meaningful = claim_tokens.intersection(evidence_tokens)
    return "relevant" if len(meaningful) >= 2 else "partial" if meaningful else "irrelevant"


def _provenance_check(evidence):
    provenance = evidence.get("provenance", {})
    # Match the store-side guard: identify the source, acquisition mechanism,
    # and durable reference to the source or raw acquisition artifact.
    trace = bool(provenance.get("tool")) and bool(
        provenance.get("source_uri") or evidence.get("raw_result_reference"))
    return "complete" if provenance.get("source_id") and trace else "incomplete"


def _audit_record(context, evidence, claims):
    relevances = {claim["claim_id"]: claim_evidence_relevance(context, claim, evidence) for claim in claims}
    related = tuple(cid for cid, rel in relevances.items() if rel != "irrelevant")
    relevance = "relevant" if "relevant" in relevances.values() else "partial" if related else "irrelevant"
    directness = evidence.get("directness", "unknown")
    support = evidence.get("support_quality", "unknown")
    quality = evidence.get("source_quality", "unknown")
    matched = evidence.get("context_match", "unknown")
    provenance = _provenance_check(evidence)
    text = evidence.get("claim_tested", "") + " " + evidence.get("result_summary", "")
    details = _details(evidence)
    issues = []
    overclaim = False
    if evidence.get("source_type") == "grn":
        overclaim = bool(_CAUSAL_ASSERTION.search(evidence.get("result_summary", ""))) or directness == "direct"
        directness, support = "indirect", "limited" if support != "insufficient" else "insufficient"
        issues.append("Network connectivity supports a candidate architecture; it does not establish causal regulation.")
    if _GENERIC.search(text):
        overclaim = overclaim or bool(_CAUSAL_ASSERTION.search(evidence.get("result_summary", ""))) or directness == "direct"
        directness, support = "contextual", "insufficient"
        issues.append("A generic co-mention or unverified passage is not a direct test of the mechanistic claim.")
    if evidence.get("source_type") == "dataset" and _CAUSAL_ASSERTION.search(evidence.get("result_summary", "")):
        overclaim = True
        directness = "indirect"
        if support == "sufficient":
            support = "limited"
        issues.append("An observational dataset association cannot establish causal regulation.")
    elif evidence.get("source_type") == "dataset" and related and all(
        c.get("claim_type") in {"cell_state", "statistical", "dataset_prediction"}
        for c in claims if c["claim_id"] in related
    ):
        directness = "direct"
        issues.append("The dataset directly tests the stated statistical or cell-state prediction; this does not establish a regulatory cause.")
    elif evidence.get("source_type") == "dataset":
        directness = "indirect"
        if support == "sufficient":
            support = "limited"
        issues.append("The observed dataset can constrain this mechanism but does not directly establish its regulatory components.")
    if evidence.get("negative_evidence_type") == "not_found":
        support = "insufficient"
        issues.append("Failure to retrieve evidence is an unresolved information gap, not evidence against the claim.")
    power = details.get("sufficient_power", evidence.get("provenance", {}).get("parameters", {}).get("sufficient_power"))
    if evidence.get("negative_evidence_type") == "explicit_null_result" and power is not True:
        support = "limited"
        issues.append("The explicit null result lacks established statistical power and cannot decisively challenge the claim.")
    if provenance != "complete":
        issues.append("Source provenance is incomplete; a traceable acquisition or primary source reference is missing.")
        if support == "sufficient":
            support = "limited"
    if matched == "mismatched":
        issues.append("The biological context differs; context dependency must be preserved rather than treated as a matched contradiction.")
    if relevance == "irrelevant":
        issues.append("Reference linkage does not establish that this observation answers the current claims.")
    interpretation = " ".join(issues) or "The traceable observation is relevant to the linked verification claim within its stated evidence and context limits."
    return EvidenceAuditRecord(evidence_audit_id=stable_id("EVA", context, evidence["evidence_id"]),
        evidence_id=evidence["evidence_id"], claim_ids=related, relevance=relevance,
        directness_assessment=directness, context_assessment=matched, source_quality_assessment=quality,
        support_quality_assessment=support, provenance_check=provenance, overclaim_detected=overclaim,
        issues=tuple(issues), critic_interpretation=interpretation,
        critic_round=context.get("critic_round", 0), created_at=audit_time(context)), relevances


def _relation(context, claim, evidence, audit):
    if evidence.get("negative_evidence_type") == "not_found" or audit.support_quality_assessment == "insufficient":
        return "inconclusive"
    linked = [a for a in context.get("evidence_assessments", ())
              if a.get("evidence_id") == evidence["evidence_id"] and a.get("hypothesis_id") == claim["hypothesis_id"]
              and a.get("prediction_id") in claim.get("derived_from_prediction_ids", ())
              and (not claim.get("hypothesis_revision_id") or a.get("hypothesis_revision_id") == claim["hypothesis_revision_id"])]
    relations = {a.get("relation") for a in linked}
    if "challenges" in relations:
        return "challenges"
    if "supports" in relations:
        return "supports"
    details = _details(evidence)
    if evidence.get("negative_evidence_type") == "explicit_null_result":
        return "challenges"
    if details.get("relation_effect") in {"supports", "challenges"}:
        return details["relation_effect"]
    parameters = evidence.get("provenance", {}).get("parameters", {})
    if evidence.get("source_type") == "grn" and parameters.get("query_answer_complete"):
        return "supports"
    summary = evidence.get("result_summary", "")
    if re.search(r"contradict|inconsistent with|exclud(?:es|ed)|unchanged|no measurable effect", summary, re.I):
        return "challenges"
    if re.search(r"support|consistent with|connect|decreas|increas|alter|regulat", summary, re.I):
        return "supports"
    return "inconclusive"


def _strong(audit, claim, evidence):
    design = audit.directness_assessment == "direct"
    return (design and audit.context_assessment == "matched"
            and audit.source_quality_assessment in {"primary_experiment", "curated_database"}
            and audit.support_quality_assessment == "sufficient"
            and audit.provenance_check == "complete" and not audit.overclaim_detected)


def _context_label(evidence):
    details = _details(evidence)
    return details.get("biological_context") or details.get("cell_type_or_model") or evidence.get("context_match", "unknown")


def audit_evidence(context):
    claims = list(context.get("claims", ()))
    records = {e["evidence_id"]: e for e in context.get("evidence_records", ())}
    audits, relevance = {}, {}
    for eid, evidence in records.items():
        audits[eid], relevance[eid] = _audit_record(context, evidence, claims)
    claim_audits, gaps, contradictions = [], [], []
    conflict_eids = set()
    for claim in claims:
        cid, hid = claim["claim_id"], claim["hypothesis_id"]
        related = [eid for eid in records if relevance[eid][cid] != "irrelevant"]
        relations = {eid: _relation(context, claim, records[eid], audits[eid]) for eid in related}
        support = [eid for eid in related if relations[eid] == "supports" and relevance[eid][cid] == "relevant"
                   and audits[eid].context_assessment != "mismatched"]
        challenge = [eid for eid in related if relations[eid] == "challenges" and relevance[eid][cid] == "relevant"]
        strong_support = [eid for eid in support if _strong(audits[eid], claim, records[eid])]
        strong_challenge = [eid for eid in challenge if _strong(audits[eid], claim, records[eid])]
        usable_support = [eid for eid in support if audits[eid].support_quality_assessment in {"sufficient", "limited"}
                          and audits[eid].directness_assessment not in {"contextual", "unknown"}]
        cids = []
        pairs = [(a, b) for a in support for b in challenge if a != b]
        if not pairs and strong_challenge:
            pairs = [(eid,) for eid in strong_challenge]
        for pair in pairs:
            contexts = tuple(dict.fromkeys(str(_context_label(records[eid])) for eid in pair))
            mismatched = any(audits[eid].context_assessment == "mismatched" for eid in pair)
            dependency = mismatched or len(contexts) > 1
            contradiction_id = stable_id("CONTRA", context, cid, *sorted(pair), per_round=False)
            prior = next((c for c in context.get("contradictions", ())
                          if c.get("contradiction_id") == contradiction_id), None)
            if prior and prior.get("status") == "resolved":
                continue
            contrad = ContradictionRecord(contradiction_id=contradiction_id,
                description="Opposing observations require context-aware resolution." if len(pair) > 1 else "A direct, sufficiently supported observation conflicts with this mechanistic prediction.",
                evidence_ids=tuple(pair), hypothesis_ids=(hid,), claim_ids=(cid,), status="unresolved",
                context_difference="; ".join(contexts) if dependency else "No recorded biological-context difference.",
                possible_explanations=("Biological context may modify the observed effect.",) if dependency
                    else ("Differences in experimental design or the proposed mechanism require investigation.",),
                potential_context_dependency=dependency,
                critical=bool(claim.get("critical", True)) and not dependency)
            contradictions.append(contrad)
            cids.append(contradiction_id)
            conflict_eids.update(pair)
        # Preserve existing unresolved contradictions even if their records
        # require a provider's richer interpretation than these mock rules.
        cids.extend(c["contradiction_id"] for c in context.get("contradictions", ())
                    if c.get("status") != "resolved" and cid in c.get("claim_ids", ()))
        cids = list(dict.fromkeys(cids))
        if strong_challenge:
            status = "challenged"
            summary = "Direct, context-matched, sufficiently supported evidence challenges the required observation; supporting counts do not override it."
        elif strong_support and not cids:
            status = "supported"
            summary = "The claim has relevant direct, context-matched, traceable support without an unresolved claim-level contradiction."
        elif usable_support:
            status = "partially_supported"
            summary = "Relevant evidence provides limited or indirect support; direct/context-matched verification or conflict resolution remains necessary."
        else:
            status = "insufficient"
            summary = "Available observations do not provide sufficient relevant, traceable support or a strong matched challenge."
        gap_ids = []
        if status in {"partially_supported", "insufficient"} or cids and status != "challenged":
            matching = [g for g in context.get("evidence_gaps", ()) if cid in g.get("related_claim_ids", ())]
            gap_id = matching[-1]["gap_id"] if matching else stable_id("GAP", context, cid, per_round=False)
            old = matching[-1] if matching else {}
            questions = tuple(q["question_id"] for q in context.get("evidence_questions", ())
                              if set(claim.get("derived_from_prediction_ids", ())).intersection(q.get("derived_from_prediction_ids", ())))
            gaps.append(EvidenceGap(gap_id=gap_id,
                description=old.get("description") or f"Direct/context-matched evidence or discriminating conflict resolution is missing for: {claim['statement']}",
                related_hypotheses=(hid,), related_predictions=tuple(claim.get("derived_from_prediction_ids", ())),
                related_claim_ids=(cid,), related_question_ids=questions, related_evidence_ids=tuple(related),
                status="open" if old.get("status") == "addressed" else old.get("status", "open"),
                critical=bool(claim.get("critical", True)),
                criticality_reason=claim.get("criticality_reason", "Required for the stated mechanism."),
                reason="evidence_conflict" if cids else "evidence_missing",
                resolvable_with_current_tools=old.get("resolvable_with_current_tools")))
            gap_ids.append(gap_id)
        claim_audits.append(ClaimAuditRecord(claim_audit_id=stable_id("CA", context, cid), claim_id=cid,
            status=status, evidence_ids=tuple(related), supporting_evidence_ids=tuple(usable_support),
            challenging_evidence_ids=tuple(challenge), gap_ids=tuple(gap_ids), contradiction_ids=tuple(cids),
            summary=summary, critic_round=context.get("critic_round", 0), created_at=audit_time(context)))
    # Audits are interpretations appended beside immutable source records.
    audited = tuple(a.model_copy(update={"contradiction_detected": a.evidence_id in conflict_eids}) for a in audits.values())
    return EvidenceAuditResult(evidence_audits=audited, claim_audits=tuple(claim_audits),
                               evidence_gaps=tuple(gaps), contradictions=tuple(contradictions))
