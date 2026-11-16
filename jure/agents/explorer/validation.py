"""Explicitly classified structural checks and fallible scientific audit flags.

The legacy wrapper returns every finding as an error. Three-layer admission
blocks only machine and completeness findings, leaving science to Critic C1.
Atomic case writes and immutable before/after checks remain at the store boundary.
"""

from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from itertools import combinations
from types import SimpleNamespace
from typing import Any

from jure.casefile.models import CaseFile
from jure.casefile.critic_validation import register_critic_objects

from .models import ExplorerConfig, ExplorerOutput, MechanismStructure


def interpret_observation(case_file: CaseFile) -> str:
    """Render only recorded facts, without inventing significance thresholds.

    Requiring the backend to copy this supplied sentence makes observation
    validation deterministic, including the meaning of the binary states. Raw
    statistics retain their reference/condition and discovery/validation stage.
    """
    clue = case_file.clue
    shift = clue.perturbation_shift
    direction = "increased" if shift.delta_frequency > 0 else "decreased" if shift.delta_frequency < 0 else "unchanged"
    parts = [
        f"Perturbation {clue.perturbation!r} is associated with {direction} prevalence "
        f"of the joint expression state {clue.pattern.pattern_string!r} "
        f"(order={clue.pattern.order}).",
        f"Control frequency={shift.control_frequency!r}; perturbation frequency="
        f"{shift.perturb_frequency!r}; delta_frequency={shift.delta_frequency!r}.",
        f"Recorded +/− state semantics (+=1, −=0): {clue.pattern.encoding!r}.",
    ]
    context = {key: getattr(case_file.metadata, key) for key in ("cell_context", "source_dataset")
               if getattr(case_file.metadata, key) is not None}
    if context:
        parts.append("Biological/data context: " + json.dumps(context, ensure_ascii=False, sort_keys=True) + ".")
    parts.append(f"Clue Discovery mode={clue.discovery_mode!r}; replication status={clue.replication_status!r}.")
    for label, value in (
        ("Reference discovery statistics", clue.reference_evidence.discovery),
        ("Reference validation statistics", clue.reference_evidence.validation),
        ("Legacy control statistics", clue.legacy_control),
        ("Legacy perturbation statistics", clue.legacy_perturbation),
    ):
        if value is not None:
            parts.append(label + ": " + json.dumps(value.model_dump(mode="json", exclude_none=True),
                                                    sort_keys=True, ensure_ascii=False) + ".")
    shift_details = shift.model_dump(mode="json", exclude_none=True)
    for key in ("control_frequency", "perturb_frequency", "delta_frequency"):
        shift_details.pop(key)
    parts.append("Perturbation-associated shift statistics: " + json.dumps(shift_details, sort_keys=True,
                                                                         ensure_ascii=False) + ".")
    parts.append("These observations do not by themselves establish a causal regulatory mechanism; "
                 "recorded statistics are not assigned new significance or stability thresholds.")
    return " ".join(parts)


def _objects(case: CaseFile) -> dict[str, str]:
    result = {case.metadata.case_id: "case", case.clue.clue_id: "clue"}
    if case.mechanistic_question:
        result[case.mechanistic_question.question_id] = "mechanistic_question"
        result.update((r.revision_id, "question_revision") for r in case.mechanistic_question.revisions)
    for hypothesis in case.hypotheses:
        result[hypothesis.hypothesis_id] = "hypothesis"
        result.update((r.revision_id, "hypothesis_revision") for r in hypothesis.revisions)
        result.update((p.prediction_id, "prediction") for p in hypothesis.predictions)
    for records, key, kind in (
        (case.evidence_questions, "question_id", "evidence_question"),
        (case.evidence_records, "evidence_id", "evidence_record"),
        (case.evidence_assessments, "assessment_id", "evidence_assessment"),
        (case.evidence_gaps, "gap_id", "evidence_gap"),
        (case.contradictions, "contradiction_id", "contradiction"),
        (case.investigation_history, "event_id", "history_event"),
    ):
        result.update((getattr(record, key), kind) for record in records)
    # Match the authoritative Case File namespace, including Critic requests.
    register_critic_objects(case, lambda identifier, kind: result.__setitem__(identifier, kind))
    return result


def _normalize(text: str) -> str:
    text = text.casefold().replace("→", " to ").replace("->", " to ")
    text = re.sub(r"\b(?:regulates?|controls?|affects?|influences?)\b", "regulate", text)
    text = re.sub(r"\b(?:common|shared)\b", "shared", text)
    text = re.sub(r"\b(?:a|an|the|may|might|could|would|should|possibly|potentially|hypothesis|mechanism)\b", " ", text)
    return " ".join(re.findall(r"\w+", text))


def _simple_edges(text: str, genes: tuple[str, ...]) -> frozenset[tuple[str, str]]:
    """Recognize the explicit active/passive one-edge paraphrases in the spec."""
    edges = set()
    for source in genes:
        for target in genes:
            if source == target:
                continue
            start, end = re.escape(source), re.escape(target)
            verb = r"(?:regulat\w*|control\w*|affect\w*|influenc\w*)"
            active = rf"\b{start}\b\s+(?:(?:may|might|could|can|directly)\s+)*{verb}\s+(?:gene\s+)?\b{end}\b"
            passive = rf"\b{end}\b\s+(?:(?:is|may|might|could|be|directly)\s+)*{verb}\s+by\s+(?:gene\s+)?\b{start}\b"
            response = rf"\b{end}\b\s+(?:(?:may|might|could|can)\s+)*respond\w*\s+to\s+\b{start}\b"
            if any(re.search(pattern, text, flags=re.I) for pattern in (active, passive, response)):
                edges.add((source.casefold(), target.casefold()))
    return frozenset(edges)


def _redundant(left: Any, right: Any, genes: tuple[str, ...]) -> bool:
    a, b = _normalize(left.mechanism_statement), _normalize(right.mechanism_statement)
    if a == b or SequenceMatcher(None, a, b).ratio() >= .91:
        return True
    # Mechanism-type labels cannot rescue the same simple directional claim.
    edges_a, edges_b = _simple_edges(left.mechanism_statement, genes), _simple_edges(right.mechanism_statement, genes)
    extra_structure = re.compile(r"indirect|mediat|conditional|cooperat|upstream|cascade|cell.state|composition|feedback", re.I)
    if edges_a and edges_a == edges_b and not any(extra_structure.search(h.mechanism_statement) for h in (left, right)):
        return True
    sa, sb = getattr(left, "structure", None), getattr(right, "structure", None)
    if sa is None or sb is None:
        return False
    def signature(structure: Any) -> tuple[Any, ...]:
        return (
            _normalize(structure.causal_structure), structure.directness,
            structure.cell_state_explanation, structure.conditional_dependence,
            tuple(sorted(structure.directed_edges)),
            tuple(sorted(_normalize(item) for item in structure.distinguishing_features)),
        )
    return signature(sa) == signature(sb)


_GENERIC_PREDICTION = re.compile(
    r"biologically\s+(?:important|related)|mechanism\s+(?:should\s+be|is)\s+important|"
    r"there\s+should\s+be\s+supporting\s+literature|pathway\s+(?:probably\s+)?plays?\s+a\s+role|"
    r"生物学上.*(?:重要|相关)|应该有支持.*文献", re.I,
)
_OBSERVABLE = re.compile(
    r"connect|regulator|regulatory|edge|network|conditional|enrich|prevalence|frequenc|"
    r"response|perturb|cell.state|composition|program|co.occurr|dependency|dependence|"
    r"binding|occupancy|time.course|temporal|dose|表达|调控|富集|频率|状态|连[接通]|依赖|响应|扰动", re.I,
)
_OVERCLAIM = re.compile(
    r"(?:MFI|d.tuple|frequency\s+shift|bootstrap|association).{0,70}"
    r"\b(?:prove[sd]?|proven|demonstrate[sd]?|establish(?:es|ed)?|confirm(?:s|ed)?)\b.{0,70}"
    r"(?:caus|regulat|activat|repress)|(?:MFI|关联|频率|bootstrap).{0,40}(?:证明|证实).{0,40}(?:调控|因果|激活|抑制)", re.I,
)
# Strip only explicit negated assertion predicates before checking overclaims.
# A negative boundary sentence is not a claim of proof; any remaining positive
# predicate (including a second clause) must still be rejected.
_NEGATED_ASSERTION = re.compile(
    r"\b(?:do(?:es)?\s+not|cannot|can\s+not|never|not\s+sufficient\s+to|not)\s+"
    r"(?:(?:by\s+(?:itself|themselves)|alone|independently|necessarily|directly)\s+)*"
    r"(?:prove[sd]?|proven|demonstrate[sd]?|establish(?:es|ed)?|confirm(?:s|ed)?)\b|"
    r"不(?:能|足以)?(?:证明|证实)", re.I,
)
_NEGATIVE_STATISTICAL_SUBJECT = re.compile(
    r"\bno\s+(?:single\s+)?(?:statistics?|statistical\s+association|association|MFI|bootstrap(?:\s+statistic)?)"
    r"\s+(?:(?:alone|by\s+itself)\s+)?(?:can\s+)?"
    r"(?:prove[sd]?|proven|demonstrate[sd]?|establish(?:es|ed)?|confirm(?:s|ed)?)\b", re.I,
)


def _has_overclaim(text: str) -> bool:
    text = _NEGATIVE_STATISTICAL_SUBJECT.sub('', text)
    return bool(_OVERCLAIM.search(_NEGATED_ASSERTION.sub("", text)))


_MISENCODING = re.compile(
    r"(?:\+|positive|detected).{0,25}(?:means?|denotes?|represents?|=|即|表示).{0,15}"
    r"(?:upregulat|activat|上调|激活)|"
    r"(?:undetected|negative|(?<!\w)-).{0,25}(?:means?|denotes?|represents?|=|即|表示).{0,15}"
    r"(?:downregulat|repress|下调|抑制)", re.I,
)
_NUMERIC_JUDGMENT = re.compile(
    r"\b(?:probability|confidence|score)\s*(?:=|:|of\b|is\b|at\b)?\s*\d+(?:\.\d+)?\s*%?|"
    r"(?:概率|置信度|综合评分)\s*[=:：]?\s*\d+", re.I,
)


def _textual_verdict(text: str, hypothesis_ids: set[str], preserved_ids=()) -> bool:
    # Conditional future evidence is not a verdict issued by the Explorer.
    if re.match(r"\s*(?:if\b|when\b|unless\b|如果|若)", text, re.I) or not hypothesis_ids:
        return False
    # A preservation statement about an untouched existing object is not an
    # evidential 'retained' verdict. Restrict the exception to a complete clause;
    # a separate positive verdict or a proposed/revised ID remains checked.
    for identifier in preserved_ids:
        text = re.sub(rf"\b{re.escape(identifier)}\b\s+(?:is\s+)?retained\s+unchanged(?=\s*[.;:]|\s*$)",
                      '', text, flags=re.I)
    ids = "|".join(re.escape(identifier) for identifier in sorted(hypothesis_ids, key=len, reverse=True))
    return bool(re.search(
        rf"\b(?:{ids})\b\s+(?:(?:is|was|has been|should be|被|已被)\s+)?"
        r"(?:retained|rejected|confirmed|accepted|superior|wins|the winner|better than|保留|拒绝|优于)\b",
        text, re.I,
    ))


def _unbacked_names(text: str, case: CaseFile, additional_allowed: set[str]) -> set[str]:
    """Conservative named-gene/pathway guard; not a full biomedical NER model."""
    available = " ".join((case.clue.perturbation, *case.clue.pattern.genes,
                           case.metadata.cell_context or "", case.metadata.source_dataset or "",
                           json.dumps(case.clue.model_dump(mode="json", exclude={"source_payload"}), ensure_ascii=False),
                           *(json.dumps(e.model_dump(mode="json"), ensure_ascii=False) for e in case.evidence_records)))
    allowed = {word.casefold() for word in re.findall(r"[\w-]+", available)} | additional_allowed
    allowed |= {"mfi", "dna", "rna", "tf", "grn", "llm", "abc", "ci", "nt", "facs", "g1", "g2", "fdr", "fwer", "bh", "by", "qc", "and", "or", "day6", "day8"}
    # A binary pattern such as A+B-C+ is not a molecular name "B-C".
    text = text.replace(case.clue.pattern.pattern_string, " ")
    spaced_pattern = " ".join(gene + ("+" if state else "-")
                               for gene, state in zip(case.clue.pattern.genes, case.clue.pattern.states))
    text = text.replace(spaced_pattern, " ")
    tokens = re.findall(r"\b(?:[A-Z][A-Z0-9-]{1,}|[A-Z][a-z]+\d+|mTOR|NFkB|Wnt|Notch|Hedgehog)\b", text)
    def grounded(token):
        token = token.casefold().strip("-")
        if token in allowed:
            return True
        # Signed states and hyphenated references to known entities introduce
        # no new molecular name. Unknown components remain subject to the guard.
        return "-" in token and all(part in allowed for part in token.split("-"))
    return {token for token in tokens if not grounded(token)}


def _existing_comparison(case: CaseFile, hypothesis: Any) -> Any:
    structure = None
    for event in reversed(case.investigation_history):
        if (event.object_id == hypothesis.hypothesis_id
                and event.metadata.get("hypothesis_revision_id") == hypothesis.current_revision_id
                and event.metadata.get("structure") is not None):
            try:
                structure = MechanismStructure.model_validate(event.metadata["structure"])
            except ValueError:
                pass
            break
    return SimpleNamespace(mechanism_statement=hypothesis.current_revision.mechanism_statement,
                           structure=structure)


def inspect_explorer_output(
    output: ExplorerOutput, case_file: CaseFile, mode: str = "initial", *,
    config: ExplorerConfig | None = None, reframe_reason: str | None = None,
    capability_summary=None,
):
    """Return classified findings without changing state or acquiring evidence.

    Initial exploration checks every pair. Reframing checks every changed
    hypothesis against the available working hypotheses; untouched historical
    pairs need not be re-proposed. Historical objects never consume the batch
    size limit or get deleted to make room.
    """
    config = config or ExplorerConfig()
    from .admission import FindingList
    errors = FindingList()
    if mode not in {"initial", "reframe"}:
        errors.add("machine", "INVALID_MODE", f"Unsupported Explorer mode {mode!r}.")
        return tuple(errors)
    expected_observation=interpret_observation(case_file)
    received_observation=output.observation_interpretation.strip()
    if received_observation != expected_observation:
        from difflib import SequenceMatcher
        differences=[]
        for tag,start,end,received_start,received_end in SequenceMatcher(
                None,expected_observation,received_observation,autojunk=False).get_opcodes():
            if tag!='equal':
                differences.append(f"expected[{start}:{end}]={expected_observation[start:end][:80]!r}; received[{received_start}:{received_end}]={received_observation[received_start:received_end][:80]!r}")
            if len(differences)==4:break
        errors.add('machine', 'INVALID_OBJECT_CONTRACT', "observation_interpretation must exactly preserve the provided observational facts and detected/undetected semantics. Copy context.observation_interpretation_required exactly, including punctuation. Character differences (zero-based): "+'; '.join(differences))
    hypotheses = output.hypotheses
    if config.protocol_v3:
        available={x['capability_id'] for x in (capability_summary or {}).get('observables',[]) if x['availability']=='available'}
        known={h.hypothesis_id for h in case_file.hypotheses}|{h.hypothesis_id for h in hypotheses}
        covered=set()
        for q in output.evidence_questions:
            spec=q.discrimination
            if spec is None:
                errors.add('completeness', 'MISSING_COMPARISON', f'Question {q.question_id} requires a discrimination specification.');continue
            if set(spec.targets)-known or not set(spec.targets)<=set(q.relevant_hypothesis_ids) or not set(spec.targets)<=set(q.discriminates_between):
                errors.add('machine', 'INVALID_OBJECT_CONTRACT', f'Question {q.question_id} comparison targets must be linked existing/proposed hypotheses.')
            if set(spec.capability_ids)-available:
                errors.add('critic_flag', 'CAPABILITY_LIMIT', f'Question {q.question_id} uses unavailable capability IDs: {sorted(set(spec.capability_ids)-available)}')
            if config.validation_policy == 'three_layer':
                from jure.protocol.capabilities import CATALOG
                registered={cid for entries in CATALOG.values() for cid,_ in entries}
                if set(spec.capability_ids)-registered:
                    errors.add('machine','UNKNOWN_CAPABILITY_ID',f'Question {q.question_id} has unknown capability IDs: {sorted(set(spec.capability_ids)-registered)}')
                covered.update(spec.targets)
            elif not set(spec.capability_ids)-available:
                covered.update(spec.targets)
        missing={h.hypothesis_id for h in hypotheses}-covered
        if missing and not output.pair_decisions:errors.add('completeness', 'MISSING_QUESTION_COVERAGE', f'Changed hypotheses need a reachable discriminating question: {sorted(missing)}')
    if mode == "initial":
        if case_file.hypotheses or case_file.mechanistic_question is not None:
            errors.add('machine', 'INVALID_OBJECT_CONTRACT', "initial mode requires a case without an existing hypothesis space; use reframe.")
        if not config.min_hypotheses <= len(hypotheses) <= config.max_hypotheses:
            errors.add('completeness', 'HYPOTHESIS_COUNT', f"initial hypothesis count must be {config.min_hypotheses}..{config.max_hypotheses}.")
    else:
        if not reframe_reason or not reframe_reason.strip():
            errors.add('machine', 'INVALID_OBJECT_CONTRACT', "reframe requires a nonempty reframe reason.")
        if not case_file.hypotheses:
            errors.add('machine', 'INVALID_OBJECT_CONTRACT', "reframe requires existing hypotheses.")
        if not (len(hypotheses) <= config.max_hypotheses and (hypotheses or output.predictions or output.evidence_questions or output.pair_decisions)):
            errors.add('completeness', 'HYPOTHESIS_COUNT', f"reframe must change 1..{config.max_hypotheses} hypotheses; received {len(hypotheses)} "
                          f"changes ({', '.join(h.hypothesis_id for h in hypotheses)}). Both add and revise count. "
                          "Return only the changes selected for this batch; untouched existing hypotheses remain stored.")

    question = output.mechanistic_question
    if case_file.clue.perturbation.casefold() not in question.casefold():
        errors.add('critic_flag', 'QUESTION_SCOPE_UNCLEAR', "mechanistic_question must retain the clue perturbation.")
    if not all(re.search(rf"(?<!\w){re.escape(gene)}(?!\w)", question, re.I) for gene in case_file.clue.pattern.genes):
        errors.add('critic_flag', 'QUESTION_SCOPE_UNCLEAR', "mechanistic_question must retain the clue joint-state genes.")
    if not re.search(r"joint|prevalence|frequenc|co.occurr|pattern|联合|频率|共现|组合", question, re.I):
        errors.add('critic_flag', 'QUESTION_SCOPE_UNCLEAR', "mechanistic_question must ask about the observed joint state, not general gene function.")
    if case_file.metadata.cell_context and case_file.metadata.cell_context.casefold() not in question.casefold():
        errors.add('critic_flag', 'QUESTION_SCOPE_UNCLEAR', "mechanistic_question must preserve the supplied biological cell context.")
    if re.search(r"(?:why|how)\s+(?:does\s+)?(?:perturbation\s+)?"
                 + re.escape(case_file.clue.perturbation)
                 + r"\b.{0,25}\b(?:activates?|represses?|regulates?|controls?)\b", question, re.I):
        errors.add('critic_flag', 'QUESTION_SCOPE_UNCLEAR', "mechanistic_question cannot presuppose a specific causal regulatory mechanism.")
    if (re.search(r"cascade|shared upstream regulator|common upstream regulator|"
                  r"cell.state composition|cooperative regulation|级联|共同上游|协同调控", question, re.I)
            and not re.search(r"\bor\b|\bversus\b|\bwhether\b|或者|还是|是否", question, re.I)):
        errors.add('critic_flag', 'QUESTION_SCOPE_UNCLEAR', "mechanistic_question must remain open to competing mechanisms rather than presupposing one topology.")

    objects = _objects(case_file)
    occupied = set(objects)
    existing = {h.hypothesis_id: h for h in case_file.hypotheses}
    changed: dict[str, Any] = {}
    for hypothesis in hypotheses:
        identifier = hypothesis.hypothesis_id
        if identifier in changed:
            errors.add('machine', 'INVALID_OBJECT_CONTRACT', f"duplicate hypothesis ID {identifier}.")
        changed[identifier] = hypothesis
        if hypothesis.operation == "revise":
            if mode != "reframe" or identifier not in existing:
                errors.add('machine', 'INVALID_OBJECT_CONTRACT', f"revision {identifier} must reference an existing hypothesis in reframe mode.")
            if not hypothesis.reason or not hypothesis.reason.strip():
                errors.add('machine', 'INVALID_OBJECT_CONTRACT', f"revision {identifier} requires a reason.")
            if identifier in existing:
                previous = existing[identifier].current_revision
                fields = ("title", "mechanism_statement", "mechanism_type", "assumptions", "unresolved_points", "weakening_conditions")
                if all(getattr(previous, field) == getattr(hypothesis, field) for field in fields):
                    errors.add('machine', 'INVALID_OBJECT_CONTRACT', f"revision {identifier} must make a substantive change, not merely add a reason.")
        elif identifier in occupied:
            errors.add('machine', 'INVALID_OBJECT_CONTRACT', f"new hypothesis ID {identifier} collides with an existing object.")
        else:
            occupied.add(identifier)
        if hypothesis.derived_from_clue_id != case_file.clue.clue_id:
            errors.add('machine', 'INVALID_OBJECT_CONTRACT', f"hypothesis {identifier} derived_from_clue_id does not match the case clue.")
        if not hypothesis.mechanism_statement.strip():
            errors.add('machine', 'INVALID_OBJECT_CONTRACT', f"hypothesis {identifier} requires a mechanism_statement.")
        if not hypothesis.weakening_conditions:
            errors.add('completeness', 'MISSING_WEAKENING_CONDITION', f"hypothesis {identifier} requires at least one weakening condition.")
        if hypothesis.status != "proposed":
            errors.add('machine', 'INVALID_OBJECT_CONTRACT', f"hypothesis {identifier} cannot set a verdict.")
        prior_lineage = False
        for reference in hypothesis.derived_from:
            kind = "evidence_record" if reference.object_type == "evidence" else reference.object_type
            if objects.get(reference.object_id) != kind:
                errors.add('machine', 'INVALID_OBJECT_CONTRACT', f"hypothesis {identifier} has invalid lineage reference {reference.object_id}.")
            elif kind in {"hypothesis", "hypothesis_revision", "evidence_record", "evidence_gap", "contradiction", "evidence_assessment"}:
                prior_lineage = True
            elif kind == 'revision_request':
                request = next(r for r in case_file.critic_audits.revision_requests
                               if r.request_id == reference.object_id)
                # A request links the redesign to already validated Case File
                # objects. Its prose is design provenance, never new evidence.
                prior_lineage |= bool(request.affected_hypothesis_ids or request.evidence_that_triggered_reframe)
        if mode == "reframe" and not prior_lineage:
            errors.add('machine', 'INVALID_OBJECT_CONTRACT', f"reframed hypothesis {identifier} needs lineage to a prior hypothesis, evidence, gap, "
                          "contradiction, assessment, or a Critic revision request linked to prior hypotheses/evidence.")

    working = {identifier: _existing_comparison(case_file, h) for identifier, h in existing.items()
               if h.current_revision.status != "rejected"}
    working.update(changed)
    if len(working) < config.min_hypotheses:
        errors.add('completeness', 'HYPOTHESIS_COUNT', f"the working hypothesis space requires at least {config.min_hypotheses} competing hypotheses.")
    pairs = {frozenset((a, b)) for a, b in combinations(working, 2) if a in changed or b in changed}
    for pair in pairs:
        a, b = sorted(pair)
        if _redundant(working[a], working[b], case_file.clue.pattern.genes):
            errors.add('critic_flag', 'HYPOTHESIS_DISTINCTNESS_UNCLEAR', f"redundant hypotheses {a} and {b}: a different label does not establish a distinct mechanism.")
    contrasts: set[frozenset[str]] = set()
    for contrast in output.contrasts:
        pair = frozenset((contrast.hypothesis_a, contrast.hypothesis_b))
        if len(pair) != 2 or not pair.issubset(working):
            errors.add('machine', 'INVALID_OBJECT_CONTRACT', "hypothesis contrast must identify two distinct existing working hypotheses.")
        elif pair in contrasts:
            errors.add('machine', 'INVALID_OBJECT_CONTRACT', "duplicate hypothesis contrast.")
        contrasts.add(pair)
        if len(contrast.difference.split()) < 4 and len(contrast.difference) < 15:
            errors.add('critic_flag', 'CONTRAST_SPECIFICITY_UNCLEAR', "hypothesis contrast must state a substantive structural difference.")
    if output.pair_decisions:
        expected_pairs = {frozenset(p) for p in combinations(working, 2)}
        decisions = {}
        for decision in output.pair_decisions:
            pair = frozenset((decision.hypothesis_a, decision.hypothesis_b))
            if pair not in expected_pairs or pair in decisions:
                errors.add('machine', 'INVALID_PAIR_DECISION', 'Pair decisions must identify unique working pairs.')
            decisions[pair] = decision
            if decision.status == 'RELEVANT_TO_DISTINGUISH' and (pair not in contrasts or not any(
                    pair <= set(q.discriminates_between) for q in output.evidence_questions)):
                errors.add('completeness', 'MISSING_SELECTED_PAIR_DESIGN', f'Selected pair {sorted(pair)} requires its design.')
        if set(decisions) != expected_pairs:
            errors.add('completeness', 'MISSING_PAIR_DECISION', 'Every enumerated pair needs a relevance decision, not a full design.')
    elif pairs - contrasts:
        missing = sorted(tuple(sorted(pair)) for pair in pairs - contrasts)
        errors.add('completeness', 'MISSING_PAIR_CONTRAST', "hypothesis contrasts must explain every pair involving a proposed or revised hypothesis. "
                      f"Missing hypothesis ID pairs: {missing}. Unchanged, non-rejected hypotheses remain "
                      "in the working set; adding a new ID does not remove an old hypothesis.")

    predictions: dict[str, Any] = {}
    for prediction in output.predictions:
        identifier = prediction.prediction_id
        if identifier in occupied:
            errors.add('machine', 'INVALID_OBJECT_CONTRACT', f"prediction ID {identifier} collides with another object.")
        occupied.add(identifier)
        predictions[identifier] = prediction
        if prediction.hypothesis_id not in working:
            errors.add('machine', 'INVALID_OBJECT_CONTRACT', f"prediction {identifier} must belong to a working hypothesis.")
        alternatives = set(prediction.discriminates_from_hypotheses)
        if not alternatives and not output.pair_decisions:
            errors.add('completeness','MISSING_ALTERNATIVE',f'prediction {identifier} requires an alternative hypothesis.')
        if prediction.hypothesis_id in alternatives or not alternatives.issubset(working):
            errors.add('machine', 'INVALID_OBJECT_CONTRACT', f"prediction {identifier} requires a valid nonself alternative hypothesis.")
        if len(alternatives) != len(prediction.discriminates_from_hypotheses):
            errors.add('machine', 'INVALID_OBJECT_CONTRACT', f"prediction {identifier} has duplicate alternatives.")
        if not prediction.weakened_if_observed.strip():
            errors.add('completeness', 'MISSING_WEAKENING_CONDITION', f"prediction {identifier} requires weakened_if_observed.")
        if _GENERIC_PREDICTION.search(prediction.statement) or not _OBSERVABLE.search(prediction.statement):
            errors.add('critic_flag', 'OBSERVABILITY_UNCLEAR', f"prediction {identifier} is not a testable discriminating prediction.")
        if prediction.status != "untested":
            errors.add('machine', 'INVALID_OBJECT_CONTRACT', f"prediction {identifier} cannot claim an investigation result.")
    for identifier in changed:
        if not any(p.hypothesis_id == identifier for p in output.predictions) and not (
                output.pair_decisions and identifier in existing and existing[identifier].predictions):
            errors.add('completeness', 'MISSING_PREDICTION', f"hypothesis {identifier} requires at least one prediction.")

    has_discriminating_question = False
    covered_predictions: set[str] = set()
    # New questions may reference immutable predictions already in the Case
    # File. Their original hypothesis revision remains authoritative; reference
    # lookup must not require the model to duplicate scientific content.
    prior_predictions = {p.prediction_id: p for h in case_file.hypotheses
                         for p in h.predictions} if mode == 'reframe' else {}
    available_predictions = {**prior_predictions, **predictions}
    for evidence_question in output.evidence_questions:
        identifier = evidence_question.question_id
        if identifier in occupied:
            errors.add('machine', 'INVALID_OBJECT_CONTRACT', f"evidence question ID {identifier} collides with another object.")
        occupied.add(identifier)
        sources = set(evidence_question.derived_from_prediction_ids)
        covered_predictions.update(sources)
        relevant = set(evidence_question.relevant_hypothesis_ids)
        discriminates = set(evidence_question.discriminates_between)
        if not sources or not sources.issubset(available_predictions):
            errors.add('machine', 'INVALID_OBJECT_CONTRACT', f"evidence question {identifier} requires valid prediction lineage from this proposal or the Case File.")
        if not relevant or not relevant.issubset(working):
            errors.add('machine', 'INVALID_OBJECT_CONTRACT', f"evidence question {identifier} requires relevant hypothesis IDs.")
        if discriminates and len(discriminates) < 2:
            errors.add('completeness', 'MISSING_COMPARISON_TARGETS', f'evidence question {identifier} requires at least two comparison targets.')
        if discriminates and not discriminates.issubset(relevant):
            errors.add('machine', 'INVALID_OBJECT_CONTRACT', f"evidence question {identifier} must discriminate between at least two relevant hypotheses.")
        supported_comparison: set[str] = set()
        for source in sources & available_predictions.keys():
            prediction = available_predictions[source]
            owner = prediction.hypothesis_id
            if source in prior_predictions and (owner in changed or
                    prediction.hypothesis_revision_id != existing[owner].current_revision_id):
                errors.add('critic_flag', 'PRIOR_REVISION_PREDICTION',
                    f"Question {identifier} cites prediction {source} from revision "
                    f"{prediction.hypothesis_revision_id}; its applicability to the new/current "
                    "hypothesis revision requires audit. The original binding is preserved.")
            if owner not in relevant:
                errors.add('machine', 'INVALID_OBJECT_CONTRACT', f"evidence question {identifier} omits the owner of prediction {source}.")
            comparison = {owner, *prediction.discriminates_from_hypotheses}
            supported_comparison.update(comparison)
            if discriminates and owner not in discriminates:
                errors.add('machine', 'INVALID_OBJECT_CONTRACT', f"evidence question {identifier} discrimination must include its source prediction owner.")
        if discriminates and not discriminates.issubset(supported_comparison) and not output.pair_decisions:
            errors.add('machine', 'INVALID_OBJECT_CONTRACT', f"evidence question {identifier} comparison does not follow from its prediction lineage.")
        if len(discriminates) >= 2 and discriminates.issubset(relevant & supported_comparison):
            has_discriminating_question = True
        if evidence_question.status != "pending":
            errors.add('machine', 'INVALID_OBJECT_CONTRACT', f"evidence question {identifier} cannot claim an investigation result.")
    if not has_discriminating_question and not output.pair_decisions:
        errors.add('completeness', 'MISSING_COMPARISON', "at least one evidence question must discriminate between two or more hypotheses.")
    for identifier in (predictions.keys() - covered_predictions if not output.pair_decisions else ()):
        errors.add('completeness', 'MISSING_QUESTION_FOR_PREDICTION', f"prediction {identifier} requires a derived evidence question.")

    # Object names remain identifiers even when their add/revise operation is
    # invalid. Report the operation error without misclassifying IDs as genes.
    allowed_ids = {identifier.casefold() for identifier in occupied | set(changed)}
    scientific_texts = [question]
    for hypothesis in hypotheses:
        scientific_texts.extend((hypothesis.title, hypothesis.mechanism_statement, *hypothesis.assumptions,
                                 *hypothesis.unresolved_points, *hypothesis.weakening_conditions))
        scientific_texts.extend((hypothesis.structure.causal_structure,
                                 *hypothesis.structure.distinguishing_features,
                                 *(node for edge in hypothesis.structure.directed_edges for node in edge)))
        # A concrete edge among clue genes is only a possibility unless backed
        # by existing evidence, and must be explicitly labeled as assumed.
        evidence_text = " ".join(e.claim_tested + " " + e.result_summary for e in case_file.evidence_records)
        for source, target in hypothesis.structure.directed_edges:
            evidence_mentions = all(re.search(rf"(?<!\w){re.escape(node)}(?!\w)", evidence_text, re.I)
                                    for node in (source, target))
            possibility_text = " ".join((hypothesis.mechanism_statement, *hypothesis.assumptions,
                                          *hypothesis.unresolved_points))
            assumed = bool(re.search(r"assum|untested|unverif|hypothetic|hypothes|candidate|could|may|might|"
                                     r"待验证|假设|可能|尚未验证", possibility_text, re.I))
            if not evidence_mentions and not assumed:
                errors.add('critic_flag', 'CAUSAL_LANGUAGE_TOO_STRONG', f"hypothesis {hypothesis.hypothesis_id} must label its directed edge {source}->{target} as an unverified possibility in the mechanism statement or assumptions (for example, an explicit assumed/untested qualifier).")
    for prediction in output.predictions:
        scientific_texts.extend((prediction.statement, prediction.expected_if_true, prediction.weakened_if_observed))
    scientific_texts.extend(q.question_text for q in output.evidence_questions)
    for question in output.evidence_questions:
        spec=question.discrimination
        if spec:
            scientific_texts.extend((spec.observable,spec.scope_limit))
            scientific_texts.extend(x.prediction for x in spec.expectations)
            for outcome in spec.possible_outcomes:
                scientific_texts.extend((outcome.observation,outcome.interpretation_limit))
    scientific_texts.extend(contrast.difference for contrast in output.contrasts)
    scientific_texts.extend(output.warnings)
    for text in scientific_texts:
        if _NUMERIC_JUDGMENT.search(text) or _textual_verdict(text, set(working), set(existing) - set(changed)):
            errors.add('critic_flag', 'UNAUTHORIZED_VERDICT_LANGUAGE', "Explorer cannot issue numerical hypothesis scores, rankings or final verdicts in text.")
        if _has_overclaim(text):
            errors.add('critic_flag', 'CAUSAL_LANGUAGE_TOO_STRONG', "statistical association/MFI/bootstrap cannot be presented as proof of a causal mechanism.")
        if "detected" in case_file.clue.pattern.encoding.casefold() and _MISENCODING.search(text):
            errors.add('critic_flag', 'STATE_INTERPRETATION_UNCLEAR', "detected/undetected states cannot be relabeled as activation/repression or up/down regulation.")
        names = _unbacked_names(text, case_file, allowed_ids)
        if names:
            errors.add('critic_flag', 'UNSUPPORTED_NAMED_ENTITY', "unsupported named molecular specifics require case evidence: " + ", ".join(sorted(names)) + ". C1 must assess hypothetical status, provenance needs and whether evidence acquisition is required; a name outside the input is not itself a scientific verdict.")
    return tuple(errors)


def validate_explorer_output(output, case_file, mode="initial", *, config=None, reframe_reason=None, capability_summary=None):
    """Legacy API retains all diagnostic messages as blocking errors."""
    return tuple(f.message for f in inspect_explorer_output(output, case_file, mode,
        config=config, reframe_reason=reframe_reason, capability_summary=capability_summary))
