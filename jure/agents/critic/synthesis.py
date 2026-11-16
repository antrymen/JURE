"""Qualitative synthesis of critical claims, without scoring or evidence voting."""
from jure.casefile.critic_models import ClaimCoverageSummary, HypothesisSynthesis
from .hypothesis_audit import audit_time, stable_id


def synthesize_hypothesis(context):
    hid = context["target_hypothesis_id"]
    hypothesis = next(h for h in context.get("hypotheses", ()) if h["hypothesis_id"] == hid)
    claims = [c for c in context.get("claims", ()) if c["hypothesis_id"] == hid]
    latest = {a["claim_id"]: a for a in context.get("claim_audits", ())}
    statuses = {c["claim_id"]: latest.get(c["claim_id"], {}).get("status", c.get("status", "insufficient")) for c in claims}
    critical = {c["claim_id"] for c in claims if c.get("critical", True)}
    grouped = {status: tuple(cid for cid, value in statuses.items() if value == status)
               for status in ("supported", "partially_supported", "challenged", "insufficient")}
    if any(statuses[cid] == "challenged" for cid in critical):
        status = "challenged"
        summary = "A critical prediction component is challenged by relevant evidence; this conclusion remains open to future re-evaluation."
    elif claims and all(value == "supported" for value in statuses.values()):
        status = "supported"
        summary = "Every audited claim, including all critical components, has sufficient scoped support; this is not an absolute causal proof."
    elif grouped["supported"] or grouped["partially_supported"]:
        status = "partially_supported"
        summary = "Some mechanism components have support, while the listed unresolved claims limit the current interpretation."
    else:
        status = "insufficient"
        summary = "The available evidence cannot yet evaluate the required mechanism components adequately."
    gap_ids = tuple(dict.fromkeys(gid for c in claims if c["claim_id"] in critical
                    for gid in latest.get(c["claim_id"], {}).get("gap_ids", ())))
    contradictions = tuple(dict.fromkeys(x for c in claims for x in latest.get(c["claim_id"], {}).get("contradiction_ids", ())))
    uncertainties = tuple(f"{c['claim_id']}: {c['statement']} remains {statuses[c['claim_id']]}."
                          for c in claims if statuses[c["claim_id"]] != "supported")
    if not uncertainties:
        uncertainties = ("Support is limited to the measured conditions and available sources; untested contexts and alternatives remain uncertain.",)
    coverage = ClaimCoverageSummary(total_claims=len(claims), critical_claims=len(critical),
        supported_claims=len(grouped["supported"]), partially_supported_claims=len(grouped["partially_supported"]),
        challenged_claims=len(grouped["challenged"]), insufficient_claims=len(grouped["insufficient"]),
        supported_critical_claims=sum(statuses[cid] == "supported" for cid in critical),
        unresolved_critical_claims=sum(statuses[cid] != "supported" for cid in critical),
        challenged_critical_claims=sum(statuses[cid] == "challenged" for cid in critical))
    return HypothesisSynthesis(synthesis_id=stable_id("SYN", context, hid), hypothesis_id=hid,
        hypothesis_revision_id=hypothesis.get("current_revision_id"), status=status,
        supported_claim_ids=grouped["supported"], partial_claim_ids=grouped["partially_supported"],
        challenged_claim_ids=grouped["challenged"], insufficient_claim_ids=grouped["insufficient"],
        critical_gaps=gap_ids, contradictions=contradictions, remaining_uncertainties=uncertainties,
        summary=summary, coverage=coverage, critic_round=context.get("critic_round", 0), created_at=audit_time(context))
