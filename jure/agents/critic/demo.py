"""Offline mock cases: Explorer routing, Investigator routing, and both STOP types."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from jure.agents.explorer import MechanismExplorer, MockExplorerBackend
from jure.agents.explorer.demo import initial_output, synthetic_clue
from jure.agents.investigator import EvidenceInvestigator
from jure.casefile import CaseStore, EvidenceAssessment, EvidenceRecord, Provenance, save_case
from jure.tools.evidence import EvidenceToolRegistry, MockNetworkTool


def create_case(store):
    case = store.create_case_from_clue(synthetic_clue(), cell_context="K562", source_dataset="synthetic_dataset")
    result = MechanismExplorer(MockExplorerBackend([initial_output(case)])).run(store, case.metadata.case_id)
    if not result.success:
        raise RuntimeError("Explorer fixture failed: " + "; ".join(result.validation_errors))
    return store.load_case(case.metadata.case_id)


def add_synthetic_evidence(store, case, hypothesis_id="H1", *, relation="supports", evidence_id=None,
                           source_type="literature", directness="direct", context_match="matched",
                           support_quality="sufficient", source_quality="primary_experiment",
                           summary=None, claim_tested=None, negative_evidence_type="not_applicable",
                           complete_provenance=True, prediction_id=None):
    """Explicit supplied observations, never represented as a retrieved real paper."""
    hypothesis = next(h for h in case.hypotheses if h.hypothesis_id == hypothesis_id)
    prediction = next(p for p in hypothesis.predictions
                      if (p.prediction_id == prediction_id if prediction_id else
                          p.hypothesis_revision_id == hypothesis.current_revision_id))
    question = next(q for q in case.evidence_questions if prediction.prediction_id in q.derived_from_prediction_ids)
    evidence_id = evidence_id or f"E_SYNTHETIC_{len(case.evidence_records) + 1}"
    provenance = Provenance(source_id=f"synthetic_fixture_{evidence_id}",
        source_uri=f"mock://supplied/{evidence_id}" if complete_provenance else None,
        tool="synthetic_fixture" if complete_provenance else None,
        query=prediction.statement if complete_provenance else None,
        parameters={"synthetic": True, "biological_context": "K562"})
    record = EvidenceRecord(evidence_id=evidence_id, question_id=question.question_id,
        claim_tested=claim_tested or prediction.statement,
        result_summary=summary or ("Synthetic matched direct experiment supports the stated prediction."
                                  if relation == "supports" else
                                  "Synthetic adequately powered matched experiment contradicts the stated prediction."),
        source_type=source_type, directness=directness, context_match=context_match,
        source_quality=source_quality, support_quality=support_quality,
        negative_evidence_type=negative_evidence_type,
        limitations=("Manually supplied synthetic fixture; not a real biological finding.",),
        provenance=provenance, raw_result_reference=f"mock://supplied/{evidence_id}/raw" if complete_provenance else None)
    case = store.add_evidence_record(case.metadata.case_id, record, actor="investigator",
                                    expected_revision=case.metadata.case_revision)
    return store.add_evidence_assessment(case.metadata.case_id, EvidenceAssessment(
        evidence_id=evidence_id, hypothesis_id=hypothesis_id,
        hypothesis_revision_id=hypothesis.current_revision_id, prediction_id=prediction.prediction_id,
        relation=relation, rationale="Supplied synthetic observation directly tests this prediction."),
        actor="investigator", expected_revision=case.metadata.case_revision)


def sufficient_case(store, case):
    for hypothesis_id in ("H1", "H2", "H3"):
        case = add_synthetic_evidence(store, case, hypothesis_id,
                                     relation="supports" if hypothesis_id == "H1" else "challenges")
    return case


def run(output="outputs/mechanism_critic_demo"):
    from . import MechanismCritic, CriticConfig

    root = Path(output).resolve()
    root.mkdir(parents=True, exist_ok=True)
    summary = []
    for name in ("A_explorer", "B_investigator", "C1_sufficient", "C2_limited"):
        directory = root / name
        directory.mkdir(parents=True, exist_ok=True)
        with CaseStore(directory / "case_store.sqlite") as store:
            case = create_case(store)
            config = CriticConfig()
            capabilities = ("dataset", "network", "literature")
            if name == "A_explorer":
                # A malformed external revision has no current falsifiable prediction.
                case = store.update_hypothesis(case.metadata.case_id, "H2",
                    mechanism_statement="A regulates C in an unspecified way after perturbation X.",
                    weakening_conditions=(), reason="Synthetic malformed hypothesis revision for C1 audit.",
                    actor="explorer", expected_revision=case.metadata.case_revision)
            elif name == "B_investigator":
                acquisition = EvidenceInvestigator(registry=EvidenceToolRegistry([MockNetworkTool()])).run(
                    store, case.metadata.case_id, artifact_dir=directory / "acquisition")
                if not acquisition.success:
                    raise RuntimeError("Investigator demo failed: " + "; ".join(acquisition.validation_errors))
                case = store.load_case(case.metadata.case_id)
            elif name == "C1_sufficient":
                case = sufficient_case(store, case)
            else:
                case = add_synthetic_evidence(store, case, directness="indirect", source_type="grn",
                                               source_quality="curated_database", support_quality="limited")
                capabilities = ()
            save_case(case, directory / "input_case_file.json")
            result = MechanismCritic(config=config).run(store, case.metadata.case_id,
                run_id=f"CRITIC_DEMO_{name}", artifact_dir=directory, available_capabilities=capabilities)
            if not result.success:
                raise RuntimeError(f"{name} failed: " + "; ".join(result.validation_errors))
            after = store.load_case(case.metadata.case_id)
            save_case(after, directory / "updated_case_file.json")
            route = after.critic_audits.routing_decisions[-1].route_to
            expected = {"A_explorer": "explorer", "B_investigator": "investigator",
                        "C1_sufficient": "stop", "C2_limited": "stop"}[name]
            if route != expected:
                raise AssertionError(f"{name}: expected {expected}, observed {route}")
            stop_type = after.critic_audits.stop_records[-1].stop_type if route == "stop" else None
            if name.startswith("C"):
                wanted = "evidence_sufficient" if name == "C1_sufficient" else "evidence_limited"
                if stop_type != wanted:
                    raise AssertionError(f"{name}: expected {wanted}, observed {stop_type}")
            summary.append({"demo": name, "case_id": case.metadata.case_id, "route": route,
                            "stop_type": stop_type, "artifact_path": result.artifact_path,
                            "final_report_id": result.final_report_id})
    (root / "demo_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="outputs/mechanism_critic_demo")
    args = parser.parse_args()
    print(json.dumps(run(args.output), indent=2))


if __name__ == "__main__":
    main()
