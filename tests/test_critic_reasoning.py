"""Fast scientific boundary tests for the tool-free reasoning components."""
from copy import deepcopy
import json

import pytest
from pydantic import ValidationError

from jure.agents.critic.backend import (
    JSONCriticBackend, MockCriticBackend, StopEvaluation, critic_output_json_schema,
)
from jure.agents.critic.evidence_audit import EvidenceAuditResult


@pytest.fixture
def context():
    context = {
        "case_id": "CASE_REASONING", "critic_round": 1,
        "clue": {"pattern": {"genes": ["A", "B", "C"]}},
        "hypotheses": [{"hypothesis_id": "H1", "current_revision_id": "R1",
                        "current_revision": {"mechanism_statement": "A→B is a candidate mechanism."}}],
        "predictions": [{"prediction_id": "P1", "hypothesis_id": "H1", "hypothesis_revision_id": "R1",
                         "statement": "A→B", "expected_if_true": "B decreases after A knockout.",
                         "weakened_if_observed": "A knockout leaves B unchanged.",
                         "discriminates_from_hypotheses": []}],
        "evidence_questions": [{"question_id": "Q1", "derived_from_prediction_ids": ["P1"]}],
        "evidence_assessments": [],
    }
    context.update(MockCriticBackend().decompose_claims(context))
    return context


def evidence(**changes):
    value = {
        "evidence_id": "E1", "question_id": "Q1", "claim_tested": "A→B",
        "result_summary": "A knockout decreases B.", "source_type": "literature",
        "directness": "direct", "context_match": "matched", "source_quality": "primary_experiment",
        "support_quality": "sufficient", "negative_evidence_type": "not_applicable",
        "provenance": {"source_id": "SYNTHETIC", "tool": "synthetic_fixture", "query": "A→B",
                       "source_uri": "mock://supplied/experiment", "parameters": {"sufficient_power": True}},
    }
    value.update(changes)
    return value


def audit(context, *records):
    context = deepcopy(context)
    context["evidence_records"] = list(records)
    return EvidenceAuditResult.model_validate(MockCriticBackend().audit_evidence(context))


def test_reference_link_alone_cannot_make_unrelated_experiment_relevant(context):
    result = audit(context, evidence(claim_tested="D→E", result_summary="D knockout decreases E."))
    assert result.evidence_audits[0].relevance == "irrelevant"
    assert result.claim_audits[0].status == "insufficient"


def test_indirect_grn_and_co_mentions_cannot_outvote_direct_null(context):
    weak = [evidence(evidence_id=f"E_WEAK_{i}", source_type="grn", directness="indirect",
                     source_quality="curated_database") for i in range(10)]
    direct_null = evidence(evidence_id="E_NULL", negative_evidence_type="explicit_null_result",
                           result_summary="A knockout has no measurable effect on B.")
    result = audit(context, *weak, direct_null)
    assert result.claim_audits[0].status == "challenged"
    assert result.claim_audits[0].challenging_evidence_ids == ("E_NULL",)
    assert result.contradictions


@pytest.mark.parametrize("power", [False, None])
def test_null_with_unestablished_power_is_not_strong_challenge(context, power):
    item = evidence(negative_evidence_type="explicit_null_result", result_summary="B was unchanged.")
    item["provenance"]["parameters"] = {"literature": {"sufficient_power": power}}
    result = audit(context, item)
    assert result.evidence_audits[0].support_quality_assessment == "limited"
    assert result.claim_audits[0].status == "insufficient"


def test_not_found_is_gap_even_with_adversarial_challenging_assessment(context):
    context["evidence_assessments"] = [{"evidence_id": "E1", "hypothesis_id": "H1",
        "hypothesis_revision_id": "R1", "prediction_id": "P1", "relation": "challenges"}]
    result = audit(context, evidence(negative_evidence_type="not_found", result_summary="No paper found."))
    assert result.claim_audits[0].status == "insufficient"
    assert not result.contradictions
    assert not result.claim_audits[0].challenging_evidence_ids


def test_context_mismatch_preserves_dependency_without_strong_challenge(context):
    result = audit(context, evidence(), evidence(evidence_id="E_OTHER_CONTEXT",
        context_match="mismatched", negative_evidence_type="explicit_null_result",
        result_summary="A knockout has no measurable effect on B in another cell model."))
    assert result.claim_audits[0].status == "partially_supported"
    assert result.contradictions[0].potential_context_dependency
    assert not result.contradictions[0].critical
    assert result.contradictions[0].context_difference


def test_question_ancestry_preserves_verification_lineage_and_handles_cycles(context):
    context["evidence_questions"] += [
        {"question_id": "Q2", "derived_from_prediction_ids": [], "derived_from_question_ids": ["Q1", "Q3"]},
        {"question_id": "Q3", "derived_from_prediction_ids": [], "derived_from_question_ids": ["Q2"]},
        {"question_id": "Q4", "derived_from_prediction_ids": [], "derived_from_evidence_ids": ["E_SEED"]},
    ]
    seed = evidence(evidence_id="E_SEED", source_type="grn", directness="indirect")
    result = audit(context, seed, evidence(evidence_id="E_FOLLOWUP", question_id="Q3"),
                    evidence(evidence_id="E_EVIDENCE_ANCESTOR", question_id="Q4"))
    assert result.claim_audits[0].status == "supported"
    assert set(result.claim_audits[0].supporting_evidence_ids) == {"E_SEED", "E_FOLLOWUP", "E_EVIDENCE_ANCESTOR"}


def test_association_does_not_become_regulatory_support_by_direct_label(context):
    result = audit(context, evidence(source_type="dataset", result_summary="A and B are associated."))
    assert result.evidence_audits[0].directness_assessment == "indirect"
    assert result.claim_audits[0].status != "supported"


def test_grn_overclaim_preserves_original_input(context):
    item = evidence(source_type="grn", result_summary="GRN shows A→B; therefore A causally regulates B.")
    before = deepcopy(item)
    result = audit(context, item)
    assert item == before
    assert result.evidence_audits[0].overclaim_detected
    assert result.evidence_audits[0].directness_assessment == "indirect"


def test_component_experiment_cannot_establish_abstract_shared_architecture(context):
    context["claims"][0]["statement"] = "A shared upstream regulator should connect A, B and C."
    context["claims"][0]["claim_type"] = "mechanistic_prediction"
    item = evidence(claim_tested=context["claims"][0]["statement"])
    item["provenance"]["parameters"] = {"literature": {"perturbed_entity": "X", "measured_entity": "B"}}
    result = audit(context, item)
    assert result.claim_audits[0].status == "insufficient"
    assert result.evidence_audits[0].relevance == "partial"


def test_explicit_empty_capabilities_differs_from_unknown(context):
    backend = MockCriticBackend()
    assert not backend.evaluate_stop(dict(context, available_capabilities=None))["no_further_queries"]
    assert backend.evaluate_stop(dict(context, available_capabilities=[]))["no_further_queries"]


def test_json_transport_receives_detached_closed_schema(context):
    requests = []
    def transport(request):
        requests.append(deepcopy(request))
        request["context"]["claims"].clear()
        return json.dumps({"reason": "Insufficient evidence."})
    value = JSONCriticBackend(transport).evaluate_stop(context)
    assert StopEvaluation.model_validate_json(value).reason
    assert context["claims"]
    assert requests[0]["strict_json"]
    for method in ("audit_hypotheses", "decompose_claims", "audit_evidence", "synthesize_hypothesis",
                   "attribute_failure", "decide_route", "evaluate_stop"):
        assert critic_output_json_schema(method)["additionalProperties"] is False
    with pytest.raises(ValidationError):
        StopEvaluation.model_validate({"reason": "test", "confidence": 0.9})


def test_mock_trace_determinism_and_override_exhaustion(context):
    backend = MockCriticBackend()
    assert backend.audit_evidence(context) == backend.audit_evidence(context)
    context["claims"].clear()
    assert backend.calls[0]["context"]["claims"]
    custom = MockCriticBackend(evaluate_stop=[{"reason": "one response"}])
    assert custom.evaluate_stop(context)["reason"] == "one response"
    with pytest.raises(RuntimeError, match="exhausted"):
        custom.evaluate_stop(context)


def test_c1_simple_paraphrases_and_missing_nondirect_alternative(context):
    variants = ("A regulates C.", "A controls C.", "C is affected by A.")
    context["hypotheses"] = [
        {"hypothesis_id": f"H{i}", "current_revision_id": f"R{i}",
         "current_revision": {"mechanism_statement": statement}}
        for i, statement in enumerate(variants, 1)]
    context["predictions"] = [
        {**context["predictions"][0], "prediction_id": f"P{i}", "hypothesis_id": f"H{i}",
         "hypothesis_revision_id": f"R{i}", "discriminates_from_hypotheses": [f"H{j}" for j in range(1, 4) if j != i]}
        for i in range(1, 4)]
    result = MockCriticBackend().audit_hypotheses(context)
    assert result["overall_status"] == "revision_required"
    assert result["coverage_issues"]
    assert all(item["distinctness"] == "fail" for item in result["per_hypothesis"])


def test_ungrounded_causal_assertion_is_not_licensed_by_the_clue(context):
    context["clue"]["perturbation"] = "X"
    context["hypotheses"][0]["current_revision"]["mechanism_statement"] = "Perturbation X activates A and C and represses B."
    result = MockCriticBackend().audit_hypotheses(context)
    assert result["overall_status"] == "revision_required"
    assert result["per_hypothesis"][0]["groundedness"] == "fail"
