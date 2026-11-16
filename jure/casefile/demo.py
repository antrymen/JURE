"""Deterministic record-entry example; no agents, tools, or scientific inference."""
import argparse
import json
from pathlib import Path

from . import (
    ActionState, CaseStore, EvidenceAssessment, EvidenceQuestion, EvidenceRecord,
    MechanisticQuestion, ObjectReference, PredictionRecord, Provenance,
    case_json_schema, clue_from_v02,
)


def run(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    # This is a supplied synthetic output row, not a discovery calculation.
    clue = clue_from_v02(
        dict(perturbation="synthetic_KO", reference_id="R7727ae6d4ba54f23", genes=["A", "B", "C"],
             states=[1, 0, 1], order=3, pattern_string="A+B-C+", control_frequency=0.2,
             perturb_frequency=0.125, delta_frequency=-0.075, control_count=400,
             perturb_count=250, support=400, reference_mfi=-5.5, validation_mfi=-5.4,
             p_value_shift=0.0001, q_value_shift=0.001, status="candidate_shift",
             bootstrap_delta_ci_low=-0.10, bootstrap_delta_ci_high=-0.05,
             delta_sign_stability=1.0, replication_status="not_available"),
        source_run_id="synthetic_example", source_artifact="synthetic://provided_shift_row",
    )
    with CaseStore(output / "case_store.sqlite") as store:
        case = store.create_case_from_clue(clue, cell_context="synthetic cells")
        case_id = case.metadata.case_id

        def command(method, *args, actor, **kwargs):
            nonlocal case
            case = method(case_id, *args, actor=actor,
                          expected_revision=case.metadata.case_revision, **kwargs)

        question = MechanisticQuestion(question_text="What might explain the synthetic state shift?",
                                       derived_from_clue_id=clue.clue_id)
        command(store.add_mechanistic_question, question, actor="explorer")
        command(store.add_hypothesis, actor="explorer", title="Shared regulator hypothesis",
                mechanism_statement="A shared upstream regulator may contribute to this pattern.",
                mechanism_type="shared_regulator",
                derived_from=(ObjectReference(object_type="mechanistic_question", object_id=question.question_id),))
        hypothesis = case.hypotheses[0]
        prediction = PredictionRecord(
            hypothesis_id=hypothesis.hypothesis_id, hypothesis_revision_id=hypothesis.current_revision_id,
            statement="A shared regulator should connect A, B, and C.",
            expected_if_true="Context-matched connections to all three genes.",
            weakened_if_observed="Adequate direct testing excludes a shared regulator.",
        )
        command(store.add_prediction, prediction, actor="explorer")
        evidence_question = EvidenceQuestion(
            question_text="Is there context-matched evidence for a shared regulator?",
            derived_from_prediction_ids=(prediction.prediction_id,),
            relevant_hypothesis_ids=(hypothesis.hypothesis_id,), suggested_evidence_type="network",
        )
        command(store.add_evidence_question, evidence_question, actor="explorer")
        command(store.mark_selected, evidence_question.question_id, actor="investigator")
        command(store.set_action_state, ActionState(current_phase="evidence_in_progress",
                next_actor="investigator", selected_question_id=evidence_question.question_id), actor="controller")
        evidence = EvidenceRecord(
            question_id=evidence_question.question_id, source_type="other",
            claim_tested=prediction.statement, result_summary="The supplied synthetic fixture contains no regulator data.",
            provenance=Provenance(source_id="synthetic_fixture"),
            limitations=("No actual network or literature query was performed.",),
            raw_result_reference="synthetic://fixture/no_regulator_data",
        )
        command(store.add_evidence_record, evidence, actor="investigator")
        command(store.add_evidence_assessment, EvidenceAssessment(
            evidence_id=evidence.evidence_id, hypothesis_id=hypothesis.hypothesis_id,
            hypothesis_revision_id=hypothesis.current_revision_id, prediction_id=prediction.prediction_id,
            relation="inconclusive", rationale="Missing regulator data neither supports nor challenges this hypothesis.",
        ), actor="critic")
        command(store.mark_unresolved, evidence_question.question_id, actor="investigator")
        command(store.set_action_state, ActionState(current_phase="stopped", next_actor="none",
                stop_reason="Synthetic record-entry example complete; scientific question remains unresolved."), actor="controller")
        paths = store.export_case(case_id, output / case_id)
        (output / "case_schema.json").write_text(json.dumps(case_json_schema(), indent=2) + "\n", encoding="utf-8")
    return case, paths


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="outputs/shared_case_file_demo")
    args = parser.parse_args()
    case, paths = run(args.output)
    print(f"{case.metadata.case_id}: revision {case.metadata.case_revision}")
    for name, path in paths.items():
        print(f"{name}: {path}")


if __name__ == "__main__":
    main()
