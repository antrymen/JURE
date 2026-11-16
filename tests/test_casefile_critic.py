"""Critic graph integrity, additive compatibility, and transactional boundaries."""
import copy

import pytest

from jure.casefile import (
    ActionState, CaseStore, ClaimAuditRecord, ClueRecord, ContradictionRecord,
    EvidenceAuditRecord, EvidenceGap, EvidenceQuestion, EvidenceRecord,
    HypothesisAuditResult, HypothesisSynthesis, InvestigationRequest,
    MechanisticClaim, PatternRecord, PerHypothesisAudit, PredictionRecord,
    Provenance, RevisionConflict, RoutingDecision, ShiftEvidence, StopRecord,
    load_case, save_case, validate_case,
)
from jure.casefile.critic_models import CriticAudits
from jure.casefile.history import verify_history


def call(store, case, method, *args, actor="critic", **kwargs):
    return getattr(store, method)(case.metadata.case_id, *args,
                                  expected_revision=case.metadata.case_revision, actor=actor, **kwargs)


@pytest.fixture
def store_case(tmp_path):
    with CaseStore(tmp_path / "critic.sqlite") as store:
        case = store.create_case_from_clue(ClueRecord(
            clue_id="CLUE", perturbation="X", discovery_mode="reference_guided",
            source_schema_version="0.2.0", source_run_id="mock", source_artifact="mock.csv",
            pattern=PatternRecord(genes=("A", "B"), states=(1, 0), order=2, pattern_string="A+B-"),
            perturbation_shift=ShiftEvidence(control_frequency=.1, perturb_frequency=.2,
                                            delta_frequency=.1, control_count=10, perturb_count=20),
        ), case_id="CASE")
        case = call(store, case, "add_hypothesis", actor="explorer", hypothesis_id="H1",
                    title="Shared upstream", mechanism_statement="A shared upstream pathway may affect A and B.",
                    mechanism_type="shared_upstream")
        case = call(store, case, "add_prediction", PredictionRecord(
            prediction_id="P1", hypothesis_id="H1", hypothesis_revision_id=case.hypotheses[0].current_revision_id,
            statement="A common upstream path exists", expected_if_true="Shared paths are detected",
            weakened_if_observed="Well-covered network excludes shared paths"), actor="explorer")
        case = call(store, case, "add_evidence_question", EvidenceQuestion(
            question_id="Q1", question_text="Do shared upstream paths exist?",
            relevant_hypothesis_ids=("H1",), derived_from_prediction_ids=("P1",)), actor="explorer")
        case = call(store, case, "add_evidence_record", EvidenceRecord(
            evidence_id="E1", question_id="Q1", claim_tested="Common upstream path",
            result_summary="Synthetic network reports a path", source_type="grn",
            provenance=Provenance(source_id="fixture", tool="mock_network")), actor="investigator")
        yield store, case


def claim(case, **changes):
    values = dict(claim_id="CLAIM1", hypothesis_id="H1", hypothesis_revision_id=case.hypotheses[0].current_revision_id,
                  statement="A shared upstream pathway affects both genes", derived_from_prediction_ids=("P1",),
                  criticality_reason="Both targets are required to explain the full observed joint state.")
    values.update(changes)
    return MechanisticClaim(**values)


def add_audit(store, case):
    return call(store, case, "append_critic_records", claims=(claim(case),), evidence_gaps=(EvidenceGap(
        gap_id="GAP1", description="Direct perturbational validation is unavailable",
        related_hypotheses=("H1",), related_predictions=("P1",), related_claim_ids=("CLAIM1",),
        related_evidence_ids=("E1",), critical=True, resolvable_with_current_tools=True),),
        hypothesis_audits=(HypothesisAuditResult(case_id="CASE", overall_status="pass",
                                               per_hypothesis=(PerHypothesisAudit(hypothesis_id="H1"),),
                                               audit_summary="Testable architecture"),),
        evidence_audits=(EvidenceAuditRecord(evidence_id="E1", claim_ids=("CLAIM1",),
                                             critic_interpretation="Network connectivity is indirect evidence"),),
        claim_audits=(ClaimAuditRecord(claim_id="CLAIM1", status="partially_supported", evidence_ids=("E1",),
                                      supporting_evidence_ids=("E1",), gap_ids=("GAP1",), summary="Indirect support"),),
        hypothesis_syntheses=(HypothesisSynthesis(hypothesis_id="H1", status="partially_supported",
                                                 partial_claim_ids=("CLAIM1",), critical_gaps=("GAP1",), summary="Partial support"),),
        investigation_requests=(InvestigationRequest(target_claim_ids=("CLAIM1",), target_gap_ids=("GAP1",),
                                                     objective="Obtain relevant direct evidence", why_needed="Critical path remains unresolved"),),
    )


def test_typed_critic_graph_roundtrip_and_immutable_evidence(store_case, tmp_path):
    store, before = store_case
    case = add_audit(store, before)
    assert isinstance(case.critic_audits, CriticAudits)
    assert case.evidence_records == before.evidence_records
    assert case.clue == before.clue
    assert case.hypotheses == before.hypotheses
    assert case.investigation_history[:-1] == before.investigation_history
    for suffix in ("json", "yaml"):
        assert load_case(save_case(case, tmp_path / f"case.{suffix}")) == case
    verify_history(case)


def test_four_status_reevaluation_preserves_previous_states(store_case):
    store, case = store_case
    case = add_audit(store, case)
    old_history = case.investigation_history
    for round_number, status in enumerate(("insufficient", "partially_supported", "supported", "challenged"), 1):
        previous = case.hypotheses[0].status
        case = call(store, case, "update_hypothesis", "H1", status=status, reason="Reassessed current evidence",
                    claim_ids=("CLAIM1",), evidence_ids=("E1",), gap_ids=("GAP1",), critic_round=round_number)
        change = case.critic_audits.status_changes[-1]
        assert (change.previous_status, change.new_status) == (previous, status)
        assert change.critic_round == round_number
        assert case.hypotheses[0].status == status
    assert case.investigation_history[:len(old_history)] == old_history
    assert case.critic_audits.status_changes[0].previous_status == "proposed"
    verify_history(case)


def test_claim_status_and_gap_updates_are_traced(store_case):
    store, case = store_case
    case = add_audit(store, case)
    original_claim = case.mechanistic_claims[0]
    case = call(store, case, "update_mechanistic_claim_status", "CLAIM1", "supported", reason="Matched direct support")
    assert case.mechanistic_claims[0].statement == original_claim.statement
    assert case.mechanistic_claims[0].status == "supported"
    case = call(store, case, "update_evidence_gap", "GAP1", status="addressed", reason="Direct support now recorded")
    assert case.evidence_gaps[0].status == "addressed"
    assert case.evidence_gaps[0].related_claim_ids == ("CLAIM1",)
    with pytest.raises(ValueError):
        call(store, case, "update_mechanistic_claim_status", "CLAIM1", "proven")
    assert store.load_case("CASE") == case


@pytest.mark.parametrize("collection,fields", [
    ("claims", {"hypothesis_id": "H_missing", "statement": "A claim"}),
    ("claims", {"hypothesis_id": "H1", "hypothesis_revision_id": "HR_missing", "statement": "A claim"}),
    ("claims", {"hypothesis_id": "H1", "derived_from_prediction_ids": ["P_missing"], "statement": "A claim"}),
    ("evidence_audits", {"evidence_id": "E_missing", "critic_interpretation": "Unknown evidence"}),
    ("evidence_audits", {"evidence_id": "E1", "claim_ids": ["C_missing"], "critic_interpretation": "Unknown claim"}),
    ("claim_audits", {"claim_id": "C_missing", "status": "insufficient", "summary": "Unknown claim"}),
    ("hypothesis_syntheses", {"hypothesis_id": "H_missing", "status": "insufficient", "summary": "Unknown hypothesis"}),
    ("routing_decisions", {"route_to": "investigator", "reason_type": "evidence_missing", "reason_summary": "Missing gap", "related_gap_ids": ["G_missing"]}),
    ("revision_requests", {"reason": "Missing evidence", "evidence_that_triggered_reframe": ["E_missing"]}),
    ("investigation_requests", {"objective": "Fill gap", "why_needed": "Unknown gap", "target_gap_ids": ["G_missing"]}),
    ("evidence_gaps", {"description": "Missing claim", "related_claim_ids": ["C_missing"]}),
    ("evidence_gaps", {"description": "Missing evidence", "related_evidence_ids": ["E_missing"]}),
    ("contradictions", {"description": "Missing claim", "claim_ids": ["C_missing"]}),
    ("stop_records", {"stop_type": "evidence_limited", "stop_reason": "tool_limit", "critic_summary": "Limited", "final_hypothesis_states": {"H_missing": "insufficient"}}),
    ("progress_snapshots", {"critic_round": 1, "route": "investigator", "effective_evidence_ids": ["E_missing"]}),
])
def test_every_new_reference_is_checked_and_failed_batch_rolls_back(store_case, collection, fields):
    store, case = store_case
    with pytest.raises(ValueError):
        call(store, case, "append_critic_records", **{collection: [fields]})
    assert store.load_case("CASE") == case


def test_duplicate_ids_and_cross_hypothesis_claims_are_rejected(store_case):
    store, case = store_case
    with pytest.raises(ValueError, match="duplicate"):
        call(store, case, "append_critic_records", claims=(claim(case, claim_id="H1"),))
    case = call(store, case, "add_hypothesis", actor="explorer", hypothesis_id="H2", title="Composition",
                mechanism_statement="Cell-state composition may change", mechanism_type="composition")
    with pytest.raises(ValueError, match="own hypothesis"):
        call(store, case, "append_critic_records", claims=(claim(case, hypothesis_id="H2"),))


def test_critic_atomic_commit_and_stale_run_rollback(store_case):
    store, original = store_case
    with CaseStore() as staging:
        staging.import_case(original)
        case = add_audit(staging, original)
        case = call(staging, case, "append_history_event", action="CRITIC_STARTED", summary="Begin critic audit")
        case = call(staging, case, "update_hypothesis", "H1", status="partially_supported", reason="Indirect support", critic_round=1)
        case = call(staging, case, "set_action_state", ActionState(current_phase="evidence_needed", next_actor="investigator"))
        assert store.load_case("CASE") == original
        result = store.commit_critic_case("CASE", case, expected_revision=original.metadata.case_revision)
        assert result == store.load_case("CASE")
        with pytest.raises(RevisionConflict):
            store.commit_critic_case("CASE", case, expected_revision=original.metadata.case_revision)
        assert store.load_case("CASE") == result


@pytest.mark.parametrize("kind", ["clue", "hypothesis", "prediction", "evidence", "question", "actor", "audit", "claim", "metadata"])
def test_critic_commit_rejects_protected_writes_even_if_later_restored(store_case, kind):
    store, original = store_case
    with CaseStore() as staging:
        staging.import_case(original)
        case = add_audit(staging, original)
        if kind == "actor":
            forged = call(staging, case, "append_history_event", actor="explorer", summary="Wrong actor")
        else:
            saved = case.model_dump(mode="json")
            section = {"clue": "clue", "hypothesis": "hypotheses", "prediction": "hypotheses",
                       "evidence": "evidence_records", "question": "evidence_questions", "audit": "critic_audits",
                       "claim": "mechanistic_claims", "metadata": "metadata"}[kind]
            def forge(data):
                if kind == "clue": data[section]["source_run_id"] = "forged"
                elif kind == "hypothesis": data[section][0]["revisions"][0]["mechanism_statement"] = "Forged mechanism"
                elif kind == "prediction": data[section][0]["predictions"][0]["statement"] = "Forged prediction"
                elif kind == "evidence": data[section][0]["provenance"]["source_id"] = "forged"
                elif kind == "question": data[section][0]["question_text"] = "Forged question"
                elif kind == "audit": data[section]["hypothesis_audits"][0]["audit_summary"] = "Forged audit"
                elif kind == "claim": data[section][0]["statement"] = "Forged claim"
                elif kind == "metadata": data[section]["cell_context"] = "forged"
            action = "hypothesis.verdict_changed" if kind in {"hypothesis", "prediction"} else "critic.records_appended"
            forged = staging._mutate("CASE", expected_revision=case.metadata.case_revision, actor="critic",
                                      action=action, object_type="case", object_id="CASE", summary="Forged transition", change=forge)
            if kind != "metadata":
                forged = staging._mutate("CASE", expected_revision=forged.metadata.case_revision, actor="critic",
                                          action=action, object_type="case", object_id="CASE", summary="Restored snapshot",
                                          change=lambda data: data.update({section: saved[section]}))
        with pytest.raises(PermissionError):
            store.commit_critic_case("CASE", forged, expected_revision=original.metadata.case_revision)
    assert store.load_case("CASE") == original


def test_commit_write_failure_rolls_back_new_events(store_case, monkeypatch):
    store, case = store_case
    with CaseStore() as staging:
        staging.import_case(case)
        result = add_audit(staging, case)
    def fail(_):
        raise OSError("synthetic disk failure")
    monkeypatch.setattr(store, "_write_snapshot", fail)
    with pytest.raises(OSError):
        store.commit_critic_case("CASE", result, expected_revision=case.metadata.case_revision)
    assert store.load_case("CASE") == case


def test_pre_critic_snapshot_import_preserves_original_history(store_case, tmp_path):
    _, case = store_case
    data = case.model_dump(mode="json")
    def strip(value):
        if isinstance(value, dict):
            value.pop("mechanistic_claims", None)
            value.pop("critic_audits", None)
            for child in value.values(): strip(child)
        elif isinstance(value, list):
            for child in value: strip(child)
    strip(data)
    events = copy.deepcopy(data["investigation_history"])
    with CaseStore() as imported:
        original = imported.import_case(data)
        result = add_audit(imported, original)
        assert [e.model_dump(mode="json") for e in result.investigation_history[:len(events)]] == events
        verify_history(result)
        assert load_case(save_case(result, tmp_path / "legacy.json")) == result


def test_critic_cannot_fetch_evidence_create_hypothesis_or_select_question(store_case):
    store, case = store_case
    with pytest.raises(PermissionError):
        call(store, case, "add_evidence_record", case.evidence_records[0])
    with pytest.raises(PermissionError):
        call(store, case, "add_hypothesis", title="Invented", mechanism_statement="Invented", mechanism_type="invented")
    with pytest.raises(PermissionError):
        call(store, case, "set_action_state", ActionState(current_phase="evidence_in_progress", next_actor="investigator"))
    with pytest.raises(ValueError, match="uppercase"):
        call(store, case, "append_history_event", summary="Cannot spoof mutation", action="hypothesis.created")
    assert store.load_case("CASE") == case


def test_staged_verdict_without_matching_status_change_is_rejected(store_case):
    store, original = store_case
    with CaseStore() as staging:
        staging.import_case(original)
        def change(data):
            data["hypotheses"][0]["revisions"][0]["status"] = "supported"
        forged = staging._mutate("CASE", expected_revision=original.metadata.case_revision, actor="critic",
                                  action="hypothesis.verdict_changed", object_type="hypothesis", object_id="H1",
                                  summary="Unsupported verdict without structured lineage", change=change)
        with pytest.raises(PermissionError, match="matching structured status change"):
            store.commit_critic_case("CASE", forged, expected_revision=original.metadata.case_revision)
    assert store.load_case("CASE") == original
