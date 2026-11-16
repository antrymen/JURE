"""Three-layer proposal admission: typed objects, required design, C1 flags.

No content repair, biological adjudication, evidence acquisition or model calls.
The legacy validator is retained as an explicit historical policy.
"""
from typing import Literal
from pydantic import ValidationError
from jure.casefile.models import FrozenModel, Identifier, Text
from jure.protocol.contracts import HypothesisExpectation, PossibleOutcome
from .models import ExplorerOutput, EvidenceQuestionProposal

POLICY = 'three_layer'
from jure.protocol.admission import POLICY_VERSION


class ValidationFinding(FrozenModel):
    layer: Literal['machine', 'completeness', 'critic_flag']
    code: Text
    message: Text
    path: str = 'proposal'


class FindingList(list):
    def add(self, layer, code, message, path='proposal'):
        item = ValidationFinding(layer=layer, code=code, message=message, path=path)
        if item not in self:
            self.append(item)


class ComparisonDraft(FrozenModel):
    # Required fields and their types are machine constraints. Content presence
    # and links are classified separately before anything reaches CaseStore.
    targets: tuple[Identifier, ...]
    expectations: tuple[HypothesisExpectation, ...]
    observable: Text
    capability_ids: tuple[Identifier, ...]
    possible_outcomes: tuple[PossibleOutcome, ...]
    scope_limit: Text


class AdmissionQuestion(EvidenceQuestionProposal):
    discrimination: ComparisonDraft | None = None


class AdmissionProposal(ExplorerOutput):
    evidence_questions: tuple[AdmissionQuestion, ...]


class AdmissionResult(FrozenModel):
    policy_version: str = POLICY_VERSION
    findings: tuple[ValidationFinding, ...] = ()

    @property
    def decision(self):
        if any(f.layer == 'machine' for f in self.findings):
            return 'REJECT'
        if any(f.layer == 'completeness' for f in self.findings):
            return 'RETURN_TO_EXPLORER'
        return 'ADMIT_TO_INVESTIGATOR'

    @property
    def blocking_messages(self):
        return tuple(f'{f.layer}:{f.code}: {f.message}' for f in self.findings if f.layer != 'critic_flag')

    @property
    def audit_flags(self):
        return tuple(f for f in self.findings if f.layer == 'critic_flag')


def inspect_comparisons(output):
    findings = FindingList()
    for q in output.evidence_questions:
        spec = q.discrimination
        if spec is None:
            continue  # Missing comparison is handled by the proposal checks.
        def add(layer, code, message):
            findings.add(layer, code, message, f'evidence_questions.{q.question_id}.discrimination')
        targets = set(spec.targets)
        if len(targets) < 2:
            add('completeness', 'MISSING_COMPARISON_TARGETS', 'Need at least two comparison targets.')
        if len(targets) != len(spec.targets):
            add('machine', 'DUPLICATE_REFERENCE', 'Duplicate comparison target.')
        ids = [x.hypothesis_id for x in spec.expectations]
        if set(ids) - targets or len(set(ids)) != len(ids):
            add('machine', 'INVALID_EXPECTATION_REFERENCE', 'Expectation owner is duplicated or outside targets.')
        for missing in sorted(targets - set(ids)):
            add('completeness', 'MISSING_TARGET_EXPECTATION', f'Missing expectation for {missing}.')
        if len(spec.expectations) >= 2 and len({x.prediction.strip() for x in spec.expectations}) < 2:
            add('critic_flag', 'DISCRIMINATION_UNCLEAR', 'Expectations repeat verbatim; C1 must assess discriminating value.')
        if not spec.capability_ids:
            add('completeness', 'MISSING_OBSERVABLE_MAPPING', 'No observable capability mapping.')
        if len(spec.possible_outcomes) < 2:
            add('completeness', 'MISSING_OUTCOMES', 'Need at least two outcome branches.')
        outcome_ids = [x.outcome_id for x in spec.possible_outcomes]
        if len(outcome_ids) != len(set(outcome_ids)):
            add('machine', 'DUPLICATE_OUTCOME_ID', 'Duplicate outcome ID within a comparison.')
        for outcome in spec.possible_outcomes:
            favors, weakens = set(outcome.favors), set(outcome.weakens)
            if (favors | weakens) - targets:
                add('machine', 'INVALID_OUTCOME_REFERENCE', f'{outcome.outcome_id}: outcome references outside targets.')
            if favors & weakens or (outcome.non_discriminating and (favors or weakens)):
                add('machine', 'CONTRADICTORY_OUTCOME_LABELS', f'{outcome.outcome_id}: contradictory structured labels.')
        if not any(x.non_discriminating for x in spec.possible_outcomes):
            add('completeness', 'MISSING_NEUTRAL_OUTCOME', 'Include an explicitly non-discriminating outcome.')
        if not any(x.favors or x.weakens for x in spec.possible_outcomes):
            add('completeness', 'MISSING_DIRECTIONAL_OUTCOME', 'Include at least one conditionally discriminating outcome.')
    return findings


def admit_proposal(payload, case, *, config, mode='initial', reframe_reason=None, capability_summary=None):
    """Return a typed draft plus findings. Never commit or modify science."""
    try:
        output = AdmissionProposal.model_validate_json(payload) if isinstance(payload, str) else AdmissionProposal.model_validate(payload)
    except ValidationError as error:
        return None, AdmissionResult(findings=tuple(ValidationFinding(layer='machine', code='SCHEMA_TYPE_FIELD',
            message=e['msg'], path='.'.join(map(str, e['loc'])))
            for e in error.errors(include_input=False, include_context=False, include_url=False)))
    from .validation import inspect_explorer_output
    findings = FindingList(inspect_explorer_output(output, case, mode, config=config,
        reframe_reason=reframe_reason, capability_summary=capability_summary))
    findings.extend(inspect_comparisons(output))
    return output, AdmissionResult(findings=tuple(findings))
