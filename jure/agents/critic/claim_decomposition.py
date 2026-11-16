"""Verification units derived only from existing predictions and explicit edges."""
from __future__ import annotations
import re
from jure.casefile.models import FrozenModel
from jure.casefile.critic_models import MechanisticClaim
from .hypothesis_audit import audit_time, current_revision, hypothesis_predictions, stable_id


class ClaimDecompositionResult(FrozenModel):
    claims: tuple[MechanisticClaim, ...] = ()


def explicit_edges(text):
    """Extract only written directions; never choose or introduce a regulator."""
    edges = re.findall(r"(?=\b([A-Za-z][A-Za-z0-9_]*)\s*(?:→|->)\s*([A-Za-z][A-Za-z0-9_]*)\b)", text)
    edges += re.findall(r"\b([A-Za-z][A-Za-z0-9_]*)\s+to\s+([A-Za-z][A-Za-z0-9_]*)\b", text)
    # Restrict English direction extraction to gene-like identifiers, so
    # 'expected to change' cannot become a fabricated biological edge.
    return tuple(dict.fromkeys((a, b) for a, b in edges
                 if (a.isupper() or any(c.isdigit() for c in a))
                 and (b.isupper() or any(c.isdigit() for c in b))))


def decompose_claims(context):
    claims = []
    existing = {(c["hypothesis_id"], c.get("hypothesis_revision_id"), c["statement"]): c
                for c in context.get("claims", ())}
    for h in context.get("hypotheses", ()):
        hid, rid = h["hypothesis_id"], h.get("current_revision_id")
        predictions = hypothesis_predictions(context, h)
        structure = h.get("structure") or {}
        proposed = {}
        for p in predictions:
            edges = explicit_edges(p.get("statement", ""))
            if not edges and len(structure.get("directed_edges", ())) > 1:
                # Edges already authored by Explorer are eligible only when the
                # prediction explicitly concerns the directed architecture.
                if re.search(r"cascade|directed|regulatory steps", p.get("statement", ""), re.I):
                    edges = tuple(tuple(edge) for edge in structure["directed_edges"])
            statements = [(f"The proposed directed step {a} → {b} operates in the relevant biological context.", "regulatory_relation") for a, b in edges]
            if not statements:
                text = p["statement"]
                kind = "cell_state" if re.search(r"cell.state|composition", text, re.I) else "mechanistic_prediction"
                statements = [(text, kind)]
            for statement, kind in statements:
                entry = proposed.setdefault(statement, {"kind": kind, "predictions": []})
                entry["predictions"].append(p["prediction_id"])
        for statement, entry in proposed.items():
            old = existing.get((hid, rid, statement))
            if old is not None:
                claims.append(MechanisticClaim.model_validate(old))
                continue
            pids = tuple(dict.fromkeys(entry["predictions"]))
            families = {q.get("suggested_evidence_type", "unknown") for q in context.get("evidence_questions", ())
                        if set(pids).intersection(q.get("derived_from_prediction_ids", ()))} - {"unknown"}
            if entry["kind"] == "regulatory_relation":
                families.add("literature")
            claims.append(MechanisticClaim(
                claim_id=stable_id("CLAIM", context, hid, rid, statement, per_round=False),
                hypothesis_id=hid, hypothesis_revision_id=rid, statement=statement,
                claim_type=entry["kind"], derived_from_prediction_ids=pids,
                required_evidence_types=tuple(sorted(families)), critical=True,
                criticality_reason="This claim is an explicitly required prediction component of the proposed mechanism; without it the mechanism does not explain its stated discriminating observation.",
                created_at=audit_time(context)))
    return ClaimDecompositionResult(claims=tuple(claims))
