"""Validate untrusted reasoning before the store performs any authoritative write."""
from collections.abc import Mapping
import json
import re


def parse_backend_output(model, response, *, max_chars=250_000):
    if hasattr(response, 'model_dump'):
        response = response.model_dump(mode='json')
    if isinstance(response, Mapping):
        response = json.dumps(dict(response), ensure_ascii=False, allow_nan=False)
    if not isinstance(response, str):
        raise ValueError('Critic backend must return a JSON object or JSON string')
    if len(response) > max_chars:
        raise ValueError('Critic response exceeds max_response_chars')
    return model.model_validate_json(response)


def validate_hypothesis_audit(case, audit):
    expected = {h.hypothesis_id for h in case.hypotheses if h.current_revision.status != 'rejected'}
    ids = [a.hypothesis_id for a in audit.per_hypothesis]
    if audit.case_id != case.metadata.case_id or set(ids) != expected or len(ids) != len(expected):
        raise ValueError('Hypothesis audit must assess each active hypothesis exactly once in this case')
    failed = any(getattr(a, dim) == 'fail' for a in audit.per_hypothesis for dim in
                 ('groundedness', 'distinctness', 'testability', 'falsifiability', 'discriminability', 'scope'))
    if audit.overall_status == 'pass' and failed:
        raise ValueError('Hypothesis audit cannot pass with an explicit failed design dimension')
    # Free-text coverage notes may describe nonblocking limits or C2 work.
    # Their presence is not a machine-readable FAIL; preserve the Critic verdict.


def normalize_claims(case, claims):
    """Preserve verification identity and criticality for the same hypothesis revision."""
    hypotheses = {h.hypothesis_id: h for h in case.hypotheses if h.current_revision.status != 'rejected'}
    pmap = {p.prediction_id: p for h in hypotheses.values() for p in h.predictions
            if p.hypothesis_revision_id == h.current_revision_id}
    if {c.hypothesis_id for c in claims} != set(hypotheses):
        raise ValueError('Claim decomposition must cover every active hypothesis')
    if len({c.claim_id for c in claims}) != len(claims):
        raise ValueError('Duplicate claim IDs')
    output = []
    for claim in claims:
        hypothesis = hypotheses[claim.hypothesis_id]
        if not claim.derived_from_prediction_ids or any(
            pid not in pmap or pmap[pid].hypothesis_id != claim.hypothesis_id
            for pid in claim.derived_from_prediction_ids
        ):
            raise ValueError('Claim must derive from current predictions of its own hypothesis')
        if claim.hypothesis_revision_id not in (None, hypothesis.current_revision_id):
            raise ValueError('Claim cannot audit a superseded hypothesis revision')
        existing = next((c for c in case.mechanistic_claims if c.hypothesis_id == claim.hypothesis_id
                         and c.hypothesis_revision_id == hypothesis.current_revision_id
                         and c.derived_from_prediction_ids == claim.derived_from_prediction_ids
                         and c.statement == claim.statement and c.claim_type == claim.claim_type), None)
        if existing:
            if claim.critical != existing.critical or claim.criticality_reason != existing.criticality_reason:
                raise ValueError('Critic cannot change established claim criticality to accommodate evidence')
            claim = existing
        else:
            claim = claim.model_copy(update={'hypothesis_revision_id': hypothesis.current_revision_id,
                                             'status': 'insufficient'})
        output.append(claim)
    current_existing = {c.claim_id for c in case.mechanistic_claims
        if c.hypothesis_id in hypotheses and
        c.hypothesis_revision_id == hypotheses[c.hypothesis_id].current_revision_id}
    if current_existing - {c.claim_id for c in output}:
        raise ValueError('Decomposition must preserve all established claims of an unchanged hypothesis revision')
    return tuple(output)


def validate_evidence_audit(case, result, claims, context):
    cids = {c.claim_id for c in claims}
    evidence = {e.evidence_id: e for e in case.evidence_records
                if e.evidence_id in {v['evidence_id'] for v in context['evidence_records']}}
    ids = [a.claim_id for a in result.claim_audits]
    if set(ids) != cids or len(ids) != len(cids):
        raise ValueError('Evidence audit must assess every current claim exactly once')
    seen_eids = {a.evidence_id for a in result.evidence_audits}
    if seen_eids != set(evidence):
        raise ValueError('Evidence audit must inspect every relevant evidence record, including contrary evidence')
    for audit in result.evidence_audits:
        if not set(audit.claim_ids) <= cids:
            raise ValueError('Evidence audit references an unknown current claim')
        raw = evidence[audit.evidence_id]
        complete = bool(raw.provenance.source_id and raw.provenance.tool
                        and (raw.provenance.source_uri or raw.raw_result_reference))
        if audit.provenance_check == 'complete' and not complete:
            raise ValueError('Backend cannot declare incomplete provenance complete')
    for audit in result.claim_audits:
        if not set(audit.evidence_ids) <= set(evidence):
            raise ValueError('Claim audit references evidence outside its stage context')
        if not (set(audit.supporting_evidence_ids) | set(audit.challenging_evidence_ids)) <= set(audit.evidence_ids):
            raise ValueError('Claim polarity references must be included in its evidence IDs')
        if audit.status == 'supported' and audit.challenging_evidence_ids:
            raise ValueError('Unresolved challenging evidence prevents a supported claim')


def validate_synthesis(synthesis, claims, claim_audits, config):
    related = {c.claim_id: c for c in claims if c.hypothesis_id == synthesis.hypothesis_id}
    expected = {'supported': 'supported_claim_ids', 'partially_supported': 'partial_claim_ids',
                'challenged': 'challenged_claim_ids', 'insufficient': 'insufficient_claim_ids'}
    states = {a.claim_id: a.status for a in claim_audits if a.claim_id in related}
    critical = {cid for cid, claim in related.items() if claim.critical}
    counts = dict(total_claims=len(related), critical_claims=len(critical),
        supported_claims=sum(s == 'supported' for s in states.values()),
        partially_supported_claims=sum(s == 'partially_supported' for s in states.values()),
        challenged_claims=sum(s == 'challenged' for s in states.values()),
        insufficient_claims=sum(s == 'insufficient' for s in states.values()),
        supported_critical_claims=sum(states[cid] == 'supported' for cid in critical),
        unresolved_critical_claims=sum(states[cid] != 'supported' for cid in critical),
        challenged_critical_claims=sum(states[cid] == 'challenged' for cid in critical))
    if synthesis.coverage.model_dump() != counts:
        raise ValueError('Descriptive claim coverage counts must match the audited claims')
    for status, field in expected.items():
        if set(getattr(synthesis, field)) != {cid for cid, value in states.items() if value == status}:
            raise ValueError('Hypothesis synthesis must preserve every claim audit status')
    if any(c.critical and states[cid] == 'challenged' for cid, c in related.items()):
        if synthesis.status != 'challenged':
            raise ValueError('A challenged critical claim requires a challenged hypothesis')
    if synthesis.status == 'supported' and config.require_critical_claim_resolution_for_supported:
        if any(c.critical and states[cid] != 'supported' for cid, c in related.items()):
            raise ValueError('Unresolved critical claims prevent SUPPORTED')
    if synthesis.status in {'supported', 'partially_supported'} and not any(
        value in {'supported', 'partially_supported'} for value in states.values()
    ):
        raise ValueError('Hypothesis support requires supporting claim evidence')


def validate_critic_action(action):
    allowed = {'audit', 'decompose_claims', 'update_hypothesis_status', 'create_gap',
               'create_contradiction', 'create_revision_request', 'create_investigation_request',
               'route', 'stop'}
    if action not in allowed:
        raise PermissionError(f'Critic cannot perform {action}')


def scientific_review_flags(case, claims=(), result=None):
    """Fallible concerns returned to the Critic; never a rejection or verdict."""
    flags=[]
    for claim in claims:
        h=next(h for h in case.hypotheses if h.hypothesis_id==claim.hypothesis_id)
        source=' '.join([h.current_revision.mechanism_statement]+[p.statement for p in h.predictions if p.prediction_id in claim.derived_from_prediction_ids])
        tokens=lambda text:set(re.findall(r'\b[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*\b',text))
        if tokens(claim.statement)-tokens(source)-{'A','I','RNA','DNA','GRN','DAY6','DAY8'}:
            flags.append({'code':'CLAIM_ENTITY_PROVENANCE_UNCLEAR','claim_id':claim.claim_id,
                          'instruction':'Assess whether the claim introduces an unsupported mediator; lexical flag only.'})
    if result is not None:
        by_id={e.evidence_id:e for e in case.evidence_records}
        for audit in result.evidence_audits:
            raw=by_id[audit.evidence_id]
            if raw.source_type=='grn' and audit.directness_assessment=='direct':
                flags.append({'code':'NETWORK_DIRECTNESS_REVIEW','evidence_id':audit.evidence_id,
                              'instruction':'Review the directness judgment against the actual source; graph connectivity alone is not causal proof.'})
            if raw.negative_evidence_type=='not_found' and audit.contradiction_detected:
                flags.append({'code':'RETRIEVAL_ABSENCE_REVIEW','evidence_id':audit.evidence_id,
                              'instruction':'Review whether this is absence of retrieval rather than an experimental null.'})
        for audit in result.claim_audits:
            if audit.status in {'supported','challenged'}:
                flags.append({'code':'CLAIM_SUPPORT_JUSTIFICATION_REVIEW','claim_id':audit.claim_id,
                              'instruction':'Judge relevance, context, provenance and experimental support explicitly; no programmed quality threshold decides this verdict.'})
    return flags
