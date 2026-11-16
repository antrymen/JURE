"""Typed, context-bound references. Never infer or repair scientific links."""
from copy import deepcopy

# These are object types, not ID prefixes: an arbitrary valid evidence ID is
# allowed, while a question remains a question even if its spelling starts E.
FAILURE_REFERENCE_FIELDS = {
    'related_hypothesis_ids': ('hypotheses', 'hypothesis_id', 'hypothesis'),
    'related_claim_ids': ('claims', 'claim_id', 'mechanistic_claim'),
    'related_evidence_ids': ('evidence_records', 'evidence_id', 'evidence_record'),
    'related_gap_ids': ('evidence_gaps', 'gap_id', 'evidence_gap'),
}


class CriticReferenceError(ValueError):
    pass


def reference_catalog(context):
    catalog = {kind: sorted({row[key] for row in context.get(collection, ())})
               for collection, key, kind in FAILURE_REFERENCE_FIELDS.values()}
    catalog['evidence_question'] = sorted({q['question_id'] for q in context.get('evidence_questions', ())})
    return catalog


def bind_failure_reference_schema(schema, context):
    schema = deepcopy(schema)
    catalog = reference_catalog(context)
    for field, (_, _, kind) in FAILURE_REFERENCE_FIELDS.items():
        node = schema['properties'][field]
        allowed = catalog[kind]
        node['items'] = {'type': 'string', **({'enum': allowed} if allowed else {})}
        node['description'] = f'Only existing {kind} IDs in the supplied context; use [] when none apply. Never substitute a question ID.'
        if not allowed:
            node['maxItems'] = 0
    return schema


def validate_failure_references(response, context):
    if hasattr(response, 'model_dump'):
        response = response.model_dump(mode='json')
    catalog = reference_catalog(context)
    errors = []
    for field, (_, _, kind) in FAILURE_REFERENCE_FIELDS.items():
        invalid = set(response.get(field, ())) - set(catalog[kind])
        if invalid:
            errors.append(f'{field} requires {kind} references; invalid IDs {sorted(invalid)}; '
                          f'allowed IDs {catalog[kind]}. EvidenceQuestion IDs are not EvidenceRecord IDs. '
                          'Return a complete corrected attribution; do not invent records.')
    if errors:
        raise CriticReferenceError('; '.join(errors))


REFERENCE_INSTRUCTIONS = '''Use the typed reference_catalog and context-bound response schema. EvidenceQuestion IDs denote investigation questions, not acquired EvidenceRecords. related_evidence_ids may contain only listed evidence_record IDs; when that list is empty, output []. Questions may be discussed in the reason text without relabeling them as evidence. Do not fabricate, drop, or reinterpret scientific content to accommodate an invalid link; only you may choose the intended valid references in a corrected response.'''
