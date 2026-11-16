"""Deterministic scientific guards between tool output and the shared evidence API."""
from dataclasses import dataclass, field
import hashlib
import json
import re

from jure.casefile import EvidenceRecord, Provenance, new_id

NETWORK_LIMITATION = (
    "Network connectivity alone does not establish causal regulation in the current perturbation context."
)
DATASET_LIMITATION = "An observed conditional association does not establish a causal regulatory mechanism."


@dataclass
class NormalizedEvidence:
    records: list = field(default_factory=list)
    question_status: str = "unresolved"
    gap: str | None = None
    followup_candidates: list = field(default_factory=list)
    potential_conflict: bool = False


def evidence_fingerprint(source_type, specification):
    text = json.dumps(specification, sort_keys=True, ensure_ascii=False, allow_nan=False)
    return hashlib.sha256((source_type + ":" + text).encode()).hexdigest()


def _context_match(observed, expected):
    if not observed or not expected:
        return "unknown"
    return "matched" if str(observed).strip().casefold() == str(expected).strip().casefold() else "mismatched"


def _expected_relations(inputs, question_text=""):
    source = inputs.get("source_gene", inputs.get("perturbed_gene"))
    target = inputs.get("target_gene", inputs.get("measured_gene"))
    if source and target:
        return {(source.casefold(), target.casefold())}
    text = str(inputs.get("claim", question_text))
    match = re.fullmatch(r"(\w+) regulates ([\w, ]+)", text)
    if match:
        return {(match[1].casefold(), target.strip().casefold()) for target in match[2].split(",")}
    # Lookahead retains overlapping A->B and B->C in a chain.
    pairs = re.findall(r"(?=\b([A-Za-z][A-Za-z0-9_]*)\s*(?:→|->)\s*([A-Za-z][A-Za-z0-9_]*)\b)", text)
    pairs += re.findall(r"\b([A-Za-z][A-Za-z0-9_]*)\s+to\s+([A-Za-z][A-Za-z0-9_]*)\b", text)
    return {(a.casefold(), b.casefold()) for a, b in pairs}


def _record(question, result, raw, run_id, *, source_type, source_id, claim, summary,
            details, fingerprint, limitations=(), directness="indirect", context_match="unknown",
            source_quality="unknown", support_quality="unknown", negative_evidence_type="not_applicable",
            source_uri=None, potential_conflict=False):
    return EvidenceRecord(
        evidence_id=new_id("E"), question_id=question.question_id,
        claim_tested=claim, result_summary=summary, source_type=source_type,
        directness=directness, context_match=context_match, source_quality=source_quality,
        support_quality=support_quality, limitations=tuple(dict.fromkeys(limitations)),
        negative_evidence_type=negative_evidence_type, potential_conflict=potential_conflict,
        fingerprint=fingerprint, created_by="evidence_investigator",
        raw_result_reference=raw.raw_result_reference,
        provenance=Provenance(source_id=str(source_id), source_uri=source_uri,
            tool=result.tool_id, query=question.question_text, artifact_sha256=raw.sha256,
            parameters={"actor": "evidence_investigator", "run_id": run_id,
                        "question_id": question.question_id, "tool_version": result.tool_version,
                        "operation": result.operation, "query_parameters": result.parameters.to_dict(),
                        "execution_status": result.status,
                        "started_at": result.started_at.isoformat(),
                        "completed_at": result.completed_at.isoformat(), **details}),
    )


def _dataset(question, result, raw, case, config, run_id):
    data = result.payload.to_dict()
    parameters = result.parameters.to_dict()
    expected = {"operation": result.operation}
    if result.operation in {"conditional_frequency", "compare_conditional_frequency"}:
        target = parameters.get("target_state", 1)
        expected["target_state"] = target if isinstance(target, dict) else {parameters.get("target_gene"): target}
    if result.operation in {"joint_frequency", "get_support", "compare_pattern_between_conditions"}:
        expected["pattern"] = parameters.get("pattern", {})
    if result.operation in {"conditional_frequency", "get_support"}:
        expected["conditions"] = parameters.get("conditions", {})
    if result.operation == "compare_conditional_frequency":
        base = parameters.get("conditions", {})
        gene = parameters.get("conditioning_gene")
        expected["condition_a"] = {**base, **({gene: 1} if gene else parameters.get("condition_a", {}))}
        expected["condition_b"] = {**base, **({gene: 0} if gene else parameters.get("condition_b", {}))}
    if result.operation == "compare_pattern_between_conditions":
        expected["control_condition"] = parameters.get("condition_a", parameters.get("control_condition", "control"))
        expected["perturbation_condition"] = parameters.get("condition_b", parameters.get("perturbation_condition", "perturbation"))
    else:
        expected["condition"] = parameters.get("condition")
    actual = data.get("query_specification", {})
    if any(key not in actual or actual[key] != value for key, value in expected.items()):
        raise ValueError("dataset response query differs from the requested target, subset or conditions")
    groups = [data[key] for key in ("group_positive", "group_negative", "group_a", "group_b",
                                    "control", "perturbation") if isinstance(data.get(key), dict)]
    if not groups:
        groups = [data]
    counts = [group.get("denominator", group.get("denominator_count")) for group in groups]
    if any(type(count) is not int or count < 0 for count in counts):
        raise ValueError("dataset result requires nonnegative denominator support counts")
    limited = result.status == "insufficient_data" or min(counts) < config.min_conditional_support
    limitations = list(data.get("limitations", ())) + list(result.warnings) + [DATASET_LIMITATION]
    if limited:
        summary = (f"Conditional estimate is not considered reliable: only {min(counts)} cells "
                   "satisfy at least one queried conditioning state (insufficient support).")
        limitations.append(f"Only {min(counts)} cells satisfy the least-supported conditioning state.")
    elif len(groups) > 1:
        values = [g.get("probability", g.get("estimated_probability")) for g in groups]
        summary = ("Observed target-state frequencies across the queried conditions are "
                   + " versus ".join(f"{v:g} ({g.get('numerator', g.get('numerator_count'))}/{n})"
                                     for v, g, n in zip(values, groups, counts))
                   + "; this is a statistical comparison within the observed dataset.")
    else:
        group = groups[0]
        numerator = group.get("numerator", group.get("numerator_count"))
        probability = group.get("probability", group.get("estimated_probability"))
        summary = (f"The observed query has {numerator}/{counts[0]} cells satisfying the target "
                   f"state (frequency {probability:g}); counts and uncertainty are retained.")
    # Store query-sized sufficient statistics, never the underlying cell matrix.
    record = _record(question, result, raw, run_id, source_type="dataset",
        source_id=data["dataset_id"], claim=question.question_text, summary=summary,
        details={"dataset": data},
        fingerprint=evidence_fingerprint("dataset", {
            "dataset_id": data["dataset_id"], "dataset_version": data.get("dataset_version"),
            "query": data.get("query_specification", result.parameters.to_dict()),
            "cell_subset": data.get("cell_subset"), "filters": data.get("filters")}),
        limitations=limitations, context_match=_context_match(data.get("cell_context"), case.metadata.cell_context),
        support_quality="insufficient" if limited else "sufficient")
    return NormalizedEvidence([record], "unresolved" if limited else "answered",
                              "The dataset cannot answer this query reliably with the available support." if limited else None)


def _network(question, result, raw, case, run_id):
    data = result.payload.to_dict()
    edges = data.get("edges", [])
    candidates = data.get("shared_regulators", data.get("candidate_regulators", []))
    for candidate in candidates:
        if isinstance(candidate, dict):
            edges += [e for e in candidate.get("edges", []) if e not in edges]
    for path in data.get("paths", []):
        if isinstance(path, dict):
            edges += [e for e in path.get("edges", []) if e not in edges]
    parameters = result.parameters.to_dict()
    required_targets = set(parameters.get("target_genes", []))
    complete = bool(edges)
    if result.operation == "query_shared_regulators":
        complete = any(isinstance(c, dict) and required_targets and required_targets <= {
            e.get("target", e.get("target_gene")) for e in c.get("edges", [])
            if e.get("source", e.get("source_gene")) == c.get("regulator")} for c in candidates)
    elif result.operation == "query_edge":
        edges = [e for e in edges if e.get("source", e.get("source_gene")) == parameters.get("source_gene")
                 and e.get("target", e.get("target_gene")) == parameters.get("target_gene")]
        complete = bool(edges)
    elif result.operation == "query_paths":
        complete = any(p.get("nodes", [None])[0] == parameters.get("source_gene")
                       and p.get("nodes", [None])[-1] == parameters.get("target_gene")
                       and 1 <= len(p.get("edges", [])) <= parameters.get("max_hops", 2)
                       for p in data.get("paths", []))
    output = NormalizedEvidence(question_status="answered" if complete else "partially_answered" if edges else "unresolved")
    seen = set()
    for edge in edges:
        source, target = edge.get("source", edge.get("source_gene")), edge.get("target", edge.get("target_gene"))
        if not source or not target:
            raise ValueError("network edge requires source and target")
        name = edge.get("network_name", data.get("network_name"))
        version = edge.get("network_version", data.get("network_version"))
        context = edge.get("context", data.get("context"))
        fingerprint = evidence_fingerprint("grn", {"network_name": name, "version": version,
            "source": source, "target": target, "edge_type": edge.get("edge_type"),
            "direction": edge.get("direction"), "context": context})
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        output.records.append(_record(question, result, raw, run_id, source_type="grn", source_id=name,
            claim=f"Candidate network relation {source} -> {target}",
            summary=f"Network {name} contains a candidate connection {source} -> {target}.",
            details={"network_name": name, "network_version": version, "context": context,
                     "query_type": result.operation, "edge": edge, "query_answer_complete": complete}, fingerprint=fingerprint,
            source_uri=edge.get("source_reference"), limitations=[NETWORK_LIMITATION, *result.warnings],
            context_match=_context_match(context, case.metadata.cell_context), source_quality="curated_database",
            support_quality="limited"))
    for candidate in candidates:
        if isinstance(candidate, str):
            regulator = candidate
        else:
            regulator = candidate.get("regulator", candidate.get("name"))
        targets = sorted({e.get("target", e.get("target_gene")) for e in edges
                          if e.get("source", e.get("source_gene")) == regulator})
        if regulator and targets and (not required_targets or required_targets <= set(targets)):
            output.followup_candidates.append({"regulator": regulator, "targets": targets,
                                               "context": case.metadata.cell_context})
    if not edges:
        output.gap = "No candidate connectivity was found in the queried network; this does not exclude the mechanism."
    elif not complete:
        output.gap = "Returned network connections do not completely cover the queried architecture."
    return output


def _literature(question, result, raw, case, run_id):
    data = result.payload.to_dict()
    candidates = data.get("verified_candidates", data.get("candidate_evidence", []))
    retrieved = data.get("retrieved_items", data.get("papers", []))
    output = NormalizedEvidence()
    outcomes = {}
    covered_pairs = set()
    direct_records = []
    expected_pairs = _expected_relations(result.parameters.to_dict(), question.question_text)
    for candidate in candidates:
        fields = ("claim_tested", "experiment_type", "perturbed_entity", "measured_entity", "observed_effect")
        experimental = all(candidate.get(key) for key in fields)
        directness = candidate.get("directness", "unknown")
        if directness == "direct" and not experimental:
            directness = "contextual"
        explicit_null = candidate.get("negative_evidence_type") == "explicit_null_result"
        power = candidate.get("sufficient_power", False)
        context = candidate.get("biological_context") or candidate.get("cell_type_or_model")
        limitations = list(candidate.get("limitations", ())) + list(result.warnings)
        support = candidate.get("support_quality", "unknown")
        candidate_pair = (str(candidate.get("perturbed_entity", "")).casefold(),
                          str(candidate.get("measured_entity", "")).casefold())
        relevant = not expected_pairs or candidate_pair in expected_pairs
        if not relevant:
            # A valid experiment about X/Y is not an answer to a query about A/B.
            continue
        if directness == "direct":
            # A null X->B and an effect X->A are different tested claims.
            key = (*candidate_pair, str(context).casefold())
            outcomes.setdefault(key, set()).add("null" if explicit_null else "effect")
        if not experimental:
            limitations.append("Retrieved text does not verify an experiment supporting this regulatory claim.")
        if explicit_null and not power:
            limitations.append("Statistical power for this null result is not established.")
        if _context_match(context, case.metadata.cell_context) == "mismatched":
            limitations.append("The experimental context differs from the current case.")
        record = _record(question, result, raw, run_id, source_type="literature",
            source_id=candidate["paper_id"], source_uri=candidate.get("source_reference"),
            claim=candidate.get("claim_tested") or "Retrieved contextual association",
            summary=(f"{candidate['experiment_type']} of {candidate['perturbed_entity']}: "
                     f"{candidate['observed_effect']} (measured {candidate['measured_entity']})."
                     if experimental else "A retrieved passage provides contextual information; a direct experiment was not verified."),
            details={"literature": candidate, "query": data.get("query"),
                     "retrieval_timestamp": result.completed_at.isoformat()},
            fingerprint=evidence_fingerprint("literature", {"paper_id": candidate["paper_id"],
                "claim_tested": candidate.get("claim_tested"),
                "experiment_identifier": candidate.get("experiment_identifier", candidate.get("claim_location"))}),
            limitations=limitations, directness=directness,
            context_match=_context_match(context, case.metadata.cell_context),
            source_quality=candidate.get("source_quality", "unknown"),
            support_quality=("limited" if explicit_null and not power else support) if experimental else "limited",
            negative_evidence_type="explicit_null_result" if explicit_null else "not_applicable")
        output.records.append(record)
        if (directness == "direct" and support == "sufficient" and (not explicit_null or power)
            and (not case.metadata.cell_context or _context_match(context, case.metadata.cell_context) == "matched")):
            direct_records.append(record)
            covered_pairs.add((str(candidate["perturbed_entity"]).casefold(),
                               str(candidate["measured_entity"]).casefold()))
    candidate_papers = {c["paper_id"] for c in candidates}
    for item in retrieved:
        if item["paper_id"] in candidate_papers:
            continue
        output.records.append(_record(question, result, raw, run_id, source_type="literature",
            source_id=item["paper_id"], source_uri=item.get("source_reference"),
            claim="Co-mention or contextual search hit",
            summary="The retrieved source mentions relevant entities; a regulatory experiment was not verified.",
            details={"literature": item, "query": data.get("query"),
                     "retrieval_timestamp": result.completed_at.isoformat()},
            fingerprint=evidence_fingerprint("literature", {"paper_id": item["paper_id"],
                "claim": "contextual", "location": item.get("claim_location")}),
            limitations=("Co-mention alone does not establish regulation.",), directness="contextual",
            source_quality="secondary_source", support_quality="limited"))
    # One verified pair cannot answer a question about a complete cascade or fan-out.
    complete = bool(direct_records) and bool(expected_pairs) and expected_pairs <= covered_pairs
    output.question_status = "answered" if complete else "partially_answered" if output.records else "unresolved"
    if not complete:
        output.gap = "No complete direct experimental answer was identified for the queried claim in the searched sources."
    output.potential_conflict = any(values == {"null", "effect"} for values in outcomes.values())
    if output.potential_conflict:
        output.records = [r.model_copy(update={"potential_conflict": True}) for r in output.records]
        output.question_status = "partially_answered"
        output.gap = "Potentially conflicting experimental outcomes require critique; no conflict was adjudicated."
    return output


def normalize_tool_result(question, result, raw, case, config, run_id, evidence_type):
    if result.status == "failed":
        return NormalizedEvidence(question_status="pending",
                                  gap=f"Evidence acquisition failed and may be retried: {result.failure_reason}")
    if result.status == "no_result":
        return NormalizedEvidence(gap="No evidence was identified in the queried source; this is absence of retrieved evidence.")
    if evidence_type == "dataset":
        return _dataset(question, result, raw, case, config, run_id)
    if evidence_type == "network":
        return _network(question, result, raw, case, run_id)
    if evidence_type == "literature":
        return _literature(question, result, raw, case, run_id)
    return NormalizedEvidence(gap="The evidence family has no normalization adapter.")
