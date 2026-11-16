"""Three offline cases proving dynamic dataset/network/literature selection."""
import argparse
import json
from pathlib import Path

from jure.agents.explorer import MechanismExplorer, MockExplorerBackend
from jure.agents.explorer.demo import initial_output, synthetic_clue
from jure.casefile import CaseStore, load_case, save_case
from jure.casefile.store import _atomic_write
from jure.tools.evidence import EvidenceToolRegistry, MockDatasetTool, MockLiteratureTool, MockNetworkTool

from .agent import EvidenceInvestigator


def mock_registry():
    return EvidenceToolRegistry([MockDatasetTool(), MockNetworkTool(), MockLiteratureTool()])


def create_explored_case(store, variant="network"):
    case = store.create_case_from_clue(synthetic_clue(), cell_context="K562", source_dataset="synthetic_dataset")
    proposal = initial_output(case)
    if variant == "dataset":
        # A separate synthetic cell-state prediction, supplied to Explorer before
        # investigation. The Investigator never rewrites a prediction or question.
        prediction = proposal["predictions"][2]
        prediction.update(
            statement="C expression state should vary with the cell state indicated by B in the observed dataset.",
            expected_if_true="Observed C frequencies should differ between detected and undetected B cell states.",
            weakened_if_observed="With adequate support, C+ frequencies remain similar across B states.")
        proposal["evidence_questions"][2]["question_text"] = "Does B state alter C response in the observed dataset?"
    result = MechanismExplorer(MockExplorerBackend([proposal])).run(store, case.metadata.case_id)
    if not result.success:
        raise RuntimeError("Synthetic Explorer setup failed: " + "; ".join(result.validation_errors))
    return store.load_case(case.metadata.case_id)


def export_demo(store, case_id, directory):
    case = store.load_case(case_id)
    save_case(case, directory / "updated_case_file.json")
    history = "".join(e.model_dump_json() + "\n" for e in case.investigation_history)
    # A complete read-only view of the immutable authoritative history.
    _atomic_write(directory / "investigator_history.jsonl", history)
    if load_case(directory / "updated_case_file.json") != case:
        raise AssertionError("Case File round-trip changed the investigation")
    return case


def run(output="outputs/evidence_investigator_demo", *, input_case=None, variant="all"):
    root = Path(output).resolve()
    root.mkdir(parents=True, exist_ok=True)
    variants = ["input"] if input_case else (["network", "dataset", "literature"] if variant == "all" else [variant])
    summary = []
    for family in variants:
        directory = root if family == "input" else root / f"{family}_first"
        directory.mkdir(parents=True, exist_ok=True)
        with CaseStore(directory / "case_store.sqlite") as store:
            if input_case:
                case = store.import_case(load_case(input_case))
            else:
                case = create_explored_case(store, family)
            investigator = EvidenceInvestigator(registry=mock_registry())
            if family == "literature":
                seed = investigator.run(store, case.metadata.case_id, artifact_dir=directory / "network_seed")
                if not seed.success:
                    raise RuntimeError("Network seed failed: " + "; ".join(seed.validation_errors))
                case = store.load_case(case.metadata.case_id)
            save_case(case, directory / "input_case_file.json")
            result = investigator.run(store, case.metadata.case_id, artifact_dir=directory)
            if not result.success:
                raise RuntimeError("Investigator demo failed: " + "; ".join(result.validation_errors))
            after = export_demo(store, case.metadata.case_id, directory)
            actual = result.tool_calls[0]["tool_id"] if result.tool_calls else None
            if family != "input" and actual != f"mock_{family}":
                raise AssertionError(f"Expected {family}-first acquisition, observed {actual}")
            summary.append({"variant": family, "case_id": case.metadata.case_id,
                            "selected_question_id": result.selected_question_id, "first_tool": actual,
                            "evidence_records_created": len(result.created_evidence_ids),
                            "followup_questions_created": len(result.created_followup_question_ids),
                            "question_final_status": result.question_final_status,
                            "next_actor": after.action_state.next_actor,
                            "run_artifact": result.artifact_path, "round_trip_verified": True})
    _atomic_write(root / "demo_summary.json", json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="outputs/evidence_investigator_demo")
    parser.add_argument("--input-case", help="Existing Explorer-populated JSON/YAML Case File")
    parser.add_argument("--variant", choices=("all", "network", "dataset", "literature"), default="all")
    args = parser.parse_args()
    print(json.dumps(run(args.output, input_case=args.input_case, variant=args.variant), indent=2))


if __name__ == "__main__":
    main()
