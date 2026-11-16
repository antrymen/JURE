"""Read-only S3/S4/S5 audit. No provider, invented rationale or repaired design."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pydantic import ValidationError
from jure.agents.explorer.content_adapter import content_model
from jure.agents.explorer.pairwise_adapter import enumerate_pairs, design_model_for_prediction_counts
from jure.protocol.normalization import normalize_output


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def audit(root):
    source = Path('outputs/contract_stabilization_v1_20260928/smoke')
    frozen = json.loads((source / 'SMOKE_FROZEN.json').read_text())
    root.mkdir(parents=True, exist_ok=False)
    rows, hashes = [], {}
    for i in (3, 4, 5):
        folder = source / 'model_calls' / f'call_{i:04d}_explorer'
        request_path, response_path = folder / 'request.json', folder / 'response.json'
        hashes.update({str(p): sha(p) for p in (request_path, response_path)})
        request = json.loads(json.loads(request_path.read_text())['messages'][1]['content'])
        raw = json.loads(response_path.read_text())['content']
        model = content_model(request['context'])
        normalized, normalization = normalize_output(raw, role='explorer', method='initial_content',
            schema=model.model_json_schema(), context=request['context'])
        content = model.model_validate(normalized)
        n = len(content.hypotheses)
        plan = enumerate_pairs(n)
        schema_model = design_model_for_prediction_counts(tuple(len(h.predictions) for h in content.hypotheses))
        contrasts = {(min(c.hypothesis_a, c.hypothesis_b), max(c.hypothesis_a, c.hypothesis_b)): c.difference
                     for c in content.contrasts}
        missing = [p['key'] for p in plan if (p['first'], p['second']) not in contrasts]
        conflicts, self_alternatives = [], []
        for hi, h in enumerate(content.hypotheses, 1):
            for pi, p in enumerate(h.predictions, 1):
                for alt in p.alternatives:
                    if alt.hypothesis == hi:
                        self_alternatives.append(dict(hypothesis=hi, prediction=pi,
                            raw_alternative=alt.model_dump(mode='json'),
                            allowed_alternatives=[j for j in range(1, n + 1) if j != hi]))
                for oi, o in enumerate(p.evidence_question.possible_outcomes, 1):
                    if o.non_discriminating and (o.favors or o.weakens) or set(o.favors) & set(o.weakens):
                        conflicts.append(dict(hypothesis=hi, prediction=pi, outcome=oi,
                            raw_value=o.model_dump(mode='json'), new_relation=None,
                            disposition='EXPLORER_REQUIRED_NO_LABEL_GUESS'))
        # Only existing differences are projected; all other required answers stay absent.
        partial = {p['key']: {'difference': contrasts[(p['first'], p['second'])]}
                   for p in plan if (p['first'], p['second']) in contrasts}
        try:
            schema_model.model_validate(partial)
            raise AssertionError('Incomplete historical projection must not pass')
        except ValidationError as error:
            incomplete = [{'path': list(e['loc']), 'type': e['type']}
                          for e in error.errors(include_input=False, include_context=False, include_url=False)]
        row = dict(slot=f'S{i}', source=str(response_path), schema_before_pairwise_pass=True,
            required_pairs=plan, missing_legacy_contrasts=missing, contradictory_legacy_outcomes=conflicts,
            legacy_self_alternatives=self_alternatives, existing_contrasts_only=partial,
            partial_projection_errors=incomplete, new_proposal_submitted=False,
            new_scientific_fields_authored=False, automatic_scientific_conversion=False,
            limitation='Historical outputs used another contract and have no separate stage B or outcome reasons. Do not count partial projections as new-interface attempts or fabricate missing answers.')
        (root / f'S{i}_SCHEMA.json').write_text(json.dumps(schema_model.model_json_schema(), indent=2) + '\n')
        (root / f'S{i}_NORMALIZATION.json').write_text(json.dumps(normalization, ensure_ascii=False, indent=2) + '\n')
        rows.append(row)
    assert all(sha(p) == value for p, value in hashes.items())
    summary = dict(version='initial-pairwise-v1', scope='OFFLINE_HISTORICAL_DIAGNOSIS', rows=rows,
        sources=hashes, source_hashes_unchanged=True, model_calls=0, evidence_calls=0, critic_calls=0,
        casefile_writes=0, proposals_repaired=0, scientific_validity='NOT_ASSESSED',
        future_smoke_slots=[{k: c[k] for k in ('slot', 'type', 'path', 'sha256')} for c in frozen['cases']])
    (root / 'HISTORICAL_AUDIT.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps([dict(slot=r['slot'], missing_pairs=r['missing_legacy_contrasts'],
        contradictory_outcomes=len(r['contradictory_legacy_outcomes']), self_alternatives=len(r['legacy_self_alternatives'])) for r in rows]))
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--output', required=True)
    audit(Path(parser.parse_args().output))
