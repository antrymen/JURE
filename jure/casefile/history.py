"""Structured audit records. Only the store assigns sequence and revision."""
import json
from copy import deepcopy

from .models import HistoryEvent, new_id, utc_now


_COMPAT_DEFAULTS = {
    "evidence_questions": {
        "derived_from_question_ids": [], "derived_from_evidence_ids": [],
        "investigation_depth": None, "query_spec": {},
    },
    "evidence_records": {
        "related_question_ids": [], "source_quality": "unknown", "support_quality": "unknown",
        "negative_evidence_type": "not_applicable", "potential_conflict": False, "fingerprint": None,
    },
    "evidence_gaps": {
        "related_question_ids": [], "related_claim_ids": [], "related_evidence_ids": [],
        "critical": False, "criticality_reason": None, "reason": None,
        "resolvable_with_current_tools": None,
    },
    "contradictions": {
        "claim_ids": [], "context_difference": None, "possible_explanations": [],
        "potential_context_dependency": False, "critical": False,
    },
}


def normalize_legacy_sections(value):
    """Fill additive 0.1.1 defaults without changing any stored audit payload.

    Historical 0.1.0 events contain their original section shape. New events
    contain parsed 0.1.1 defaults, even when their preceding event is legacy.
    Only the known additive defaults are normalized for replay comparisons.
    """
    value = deepcopy(value)
    if "clue" in value:
        value["clue"].setdefault("upstream_context", None)
        from .critic_models import CriticAudits
        value.setdefault("mechanistic_claims", [])
        value.setdefault("critic_audits", CriticAudits().model_dump(mode="json"))
    for section, defaults in _COMPAT_DEFAULTS.items():
        for record in value.get(section, ()):
            for key, default in defaults.items():
                record.setdefault(key, deepcopy(default))
    # claim-source-v1 adds optional audit annotations, never historical verdicts.
    audits = value.get('critic_audits', {})
    for record in audits.get('evidence_audits', ()):
        for key in ('mechanism_support', 'case_specific_support', 'context_transferability'):
            record.setdefault(key, None)
    for record in audits.get('stop_records', ()):
        record.setdefault('source_reviews', [])
    return value


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def verify_history(case):
    """Replay structured changes and require an exact match to the read view."""
    state = {}
    for event in case.investigation_history:
        changes = event.changes.to_dict()
        if set(changes) != {"before", "after"}:
            raise ValueError("audit event must contain structured before/after changes")
        before, after = changes["before"], changes["after"]
        if not isinstance(before, dict) or not isinstance(after, dict):
            raise ValueError("audit before/after changes must be JSON objects")
        if "investigation_history" in before or "investigation_history" in after:
            raise ValueError("audit changes cannot rewrite history")
        if normalize_legacy_sections(before) != normalize_legacy_sections(
                {key: state[key] for key in after if key in state}):
            raise ValueError("audit change does not match the preceding state")
        state.update(after)
        state = normalize_legacy_sections(state)
    expected = case.model_dump(mode="json")
    expected.pop("investigation_history")
    if normalize_legacy_sections(state) != expected:
        raise ValueError("snapshot does not match replayed audit history")


def snapshot_at_revision(case, revision):
    """Reconstruct an exact audited prefix without modifying the source case.

    This is a historical read, not a reopening action. Recovery runs must keep
    their source snapshot and record a separate branch/checkpoint provenance.
    """
    from .validation import validate_case
    verify_history(case)
    if type(revision) is not int or not 1 <= revision <= case.metadata.case_revision:
        raise ValueError('Revision is outside the audited history')
    state = {}
    prefix = []
    for event in case.investigation_history:
        if event.case_revision > revision:
            break
        state.update(event.changes.to_dict()['after'])
        state = normalize_legacy_sections(state)
        prefix.append(event.model_dump(mode='json'))
    if not prefix or prefix[-1]['case_revision'] != revision:
        raise ValueError('Revision does not exist in the audited history')
    snapshot = validate_case({**state, 'investigation_history': prefix})
    verify_history(snapshot)
    return snapshot


def make_event(before, after, *, actor, action, object_type, object_id, summary, metadata=None):
    """Record changed top-level sections, excluding recursive audit history."""
    old = {} if before is None else before.model_dump(mode="json")
    new = after if isinstance(after, dict) else after.model_dump(mode="json")
    keys = [key for key in new if key != "investigation_history" and (key not in old or old[key] != new[key])]
    revision = new["metadata"]["case_revision"]
    return HistoryEvent(
        event_id=new_id("event"), sequence=revision, case_revision=revision,
        timestamp=utc_now(), actor=actor, action=action, object_type=object_type,
        object_id=object_id, summary=summary, metadata=metadata or {},
        changes={"before": {key: old[key] for key in keys if key in old},
                 "after": {key: new[key] for key in keys}},
    )


def count_evidence_tool_calls(case):
    """Count actual attempts even when an Investigator transaction rolled back.

    Successful calls have committed TOOL_CALL_STARTED events; failed staged
    runs retain their attempts in the immutable run artifact. Deduplicate
    actual executions across saved-prefix replay; repeated live queries and
    unfinished attempts still consume their original slots.
    """
    committed, recorded, completed = {}, {}, {}
    for event in case.investigation_history:
        run_id = event.metadata.get("run_id") or event.event_id
        if event.action == "TOOL_CALL_STARTED":
            committed[run_id] = committed.get(run_id, 0) + 1
        if event.action == "TOOL_CALL_COMPLETED":
            completed.setdefault(run_id, []).append(dict(event.metadata))
        artifact = event.metadata.get("run_artifact")
        if event.actor == "evidence_investigator" and artifact:
            calls = list(artifact.get("tool_calls", ()))
            if len(calls) >= len(recorded.get(run_id, ())):
                recorded[run_id] = calls
    # Replayed raw executions retain both timestamps and the content-addressed
    # result name. Deduplicate those executions, never merely identical queries.
    # Unfinished attempts still consume a slot even without a result artifact.
    from pathlib import Path
    executions, unfinished = set(), 0
    for run_id in committed.keys() | recorded.keys() | completed.keys():
        rows = recorded.get(run_id, ())
        if len(completed.get(run_id, ())) > len(rows):
            rows = completed[run_id]
        unfinished += max(0, committed.get(run_id, 0) - len(rows))
        for index, row in enumerate(rows):
            raw = row.get('raw_result_reference')
            if raw and row.get('started_at') and row.get('completed_at'):
                identity = (row.get('tool_id'), row.get('operation'),
                            row['started_at'], row['completed_at'], Path(raw).name)
            else:
                identity = (run_id, index)
            executions.add(identity)
    return len(executions) + unfinished


def agent_round_counts(case, role, *, mode=None):
    """Separate attempts from successful commits; never refund real tool calls.

    Explorer uses metadata event names; the other roles use action names.
    A repeated export/annotation for one run must not count as another round.
    """
    if role not in {'explorer', 'investigator', 'critic'}:
        raise ValueError('Unknown Agent role')
    counts = {}
    for outcome in ('started', 'completed', 'failed'):
        expected = f'{role.upper()}_{outcome.upper()}'
        runs = set()
        for event in case.investigation_history:
            name = event.metadata.get('explorer_event') if role == 'explorer' else event.action
            if name != expected or (mode is not None and event.metadata.get('mode') != mode):
                continue
            runs.add(event.metadata.get('run_id') or event.event_id)
        counts[outcome] = len(runs)
    return counts
