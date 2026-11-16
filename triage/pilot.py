"""Deterministic pilot preparation. Stops before Explorer; has no Agent backend."""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import tempfile

from clue_discovery.integration.io import sha256, write_json, write_jsonl
from clue_discovery.schemas import SelectedCase
from jure.casefile import CaseStore, load_case, case_json_schema
from jure.casefile.selected_adapter import initialize_selected_case
from .pilot_sources import VerifiedPilotSource, require_equal

DEFAULT_SOURCE = "outputs/integration_tests/adapter_smoke/replogle_frozen"
DEFAULT_PROTOCOL = "configs/pilot_selection_v1.json"


def directional_support(case, shift):
    return shift.perturb_count if case.matched_effect > 0 else sum(b["nt_hits"] for b in shift.batch_support)


def eligibility(case, shift, protocol):
    gates = protocol["eligibility"]
    checks = {
        "condition_cells": shift.perturbation_n >= gates["min_condition_cells"],
        "abs_effect": abs(case.matched_effect) >= gates["min_abs_matched_effect"],
        "nt_per_batch": all(b["nt_n"] >= gates["min_nt_cells_per_occupied_batch"] for b in shift.batch_support),
        "effective_nt": shift.matched_nt_effective_n >= gates["min_effective_matched_nt"],
        "directional_support": directional_support(case, shift) >= gates["min_directional_support"],
        "holm": shift.selected_family_holm_exploratory <= gates["max_selected_family_holm_exploratory"],
        "evidence_level": case.evidence_level.value == gates["evidence_level"],
        "external_validation_status": case.external_validation_status == gates["external_validation_status"],
    }
    return [name for name, passed in checks.items() if not passed]


def structural_tier(case, relations, protocol):
    condition_relations = [relations[r] for r in case.signed_state_contrast_context + case.coresponse_context
                           if case.condition_id in relations[r].shared_candidate_conditions]
    present = {
        "signed_state_contrast": any(r.relation_type == "SIGNED_STATE_CONTRAST" for r in condition_relations),
        "gene_disjoint_correlated_context": any(r.relation_type == "GENE_DISJOINT_CORESPONSE" for r in condition_relations),
        "cross_module": "cross_module" in case.strata,
    }
    for i, tag in enumerate(protocol["slots"]["D"]["priority"]):
        if present[tag]:
            return i
    return None


def select_cases(cases, shifts, relations, protocol):
    """Pure greedy selection, independent of input row order and gene annotations."""
    if len({c.case_id for c in cases}) != len(cases):
        raise ValueError("duplicate case ID")
    eligible, candidate_audit = [], []
    tiers = {c.case_id: structural_tier(c, relations, protocol) for c in cases}
    for case in cases:
        rejected = eligibility(case, shifts[case.case_id], protocol)
        if not rejected:
            eligible.append(case)
        candidate_audit.append(dict(case_id=case.case_id, condition_id=case.condition_id,
            reference_id=case.reference_id, group_id=case.group_context["group_id"],
            matched_effect=case.matched_effect, condition_cells=shifts[case.case_id].perturbation_n,
            directional_support=directional_support(case, shifts[case.case_id]),
            eligible=not rejected, exclusions="|".join(rejected), structural_tier=tiers[case.case_id]))
    selected, trace = [], []
    for slot in protocol["slot_order"]:
        def in_slot(c):
            if slot == "A":
                return c.group_context["group_id"] in protocol["slots"]["A"]["groups"] and (
                    c.stable_core_context["status"] == "stable_core")
            if slot == "B":
                return c.matched_effect > 0
            if slot == "C":
                return c.matched_effect < 0
            return tiers[c.case_id] is not None

        def rank(c):
            shift = shifts[c.case_id]
            return ((tiers[c.case_id],) if slot == "D" else ()) + (
                -abs(c.matched_effect), -shift.perturbation_n, -directional_support(c, shift),
                c.condition_id, c.reference_id, c.case_id)

        ranked = sorted(filter(in_slot, eligible), key=rank)
        previous = [c for _, c in selected]
        winner, rows = None, []
        for i, case in enumerate(ranked, 1):
            duplicates = [field for field in ("condition_id", "reference_id", "sampling_block_id")
                          if any(getattr(case, field) == getattr(old, field) for old in previous)]
            if not duplicates and winner is None:
                winner = case
            rows.append(dict(rank=i, case_id=case.case_id, rank_key=rank(case),
                             blocked_by=duplicates, selected=case is winner))
        if winner is None:
            raise ValueError(f"FAIL_CLOSED: no eligible nonredundant candidate for slot {slot}")
        selected.append((slot, winner))
        trace.append(dict(slot=slot, category=protocol["slots"][slot]["category"],
                          eligible_before_dedup=len(ranked), selected_case_id=winner.case_id, ranking=rows))
    return selected, trace, sorted(candidate_audit, key=lambda r: r["case_id"])


def assert_initial(case):
    if case.metadata.case_revision != 1 or case.mechanistic_question is not None:
        raise ValueError("not a pristine initial case")
    for field in ("hypotheses", "evidence_questions", "evidence_records", "evidence_assessments",
                  "evidence_gaps", "contradictions", "mechanistic_claims"):
        if getattr(case, field):
            raise ValueError(f"investigation content forbidden: {field}")
    if any(case.critic_audits.model_dump().values()):
        raise ValueError("critic output forbidden")
    if case.action_state.model_dump() != dict(current_phase="clue_ready", next_actor="none",
                                             selected_question_id=None, stop_reason=None):
        raise ValueError("preparation must not route or scientifically stop a case")
    if len(case.investigation_history) != 1 or case.investigation_history[0].action != "case.created" or (
        case.investigation_history[0].actor != "controller"
    ):
        raise ValueError("only controller initialization is allowed")


def validate_protocol(protocol):
    # Free-text executable policies must not silently diverge from implementation.
    require_equal(protocol["protocol_id"], "jure_day6_four_case_pilot_v1", "supported protocol")
    require_equal(protocol["slot_order"], ["A", "B", "C", "D"], "slot priority")
    require_equal(protocol["ranking"], ["D_only:structural_priority_ascending", "abs(matched_effect)_descending",
        "condition_cells_descending", "directional_support_descending", "condition_id_ascending",
        "reference_id_ascending", "case_id_ascending"], "ranking operators")
    require_equal(protocol["deduplication"], ["different condition_id", "different reference_id (full signed state)",
        "different sampling_block_id"], "deduplication operators")
    require_equal(protocol["slots"]["A"]["membership"], "stable_core", "A membership")
    require_equal(protocol["slots"]["A"]["direction"], "either", "A direction")
    require_equal(protocol["slots"]["B"]["direction"], "enrichment", "B direction")
    require_equal(protocol["slots"]["C"]["direction"], "depletion", "C direction")
    if set(protocol["slots"]["D"]["priority"]) != {
        "signed_state_contrast", "gene_disjoint_correlated_context", "cross_module"
    } or len(protocol["slots"]["D"]["priority"]) != 3:
        raise ValueError("unsupported structural priorities")


def prepare(source_run, protocol_path, output):
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError(f"refusing to replace output: {output}")
    protocol_path = Path(protocol_path).resolve()
    protocol = json.loads(protocol_path.read_text())
    freeze_path = protocol_path.with_suffix(".freeze.json")
    freeze = json.loads(freeze_path.read_text())
    require_equal(sha256(protocol_path), freeze["protocol_sha256"], "frozen protocol")
    validate_protocol(protocol)
    started = datetime.now(timezone.utc).isoformat()
    if datetime.fromisoformat(freeze["frozen_at"]) >= datetime.fromisoformat(started):
        raise ValueError("protocol must be frozen before execution")
    repo = Path(__file__).resolve().parents[1]
    code_paths = sorted(set(Path(__file__).parent.glob("*.py")) | set((repo / "jure/casefile").glob("*.py")) |
                        {repo / "clue_discovery/schemas/__init__.py"})
    code_hashes = {str(p.relative_to(repo)): sha256(p) for p in code_paths}
    source = VerifiedPilotSource(source_run)
    require_equal(len(source.cases), protocol["expected_candidate_count"], "candidate count")
    require_equal(source.manifest["dataset_id"], protocol["dataset_id"], "protocol dataset")
    choices, trace, audit = select_cases(source.cases, source.shifts, source.relations, protocol)
    selected_at = datetime.now(timezone.utc).isoformat()
    source_lines = {c.case_id: i for i, c in enumerate(source.cases, 1)}
    selected_cases = [SelectedCase(case=c, selection_method="rule",
        selection_reason=f"Slot {slot}: {protocol['slots'][slot]['category']}; frozen deterministic ranking and deduplication.",
        selector=protocol["protocol_id"], selected_at=selected_at,
        selection_provenance={"slot": slot, "protocol_sha256": freeze["protocol_sha256"],
            "protocol_frozen_at": freeze["frozen_at"], "triage_path": str(source.triage_path),
            "triage_sha256": source.checked[str(source.triage_path)],
            "source_line": source_lines[c.case_id],
            "ranking_trace": f"selection_trace.json#slot={slot}"}) for slot, c in choices]
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".pilot-preparation-", dir=output.parent) as temp:
        stage = Path(temp) / "result"
        stage.mkdir()
        shutil.copyfile(protocol_path, stage / "protocol.json")
        shutil.copyfile(freeze_path, stage / "protocol.freeze.json")
        write_json(stage / "selection_trace.json", trace)
        write_jsonl(stage / "selected_cases.jsonl", selected_cases)
        with (stage / "candidate_eligibility.csv").open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(audit[0]))
            writer.writeheader(); writer.writerows(audit)
        summaries = []
        with CaseStore(stage / "case_store.sqlite") as store:
            for (slot, c), selected in zip(choices, selected_cases):
                case = initialize_selected_case(selected, verified_source=source, store=store)
                assert_initial(case)
                dest = stage / "initial_cases" / slot
                store.export_case(case.metadata.case_id, dest)
                write_json(dest / "selected_case.json", selected)
                require_equal(load_case(dest / "case_file.json"), case, "JSON round trip")
                require_equal(load_case(dest / "case_file.yaml"), case, "YAML round trip")
                shift = case.clue.perturbation_shift
                summaries.append(dict(slot=slot, case_id=c.case_id, condition=c.condition_id,
                    state=c.signed_pattern, group=c.group_context["group_id"],
                    core_status=c.stable_core_context["status"], nt_frequency=shift.control_frequency,
                    perturbation_hits=shift.perturb_count, perturbation_n=shift.perturbation_n,
                    perturbation_frequency=shift.perturb_frequency, delta_pp=100 * c.matched_effect,
                    evidence_level=c.evidence_level.value, day8_status="NOT_PERFORMED",
                    initial_case_file=f"initial_cases/{slot}/case_file.json"))
        write_json(stage / "case_schema.json", case_json_schema())
        write_json(stage / "initial_case_index.json", summaries)
        source.assert_unchanged()
        require_equal(sha256(protocol_path), freeze["protocol_sha256"], "protocol unchanged during preparation")
        for rel, checksum in code_hashes.items():
            require_equal(sha256(repo / rel), checksum, f"code changed during preparation: {rel}")
        integrity = {"status": "PASS", "verified_candidates": len(source.cases),
            "verified_source_files": source.checked, "source_files_unchanged": True,
            "checks": ["manifest and artifact hashes", "catalogue payload checksum", "source JSONL line identity",
                "full signed reference and qualification", "batch counts and matched estimand arithmetic",
                "group/core/relation references", "selection thresholds and deduplication",
                "JSON/YAML round trip and append-only audit replay", "revision 1 and empty reasoning state"],
            "raw_expression_recomputed": False, "statistical_tests_recomputed": False,
            "agent_calls": 0, "llm_calls": 0, "evidence_tool_calls": 0}
        write_json(stage / "integrity_audit.json", integrity)
        lines = ["# JURE 4-case pilot preparation", "", "Status: INITIAL_CASE_FILES_READY — preparation stops here.", "",
            "Protocol was frozen before pilot ranking, after Day6 results existed. This is not a prospective registration of discovery.", "",
            "| Slot | Condition | Signed state | Group | Perturbation support | Matched NT | Δ pp |",
            "|---|---|---|---|---|---|---|"]
        for s in summaries:
            lines.append(f"| {s['slot']} | {s['condition']} | {s['state']} | {s['group']} | "
                f"{s['perturbation_hits']}/{s['perturbation_n']} ({100*s['perturbation_frequency']:.2f}%) | "
                f"{100*s['nt_frequency']:.2f}% | {s['delta_pp']:+.2f} |")
        lines += ["", "All four retain EXPLORATORY_ASSOCIATION / DAY6_EXPLORATORY, Day8 NOT_PERFORMED.", "",
            "The authority is case_store.sqlite. Each initial_cases/A–D directory contains selected_case.json, "
            "case_file.json, case_file.yaml and case_history.jsonl. Each case has one controller initialization "
            "event, revision 1, clue_ready / next_actor none. Questions, hypotheses, predictions, Evidence Queue, "
            "EvidenceRecords, claims, Critic audits and final reports are empty.", "",
            "selection_trace.json records every slot ranking and duplicate exclusion; candidate_eligibility.csv "
            "accounts for the complete pool. integrity_audit.json records source hashes and checks.", "",
            "Re-running reproduces selected identities and factual content; wall-clock timestamps and audit event IDs are run-specific.", "",
            "Agent execution requires a separate explicit launch of the JURE system. No investigation or tool order was prepared here."]
        (stage / "PREPARATION_REPORT.md").write_text("\n".join(lines) + "\n")
        write_json(stage / "preparation_manifest.json", {
            "status": "INITIAL_CASE_FILES_READY", "protocol_id": protocol["protocol_id"],
            "protocol_sha256": freeze["protocol_sha256"], "started_at": started,
            "completed_at": datetime.now(timezone.utc).isoformat(), "selected_count": len(choices),
            "source_run": str(source.root), "source_pool_sha256": source.checked[str(source.triage_path)],
            "code_sha256": code_hashes, "agent_calls": 0, "llm_calls": 0, "evidence_tool_calls": 0,
            "stop_boundary": "PREPARATION_ONLY_NOT_A_CRITIC_STOP", "case_state": "clue_ready",
            "artifacts_sha256": {str(p.relative_to(stage)): sha256(p) for p in sorted(stage.rglob("*")) if p.is_file()}})
        stage.rename(output)
    return summaries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-run", default=DEFAULT_SOURCE)
    parser.add_argument("--protocol", default=DEFAULT_PROTOCOL)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.source_run, args.protocol, args.output), indent=2))


if __name__ == "__main__":
    main()
