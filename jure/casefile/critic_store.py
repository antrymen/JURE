"""Mutation capability checks for staged critic transactions."""
import re


def check_critic_routing(state):
    allowed = {"exploration_needed": {"explorer"}, "evidence_needed": {"investigator", "evidence_investigator"},
               "critique_needed": {"critic"}, "stopped": {"none"}}
    if state["next_actor"] not in allowed.get(state["current_phase"], set()):
        raise PermissionError("critic may route only exploration, investigation, critique, or stop")
    if state["selected_question_id"] is not None:
        raise PermissionError("critic cannot select an evidence question")


def check_critic_event(before, after, event):
    if event.actor != "critic":
        raise PermissionError("staged events must belong to critic")
    permissions = {
        "critic.records_appended": {"mechanistic_claims", "critic_audits", "evidence_gaps", "contradictions"},
        "hypothesis.verdict_changed": {"hypotheses", "critic_audits"},
        "mechanistic_claim.status_changed": {"mechanistic_claims"},
        "evidence_gap.created": {"evidence_gaps"}, "evidence_gap.status_changed": {"evidence_gaps"},
        "evidence_gap.updated": {"evidence_gaps"}, "contradiction.created": {"contradictions"},
        "contradiction.status_changed": {"contradictions"},
        "action_state.changed": {"action_state"}, "annotation.added": set(),
    }
    allowed = permissions.get(event.action)
    if allowed is None:
        if re.fullmatch(r"[A-Z][A-Z0-9_]*", event.action):
            allowed = set()
        else:
            raise PermissionError(f"unsupported critic event: {event.action}")
    changed = {key for key in after if before.get(key) != after[key]} - {"metadata"}
    if changed - allowed:
        raise PermissionError(f"critic event rewrites protected sections: {sorted(changed - allowed)}")
    protected = set(before["metadata"]) - {"updated_at", "case_revision", "schema_version"}
    if any(before["metadata"][key] != after["metadata"][key] for key in protected):
        raise PermissionError("critic cannot rewrite case metadata")
    if after["metadata"]["case_revision"] != before["metadata"]["case_revision"] + 1:
        raise ValueError("staged revision must advance one step per event")
    if after["metadata"]["schema_version"] != "0.1.1":
        raise ValueError("critic writes require schema 0.1.1")
    if len(before["hypotheses"]) != len(after["hypotheses"]):
        raise PermissionError("critic cannot create or remove hypotheses")
    verdict_changes = []
    for old, new in zip(before["hypotheses"], after["hypotheses"]):
        if any(old[k] != new[k] for k in old if k != "revisions"):
            raise PermissionError("critic cannot modify hypotheses or predictions")
        if len(old["revisions"]) != len(new["revisions"]):
            raise PermissionError("critic cannot create hypothesis revisions")
        for prior, current in zip(old["revisions"], new["revisions"]):
            if any(prior[k] != current[k] for k in prior if k != "status"):
                raise PermissionError("critic cannot rewrite hypothesis content")
            if prior["status"] != current["status"] and current["status"] not in {
                "supported", "partially_supported", "challenged", "insufficient"
            }:
                raise PermissionError("new critic verdicts must use the four audit statuses")
            if prior["status"] != current["status"]:
                if current["revision_id"] != new["current_revision_id"]:
                    raise PermissionError("critic cannot reinterpret a superseded hypothesis revision")
                verdict_changes.append((new["hypothesis_id"], prior["status"], current["status"]))
    for collection, identifier, mutable in (
        ("mechanistic_claims", "claim_id", {"status"}),
        ("evidence_gaps", "gap_id", None),
        ("contradictions", "contradiction_id", {"status"}),
    ):
        old, new = before[collection], after[collection]
        if len(new) < len(old) or [x[identifier] for x in old] != [x[identifier] for x in new[:len(old)]]:
            raise PermissionError("critic cannot remove or reorder existing records")
        for prior, current in zip(old, new):
            if mutable is not None and any(prior[k] != current[k] for k in prior if k not in mutable):
                raise PermissionError(f"critic cannot rewrite existing {collection}")
        if collection == "mechanistic_claims" and any(c["created_by"] != "critic" for c in new[len(old):]):
            raise PermissionError("critic cannot impersonate claim creators")
    for collection, old in before["critic_audits"].items():
        new = after["critic_audits"][collection]
        if new[:len(old)] != old:
            raise PermissionError("critic audit records are append-only")
    status_changes = after["critic_audits"]["status_changes"][len(before["critic_audits"]["status_changes"]):]
    recorded_changes = [(r["hypothesis_id"], r["previous_status"], r["new_status"]) for r in status_changes]
    if sorted(verdict_changes) != sorted(recorded_changes):
        raise PermissionError("each critic verdict change requires its matching structured status change")
    if before["action_state"] != after["action_state"]:
        if before["action_state"]["current_phase"] == "stopped":
            raise PermissionError("critic cannot reopen a stopped case")
        check_critic_routing(after["action_state"])
