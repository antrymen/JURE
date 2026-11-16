"""Rebuildable audit exports, derived exclusively from the committed Case File."""
import csv
import io
import json
from pathlib import Path
from jure.casefile.models import FrozenModel, Identifier, Text
from jure.casefile.critic_models import CriticStatus
from jure.casefile.store import _atomic_write
from .context import active_claims


class ClaimEvidenceRow(FrozenModel):
    hypothesis_id: Identifier
    claim_id: Identifier
    claim: Text
    dataset: str
    network: str
    literature: str
    critic_status: CriticStatus
    critical: bool
    critical_gap_ids: tuple[Identifier, ...] = ()
    evidence_ids: tuple[Identifier, ...] = ()
    contradiction_ids: tuple[Identifier, ...] = ()


class ClaimEvidenceMatrix(FrozenModel):
    case_id: Identifier
    rows: tuple[ClaimEvidenceRow, ...] = ()


def build_claim_evidence_matrix(case):
    evidence = {e.evidence_id: e for e in case.evidence_records}
    latest = {a.claim_id: a for a in case.critic_audits.claim_audits}
    audits = {(a.evidence_id, cid): a for a in case.critic_audits.evidence_audits for cid in a.claim_ids}
    rows = []
    for claim in active_claims(case):
        audit = latest.get(claim.claim_id)
        values = {'dataset': [], 'network': [], 'literature': []}
        for eid in audit.evidence_ids if audit else ():
            record = evidence[eid]
            family = 'network' if record.source_type == 'grn' else record.source_type
            if family not in values:
                continue
            quality = audits.get((eid, claim.claim_id))
            relation = 'challenging' if eid in audit.challenging_evidence_ids else (
                'supporting' if eid in audit.supporting_evidence_ids else 'inconclusive')
            detail = f'{eid}: {relation}'
            if quality:
                detail += f' ({quality.directness_assessment}, {quality.context_assessment}, {quality.support_quality_assessment})'
            values[family].append(detail)
        rows.append(ClaimEvidenceRow(hypothesis_id=claim.hypothesis_id, claim_id=claim.claim_id,
            claim=claim.statement, **{key: '; '.join(value) or 'not tested' for key, value in values.items()},
            critic_status=claim.status, critical=claim.critical,
            critical_gap_ids=tuple(g.gap_id for g in case.evidence_gaps if g.critical
                and g.status != 'addressed' and claim.claim_id in g.related_claim_ids),
            evidence_ids=audit.evidence_ids if audit else (),
            contradiction_ids=audit.contradiction_ids if audit else ()))
    return ClaimEvidenceMatrix(case_id=case.metadata.case_id, rows=tuple(rows))


def investigation_trajectory(case):
    return [{'sequence': event.sequence, 'case_revision': event.case_revision,
             'timestamp': event.timestamp.isoformat(), 'actor': event.actor,
             'action': event.action, 'summary': event.summary,
             'object_type': event.object_type, 'object_id': event.object_id,
             'metadata': event.metadata.to_dict()} for event in case.investigation_history]


def export_critic_artifacts(case, result, directory):
    directory = Path(directory)
    def save(name, value):
        if hasattr(value, 'model_dump'):
            value = value.model_dump(mode='json')
        return _atomic_write(directory / name, json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    save('critic_run.json', result)
    matrix = build_claim_evidence_matrix(case)
    save('hypothesis_evidence_matrix.json', matrix)
    stream = io.StringIO(newline='')
    fields = list(ClaimEvidenceRow.model_fields)
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    for row in matrix.rows:
        values = row.model_dump(mode='json')
        writer.writerow({key: json.dumps(value) if isinstance(value, list) else value for key, value in values.items()})
    _atomic_write(directory / 'hypothesis_evidence_matrix.csv', stream.getvalue())
    save('investigation_trajectory.json', investigation_trajectory(case))
    for field, name in [('hypothesis_audits', 'hypothesis_audit.json'), ('evidence_audits', 'evidence_audit.json'),
                        ('claim_audits', 'claim_evidence_audit.json'), ('hypothesis_syntheses', 'hypothesis_synthesis.json'),
                        ('routing_decisions', 'routing_decision.json'), ('stop_records', 'stop_record.json')]:
        save(name, [value.model_dump(mode='json') for value in getattr(case.critic_audits, field)
                    if value.critic_round == result.critic_round])
    if result.final_report_id:
        save('critic_final_report.json', next(r for r in case.critic_audits.final_reports
                                              if r.report_id == result.final_report_id))
    return directory
