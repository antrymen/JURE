"""Offline synthetic adapters. No real GRN or literature source is contacted."""
from __future__ import annotations

from collections.abc import Mapping
from statistics import NormalDist
import re

import pandas as pd
from scipy.stats import fisher_exact

from clue_discovery.patterns import JointPattern
from clue_discovery.statistics import pattern_frequency, pattern_shift

from .base import ToolMetadata
from .dataset import DatasetEvidenceTool
from .literature import LiteratureEvidenceTool, RetrievedItem, VerifiedEvidenceCandidate
from .network import NETWORK_LIMITATION, NetworkEdge, NetworkEvidenceTool


DATASET_LIMITATION = "Observed conditional association does not establish a regulatory or causal mechanism."


def _pattern_states(pattern):
    if isinstance(pattern, Mapping):
        values = dict(pattern)
    elif hasattr(pattern, "genes") and hasattr(pattern, "states"):
        values = dict(zip(pattern.genes, pattern.states))
    else:
        raise ValueError("a pattern must map gene names to binary states")
    if any(not isinstance(gene, str) or not gene.strip() for gene in values):
        raise ValueError("genes must be nonempty strings")
    if any(type(state) is not int or state not in (0, 1) for state in values.values()):
        raise ValueError("states must be binary integers")
    return values


def _wilson_interval(count, total, confidence=0.95):
    interval = {"method": "Wilson binomial interval", "confidence_level": confidence,
                "lower": None, "upper": None}
    if total:
        z = NormalDist().inv_cdf((1 + confidence) / 2)
        p = count / total
        center = (p + z * z / (2 * total)) / (1 + z * z / total)
        radius = z * ((p * (1 - p) / total + z * z / (4 * total * total)) ** .5) / (
            1 + z * z / total)
        interval.update(lower=max(0., center - radius), upper=min(1., center + radius))
    return interval


class MockDatasetTool(DatasetEvidenceTool):
    """Empirical counts over caller-supplied binary cells or a synthetic fixture.

    The default fixture is explicitly synthetic. A DataFrame may contain a
    ``condition`` column plus binary gene columns; each row is one observed cell.
    Conditional support thresholds are runtime policy, not scientific cutoffs.
    """

    def __init__(self, data=None, *, dataset_id="synthetic_dataset", dataset_version="0.1",
                 cell_context="K562", min_conditional_support=10,
                 tool_id="mock_dataset", availability="available"):
        if type(min_conditional_support) is not int or min_conditional_support < 1:
            raise ValueError("min_conditional_support must be a positive integer")
        if data is None:
            rows = []
            for condition in ("control", "perturbation"):
                for a in (0, 1):
                    for b in (0, 1):
                        for c in (0, 1):
                            n = 30 if b == c else 10
                            if condition == "perturbation" and (a, b, c) == (1, 0, 1):
                                n += 20
                            rows.extend([{"A": a, "B": b, "C": c, "condition": condition}] * n)
            data = rows
        self._data = pd.DataFrame(data).copy(deep=True).reset_index(drop=True)
        if self._data.columns.duplicated().any() or any(
                not isinstance(name, str) or not name for name in self._data.columns):
            raise ValueError("dataset columns must have unique nonempty names")
        gene_columns = [name for name in self._data if name != "condition"]
        if not gene_columns or not self._data[gene_columns].isin([0, 1]).all().all():
            raise ValueError("dataset gene columns must contain binary states")
        self.dataset_id = dataset_id
        self.dataset_version = dataset_version
        self.cell_context = cell_context
        self.min_conditional_support = min_conditional_support
        self.metadata = ToolMetadata(
            tool_id=tool_id, tool_type="dataset", capabilities=(
                "joint_frequency", "conditional_frequency", "compare_conditional_frequency",
                "compare_pattern_between_conditions", "get_support"),
            required_inputs={"joint_frequency": ["pattern"],
                             "compare_pattern_between_conditions": ["pattern"]},
            availability=availability,
        )

    def _threshold(self, minimum):
        minimum = self.min_conditional_support if minimum is None else minimum
        if type(minimum) is not int or minimum < 1:
            raise ValueError("min_conditional_support must be a positive integer")
        return minimum

    def _subset(self, conditions=None, condition=None):
        states = _pattern_states(conditions or {})
        unknown = set(states) - set(self._data.columns)
        if unknown or "condition" in states:
            raise ValueError(f"unknown gene columns: {sorted(unknown or {'condition'})}")
        subset = self._data
        if condition is not None:
            if "condition" not in subset:
                raise ValueError("dataset has no condition annotation")
            subset = subset.loc[subset["condition"] == condition]
        for gene, state in states.items():
            subset = subset.loc[subset[gene] == state]
        return subset

    def _frequency(self, subset, target, minimum):
        target = _pattern_states(target)
        unknown = set(target) - set(self._data.columns)
        if unknown or "condition" in target:
            raise ValueError(f"unknown target gene columns: {sorted(unknown or {'condition'})}")
        total = len(subset)
        if total and target:
            frequency = pattern_frequency(subset, JointPattern(tuple(target), tuple(target.values())))
            count = frequency.cell_count
        else:
            count = total if not target else 0
        probability = count / total if total else None
        sufficient = total >= minimum
        warnings = [] if sufficient else [
            f"Insufficient support: {total} cells satisfy the conditioning state; required {minimum}."
        ]
        return {"numerator": count, "denominator": total, "probability": probability,
                "estimate": probability, "counts": {"positive": count, "negative": total - count},
                "support": total, "support_quality": "sufficient" if sufficient else "insufficient",
                "uncertainty": _wilson_interval(count, total), "warnings": warnings}

    def _provenance(self, operation, query, condition, conditions=None):
        return {"dataset_id": self.dataset_id, "dataset_version": self.dataset_version,
                "cell_context": self.cell_context, "condition": condition,
                "filters": conditions or {},
                "cell_subset": {"condition": condition, "filters": conditions or {}},
                "n_cells": len(self._subset(conditions, condition)),
                "query_specification": {"operation": operation, **query},
                "statistical_method": "empirical counts via clue_discovery.statistics; Wilson interval",
                "code_version": self.metadata.version, "limitations": [DATASET_LIMITATION]}

    def joint_frequency(self, pattern, condition=None, min_conditional_support=None):
        states = _pattern_states(pattern)
        if not states:
            raise ValueError("joint pattern cannot be empty")
        minimum = self._threshold(min_conditional_support)
        query = {"pattern": states, "condition": condition, "min_conditional_support": minimum}
        return {**self._provenance("joint_frequency", query, condition),
                **self._frequency(self._subset(condition=condition), states, minimum)}

    def _target(self, target_gene, target_state):
        if isinstance(target_state, Mapping):
            target = _pattern_states(target_state)
            if target_gene is not None and set(target) != {target_gene}:
                raise ValueError("target_gene conflicts with target_state mapping")
        elif target_gene is not None:
            target = _pattern_states({target_gene: target_state})
        else:
            raise ValueError("provide target_gene or a target_state mapping")
        if not target:
            raise ValueError("target cannot be empty")
        return target

    def conditional_frequency(self, target_gene=None, target_state=1, conditions=None,
                              condition=None, min_conditional_support=None):
        target = self._target(target_gene, target_state)
        states = _pattern_states(conditions or {})
        if set(target) & set(states):
            raise ValueError("target and conditioning genes must be distinct")
        minimum = self._threshold(min_conditional_support)
        query = {"target_state": target, "conditions": states, "condition": condition,
                 "min_conditional_support": minimum}
        return {**self._provenance("conditional_frequency", query, condition, states),
                **self._frequency(self._subset(states, condition), target, minimum)}

    def compare_conditional_frequency(self, target_gene=None, conditioning_gene=None, target_state=1,
                                      conditions=None, condition=None, min_conditional_support=None,
                                      condition_a=None, condition_b=None):
        target = self._target(target_gene, target_state)
        base = _pattern_states(conditions or {})
        if conditioning_gene is not None:
            if condition_a is not None or condition_b is not None or conditioning_gene in base:
                raise ValueError("conditioning_gene conflicts with explicit comparison conditions")
            a, b = {**base, conditioning_gene: 1}, {**base, conditioning_gene: 0}
        else:
            if condition_a is None or condition_b is None:
                raise ValueError("provide conditioning_gene or both condition_a and condition_b")
            a, b = {**base, **_pattern_states(condition_a)}, {**base, **_pattern_states(condition_b)}
        if set(target) & (set(a) | set(b)):
            raise ValueError("target and conditioning genes must be distinct")
        minimum = self._threshold(min_conditional_support)
        subset_a, subset_b = self._subset(a, condition), self._subset(b, condition)
        positive, negative = self._frequency(subset_a, target, minimum), self._frequency(subset_b, target, minimum)
        independent = not len(subset_a.index.intersection(subset_b.index))
        comparison = self._comparison(positive, negative, independent)
        query = {"target_state": target, "condition_a": a, "condition_b": b,
                 "condition": condition, "min_conditional_support": minimum}
        return {**self._provenance("compare_conditional_frequency", query, condition, base),
                "group_positive": positive, "group_negative": negative,
                "group_positive_conditions": a, "group_negative_conditions": b, **comparison}

    def _comparison(self, a, b, independent=True):
        table = [[a["numerator"], a["denominator"] - a["numerator"]],
                 [b["numerator"], b["denominator"] - b["numerator"]]]
        enough = a["support_quality"] == b["support_quality"] == "sufficient"
        present = bool(a["denominator"] and b["denominator"])
        difference = a["probability"] - b["probability"] if present else None
        interval = {"method": "difference of Bonferroni-adjusted Wilson bounds", "confidence_level": .95,
                    "lower": None, "upper": None}
        if present and independent:
            a_interval = _wilson_interval(a["numerator"], a["denominator"], confidence=.975)
            b_interval = _wilson_interval(b["numerator"], b["denominator"], confidence=.975)
            interval.update(lower=a_interval["lower"] - b_interval["upper"],
                            upper=a_interval["upper"] - b_interval["lower"])
        warnings = a["warnings"] + b["warnings"]
        if not independent:
            warnings += ["Comparison groups overlap; no independent-group test or interval was computed."]
        return {"difference": difference, "estimate": difference, "counts": table,
                "denominator": {"group_positive": a["denominator"], "group_negative": b["denominator"]},
                "support": {"group_positive": a["support"], "group_negative": b["support"]},
                "contingency_table": table,
                "fisher_p_value": float(fisher_exact(table).pvalue) if present and independent and enough else None,
                "uncertainty": interval, "support_quality": "sufficient" if enough else "insufficient",
                "warnings": warnings}

    def compare_pattern_between_conditions(self, pattern, control_condition="control",
                                           perturbation_condition="perturbation",
                                           min_conditional_support=None, condition_a=None, condition_b=None):
        states = _pattern_states(pattern)
        if not states:
            raise ValueError("pattern cannot be empty")
        control_condition = condition_a if condition_a is not None else control_condition
        perturbation_condition = condition_b if condition_b is not None else perturbation_condition
        if control_condition == perturbation_condition:
            raise ValueError("comparison requires distinct conditions")
        minimum = self._threshold(min_conditional_support)
        control_cells = self._subset(condition=control_condition)
        perturbation_cells = self._subset(condition=perturbation_condition)
        control = self._frequency(control_cells, states, minimum)
        perturbation = self._frequency(perturbation_cells, states, minimum)
        result = self._comparison(perturbation, control)
        if len(control_cells) and len(perturbation_cells):
            shift = pattern_shift(control_cells, perturbation_cells,
                                  JointPattern(tuple(states), tuple(states.values())))
            result["difference"] = result["estimate"] = shift["delta_frequency"]
            if result["support_quality"] == "sufficient":
                result["fisher_p_value"] = shift["p_value_shift"]
        query = {"pattern": states, "control_condition": control_condition,
                 "perturbation_condition": perturbation_condition, "min_conditional_support": minimum}
        return {**self._provenance("compare_pattern_between_conditions", query, None),
                "control": control, "perturbation": perturbation, **result}

    def get_support(self, pattern=None, conditions=None, condition=None, min_conditional_support=None):
        states = _pattern_states(pattern or {})
        filters = _pattern_states(conditions or {})
        minimum = self._threshold(min_conditional_support)
        query = {"pattern": states, "conditions": filters, "condition": condition,
                 "min_conditional_support": minimum}
        return {**self._provenance("get_support", query, condition, filters),
                **self._frequency(self._subset(filters, condition), states, minimum)}


class MockNetworkTool(NetworkEvidenceTool):
    def __init__(self, edges=None, *, network_name="synthetic_grn", network_version="0.1",
                 context="K562", tool_id="mock_network", availability="available"):
        self.network_name, self.network_version = network_name, network_version
        self.context = context
        self.metadata = ToolMetadata(tool_id=tool_id, tool_type="network", capabilities=(
            "query_edge", "query_shared_regulators", "query_paths"), required_inputs={
                "query_edge": ["source_gene", "target_gene"],
                "query_shared_regulators": ["target_genes"],
                "query_paths": ["source_gene", "target_gene"]}, availability=availability)
        if edges is None:
            edges = [{"source_gene": source, "target_gene": target}
                     for source, target in (("X", "A"), ("X", "B"), ("X", "C"), ("A", "B"), ("B", "C"))]
        self._edges = tuple(edge if isinstance(edge, NetworkEdge) else NetworkEdge.model_validate({
            "network_name": network_name, "network_version": network_version,
            "edge_type": "candidate_regulatory", "direction": "source_to_target", "context": context,
            "source_reference": "mock://synthetic_grn/fixture", **edge}) for edge in edges)

    def _eligible(self, context, parameters):
        return [edge.model_copy(update={"query_parameters": type(edge.query_parameters)(parameters)})
                for edge in self._edges if context is None or edge.context is None or edge.context == context]

    @staticmethod
    def _forward_edge(edge):
        return edge.direction.casefold() in ("source_to_target", "directed", "forward")

    def _response(self, parameters, edges=(), regulators=(), paths=()):
        return {"network_name": self.network_name, "network_version": self.network_version,
                "context": parameters.get("context"), "query_parameters": parameters,
                "edges": [edge.model_dump(mode="json") for edge in edges],
                "shared_regulators": list(regulators), "candidate_regulators": [r["regulator"] for r in regulators],
                "paths": list(paths), "has_results": bool(edges or regulators or paths),
                "provenance": {"source_reference": "mock://synthetic_grn/fixture", "mock": True},
                "warnings": ["Synthetic offline network fixture; no external database was queried."],
                "limitations": [NETWORK_LIMITATION]}

    def query_edge(self, source_gene, target_gene, context=None):
        if not source_gene or not target_gene:
            raise ValueError("edge query needs source and target genes")
        parameters = {"source_gene": source_gene, "target_gene": target_gene, "context": context}
        edges = [edge for edge in self._eligible(context, parameters)
                 if edge.source_gene == source_gene and edge.target_gene == target_gene]
        return self._response(parameters, edges=edges)

    def query_shared_regulators(self, target_genes, context=None):
        if (not isinstance(target_genes, (tuple, list)) or len(set(target_genes)) < 2
                or any(not isinstance(gene, str) or not gene.strip() for gene in target_genes)):
            raise ValueError("shared regulator query requires at least two distinct target genes")
        parameters = {"target_genes": list(target_genes), "context": context}
        edges = [edge for edge in self._eligible(context, parameters) if self._forward_edge(edge)]
        regulators = []
        selected = []
        for source in sorted({edge.source_gene for edge in edges} - set(target_genes)):
            outgoing = [edge for edge in edges if edge.source_gene == source and edge.target_gene in target_genes]
            if {edge.target_gene for edge in outgoing} == set(target_genes):
                regulators.append({"regulator": source, "edges": [edge.model_dump(mode="json") for edge in outgoing]})
                selected.extend(outgoing)
        return self._response(parameters, edges=selected, regulators=regulators)

    def query_paths(self, source_gene, target_gene, max_hops=2, context=None):
        if type(max_hops) is not int or not 1 <= max_hops <= 10:
            raise ValueError("max_hops must be an integer between 1 and 10")
        parameters = {"source_gene": source_gene, "target_gene": target_gene,
                      "max_hops": max_hops, "context": context}
        edges = [edge for edge in self._eligible(context, parameters) if self._forward_edge(edge)]
        paths = []

        def visit(nodes, traversed):
            if traversed and nodes[-1] == target_gene:
                paths.append({"nodes": nodes, "edges": [edge.model_dump(mode="json") for edge in traversed]})
                return
            if len(traversed) >= max_hops:
                return
            for edge in edges:
                if edge.source_gene == nodes[-1] and edge.target_gene not in nodes:
                    visit(nodes + [edge.target_gene], traversed + [edge])

        visit([source_gene], [])
        selected = { (edge["source_gene"], edge["target_gene"], edge["source_reference"]): edge
                     for path in paths for edge in path["edges"] }
        return self._response(parameters, paths=paths,
                              edges=[NetworkEdge.model_validate(edge) for edge in selected.values()])


class MockLiteratureTool(LiteratureEvidenceTool):
    def __init__(self, retrieved_items=None, verified_candidates=None, *, tool_id="mock_literature",
                 availability="available"):
        self.metadata = ToolMetadata(tool_id=tool_id, tool_type="literature", cost_class="medium",
            capabilities=("search_claim", "search_regulatory_relation", "search_perturbation_evidence"),
            required_inputs={"search_claim": ["claim"],
                             "search_regulatory_relation": ["source_gene", "target_gene"]},
            availability=availability)
        if retrieved_items is None and verified_candidates is None:
            verified_candidates = [
                {"paper_id": f"SYNTHETIC_{source}_{target}", "title": "Synthetic perturbation experiment",
                 "year": 2026, "claim_tested": f"{source} regulates {target}",
                 "experiment_identifier": f"synthetic_knockout_{source}_{target}",
                 "experiment_type": "CRISPR knockout", "perturbed_entity": source, "measured_entity": target,
                 "observed_effect": f"{target} expression decreased after {source} knockout",
                 "biological_context": "K562", "cell_type_or_model": "K562", "directness": "direct",
                 "source_excerpt_or_summary": f"Synthetic fixture: knockout of {source} reduced {target} expression.",
                 "source_reference": f"mock://synthetic_literature/{source}/{target}",
                 "source_quality": "primary_experiment", "support_quality": "sufficient",
                 "relation_effect": "supports", "limitations": ["Synthetic fixture; not a real published experiment."]}
                for source, target in (("X", "A"), ("X", "B"), ("X", "C"), ("A", "B"), ("B", "C"))]
        self._retrieved = tuple(item if isinstance(item, RetrievedItem) else RetrievedItem.model_validate(item)
                                for item in (retrieved_items or ()))
        self._verified = tuple(item if isinstance(item, VerifiedEvidenceCandidate)
                               else VerifiedEvidenceCandidate.model_validate(item)
                               for item in (verified_candidates or ()))

    @staticmethod
    def _tokens(value):
        return set(re.findall(r"[A-Za-z0-9_-]+", value.casefold()))

    def _search(self, query, entities=(), claim=None, context=None, pairs=()):
        entity_tokens = {value.casefold() for value in entities}
        requested_pairs = tuple(pairs) or ((tuple(entities),) if entities else ())

        def matches(text):
            tokens = self._tokens(text)
            if requested_pairs:
                return any({source.casefold(), target.casefold()} <= tokens
                           for source, target in requested_pairs)
            if entity_tokens:
                return entity_tokens <= tokens
            named_genes = set(re.findall(r"\b[A-Z][A-Z0-9_-]*\b", claim or ""))
            wanted = {gene.casefold() for gene in named_genes} if named_genes else self._tokens(claim or "") - {
                "does", "is", "the", "a", "an", "regulate", "regulates", "regulation", "of", "in",
                "experimentally", "supported", "evidence", "for", "and", "by", "to", "gene", "claim",
            }
            return bool(wanted) and wanted <= tokens

        retrieved = [item.model_dump(mode="json") for item in self._retrieved
                     if matches(f"{item.title} {item.source_excerpt_or_summary}")]
        verified = [item.model_dump(mode="json") for item in self._verified
                    if matches(f"{item.claim_tested} {item.perturbed_entity or ''} {item.measured_entity or ''}")
                    and (not requested_pairs or (item.perturbed_entity, item.measured_entity) in requested_pairs)]
        # Context mismatch is retained, then evaluated separately from directness.
        verified.sort(key=lambda item: item["cell_type_or_model"] != context)
        return {"retrieved_items": retrieved, "verified_candidates": verified,
                "query": {**query, "context": context},
                "provenance": {"source_name": "synthetic_literature", "source_version": "0.1",
                               "source_reference": "mock://synthetic_literature/fixture", "mock": True},
                "warnings": ["Synthetic offline literature fixture; no published paper was retrieved."],
                "has_results": bool(retrieved or verified)}

    def search_claim(self, claim, context=None):
        if not isinstance(claim, str) or not claim.strip():
            raise ValueError("claim must be a nonempty string")
        pairs = self._claim_pairs(claim)
        return self._search({"claim": claim}, pairs=pairs, claim=claim, context=context)

    @staticmethod
    def _claim_pairs(claim):
        """Parse explicit atomic/fan-out/cascade syntax without guessing relations."""
        gene = r"[A-Za-z][A-Za-z0-9_-]*"
        text = re.sub(r"^Does\s+", "", claim.strip(), flags=re.I).rstrip("?. ")
        fanout = re.fullmatch(rf"({gene})\s*(?:->|→|regulates?)\s*(.+)", text)
        if fanout:
            source, targets_text = fanout.groups()
            targets = re.split(r"\s*,\s*(?:and\s+)?|\s+and\s+", targets_text)
            if targets and all(re.fullmatch(gene, target) for target in targets):
                return tuple(dict.fromkeys((source, target) for target in targets))
        cascade = re.sub(r"^(?:cascade\s+)?from\s+", "", text, flags=re.I)
        pairs = []
        for part in re.split(r"\s+and\s+", cascade):
            relation = re.fullmatch(rf"({gene})\s*(?:->|→|\s+to\s+|\s+regulates?\s+)\s*({gene})", part)
            if relation is None:
                return ()
            pairs.append(relation.groups())
        return tuple(dict.fromkeys(pairs))

    def search_regulatory_relation(self, source_gene, target_gene, context=None):
        return self._search({"source_gene": source_gene, "target_gene": target_gene},
                            entities=(source_gene, target_gene), context=context)

    def search_perturbation_evidence(self, perturbed_gene=None, measured_gene=None, context=None,
                                   perturbed_entity=None, measured_entity=None):
        source, target = perturbed_gene or perturbed_entity, measured_gene or measured_entity
        if not source or not target:
            raise ValueError("perturbation search requires perturbed and measured genes")
        return self._search({"perturbed_gene": source, "measured_gene": target},
                            entities=(source, target), context=context)
