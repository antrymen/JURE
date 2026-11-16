"""Offline synthetic Mechanism Explorer example; no evidence is acquired."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from jure.casefile import (
    BootstrapSummary, CaseFile, CaseStore, ClueRecord, PatternRecord,
    ReferenceEvidence, ShiftEvidence, StatisticalEvidence,
)


def synthetic_clue() -> ClueRecord:
    """A supplied synthetic observation, not a Clue Discovery computation."""
    return ClueRecord(
        clue_id="CLUE_SYNTHETIC_EXPLORER", perturbation="X",
        discovery_mode="reference_guided", source_schema_version="0.2.0",
        source_run_id="synthetic_explorer_example",
        source_artifact="synthetic://provided_clue",
        reference_id="REF_SYNTHETIC",
        pattern=PatternRecord(genes=("A", "B", "C"), states=(1, 0, 1),
                              order=3, pattern_string="A+B-C+"),
        reference_evidence=ReferenceEvidence(
            discovery=StatisticalEvidence(
                mfi=0.9, q_value_null=0.001,
                bootstrap=BootstrapSummary(ci_low=0.7, ci_high=1.1, sign_stability=0.99),
            ),
            validation=StatisticalEvidence(mfi=0.85, q_value_null=0.002),
        ),
        perturbation_shift=ShiftEvidence(
            control_frequency=0.08, perturb_frequency=0.31, delta_frequency=0.23,
            control_count=80, perturb_count=310, support=310,
            p_value_shift=0.0001, q_value_shift=0.001, status="candidate_shift",
            bootstrap=BootstrapSummary(ci_low=0.19, ci_high=0.27, sign_stability=1.0),
        ),
        replication_status="not_available",
        source_payload={"synthetic": True, "higher_order_evidence": "stable",
                        "state_definition": "+ = detected; - = undetected"},
    )


def initial_output(case: CaseFile) -> dict:
    """A deterministic fixture for this synthetic A/B/C clue only.

    These are manually supplied competing possibilities. They are not a
    universal hypothesis template for the Explorer or an evidence result.
    """
    from .validation import interpret_observation

    if case.clue.pattern.genes != ("A", "B", "C") or case.clue.perturbation != "X":
        raise ValueError("the example output is specific to the synthetic A/B/C clue")
    hypotheses = [
        {
            "hypothesis_id": "H1", "title": "Shared upstream mechanism",
            "mechanism_type": "shared_upstream",
            "mechanism_statement": (
                "A shared upstream regulator or pathway may mediate the change in the "
                "prevalence of A+B-C+ after perturbation X in K562 cells."
            ),
            "assumptions": ["A context-relevant shared upstream process is possible."],
            "unresolved_points": ["The upstream regulator or pathway remains unidentified."],
            "weakening_conditions": [
                "Adequate context-matched tests exclude shared upstream connectivity while "
                "supporting a sequential cascade."
            ],
            "structure": {
                "causal_structure": "shared_upstream", "directness": "indirect",
                "cell_state_explanation": False, "conditional_dependence": False,
                "directed_edges": [],
            },
        },
        {
            "hypothesis_id": "H2", "title": "Sequential cascade possibility",
            "mechanism_type": "sequential_cascade",
            "mechanism_statement": (
                "A sequential cascade connecting A to B and B to C could mediate the "
                "change in A+B-C+ prevalence after perturbation X in K562 cells. "
                "These directed steps are untested possibilities."
            ),
            "assumptions": ["The A to B and B to C steps are hypothetical and untested in this cell context."],
            "unresolved_points": ["The direction, sign and existence of each step need evidence."],
            "weakening_conditions": [
                "Adequate direct tests exclude the proposed intermediate steps while "
                "a shared upstream mechanism accounts for the response."
            ],
            "structure": {
                "causal_structure": "sequential_cascade", "directness": "direct",
                "cell_state_explanation": False, "conditional_dependence": False,
                "directed_edges": [["A", "B"], ["B", "C"]],
            },
        },
        {
            "hypothesis_id": "H3", "title": "Cell-state composition explanation",
            "mechanism_type": "cell_state_composition",
            "mechanism_statement": (
                "Perturbation X may change the proportions of pre-existing K562 cell states "
                "with different A+B-C+ prevalence, without requiring direct regulation "
                "between A, B and C."
            ),
            "assumptions": ["Relevant cell states can be defined independently of this pattern."],
            "unresolved_points": ["The relevant cell-state program remains unidentified."],
            "weakening_conditions": [
                "The joint-state frequency shift persists within adequately measured cell "
                "states after matching their proportions."
            ],
            "structure": {
                "causal_structure": "cell_state_composition", "directness": "indirect",
                "cell_state_explanation": True, "conditional_dependence": False,
                "directed_edges": [],
            },
        },
    ]
    for hypothesis in hypotheses:
        hypothesis.update(derived_from_clue_id=case.clue.clue_id, status="proposed")

    predictions = [
        {
            "prediction_id": "P1", "hypothesis_id": "H1",
            "statement": "A shared upstream regulator or pathway should connect A, B and C.",
            "expected_if_true": "Context-matched network or experimental evidence should support shared upstream connectivity.",
            "weakened_if_observed": "Adequate tests exclude shared connectivity while supporting the proposed sequential cascade.",
            "discriminates_from_hypotheses": ["H2", "H3"],
        },
        {
            "prediction_id": "P2", "hypothesis_id": "H2",
            "statement": "Perturbational evidence should support directed regulatory steps from A to B and from B to C.",
            "expected_if_true": "Perturbing the proposed intermediate B should alter the C response in the relevant context.",
            "weakened_if_observed": "Adequate tests exclude these directed steps while supporting shared upstream connectivity.",
            "discriminates_from_hypotheses": ["H1", "H3"],
        },
        {
            "prediction_id": "P3", "hypothesis_id": "H3",
            "statement": "The A+B-C+ frequency shift should diminish after matching cell-state proportions.",
            "expected_if_true": "Within matched cell states, the conditional joint-state frequency should remain similar across perturbation X and controls.",
            "weakened_if_observed": "The shift persists within measured cell states after matching their proportions.",
            "discriminates_from_hypotheses": ["H1", "H2"],
        },
    ]
    questions = [
        {
            "question_id": "Q1",
            "question_text": "Is there context-matched evidence for a shared upstream regulator or pathway connecting A, B and C, as opposed to a sequential cascade?",
            "derived_from_prediction_ids": ["P1"], "relevant_hypothesis_ids": ["H1", "H2"],
            "discriminates_between": ["H1", "H2"], "suggested_evidence_type": "network",
        },
        {
            "question_id": "Q2",
            "question_text": "Is there perturbational or regulatory evidence supporting the proposed steps from A to B and B to C in K562 cells?",
            "derived_from_prediction_ids": ["P2"], "relevant_hypothesis_ids": ["H2", "H1"],
            "discriminates_between": ["H2", "H1"], "suggested_evidence_type": "literature",
        },
        {
            "question_id": "Q3",
            "question_text": "Does the A+B-C+ frequency shift persist after matching the cell-state proportions across perturbation X and controls?",
            "derived_from_prediction_ids": ["P3"], "relevant_hypothesis_ids": ["H3", "H1", "H2"],
            "discriminates_between": ["H3", "H1", "H2"], "suggested_evidence_type": "dataset",
        },
    ]
    return {
        "observation_interpretation": interpret_observation(case),
        "mechanistic_question": (
            "Which regulatory or cellular mechanism could explain why perturbation X "
            "changes the prevalence of the joint expression state A+B-C+ in K562 cells?"
        ),
        "hypotheses": hypotheses, "predictions": predictions, "evidence_questions": questions,
        "contrasts": [
            {"hypothesis_a": "H1", "hypothesis_b": "H2",
             "difference": "Shared upstream connectivity versus a sequential directed cascade."},
            {"hypothesis_a": "H1", "hypothesis_b": "H3",
             "difference": "Within-cell upstream regulation versus a change in cell-state proportions."},
            {"hypothesis_a": "H2", "hypothesis_b": "H3",
             "difference": "Directed regulation between genes versus cell-state composition without those edges."},
        ],
    }


def run(output: str | Path):
    from .agent import MechanismExplorer
    from .backend import MockExplorerBackend

    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    with CaseStore(output / "case_store.sqlite") as store:
        case = store.create_case_from_clue(synthetic_clue(), cell_context="K562")
        result = MechanismExplorer(MockExplorerBackend([initial_output(case)])).run(
            store, case.metadata.case_id, artifact_dir=output / "runs",
        )
        if not result.success:
            raise RuntimeError("Explorer demo failed: " + "; ".join(result.validation_errors))
        paths = store.export_case(case.metadata.case_id, output / case.metadata.case_id)
        (output / "explorer_result.json").write_text(
            json.dumps(result.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8",
        )
        return result, paths


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="outputs/mechanism_explorer_demo")
    args = parser.parse_args()
    result, paths = run(args.output)
    print(f"{result.case_id}: {len(result.created_hypothesis_ids)} proposed hypotheses; evidence_needed")
    for name, path in paths.items():
        print(f"{name}: {path}")
    print(f"explorer artifact: {result.artifact_path}")


if __name__ == "__main__":
    main()
