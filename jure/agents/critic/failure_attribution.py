"""Locate the scientific bottleneck before deciding which agent acts next."""
from jure.casefile.critic_models import FailureAttribution
from .hypothesis_audit import stable_id


def attribute_failure(context):
    audit = context.get("hypothesis_audit", {})
    syntheses = list(context.get("hypothesis_syntheses", ()))
    claims = {c["claim_id"]: c for c in context.get("claims", ())}
    claim_audits = {a["claim_id"]: a for a in context.get("claim_audits", ())}
    hids = tuple(h["hypothesis_id"] for h in context.get("hypotheses", ()))
    related_hids, cids, eids, gids = hids, [], [], []
    space_problem = False
    if audit.get("overall_status") == "revision_required":
        structural = bool(audit.get("coverage_issues")) or any(
            a.get(dimension) == "fail" for a in audit.get("per_hypothesis", ())
            for dimension in ("groundedness", "distinctness", "scope"))
        reason = "hypothesis_problem" if structural else "prediction_problem"
        summary = "The hypothesis audit requires explicit formulation revisions before evidence investigation can be informative."
        space_problem = True
    elif syntheses and all(s.get("status") == "challenged" for s in syntheses):
        reason, space_problem = "hypothesis_space_inadequate", True
        cids = [cid for s in syntheses for cid in s.get("challenged_claim_ids", ())]
        eids = [eid for cid in cids for eid in claim_audits.get(cid, {}).get("challenging_evidence_ids", ())]
        summary = "Evidence challenges a critical component of every active hypothesis; Explorer must reconsider the mechanism space using these observations."
    else:
        remaining = {s["hypothesis_id"] for s in syntheses if s.get("status") != "challenged"}
        related_hids = tuple(h for h in hids if not syntheses or h in remaining)
        cids = [cid for cid, c in claims.items() if c["hypothesis_id"] in related_hids
                and claim_audits.get(cid, {}).get("status", c.get("status")) != "supported"]
        gids = [gid for cid in cids for gid in claim_audits.get(cid, {}).get("gap_ids", ())]
        eids = [eid for cid in cids for eid in claim_audits.get(cid, {}).get("evidence_ids", ())]
        conflict = any(claim_audits.get(cid, {}).get("contradiction_ids") for cid in cids)
        quality = any(a.get("evidence_id") in eids and (a.get("overclaim_detected")
                      or a.get("provenance_check") == "incomplete") for a in context.get("evidence_audits", ()))
        missing_questions = cids and not any(set(claims[cid].get("derived_from_prediction_ids", ())).intersection(
            q.get("derived_from_prediction_ids", ())) for cid in cids for q in context.get("evidence_questions", ()))
        capabilities = context.get("available_capabilities")
        unavailable = capabilities is not None and (not capabilities or all(
            isinstance(c, dict) and c.get("availability") == "unavailable" for c in capabilities))
        if conflict:
            reason = "evidence_conflict"
            summary = "Opposing observations for a remaining claim require discriminating evidence and context-aware resolution."
        elif missing_questions:
            reason = "evidence_question_problem"
            summary = "Unresolved predictions lack a linked, answerable evidence question and need Investigator operationalization."
        elif quality and cids:
            reason = "evidence_quality_problem"
            summary = "Overclaim or incomplete provenance limits the unresolved claims; obtain verified, traceable evidence."
        elif cids and unavailable:
            reason = "tool_limit"
            summary = "Remaining claim gaps cannot currently be investigated because the listed evidence capabilities are unavailable."
        elif cids or not syntheses:
            reason = "evidence_missing"
            summary = "The mechanism space is currently adequate, but unresolved claims still need direct or context-matched discriminating evidence."
        else:
            reason = "no_problem"
            summary = "The audited remaining explanation has no unresolved critical evidence bottleneck; evaluate sufficiency and residual uncertainty."
    return FailureAttribution(attribution_id=stable_id("FAIL", context), reason_type=reason,
        reason_summary=summary, related_hypothesis_ids=tuple(related_hids),
        related_claim_ids=tuple(dict.fromkeys(cids)), related_evidence_ids=tuple(dict.fromkeys(eids)),
        related_gap_ids=tuple(dict.fromkeys(gids)), hypothesis_space_problem=space_problem,
        critic_round=context.get("critic_round", 0))
