"""Preparation integrity and contamination boundary; no reasoning backends run."""
from copy import deepcopy
import json
from pathlib import Path
import random

import pytest

from clue_discovery.schemas import SelectedCase
from jure.casefile import CaseStore, load_case, MatchedControlShiftEvidence
from jure.casefile.selected_adapter import clue_from_selected_case, initialize_selected_case
from triage.pilot import select_cases, assert_initial, prepare, validate_protocol
from triage.pilot_sources import VerifiedPilotSource, shift_from_source

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "outputs/integration_tests/adapter_smoke/replogle_frozen"
PROTOCOL = ROOT / "configs/pilot_selection_v1.json"


@pytest.fixture(scope="module")
def source():
    return VerifiedPilotSource(SOURCE)


@pytest.fixture(scope="module")
def protocol():
    return json.loads(PROTOCOL.read_text())


def selection(source, protocol):
    return select_cases(source.cases, source.shifts, source.relations, protocol)


def selected(source, case):
    return SelectedCase(case=case, selection_method="rule", selection_reason="deterministic fixture",
        selector="fixture", selected_at="2026-09-28T03:00:00+00:00",
        selection_provenance={"triage_sha256": source.checked[str(source.triage_path)]})


def test_shuffle_cannot_change_winners_or_trace(source, protocol):
    baseline = selection(source, protocol)
    shuffled = list(source.cases)
    random.Random(193).shuffle(shuffled)
    assert select_cases(shuffled, source.shifts, source.relations, protocol) == baseline
    choices, trace, audit = baseline
    assert len(audit) == 6129 and len(choices) == 4
    assert [s for s, _ in choices] == list("ABCD")
    for field in ("case_id", "condition_id", "reference_id", "sampling_block_id"):
        assert len({getattr(c, field) for _, c in choices}) == 4
    assert choices[0][1].group_context["group_id"] in ("M02", "M03", "M04")
    assert choices[0][1].stable_core_context["status"] == "stable_core"
    assert choices[1][1].matched_effect > 0 > choices[2][1].matched_effect
    assert all(sum(row["selected"] for row in slot["ranking"]) == 1 for slot in trace)


def test_no_depletion_fails_without_fallback(source, protocol):
    with pytest.raises(ValueError, match="FAIL_CLOSED.*slot C"):
        select_cases([c for c in source.cases if c.matched_effect > 0], source.shifts, source.relations, protocol)


def test_duplicate_id_is_rejected(source, protocol):
    with pytest.raises(ValueError, match="duplicate"):
        select_cases(source.cases + [source.cases[0]], source.shifts, source.relations, protocol)


def test_structural_priority_precedes_effect_and_requires_shared_condition(source, protocol):
    choices, trace, _ = selection(source, protocol)
    d = choices[-1][1]
    rels = source.case_relations(d)
    assert any(r.relation_type == "SIGNED_STATE_CONTRAST" for r in rels)
    assert trace[-1]["ranking"][0]["rank_key"][0] == 0
    # Removing a relation's shared-condition membership must remove that tier.
    from triage.pilot import structural_tier
    altered = {key: rel.model_copy(update={"shared_candidate_conditions": []})
               for key, rel in source.relations.items()}
    tier = structural_tier(d, altered, protocol)
    assert tier is None or tier == 2  # only a pre-existing cross-module tag can remain


def test_lexical_ties_and_overlap_are_deterministic(source, protocol):
    choices, _, _ = selection(source, protocol)
    cases = [c for _, c in choices]
    a = cases[0]
    # A new condition with identical selection metrics competes in A, not by row order.
    duplicate = a.model_copy(update={"case_id": "fixture_AAA", "condition_id": "AAA",
                                    "sampling_block_id": "AAA|M02|enrichment"})
    shifts = dict(source.shifts, fixture_AAA=source.shifts[a.case_id])
    winners, _, _ = select_cases(cases + [duplicate], shifts, source.relations, protocol)
    assert winners[0][1].case_id == "fixture_AAA"
    assert all(c.reference_id != a.reference_id for _, c in winners[1:])


def test_adapter_preserves_matched_statistics_and_empty_state(source, protocol, tmp_path):
    choices, _, _ = selection(source, protocol)
    with CaseStore(tmp_path / "cases.sqlite") as store:
        for slot, c in choices:
            case = initialize_selected_case(selected(source, c), verified_source=source, store=store)
            assert_initial(case)
            shift = case.clue.perturbation_shift
            raw = source.raw_records[c.case_id]
            assert isinstance(shift, MatchedControlShiftEvidence)
            assert shift.control_frequency == raw["matched_nt_frequency"]
            assert shift.control_count == raw["pooled_nt_hits"]
            assert shift.q_value_shift is None and shift.bootstrap is None and shift.support is None
            assert shift.selected_family_holm_exploratory == raw["selected_family_holm_exploratory"]
            assert shift.ci_method == raw["ci_method"]
            assert [b.to_dict() for b in shift.batch_support] == raw["batch_support"]
            assert case.clue.upstream_context["day8_status"] == "NOT_PERFORMED"
            assert case.clue.upstream_context["reference_evidence"] == source.references[c.reference_id].model_dump(mode="json")
            assert case.clue.source_payload["selected_case"]["case"] == c.model_dump(mode="json")
            store.export_case(c.case_id, tmp_path / slot)
            assert load_case(tmp_path / slot / "case_file.json") == case
            assert load_case(tmp_path / slot / "case_file.yaml") == case
            assert isinstance(load_case(tmp_path / slot / "case_file.json").clue.perturbation_shift,
                              MatchedControlShiftEvidence)


@pytest.mark.parametrize("field,value", [("target", "OTHER"), ("delta", .99), ("family_size", 1)])
def test_changed_source_identity_or_evidence_rejected(source, field, value):
    c = source.cases[0]
    raw = deepcopy(source.raw_records[c.case_id]); raw[field] = value
    with pytest.raises(ValueError, match="source mismatch"):
        shift_from_source(c, raw)


def test_invalid_batch_arithmetic_and_semantic_relabeling_rejected(source):
    shift = source.shifts[source.cases[0].case_id].model_dump(mode="json")
    shift["batch_support"][0]["perturbation_hits"] += 1
    with pytest.raises(ValueError, match="totals"):
        MatchedControlShiftEvidence.model_validate(shift)
    shift = source.shifts[source.cases[0].case_id].model_dump(mode="json")
    shift["q_value_shift"] = shift["selected_family_holm_exploratory"]
    with pytest.raises(ValueError, match="q-value"):
        MatchedControlShiftEvidence.model_validate(shift)


def test_selected_case_cannot_change_verified_input(source):
    c = source.cases[0].model_copy(update={"matched_effect": .123})
    with pytest.raises(ValueError, match="verified source"):
        clue_from_selected_case(selected(source, c), verified_source=source)


def test_hash_mismatch_and_unsupported_rule_are_rejected(source, protocol, tmp_path):
    p = tmp_path / "bad.txt"; p.write_text("changed")
    with pytest.raises(ValueError, match="SHA256"):
        source.check_file(p, "0" * 64)
    changed = deepcopy(protocol); changed["ranking"].reverse()
    with pytest.raises(ValueError, match="ranking operators"):
        validate_protocol(changed)


def test_end_to_end_publication_and_no_overwrite(tmp_path):
    output = tmp_path / "prepared"
    rows = prepare(SOURCE, PROTOCOL, output)
    assert len(rows) == 4
    for row in rows:
        assert_initial(load_case(output / row["initial_case_file"]))
    manifest = json.loads((output / "preparation_manifest.json").read_text())
    assert manifest["agent_calls"] == manifest["llm_calls"] == manifest["evidence_tool_calls"] == 0
    with pytest.raises(FileExistsError):
        prepare(SOURCE, PROTOCOL, output)
    # Changing the frozen file is rejected before ranking or publication.
    p = tmp_path / "changed.json"; p.write_text(PROTOCOL.read_text() + " ")
    p.with_suffix(".freeze.json").write_text(PROTOCOL.with_suffix(".freeze.json").read_text())
    with pytest.raises(ValueError, match="frozen protocol"):
        prepare(SOURCE, p, tmp_path / "must_not_exist")
    assert not (tmp_path / "must_not_exist").exists()
