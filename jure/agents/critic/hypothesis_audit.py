"""Conservative, inspectable hypothesis-design audit for the offline backend.

These rules provide reproducible fixtures, not a substitute for semantic review
by a production reasoning provider. No evidence is consulted during stage C1.
"""
from __future__ import annotations

from hashlib import sha256
from itertools import combinations
import re

from jure.agents.explorer.validation import (
    _GENERIC_PREDICTION, _OBSERVABLE, _OVERCLAIM, _normalize, _simple_edges,
)
from jure.casefile.critic_models import HypothesisAuditResult, PerHypothesisAudit


def stable_id(prefix, context, *parts, per_round=True):
    values = [str(context.get("case_id", "case"))]
    if per_round:
        values.append(str(context.get("critic_round", 0)))
    values.extend(str(part) for part in parts)
    return prefix + "_" + sha256("\0".join(values).encode()).hexdigest()[:24]


def audit_time(context):
    # Context carries the Case File timestamp. The fallback also keeps pure
    # fixture inputs deterministic without consulting a process clock.
    return context.get("context_timestamp") or "2000-01-01T00:00:00Z"


def current_revision(hypothesis):
    return hypothesis.get("current_revision") or hypothesis


def hypothesis_predictions(context, hypothesis):
    hid = hypothesis["hypothesis_id"]
    rid = hypothesis.get("current_revision_id")
    predictions = hypothesis.get("predictions", context.get("predictions", ()))
    return [p for p in predictions if p.get("hypothesis_id", hid) == hid
            and (not rid or p.get("hypothesis_revision_id", rid) == rid)]


def _redundant(a, b, genes):
    ra, rb = current_revision(a), current_revision(b)
    ta, tb = ra.get("mechanism_statement", ""), rb.get("mechanism_statement", "")
    if _normalize(ta) == _normalize(tb):
        return True
    ea, eb = _simple_edges(ta, genes), _simple_edges(tb, genes)
    modifiers = re.compile(r"indirect|mediat|conditional|upstream|cascade|cell.state|composition|feedback", re.I)
    if ea and ea == eb and not modifiers.search(ta + " " + tb):
        return True
    sa, sb = a.get("structure"), b.get("structure")
    if not sa or not sb:
        return False
    def signature(s):
        return (_normalize(s.get("causal_structure", "")), s.get("directness"),
                s.get("cell_state_explanation"), s.get("conditional_dependence"),
                tuple(sorted(tuple(edge) for edge in s.get("directed_edges", ()))),
                tuple(sorted(_normalize(x) for x in s.get("distinguishing_features", ()))))
    return signature(sa) == signature(sb)


def _direct_only(hypothesis, genes):
    structure = hypothesis.get("structure") or {}
    statement = current_revision(hypothesis).get("mechanism_statement", "")
    if structure.get("cell_state_explanation") or re.search(r"indirect|cell.state|composition|shared.upstream|mediated|non.direct", statement, re.I):
        return False
    if structure.get("directness") is not None:
        return structure["directness"] == "direct"
    return bool(_simple_edges(statement, genes) or re.search(r"\w+\s*(?:→|->)\s*\w+", statement))


def audit_hypotheses(context):
    hypotheses = context.get("hypotheses", ())
    clue = context.get("clue", {})
    genes = tuple(clue.get("pattern", {}).get("genes", ()))
    hids = {h["hypothesis_id"] for h in hypotheses}
    duplicates = {h: [] for h in hids}
    for a, b in combinations(hypotheses, 2):
        if _redundant(a, b, genes):
            duplicates[a["hypothesis_id"]].append(b["hypothesis_id"])
            duplicates[b["hypothesis_id"]].append(a["hypothesis_id"])
    coverage = []
    if not hypotheses:
        coverage.append("The current case has no active hypothesis to audit.")
    elif len(hypotheses) > 1 and all(_direct_only(h, genes) for h in hypotheses):
        coverage.append("All current hypotheses assume direct regulation; consider a non-direct cellular-state or upstream alternative compatible with the clue.")
    audits = []
    for h in hypotheses:
        hid, revision = h["hypothesis_id"], current_revision(h)
        predictions = hypothesis_predictions(context, h)
        statement = revision.get("mechanism_statement", "")
        dims = {key: "pass" for key in ("groundedness", "distinctness", "testability", "falsifiability", "discriminability", "scope")}
        issues, changes = [], []
        perturbation = clue.get("perturbation")
        causal_from_clue = bool(perturbation and re.search(
            r"\b(?:perturbation\s+)?" + re.escape(perturbation) + r"\s+(?:activates|represses|causes|directly regulates)\b", statement, re.I)
            and not re.search(r"may|might|could|hypothe|candidate|proposed|untested", statement, re.I))
        if causal_from_clue or _OVERCLAIM.search(statement) or re.search(r"(?:therefore|thus).{0,40}(?:causally|proves? caus|establishes? regulat)", statement, re.I):
            dims["groundedness"] = "fail"
            issues.append("The hypothesis treats the observed association as established causal regulation.")
            changes.append("State the proposed mechanism as a testable explanation; preserve the clue's observational boundary.")
        if duplicates[hid]:
            dims["distinctness"] = "fail"
            issues.append("Mechanistic structure is redundant with " + ", ".join(duplicates[hid]) + ".")
            changes.append("Separate the causal structures or cellular explanations and state a substantive contrast.")
        testable = [p for p in predictions if p.get("expected_if_true")
                    and (_OBSERVABLE.search(p.get("statement", "") + " " + p.get("expected_if_true", ""))
                         or re.search(r"knockout|knockdown|CRISPR|measur|increas|decreas|unchanged|no effect|phenotyp|expression", p.get("expected_if_true", ""), re.I))
                    and not _GENERIC_PREDICTION.search(p.get("statement", ""))]
        if not testable:
            dims["testability"] = "fail"
            issues.append("No current prediction specifies an observable result that available evidence sources could investigate.")
            changes.append("Add a prediction with a concrete expected observation and a matching evidence question.")
        falsifiable = [p for p in testable if p.get("weakened_if_observed", "").strip()
                       and not re.fullmatch(r"(?:unknown|none|not supported|not true|otherwise|anything)[.! ]*", p["weakened_if_observed"], re.I)
                       and _normalize(p["weakened_if_observed"]) != _normalize(p.get("expected_if_true", ""))]
        if not falsifiable:
            dims["falsifiability"] = "fail"
            issues.append("No current testable prediction has a distinct weakening observation.")
            changes.append("Specify an observation that would weaken this hypothesis, distinct from its expected outcome.")
        discriminating = []
        for p in testable:
            alternatives = set(p.get("discriminates_from_hypotheses", ())) & (hids - {hid})
            for other in hypotheses:
                if other["hypothesis_id"] not in alternatives:
                    continue
                others = hypothesis_predictions(context, other)
                if not others or any(_normalize(q.get("expected_if_true", "")) != _normalize(p.get("expected_if_true", "")) for q in others):
                    discriminating.append(p)
        if len(hypotheses) > 1 and not discriminating:
            dims["discriminability"] = "fail"
            issues.append("Current predictions do not specify a different expected observation from named alternatives.")
            changes.append("Add a prediction that distinguishes this mechanism from a named competing explanation.")
        if genes:
            scoped_text = " ".join([statement] + [p.get("statement", "") for p in predictions])
            if not any(re.search(r"(?<!\w)" + re.escape(gene) + r"(?!\w)", scoped_text, re.I) for gene in genes):
                dims["scope"] = "fail"
                issues.append("The mechanism and predictions are not tied to the observed joint-state genes.")
                changes.append("Tie the explanation and predictions to the current clue and biological context.")
        audits.append(PerHypothesisAudit(hypothesis_id=hid, **dims, issues=tuple(issues), required_revisions=tuple(changes)))
    failed = bool(coverage) or any("fail" in (a.groundedness, a.distinctness, a.testability, a.falsifiability, a.discriminability, a.scope) for a in audits)
    return HypothesisAuditResult(audit_id=stable_id("HA", context), case_id=context["case_id"],
        overall_status="revision_required" if failed else "pass", per_hypothesis=tuple(audits),
        coverage_issues=tuple(coverage), critic_round=context.get("critic_round", 0), created_at=audit_time(context),
        audit_summary="Hypothesis design requires the listed structural revisions before evidence audit." if failed
            else "The current mechanisms have distinct structures, testable and falsifiable predictions, and a focused scope.")
