"""Evidence-tool contracts protect empirical support and source provenance."""
import pandas as pd
import pytest
from pydantic import ValidationError

from clue_discovery.patterns import JointPattern
from clue_discovery.statistics import pattern_frequency, pattern_shift
from jure.tools.evidence import (
    EvidenceTool, EvidenceToolRegistry, MockDatasetTool, MockLiteratureTool,
    MockNetworkTool, RetrievedItem, ToolMetadata, VerifiedEvidenceCandidate,
)
from jure.tools.evidence.network import NETWORK_LIMITATION


def execute(tool, operation, **inputs):
    return EvidenceToolRegistry([tool]).execute(tool.metadata.tool_id, operation, inputs)


def binary_cells():
    return pd.DataFrame([{"B": b, "C": c, "A": a}
                         for a, b, c in [(1, 1, 1)] * 6 + [(1, 1, 0)] * 2
                         + [(1, 0, 1)] * 2 + [(1, 0, 0)] * 6])


def test_conditional_counts_uncertainty_and_configurable_support():
    tool = MockDatasetTool(binary_cells())
    result = execute(tool, "conditional_frequency", target_gene="C", conditions={"B": 1})
    assert result.status == "insufficient_data"
    assert result.payload["numerator"] == 6
    assert result.payload["denominator"] == result.payload["support"] == 8
    assert result.payload["probability"] == .75
    assert result.payload["uncertainty"]["lower"] < .75 < result.payload["uncertainty"]["upper"]
    assert result.warnings
    sufficient = execute(tool, "conditional_frequency", target_state={"C": 1},
                         conditions={"B": 1}, min_conditional_support=8)
    assert sufficient.status == "success"
    assert sufficient.payload["support_quality"] == "sufficient"
    assert sufficient.payload["n_cells"] == 8
    assert sufficient.parameters["min_conditional_support"] == 8
    assert result.completed_at >= result.started_at


def test_zero_support_is_not_a_precise_zero_probability():
    result = execute(MockDatasetTool(binary_cells()), "conditional_frequency",
                     target_gene="C", conditions={"A": 0})
    assert result.status == "insufficient_data"
    assert result.payload["probability"] is None
    assert result.payload["denominator"] == 0
    assert result.payload["uncertainty"]["lower"] is None


def test_conditional_comparison_counts_match_data_and_low_support_suppresses_test():
    tool = MockDatasetTool(binary_cells(), min_conditional_support=8)
    result = execute(tool, "compare_conditional_frequency", target_gene="C", conditioning_gene="B")
    assert result.status == "success"
    assert result.payload["contingency_table"] == [[6, 2], [2, 6]]
    assert result.payload["difference"] == .5
    assert result.payload["group_positive"]["denominator"] == 8
    assert 0 <= result.payload["fisher_p_value"] <= 1
    insufficient = execute(tool, "compare_conditional_frequency", target_state={"C": 1},
                           condition_a={"B": 1}, condition_b={"B": 0}, min_conditional_support=9)
    assert insufficient.status == "insufficient_data"
    assert insufficient.payload["fisher_p_value"] is None


def test_overlapping_groups_do_not_receive_independent_group_inference():
    result = execute(MockDatasetTool(binary_cells(), min_conditional_support=2),
                     "compare_conditional_frequency", target_gene="C",
                     condition_a={"A": 1}, condition_b={"B": 1})
    assert result.status == "success"
    assert result.payload["fisher_p_value"] is None
    assert result.payload["uncertainty"]["lower"] is None
    assert any("overlap" in warning for warning in result.warnings)


def test_joint_frequency_reuses_clue_statistics_and_input_is_detached():
    data = binary_cells()
    tool = MockDatasetTool(data, min_conditional_support=2)
    pattern = JointPattern(("B", "C"), (1, 1))
    expected = pattern_frequency(data, pattern)
    data.loc[:, "C"] = 0
    result = execute(tool, "joint_frequency", pattern={"B": 1, "C": 1})
    assert result.status == "success"
    assert result.payload["probability"] == expected.frequency
    assert result.payload["numerator"] == expected.cell_count
    assert all(result.payload[field] for field in ("dataset_version", "code_version", "statistical_method"))


def test_pattern_shift_matches_existing_clue_statistics():
    data = binary_cells()
    control, perturbation = data.iloc[:8].copy(), data.iloc[8:].copy()
    control["condition"], perturbation["condition"] = "control", "perturbation"
    tool = MockDatasetTool(pd.concat([control, perturbation]), min_conditional_support=4)
    result = execute(tool, "compare_pattern_between_conditions", pattern={"C": 1})
    expected = pattern_shift(control, perturbation, JointPattern(("C",), (1,)))
    assert result.status == "success"
    assert result.payload["difference"] == expected["delta_frequency"]
    assert result.payload["fisher_p_value"] == expected["p_value_shift"]
    assert result.payload["control"]["numerator"] == 6
    assert result.payload["perturbation"]["numerator"] == 2


@pytest.mark.parametrize("inputs", [
    {"target_gene": "C", "conditions": {"UNKNOWN": 1}},
    {"target_gene": "C", "conditions": {"C": 1}},
    {"target_gene": "C", "conditions": {"B": .5}},
    {"target_gene": "C", "min_conditional_support": 0},
])
def test_invalid_statistical_queries_fail_without_an_estimate(inputs):
    result = EvidenceToolRegistry([MockDatasetTool()]).execute("mock_dataset", "conditional_frequency", inputs)
    assert result.status == "failed"
    assert not result.payload


def test_network_edges_keep_provenance_and_no_causal_upgrade():
    result = execute(MockNetworkTool(), "query_shared_regulators", target_genes=["A", "B", "C"], context="K562")
    assert result.status == "success"
    assert result.payload["candidate_regulators"] == ["X"]
    assert NETWORK_LIMITATION in result.payload["limitations"]
    assert len(result.payload["edges"]) == 3
    for edge in result.payload["edges"]:
        assert edge["network_name"] == "synthetic_grn"
        assert edge["network_version"] == "0.1"
        assert edge["direction"] == "source_to_target"
        assert edge["source_reference"].startswith("mock://")
        assert edge["query_parameters"]["target_genes"] == ["A", "B", "C"]


def test_network_path_hop_limit_and_direction_are_respected():
    tool = MockNetworkTool(edges=[{"source_gene": "A", "target_gene": "B"},
                                  {"source_gene": "B", "target_gene": "C"}])
    no_path = execute(tool, "query_paths", source_gene="A", target_gene="C", max_hops=1)
    assert no_path.status == "no_result"
    result = execute(tool, "query_paths", source_gene="A", target_gene="C", max_hops=2)
    assert result.status == "success"
    assert result.payload["paths"][0]["nodes"] == ["A", "B", "C"]
    assert execute(tool, "query_paths", source_gene="C", target_gene="A").status == "no_result"


def test_no_network_result_is_absence_of_retrieved_evidence():
    result = execute(MockNetworkTool(edges=[]), "query_edge", source_gene="A", target_gene="B")
    assert result.status == "no_result"
    assert any("not evidence against" in warning for warning in result.warnings)


def test_undirected_connectivity_cannot_become_an_upstream_regulator():
    tool = MockNetworkTool(edges=[{"source_gene": "X", "target_gene": target, "direction": "undirected"}
                                  for target in ("A", "B", "C")])
    result = execute(tool, "query_shared_regulators", target_genes=["A", "B", "C"])
    assert result.status == "no_result"
    assert not result.payload["candidate_regulators"]


def test_co_mention_remains_retrieved_text():
    tool = MockLiteratureTool(retrieved_items=[RetrievedItem(
        paper_id="SYNTHETIC_RAG", title="Synthetic co-mention of A and B", year=2026,
        source_excerpt_or_summary="Synthetic fixture: A and B are associated with a cell-state program.",
        source_reference="mock://synthetic/co-mention")])
    result = execute(tool, "search_regulatory_relation", source_gene="A", target_gene="B")
    assert result.status == "success"
    assert len(result.payload["retrieved_items"]) == 1
    assert not result.payload["verified_candidates"]


def direct_candidate(**updates):
    values = MockLiteratureTool().search_regulatory_relation("A", "B")["verified_candidates"][0]
    values.update(updates)
    return values


@pytest.mark.parametrize("updates", [
    {"experiment_type": None}, {"observed_effect": None},
    {"experiment_type": "generic co-mention"}, {"source_quality": "secondary_source"},
])
def test_direct_evidence_requires_experimental_content(updates):
    with pytest.raises(ValidationError):
        VerifiedEvidenceCandidate.model_validate(direct_candidate(**updates))


def test_context_mismatch_does_not_change_experiment_directness():
    candidate = direct_candidate(cell_type_or_model="HEK293", biological_context="HEK293")
    result = execute(MockLiteratureTool(verified_candidates=[candidate]),
                     "search_perturbation_evidence", perturbed_gene="A", measured_gene="B", context="K562")
    assert result.status == "success"
    assert result.payload["verified_candidates"][0]["directness"] == "direct"
    assert result.payload["verified_candidates"][0]["cell_type_or_model"] == "HEK293"


def test_null_evidence_requires_power_before_claiming_challenge():
    candidate = direct_candidate(negative_evidence_type="explicit_null_result",
                                 observed_effect="No change detected", relation_effect="challenges")
    with pytest.raises(ValidationError):
        VerifiedEvidenceCandidate.model_validate(candidate)
    candidate["sufficient_power"] = True
    assert VerifiedEvidenceCandidate.model_validate(candidate).relation_effect == "challenges"
    candidate["negative_evidence_type"] = "not_found"
    with pytest.raises(ValidationError):
        VerifiedEvidenceCandidate.model_validate(candidate)


def test_literature_no_result_does_not_invent_a_candidate():
    result = execute(MockLiteratureTool(retrieved_items=[], verified_candidates=[]),
                     "search_claim", claim="A regulates B")
    assert result.status == "no_result"
    assert not result.payload["verified_candidates"]


def test_claim_search_preserves_gene_a_and_relation_direction():
    tool = MockLiteratureTool()
    result = execute(tool, "search_claim", claim="Does A regulate B?")
    assert result.status == "success"
    assert [(candidate["perturbed_entity"], candidate["measured_entity"])
            for candidate in result.payload["verified_candidates"]] == [("A", "B")]
    reverse = execute(tool, "search_claim", claim="B regulates A")
    assert reverse.status == "no_result"


@pytest.mark.parametrize("claim, expected", [
    ("X regulates A, B, C", [("X", "A"), ("X", "B"), ("X", "C")]),
    ("Does X regulate A, B, and C?", [("X", "A"), ("X", "B"), ("X", "C")]),
    ("from A to B and B to C", [("A", "B"), ("B", "C")]),
    ("A -> B and B -> C", [("A", "B"), ("B", "C")]),
])
def test_fanout_and_cascade_claims_retrieve_only_requested_atomic_relations(claim, expected):
    result = execute(MockLiteratureTool(), "search_claim", claim=claim)
    assert result.status == "success"
    assert [(candidate["perturbed_entity"], candidate["measured_entity"])
            for candidate in result.payload["verified_candidates"]] == expected


class BrokenTool(EvidenceTool):
    metadata = ToolMetadata(tool_id="broken", tool_type="other", capabilities=("query",))

    def __init__(self, behavior):
        self.behavior = behavior

    def query(self):
        if isinstance(self.behavior, Exception):
            raise self.behavior
        return self.behavior


@pytest.mark.parametrize("behavior, status, reason", [
    (TimeoutError("secret"), "failed", "timeout"),
    (ConnectionError("secret"), "failed", "source_unavailable"),
    (None, "no_result", "no_result"),
    (["malformed"], "failed", "malformed_response"),
    ({"warnings": "malformed"}, "failed", "malformed_response"),
])
def test_registry_normalizes_failures(behavior, status, reason):
    result = execute(BrokenTool(behavior), "query")
    assert result.status == status
    assert reason in result.failure_reason
    assert "secret" not in result.model_dump_json()


def test_registry_unavailable_missing_tool_and_unsupported_operation():
    registry = EvidenceToolRegistry([MockNetworkTool(availability="unavailable")])
    assert registry.execute("missing", "query", {}).failure_reason == "source_unavailable"
    assert registry.execute("mock_network", "query_edge", {}).failure_reason == "source_unavailable"
    available = EvidenceToolRegistry([MockNetworkTool()])
    assert available.execute("mock_network", "__dict__", {}).status == "failed"
    assert available.execute("mock_network", "query_edge", {}).failure_reason.startswith("missing_inputs")
    assert registry.metadata_snapshot()[0].availability == "unavailable"
    with pytest.raises(ValueError, match="already registered"):
        registry.register_tool(MockNetworkTool())


@pytest.mark.parametrize("family, operation, inputs", [
    (MockDatasetTool, "conditional_frequency", {"target_gene": "C"}),
    (MockNetworkTool, "query_edge", {"source_gene": "A", "target_gene": "B"}),
    (MockLiteratureTool, "search_claim", {"claim": "A regulates B"}),
])
def test_malformed_family_payload_is_rejected(family, operation, inputs):
    tool = family()
    tool.execute = lambda *_: {"made_up_answer": True}
    result = EvidenceToolRegistry([tool]).execute(tool.metadata.tool_id, operation, inputs)
    assert result.status == "failed"
    assert result.failure_reason.startswith("malformed_response")
    assert not result.payload


def test_invalid_dataset_counts_are_rejected_even_when_json_is_well_formed():
    tool = MockDatasetTool()
    response = tool.conditional_frequency(target_gene="C")
    response["numerator"] = response["denominator"] + 1
    tool.execute = lambda *_: response
    result = execute(tool, "conditional_frequency", target_gene="C")
    assert result.status == "failed"
    assert result.failure_reason.startswith("malformed_response")


def test_malformed_nested_response_does_not_escape_failure_normalization():
    tool = MockNetworkTool()
    payload = tool.query_shared_regulators(["A", "B", "C"])
    payload["shared_regulators"] = [None]
    tool.execute = lambda *_: payload
    result = execute(tool, "query_shared_regulators", target_genes=["A", "B", "C"])
    assert result.status == "failed"
    assert result.failure_reason.startswith("malformed_response")
