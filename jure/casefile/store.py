"""Transactional shared state; no reasoning, evidence retrieval, or routing policy.

SQLite is authoritative. Frozen model snapshots are read views, never write
commands. Agent identity is supplied by the trusted host application; this is
an API ownership contract, not authentication against hostile local clients.
"""
from contextlib import contextmanager
import json
import os
import re
from pathlib import Path
import sqlite3
import tempfile

import yaml

from .history import canonical_json, make_event, normalize_legacy_sections, verify_history
from .models import (
    ActionState, CaseFile, CaseMetadata, ClueRecord, ContradictionRecord,
    EvidenceAssessment, EvidenceGap, EvidenceQuestion, EvidenceRecord,
    HypothesisRecord, HypothesisRevision, MechanisticQuestion, PredictionRecord,
    QuestionRevision, new_id, utc_now,
)
from .validation import validate_case
from .critic_models import CRITIC_COLLECTIONS, HypothesisStatusChange, MechanisticClaim
from .critic_store import check_critic_event, check_critic_routing


class RevisionConflict(ValueError):
    """The caller read an older revision and must reload before retrying."""


class IntegrityError(ValueError):
    """Stored state and its append-only audit trail disagree."""


def _require(actor, *allowed):
    if actor not in allowed:
        raise PermissionError(f"{actor!r} cannot perform this operation; allowed: {', '.join(allowed)}")


def _find(records, key, value):
    for record in records:
        if record[key] == value:
            return record
    raise ValueError(f"unknown {key}: {value}")


def _dump(value):
    return value.model_dump(mode="json")


_INVESTIGATOR_TRANSITIONS = {
    "pending": {"selected", "cancelled", "unresolved"},
    "selected": {"in_progress", "pending", "unresolved", "cancelled"},
    "in_progress": {"answered", "partially_answered", "unresolved", "pending"},
    "partially_answered": {"selected", "pending", "unresolved", "cancelled"},
    "unresolved": {"pending", "selected", "cancelled"},
    "answered": set(), "cancelled": set(),
}


def _check_question_transition(previous, status):
    if status not in _INVESTIGATOR_TRANSITIONS[previous]:
        raise ValueError(f"invalid investigator question transition: {previous} -> {status}")


def _check_investigator_routing(state):
    allowed = {
        "evidence_needed": {"investigator", "evidence_investigator"},
        "evidence_in_progress": {"investigator", "evidence_investigator"},
        "critique_needed": {"critic"},
    }
    if state["next_actor"] not in allowed.get(state["current_phase"], set()):
        raise PermissionError("evidence_investigator may route only evidence work or critique_needed")
    if state["current_phase"] != "evidence_in_progress" and state["selected_question_id"] is not None:
        raise ValueError("completed investigator routing cannot retain a selected question")


def _check_investigator_event(before, after, event):
    """Validate every staged transition, including transient protected writes."""
    if event.actor != "evidence_investigator":
        raise PermissionError("staged events must belong to evidence_investigator")
    permissions = {
        "evidence_question.created": {"evidence_questions"},
        "evidence_question.status_changed": {"evidence_questions", "action_state"},
        "evidence_question.priority_changed": {"evidence_questions"},
        "evidence_record.created": {"evidence_records"},
        "evidence_record.question_linked": {"evidence_records"},
        "evidence_assessment.created": {"evidence_assessments"},
        "evidence_gap.created": {"evidence_gaps"},
        "evidence_gap.status_changed": {"evidence_gaps"},
        "contradiction.created": {"contradictions"},
        "action_state.changed": {"action_state"},
        "annotation.added": set(),
    }
    allowed = permissions.get(event.action)
    if allowed is None:
        if re.fullmatch(r"[A-Z][A-Z0-9_]*", event.action):
            allowed = set()
        else:
            raise PermissionError(f"unsupported investigator event: {event.action}")
    changed = {key for key in after if before.get(key) != after[key]} - {"metadata"}
    if changed - allowed:
        raise PermissionError(f"investigator event rewrites protected sections: {sorted(changed - allowed)}")
    immutable_metadata = set(before["metadata"]) - {"updated_at", "case_revision", "schema_version"}
    if any(before["metadata"][key] != after["metadata"][key] for key in immutable_metadata):
        raise PermissionError("investigator cannot rewrite case metadata")
    if after["metadata"]["case_revision"] != before["metadata"]["case_revision"] + 1:
        raise ValueError("staged revision must advance one step per event")
    if after["metadata"]["schema_version"] != "0.1.1":
        raise ValueError("investigator writes require schema 0.1.1")
    for collection, identifier in (
        ("evidence_questions", "question_id"), ("evidence_records", "evidence_id"),
        ("evidence_assessments", "assessment_id"), ("evidence_gaps", "gap_id"),
        ("contradictions", "contradiction_id"),
    ):
        old, new = before[collection], after[collection]
        if len(new) < len(old) or [r[identifier] for r in new[:len(old)]] != [r[identifier] for r in old]:
            raise PermissionError("investigator cannot remove or reorder existing records")
        for previous, current in zip(old, new):
            fields = {key for key in current if current[key] != previous[key]}
            if collection == "evidence_questions":
                if fields - {"status", "priority"}:
                    raise PermissionError("investigator cannot rewrite existing question content")
                if "status" in fields:
                    _check_question_transition(previous["status"], current["status"])
            elif collection == "evidence_records":
                if fields - {"related_question_ids"}:
                    raise PermissionError("investigator cannot rewrite existing evidence bodies")
                prior_links = previous["related_question_ids"]
                if current["related_question_ids"][:len(prior_links)] != prior_links:
                    raise PermissionError("evidence links are append-only")
            elif collection == "evidence_gaps":
                if fields - {"status"}:
                    raise PermissionError("investigator cannot rewrite existing gap content or references")
            elif fields:
                raise PermissionError("investigator cannot rewrite prior evidence or contradictions")
        for record in new[len(old):]:
            if collection == "evidence_questions" and (record["status"] != "pending" or record["created_by"] != "evidence_investigator"):
                raise PermissionError("investigator may create only pending follow-up questions")
            if collection == "evidence_records" and record["created_by"] != "evidence_investigator":
                raise PermissionError("investigator cannot impersonate an evidence creator")
            if collection == "evidence_assessments" and record["assessed_by"] != "evidence_investigator":
                raise PermissionError("investigator cannot impersonate an evidence assessor")
            if collection in {"evidence_gaps", "contradictions"} and record["status"] != "open":
                raise PermissionError("investigator may only create open gaps or contradictions")
    if before["action_state"] != after["action_state"]:
        if before["action_state"]["current_phase"] == "stopped":
            raise PermissionError("investigator cannot reopen a stopped case")
        if event.action == "action_state.changed":
            _check_investigator_routing(after["action_state"])
        elif any(before["action_state"][key] != after["action_state"][key]
                 for key in ("current_phase", "next_actor", "stop_reason")):
            raise PermissionError("question updates may only clear the selected question pointer")


def _atomic_write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return path


def save_case(case, path):
    """Export a validated snapshot; this never changes the authoritative store."""
    case = validate_case(case)
    verify_history(case)
    path = Path(path)
    payload = _dump(case)
    if path.suffix.lower() in {".yaml", ".yml"}:
        content = yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)
    elif path.suffix.lower() == ".json":
        content = json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    else:
        raise ValueError("snapshot path must end in .json, .yaml, or .yml")
    return _atomic_write(path, content)


def load_case(path):
    """Load a JSON/YAML read snapshot, validating all IDs and references."""
    path = Path(path)
    content = path.read_text(encoding="utf-8")
    if path.suffix.lower() in {".yaml", ".yml"}:
        payload = yaml.safe_load(content)
    elif path.suffix.lower() == ".json":
        payload = json.loads(content)
    else:
        raise ValueError("snapshot path must end in .json, .yaml, or .yml")
    case = validate_case(payload)
    verify_history(case)
    return case


class CaseStore:
    """One SQLite file may serve many cases and multiple independent clients.

    Use a separate instance per thread/process. Every command compares the
    expected revision inside BEGIN IMMEDIATE and commits event + state together.
    """

    def __init__(self, path=":memory:"):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA synchronous=FULL")
        self._connection.executescript("""
            CREATE TABLE IF NOT EXISTS cases (
                case_id TEXT PRIMARY KEY,
                revision INTEGER NOT NULL CHECK (revision >= 1),
                snapshot_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS events (
                case_id TEXT NOT NULL REFERENCES cases(case_id),
                sequence INTEGER NOT NULL,
                event_id TEXT NOT NULL UNIQUE,
                payload_json TEXT NOT NULL,
                PRIMARY KEY (case_id, sequence)
            );
            CREATE TRIGGER IF NOT EXISTS events_no_update
                BEFORE UPDATE ON events BEGIN
                SELECT RAISE(ABORT, 'audit events are append-only'); END;
            CREATE TRIGGER IF NOT EXISTS events_no_delete
                BEFORE DELETE ON events BEGIN
                SELECT RAISE(ABORT, 'audit events are append-only'); END;
            CREATE TRIGGER IF NOT EXISTS events_no_replace
                BEFORE INSERT ON events WHEN EXISTS (
                    SELECT 1 FROM events WHERE event_id = NEW.event_id
                    OR (case_id = NEW.case_id AND sequence = NEW.sequence)
                ) BEGIN SELECT RAISE(ABORT, 'audit events are append-only'); END;
        """)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        self._connection.close()

    @contextmanager
    def _transaction(self, *, write=False):
        if self._connection.in_transaction:
            # A service may group existing commands without weakening their
            # checks. Savepoints keep a failed nested command independently safe.
            savepoint = new_id("transaction")
            self._connection.execute(f"SAVEPOINT {savepoint}")
            try:
                yield
                self._connection.execute(f"RELEASE SAVEPOINT {savepoint}")
            except BaseException:
                self._connection.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                self._connection.execute(f"RELEASE SAVEPOINT {savepoint}")
                raise
            return
        self._connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
        try:
            yield
            self._connection.commit()
        except BaseException:
            self._connection.rollback()
            raise

    @contextmanager
    def atomic(self, case_id, *, expected_revision):
        """Group normal commands into one all-or-nothing, version-checked write.

        Perform slow computation before entering this context. All commands keep
        their individual actor checks and audit events. A failure rolls the
        entire group back; callers must not retry a stale reasoning result.
        """
        if type(expected_revision) is not int or expected_revision < 1:
            raise ValueError("expected_revision must be a positive integer")
        with self._transaction(write=True):
            case = self._load(case_id)
            if case.metadata.case_revision != expected_revision:
                raise RevisionConflict(
                    f"expected revision {expected_revision}, found {case.metadata.case_revision}; reload case")
            yield case

    def _load(self, case_id):
        row = self._connection.execute(
            "SELECT revision, snapshot_json FROM cases WHERE case_id=?", (case_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown case: {case_id}")
        case = validate_case(json.loads(row[1]))
        try:
            verify_history(case)
        except ValueError as error:
            raise IntegrityError(str(error)) from error
        events = [json.loads(record[0]) for record in self._connection.execute(
            "SELECT payload_json FROM events WHERE case_id=? ORDER BY sequence", (case_id,),
        )]
        if (case.metadata.case_id != case_id or case.metadata.case_revision != row[0]
                or events != [_dump(event) for event in case.investigation_history]):
            raise IntegrityError("snapshot and audit trail disagree")
        return case

    def load_case(self, case_id):
        with self._transaction():
            return self._load(case_id)

    def import_case(self, case):
        """Import a verified snapshot and its exact history into a new store.

        This is an import boundary, not an agent write operation. It never
        overwrites an existing case or fabricates a replacement creation event.
        """
        case = validate_case(case)
        verify_history(case)
        with self._transaction(write=True):
            self._connection.execute(
                "INSERT INTO cases(case_id, revision, snapshot_json) VALUES (?, ?, ?)",
                (case.metadata.case_id, case.metadata.case_revision, canonical_json(_dump(case))),
            )
            for event in case.investigation_history:
                self._insert_event(case.metadata.case_id, event)
        return case

    def commit_investigator_case(self, case_id, staged_case, *, expected_revision,
                                 actor="evidence_investigator"):
        """Commit an independently staged run after validating its full delta.

        Tools can run against an imported in-memory store without holding the
        authoritative database lock. A stale revision or any disallowed event
        rejects the entire run, including its evidence and history changes.
        """
        _require(actor, "evidence_investigator")
        staged_case = validate_case(staged_case)
        verify_history(staged_case)
        if staged_case.metadata.case_id != case_id:
            raise ValueError("staged case ID must match the destination")
        with self.atomic(case_id, expected_revision=expected_revision) as original:
            history = original.investigation_history
            if staged_case.investigation_history[:len(history)] != history:
                raise IntegrityError("staged history must preserve the complete original prefix")
            state = _dump(original)
            state.pop("investigation_history")
            events = staged_case.investigation_history[len(history):]
            for event in events:
                following = dict(state)
                following.update(normalize_legacy_sections(event.changes["after"]))
                _check_investigator_event(state, following, event)
                # Validate references at every intermediate event, not merely
                # the eventual final snapshot (which could conceal a cycle).
                candidate = dict(following, investigation_history=[
                    _dump(item) for item in staged_case.investigation_history[:event.sequence]
                ])
                validate_case(candidate)
                state = following
            if not events:
                if staged_case != original:
                    raise IntegrityError("staged case changed without an audit event")
                return original
            for event in events:
                self._insert_event(case_id, event)
            self._write_snapshot(staged_case)
        return staged_case

    def commit_critic_case(self, case_id, staged_case, *, expected_revision, actor="critic"):
        """Atomically commit a staged audit after checking every protected transition."""
        _require(actor, "critic")
        staged_case = validate_case(staged_case)
        verify_history(staged_case)
        if staged_case.metadata.case_id != case_id:
            raise ValueError("staged case ID must match the destination")
        with self.atomic(case_id, expected_revision=expected_revision) as original:
            history = original.investigation_history
            if staged_case.investigation_history[:len(history)] != history:
                raise IntegrityError("staged history must preserve the complete original prefix")
            state = _dump(original)
            state.pop("investigation_history")
            events = staged_case.investigation_history[len(history):]
            for event in events:
                following = dict(state)
                following.update(normalize_legacy_sections(event.changes["after"]))
                check_critic_event(state, following, event)
                validate_case(dict(following, investigation_history=[
                    _dump(item) for item in staged_case.investigation_history[:event.sequence]
                ]))
                state = following
            if not events:
                if staged_case != original:
                    raise IntegrityError("staged case changed without an audit event")
                return original
            for event in events:
                self._insert_event(case_id, event)
            self._write_snapshot(staged_case)
        return staged_case

    def append_critic_records(self, case_id, *, claims=(), evidence_gaps=(), contradictions=(),
                              expected_revision, actor="critic", **collections):
        """Append typed audit records and their new graph objects in one atomic event."""
        _require(actor, "critic")
        unknown = collections.keys() - CRITIC_COLLECTIONS.keys()
        if unknown:
            raise ValueError(f"unknown critic collection: {sorted(unknown)}")
        if collections.get("status_changes"):
            raise ValueError("status_changes are created atomically by update_hypothesis")
        records = {name: [_dump(CRITIC_COLLECTIONS[name][0].model_validate(r)) for r in values]
                   for name, values in collections.items()}
        new_claims = [_dump(MechanisticClaim.model_validate(c)) for c in claims]
        new_gaps = [_dump(EvidenceGap.model_validate(g)) for g in evidence_gaps]
        new_contradictions = [_dump(ContradictionRecord.model_validate(c)) for c in contradictions]

        def change(data):
            data["mechanistic_claims"].extend(new_claims)
            data["evidence_gaps"].extend(new_gaps)
            data["contradictions"].extend(new_contradictions)
            for name, values in records.items():
                data["critic_audits"][name].extend(values)
        return self._mutate(case_id, expected_revision=expected_revision, actor=actor,
                            action="critic.records_appended", object_type="case", object_id=case_id,
                            summary="Appended structured critic audit records", change=change)

    def update_mechanistic_claim_status(self, case_id, claim_id, status, *, expected_revision,
                                        actor="critic", reason=None):
        _require(actor, "critic")
        return self._mutate(case_id, expected_revision=expected_revision, actor=actor,
                            action="mechanistic_claim.status_changed", object_type="mechanistic_claim",
                            object_id=claim_id, summary=reason or f"Mechanistic claim status: {status}",
                            change=lambda data: _find(data["mechanistic_claims"], "claim_id", claim_id).update(status=status))

    def update_evidence_gap(self, case_id, gap_id, *, expected_revision, actor="critic", **changes):
        _require(actor, "critic")
        if "gap_id" in changes or changes.keys() - EvidenceGap.model_fields.keys():
            raise ValueError("unsupported evidence gap fields")
        return self._mutate(case_id, expected_revision=expected_revision, actor=actor,
                            action="evidence_gap.updated", object_type="evidence_gap", object_id=gap_id,
                            summary="Updated critic interpretation of evidence gap",
                            change=lambda data: _find(data["evidence_gaps"], "gap_id", gap_id).update(changes))

    def _insert_event(self, case_id, event):
        self._connection.execute(
            "INSERT INTO events(case_id, sequence, event_id, payload_json) VALUES (?, ?, ?, ?)",
            (case_id, event.sequence, event.event_id, canonical_json(_dump(event))),
        )

    def _write_snapshot(self, case):
        self._connection.execute(
            "UPDATE cases SET revision=?, snapshot_json=? WHERE case_id=?",
            (case.metadata.case_revision, canonical_json(_dump(case)), case.metadata.case_id),
        )

    def create_case_from_clue(self, clue, *, case_id=None, actor="controller",
                              source_dataset=None, cell_context=None):
        _require(actor, "controller", "system")
        clue = ClueRecord.model_validate(clue)
        metadata = CaseMetadata(case_id=case_id or new_id("case"), perturbation=clue.perturbation,
                                source_dataset=source_dataset, cell_context=cell_context)
        # Initial event needs the full initial state, before cross-reference validation.
        data = _dump(CaseFile.model_construct(
            metadata=metadata, clue=clue, mechanistic_question=None, hypotheses=(),
            evidence_questions=(), evidence_records=(), evidence_assessments=(),
            evidence_gaps=(), contradictions=(), action_state=ActionState(),
            investigation_history=(),
        ))
        event = make_event(None, data, actor=actor, action="case.created", object_type="case",
                           object_id=metadata.case_id, summary="Created case from observed clue")
        data["investigation_history"] = [_dump(event)]
        case = validate_case(data)
        with self._transaction(write=True):
            self._connection.execute(
                "INSERT INTO cases(case_id, revision, snapshot_json) VALUES (?, ?, ?)",
                (metadata.case_id, 1, canonical_json(_dump(case))),
            )
            self._insert_event(metadata.case_id, event)
        return case

    def _mutate(self, case_id, *, expected_revision, actor, action, object_type,
                object_id, summary, change, metadata=None):
        if type(expected_revision) is not int or expected_revision < 1:
            raise ValueError("expected_revision must be a positive integer")
        with self._transaction(write=True):
            before = self._load(case_id)
            if before.metadata.case_revision != expected_revision:
                raise RevisionConflict(
                    f"expected revision {expected_revision}, found {before.metadata.case_revision}; reload case")
            data = _dump(before)
            change(data)
            data["metadata"]["case_revision"] += 1
            data["metadata"]["updated_at"] = utc_now().isoformat()
            data["metadata"]["schema_version"] = "0.1.1"
            data = _dump(CaseFile.model_validate(data))
            event = make_event(before, data, actor=actor, action=action, object_type=object_type,
                               object_id=object_id, summary=summary, metadata=metadata)
            data["investigation_history"].append(_dump(event))
            case = validate_case(data)
            self._insert_event(case_id, event)
            self._write_snapshot(case)
            return case

    def add_mechanistic_question(self, case_id, question, *, actor, expected_revision):
        _require(actor, "explorer")
        question = MechanisticQuestion.model_validate(question)
        if question.revisions:
            raise ValueError("new mechanistic question cannot supply revision history")

        def change(data):
            if data["mechanistic_question"] is not None:
                raise ValueError("mechanistic question already exists; revise it instead")
            data["mechanistic_question"] = _dump(question)
        return self._mutate(case_id, expected_revision=expected_revision, actor=actor,
                            action="mechanistic_question.created", object_type="mechanistic_question",
                            object_id=question.question_id, summary="Created mechanistic question", change=change)

    def revise_mechanistic_question(self, case_id, *, new_text, reason, actor, expected_revision):
        _require(actor, "explorer")
        if not reason or not reason.strip():
            raise ValueError("revision reason is required")

        def change(data):
            question = data["mechanistic_question"]
            if question is None:
                raise ValueError("mechanistic question does not exist")
            revision = QuestionRevision(revision_id=new_id("question_revision"), previous_text=question["question_text"],
                                        new_text=new_text, reason=reason, timestamp=utc_now(), actor=actor)
            question["revisions"].append(_dump(revision))
            question["question_text"] = new_text
            question["status"] = "reframed"
        # Event points at the case; the structured change identifies its question.
        return self._mutate(case_id, expected_revision=expected_revision, actor=actor,
                            action="mechanistic_question.revised", object_type="case", object_id=case_id,
                            summary=reason, change=change)

    def add_hypothesis(self, case_id, *, title, mechanism_statement, mechanism_type,
                       derived_from=(), weakening_conditions=(), assumptions=(), unresolved_points=(),
                       hypothesis_id=None, actor, expected_revision):
        _require(actor, "explorer")
        revision = HypothesisRevision(
            revision_id=new_id("hypothesis_revision"), title=title, mechanism_statement=mechanism_statement,
            mechanism_type=mechanism_type, derived_from=derived_from, weakening_conditions=weakening_conditions,
            assumptions=assumptions, unresolved_points=unresolved_points, created_at=utc_now(), created_by=actor,
        )
        hypothesis = HypothesisRecord(hypothesis_id=hypothesis_id or new_id("hypothesis"),
                                      current_revision_id=revision.revision_id, revisions=(revision,))
        return self._mutate(case_id, expected_revision=expected_revision, actor=actor,
                            action="hypothesis.created", object_type="hypothesis", object_id=hypothesis.hypothesis_id,
                            summary=f"Created hypothesis: {title}",
                            change=lambda data: data["hypotheses"].append(_dump(hypothesis)))

    def update_hypothesis(self, case_id, hypothesis_id, *, reason, status=None,
                          revision_id=None, actor, expected_revision, claim_ids=(), evidence_ids=(),
                          gap_ids=(), critic_round=0, **changes):
        if not reason or not reason.strip():
            raise ValueError("hypothesis update reason is required")
        allowed = {"title", "mechanism_statement", "mechanism_type", "derived_from",
                   "weakening_conditions", "assumptions", "unresolved_points"}
        if changes.keys() - allowed:
            raise ValueError(f"unsupported hypothesis fields: {sorted(changes.keys() - allowed)}")
        if status is not None:
            _require(actor, "critic")
            if changes:
                raise ValueError("verdict update cannot rewrite hypothesis content")
        else:
            _require(actor, "explorer")
            if not changes:
                raise ValueError("a hypothesis revision must change content")

        def change(data):
            hypothesis = _find(data["hypotheses"], "hypothesis_id", hypothesis_id)
            target = revision_id or hypothesis["current_revision_id"]
            old = _find(hypothesis["revisions"], "revision_id", target)
            if status is not None:
                if status in {"supported", "partially_supported", "challenged", "insufficient"} and old["status"] != status:
                    if target != hypothesis["current_revision_id"]:
                        raise ValueError("critic verdict must apply to the current hypothesis revision")
                    record = HypothesisStatusChange(
                        hypothesis_id=hypothesis_id, previous_status=old["status"], new_status=status,
                        claim_ids=claim_ids, evidence_ids=evidence_ids, gap_ids=gap_ids,
                        reason=reason, critic_round=critic_round,
                    )
                    data["critic_audits"]["status_changes"].append(_dump(record))
                old["status"] = status
                return
            if target != hypothesis["current_revision_id"]:
                raise ValueError("new revision must supersede the current hypothesis revision")
            revised = dict(old, **changes)
            revised.update(revision_id=new_id("hypothesis_revision"), supersedes_revision_id=target,
                           status="proposed", reason=reason, created_at=utc_now().isoformat(), created_by=actor)
            hypothesis["revisions"].append(revised)
            hypothesis["current_revision_id"] = revised["revision_id"]
        return self._mutate(case_id, expected_revision=expected_revision, actor=actor,
                            action="hypothesis.verdict_changed" if status is not None else "hypothesis.revised",
                            object_type="hypothesis", object_id=hypothesis_id, summary=reason, change=change)

    def add_prediction(self, case_id, prediction, *, actor, expected_revision):
        _require(actor, "explorer")
        prediction = PredictionRecord.model_validate(prediction)
        if prediction.status != "untested":
            raise ValueError("new prediction must be untested")

        def change(data):
            hypothesis = _find(data["hypotheses"], "hypothesis_id", prediction.hypothesis_id)
            hypothesis["predictions"].append(_dump(prediction))
        return self._mutate(case_id, expected_revision=expected_revision, actor=actor,
                            action="prediction.created", object_type="prediction", object_id=prediction.prediction_id,
                            summary="Created hypothesis prediction", change=change)

    def update_prediction_status(self, case_id, prediction_id, status, *, actor, expected_revision):
        _require(actor, "investigator")

        def change(data):
            predictions = [p for h in data["hypotheses"] for p in h["predictions"]]
            _find(predictions, "prediction_id", prediction_id)["status"] = status
        return self._mutate(case_id, expected_revision=expected_revision, actor=actor,
                            action="prediction.status_changed", object_type="prediction", object_id=prediction_id,
                            summary=f"Prediction status: {status}", change=change)

    def add_evidence_question(self, case_id, question, *, actor, expected_revision):
        _require(actor, "explorer", "evidence_investigator", "human")
        values = _dump(EvidenceQuestion.model_validate(question))
        values.update(created_by=actor, created_at=utc_now().isoformat())
        if values["status"] != "pending":
            raise ValueError("new evidence question must be pending")
        return self._mutate(case_id, expected_revision=expected_revision, actor=actor,
                            action="evidence_question.created", object_type="evidence_question",
                            object_id=values["question_id"], summary="Queued evidence question",
                            change=lambda data: data["evidence_questions"].append(values))

    def update_evidence_question_status(self, case_id, question_id, status, *, actor, expected_revision):
        _require(actor, "investigator", "evidence_investigator")

        def change(data):
            question = _find(data["evidence_questions"], "question_id", question_id)
            if actor == "evidence_investigator":
                _check_question_transition(question["status"], status)
            question["status"] = status
            # Clear an obsolete pointer without selecting a next actor or phase.
            if status not in {"selected", "in_progress", "partially_answered"} and data["action_state"]["selected_question_id"] == question_id:
                data["action_state"]["selected_question_id"] = None
        return self._mutate(case_id, expected_revision=expected_revision, actor=actor,
                            action="evidence_question.status_changed", object_type="evidence_question",
                            object_id=question_id, summary=f"Evidence question status: {status}", change=change)

    def update_evidence_question_priority(self, case_id, question_id, priority, *, actor, expected_revision):
        _require(actor, "evidence_investigator", "human")
        return self._mutate(case_id, expected_revision=expected_revision, actor=actor,
                            action="evidence_question.priority_changed", object_type="evidence_question",
                            object_id=question_id, summary=f"Evidence question priority: {priority}",
                            change=lambda data: _find(data["evidence_questions"], "question_id", question_id).update(priority=priority))

    def manually_prioritize_question(self, case_id, question_id, priority="high", *, expected_revision):
        return self.update_evidence_question_priority(case_id, question_id, priority, actor="human",
                                                      expected_revision=expected_revision)

    def manually_cancel_question(self, case_id, question_id, *, expected_revision, reason="Human cancelled question"):
        def change(data):
            _find(data["evidence_questions"], "question_id", question_id)["status"] = "cancelled"
            if data["action_state"]["selected_question_id"] == question_id:
                data["action_state"]["selected_question_id"] = None
        return self._mutate(case_id, expected_revision=expected_revision, actor="human",
                            action="evidence_question.cancelled", object_type="evidence_question",
                            object_id=question_id, summary=reason, change=change)

    def manually_add_evidence_question(self, case_id, question, *, expected_revision):
        return self.add_evidence_question(case_id, question, actor="human", expected_revision=expected_revision)

    def mark_selected(self, case_id, question_id, *, actor, expected_revision):
        return self.update_evidence_question_status(case_id, question_id, "selected", actor=actor,
                                                    expected_revision=expected_revision)

    def mark_answered(self, case_id, question_id, *, actor, expected_revision):
        return self.update_evidence_question_status(case_id, question_id, "answered", actor=actor,
                                                    expected_revision=expected_revision)

    def mark_unresolved(self, case_id, question_id, *, actor, expected_revision):
        return self.update_evidence_question_status(case_id, question_id, "unresolved", actor=actor,
                                                    expected_revision=expected_revision)

    def _add_record(self, case_id, record, model, collection, id_field, *, actor,
                    expected_revision, creator_field="created_by"):
        values = _dump(model.model_validate(record))
        if creator_field in values:
            values[creator_field] = actor
        if "created_at" in values:
            values["created_at"] = utc_now().isoformat()
        object_type = collection.removesuffix("s")
        return self._mutate(case_id, expected_revision=expected_revision, actor=actor,
                            action=f"{object_type}.created", object_type=object_type,
                            object_id=values[id_field], summary=f"Added {object_type}",
                            change=lambda data: data[collection].append(values))

    def add_evidence_record(self, case_id, evidence, *, actor, expected_revision):
        _require(actor, "investigator", "evidence_investigator")
        return self._add_record(case_id, evidence, EvidenceRecord, "evidence_records", "evidence_id",
                                actor=actor, expected_revision=expected_revision)

    def link_evidence_to_question(self, case_id, evidence_id, question_id, *, actor="evidence_investigator", expected_revision):
        _require(actor, "investigator", "evidence_investigator")

        def change(data):
            evidence = _find(data["evidence_records"], "evidence_id", evidence_id)
            _find(data["evidence_questions"], "question_id", question_id)
            if question_id == evidence["question_id"] or question_id in evidence["related_question_ids"]:
                raise ValueError("evidence is already linked to this question")
            evidence["related_question_ids"].append(question_id)
        return self._mutate(case_id, expected_revision=expected_revision, actor=actor,
                            action="evidence_record.question_linked", object_type="evidence_record",
                            object_id=evidence_id, summary=f"Linked evidence to question {question_id}", change=change)

    def add_evidence_assessment(self, case_id, assessment, *, actor, expected_revision):
        _require(actor, "investigator", "evidence_investigator", "critic")
        return self._add_record(case_id, assessment, EvidenceAssessment, "evidence_assessments", "assessment_id",
                                actor=actor, expected_revision=expected_revision, creator_field="assessed_by")

    def add_evidence_gap(self, case_id, gap, *, actor, expected_revision):
        _require(actor, "explorer", "investigator", "evidence_investigator", "critic")
        gap = EvidenceGap.model_validate(gap)
        if gap.status != "open":
            raise ValueError("new evidence gap must be open")
        return self._add_record(case_id, gap, EvidenceGap, "evidence_gaps", "gap_id",
                                actor=actor, expected_revision=expected_revision)

    def add_contradiction(self, case_id, contradiction, *, actor, expected_revision):
        _require(actor, "critic", "evidence_investigator")
        contradiction = ContradictionRecord.model_validate(contradiction)
        if actor == "evidence_investigator" and contradiction.status != "open":
            raise PermissionError("investigator may only report open contradictions")
        return self._add_record(case_id, contradiction, ContradictionRecord, "contradictions", "contradiction_id",
                                actor=actor, expected_revision=expected_revision)

    def update_evidence_gap_status(self, case_id, gap_id, status, *, actor, expected_revision):
        _require(actor, "investigator", "evidence_investigator", "critic")
        return self._mutate(case_id, expected_revision=expected_revision, actor=actor,
                            action="evidence_gap.status_changed", object_type="evidence_gap", object_id=gap_id,
                            summary=f"Evidence gap status: {status}",
                            change=lambda data: _find(data["evidence_gaps"], "gap_id", gap_id).update(status=status))

    def update_contradiction_status(self, case_id, contradiction_id, status, *, actor, expected_revision):
        _require(actor, "critic")
        return self._mutate(case_id, expected_revision=expected_revision, actor=actor,
                            action="contradiction.status_changed", object_type="contradiction", object_id=contradiction_id,
                            summary=f"Contradiction status: {status}",
                            change=lambda data: _find(data["contradictions"], "contradiction_id", contradiction_id).update(status=status))

    def set_action_state(self, case_id, state, *, actor, expected_revision):
        _require(actor, "controller", "evidence_investigator", "critic")
        state = ActionState.model_validate(state)
        if actor == "evidence_investigator":
            _check_investigator_routing(_dump(state))
        if actor == "critic":
            check_critic_routing(_dump(state))

        def change(data):
            if actor in {"evidence_investigator", "critic"} and data["action_state"]["current_phase"] == "stopped":
                raise PermissionError(f"{actor} cannot reopen a stopped case")
            data["action_state"] = _dump(state)
        return self._mutate(case_id, expected_revision=expected_revision, actor=actor,
                            action="action_state.changed", object_type="case", object_id=case_id,
                            summary="Recorded external routing decision",
                            change=change)

    def append_history_event(self, case_id, *, summary, metadata=None, object_type="case",
                              object_id=None, actor, expected_revision, action="annotation.added"):
        _require(actor, "explorer", "investigator", "evidence_investigator", "critic", "controller", "human")
        if action != "annotation.added" and (actor not in {"evidence_investigator", "critic"} or
                re.fullmatch(r"[A-Z][A-Z0-9_]*", action) is None):
            raise ValueError("custom investigator/critic annotations require an uppercase event name")
        return self._mutate(case_id, expected_revision=expected_revision, actor=actor,
                            action=action, object_type=object_type, object_id=object_id or case_id,
                            summary=summary, metadata=metadata, change=lambda data: None)

    def export_case(self, case_id, directory):
        """Export one committed revision; JSONL must remain an exact history prefix.

        Export files are rebuildable views, not a three-file atomic database.
        BEGIN IMMEDIATE serializes exports through this database with writes and
        other exports, preventing two clients from appending duplicate events.
        """
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        paths = {"json": directory / "case_file.json", "yaml": directory / "case_file.yaml",
                 "history": directory / "case_history.jsonl"}
        with self._transaction(write=True):
            case = self._load(case_id)
            history = [_dump(event) for event in case.investigation_history]
            previous = []
            if paths["history"].exists():
                content = paths["history"].read_text(encoding="utf-8")
                if content and not content.endswith("\n"):
                    raise IntegrityError("incomplete exported history; export into a new directory")
                try:
                    previous = [json.loads(line) for line in content.splitlines()]
                except ValueError as error:
                    raise IntegrityError("invalid exported history; export into a new directory") from error
                if previous != history[:len(previous)]:
                    raise IntegrityError("exported history is not a prefix of this case's audit trail")
            save_case(case, paths["json"])
            save_case(case, paths["yaml"])
            with paths["history"].open("a", encoding="utf-8") as stream:
                for event in history[len(previous):]:
                    stream.write(canonical_json(event) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
        return paths


def create_case_from_clue(clue, *, store=None, **kwargs):
    """Create a case in the supplied store, or an in-memory snapshot for export."""
    if store is not None:
        return store.create_case_from_clue(clue, **kwargs)
    with CaseStore() as temporary:
        return temporary.create_case_from_clue(clue, **kwargs)
