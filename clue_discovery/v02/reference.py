"""Discovery-only search followed by locked reference-cell validation."""
from dataclasses import dataclass
import hashlib
from itertools import combinations, product
import json
import math
from pathlib import Path
import pandas as pd
from ..patterns import JointPattern
from ..candidate_search import merge_candidates
from ..statistics import benjamini_hochberg
from ..io import json_safe
from .config import ReferenceConfig, config_dict
from .populations import assert_disjoint
from .statistics import joint_table, pattern_code, stable_reference


def canonical_json(value):
    return json.dumps(json_safe(value), sort_keys=True, separators=(',', ':'), allow_nan=False)


def identity(pattern):
    return 'R' + hashlib.sha256(canonical_json([pattern.genes, pattern.states]).encode()).hexdigest()[:16]


def binary_fingerprint(matrix, cell_ids):
    digest = hashlib.sha256(canonical_json([list(matrix.columns), list(cell_ids)]).encode())
    digest.update(matrix.to_numpy(dtype='uint8').tobytes())
    return digest.hexdigest()


BASE_COLUMNS = ['reference_id', 'genes', 'states', 'pattern_string', 'order', 'support', 'state_support',
                'expected_support', 'frequency', 'mfi', 'state_table_occupancy', 'zero_state_count',
                'zero_state_fraction', 'min_state_count', 'min_observed_state_count',
                'p_value_null', 'q_value_null', 'stable_in_discovery', 'KEEP_AS_REFERENCE', 'EXPAND', 'PRUNE']
LOG_COLUMNS = ['reference_id', 'pattern_string', 'order', 'generated_from', 'KEEP_AS_REFERENCE',
               'EXPAND', 'PRUNE', 'expansion_reason']
VALIDATION_COLUMNS = BASE_COLUMNS[:17] + ['reference_mfi_direction_consistent',
                                        'replicated_in_reference_validation', 'validation_reason']


def table(rows, columns):
    return pd.DataFrame(rows).reindex(columns=list(dict.fromkeys(columns + [k for r in rows for k in r])))


def write_table(frame, path):
    frame = frame.copy()
    for column in frame:
        frame[column] = frame[column].map(lambda x: canonical_json(x) if isinstance(x, (dict, list, tuple)) else x)
    frame.to_csv(path, index=False)


@dataclass(frozen=True)
class FrozenCatalogue:
    """Immutable serialized evidence and split identities, with a tamper-evident digest."""
    payload_json: str
    sha256: str

    def __post_init__(self):
        if hashlib.sha256(self.payload_json.encode()).hexdigest() != self.sha256:
            raise ValueError('catalogue checksum mismatch')

    @classmethod
    def create(cls, payload):
        raw = canonical_json(payload)
        return cls(raw, hashlib.sha256(raw.encode()).hexdigest())

    @property
    def payload(self):
        return json.loads(self.payload_json)

    @property
    def patterns(self):
        return tuple(JointPattern(tuple(r['genes']), tuple(r['states'])) for r in self.payload['records'])

    def to_frame(self):
        return table(self.payload['records'], BASE_COLUMNS[:17] + ['reference_validation'])

    def save(self, path):
        Path(path).write_text(canonical_json(dict(payload=self.payload, sha256=self.sha256)) + '\n')

    @classmethod
    def load(cls, path):
        saved = json.loads(Path(path).read_text())
        return cls(canonical_json(saved['payload']), saved['sha256'])


@dataclass
class ReferenceResult:
    candidates: pd.DataFrame
    search_log: pd.DataFrame
    validation: pd.DataFrame
    catalogue: FrozenCatalogue
    order_summary: pd.DataFrame
    gene_qc: pd.DataFrame
    metadata: dict

    def write(self, output_dir):
        folder = Path(output_dir)
        folder.mkdir(parents=True, exist_ok=True)
        for filename, frame in [('reference_candidates.csv', self.candidates),
                                ('reference_search_log.csv', self.search_log),
                                ('reference_validation.csv', self.validation),
                                ('frozen_reference_catalogue.csv', self.catalogue.to_frame()),
                                ('order_summary.csv', self.order_summary), ('reference_gene_qc.csv', self.gene_qc)]:
            write_table(frame, folder / filename)
        self.catalogue.save(folder / 'frozen_reference_catalogue.json')
        (folder / 'reference_metadata.json').write_text(canonical_json(self.metadata) + '\n')
        return folder


def evaluate(matrix, pattern, config, stage, cache):
    if pattern.genes not in cache:
        cache[pattern.genes] = joint_table(matrix, pattern.genes, config, stage)
    return dict(cache[pattern.genes][pattern_code(pattern)], genes=pattern.genes, states=pattern.states,
                reference_id=identity(pattern), pattern_string=pattern.to_string())


def apply_null_fdr(rows):
    for row, q in zip(rows, benjamini_hochberg([r['p_value_null'] for r in rows])):
        row['q_value_null'] = float(q)


def discovery_search(matrix, config):
    """Only enumerate pairs. Every higher-order candidate is a compatible join."""
    genes = sorted(matrix.columns)
    n_pairs = 4 * math.comb(len(genes), 2)
    if n_pairs > config.max_candidates:
        raise ValueError('candidate budget exceeded at level 2; reduce the input module')
    generation = {JointPattern(g, s): [] for g in combinations(genes, 2) for s in product((0, 1), repeat=2)}
    rows, logs, summaries = [], [], []
    stop_reason = 'max_order'
    for order in range(2, config.max_order + 1):
        if not generation:
            stop_reason = 'no_expandable_candidates' if rows else 'fewer_than_two_eligible_genes'
            break
        cache, expandable, level = {}, [], []
        for pattern, parents in generation.items():
            row = evaluate(matrix, pattern, config, 'discovery', cache)
            if not row['table_quality_pass']:
                expand, reason = False, 'sparse_state_table'
            elif row['support'] < config.min_support:
                expand, reason = False, 'insufficient_pattern_support'
            elif row['expected_support'] < config.expansion_min_expected:
                expand, reason = False, 'insufficient_expected_support'
            elif config.allow_support_only or row['p_value_null'] <= config.expansion_p:
                expand, reason = True, ('null_deviation' if row['p_value_null'] <= config.expansion_p else 'support_only')
            else:
                expand, reason = False, 'no_expansion_signal'
            if order == config.max_order:
                expand, reason = False, 'max_order'
            elif order == len(genes):
                expand, reason = False, 'gene_module_exhausted'
            row.update(EXPAND=expand, expansion_reason=reason)
            rows.append(row)
            level.append(row)
            if expand:
                expandable.append(pattern)
            logs.append(dict(reference_id=row['reference_id'], pattern_string=pattern.to_string(),
                             order=order, generated_from=parents, EXPAND=expand, expansion_reason=reason))
        summaries.append(dict(order=order, candidates_generated=len(generation), candidates_evaluated=len(level),
                              expandable_candidates=len(expandable),
                              median_pattern_support=float(pd.Series([r['support'] for r in level]).median()),
                              median_state_table_occupancy=float(pd.Series([r['state_table_occupancy'] for r in level]).median()),
                              median_zero_state_fraction=float(pd.Series([r['zero_state_fraction'] for r in level]).median())))
        if order == config.max_order:
            stop_reason = 'max_order'
            break
        if not expandable:
            stop_reason = 'gene_module_exhausted' if order == len(genes) else 'no_expandable_candidates'
            break
        generation = merge_candidates(expandable, max_candidates=config.max_candidates-len(rows))
        if not generation:
            stop_reason = 'no_compatible_merges'
            break
    # One discovery family across every evaluated order, never only the shortlist.
    apply_null_fdr(rows)
    for row, log in zip(rows, logs):
        keep = bool(stable_reference(row, config))
        row.update(stable_in_discovery=keep, KEEP_AS_REFERENCE=keep, PRUNE=not (keep or row['EXPAND']))
        log.update(KEEP_AS_REFERENCE=keep, PRUNE=row['PRUNE'])
    return rows, logs, summaries, stop_reason


def fit_reference(discovery, validation, reference_test, *, candidate_genes, config=None):
    """Test-cell values are not accessed. Validation cannot alter search or order stopping."""
    config = ReferenceConfig() if config is None else config
    if not isinstance(config, ReferenceConfig):
        raise TypeError('reference-guided discovery requires ReferenceConfig')
    assert_disjoint(discovery, validation, reference_test)
    genes = list(candidate_genes)
    if not genes or len(set(genes)) != len(genes):
        raise ValueError('supply a nonempty unique candidate_genes module chosen without held-out data')
    for pop in (discovery, validation, reference_test):
        if not set(genes) <= set(pop.gene_names):
            raise ValueError('candidate genes missing from a population')
    encoded, qc = discovery.encode(sorted(genes), config)
    qc['retained'] = qc.detection_rate.between(config.min_detection_rate, config.max_detection_rate)
    keep = qc.loc[qc.retained, 'gene'].tolist()
    rows, logs, summaries, stop = discovery_search(encoded[keep], config)
    locked = [r for r in rows if r['stable_in_discovery']]
    checks, cache = [], {}
    validation_fingerprint = None
    if locked:
        val, _ = validation.encode(keep, config)
        validation_fingerprint = binary_fingerprint(val, validation.cell_ids)
        for row in locked:
            pattern = JointPattern(row['genes'], row['states'])
            checks.append(evaluate(val, pattern, config, 'validation', cache))
        apply_null_fdr(checks)  # locked discovery family, including validation failures
    records = []
    for discovery_row, check in zip(locked, checks):
        same = bool(discovery_row['mfi'] * check['mfi'] > 0)
        passed = bool(stable_reference(check, config) and same)
        check.update(reference_mfi_direction_consistent=same,
                     replicated_in_reference_validation=passed,
                     validation_reason='passed' if passed else 'support_occupancy_null_or_bootstrap_failed_or_mfi_reversed')
        if passed:
            records.append(dict(discovery_row, reference_validation=check))
    for summary in summaries:
        order = summary['order']
        stable = sum(r['stable_in_discovery'] for r in rows if r['order'] == order)
        replicated = sum(r['replicated_in_reference_validation'] for r in checks if r['order'] == order)
        summary.update(stable_in_discovery=stable, replicated_in_reference_validation=replicated,
                       replication_rate=replicated/stable if stable else None)
    payload = dict(version='0.2.0', config=config_dict(config), candidate_genes=sorted(genes), retained_genes=keep,
                   discovery_binary_sha256=binary_fingerprint(encoded, discovery.cell_ids),
                   validation_binary_sha256=validation_fingerprint,
                   discovery_cell_ids=discovery.cell_ids, validation_cell_ids=validation.cell_ids,
                   test_cell_ids=reference_test.cell_ids, records=records,
                   reference_validation_scope='disjoint cells; experimental independence not established by cell IDs')
    catalogue = FrozenCatalogue.create(payload)
    metadata = dict(version='0.2.0', mode='reference_guided', config=config_dict(config),
                    stop_reason=stop, highest_evaluated_order=max([r['order'] for r in rows], default=None),
                    catalogue_sha256=catalogue.sha256, n_catalogue_patterns=len(records),
                    n_discovery=len(discovery.cell_ids), n_validation=len(validation.cell_ids),
                    n_reference_test=len(reference_test.cell_ids),
                    discovery_fdr_family='all evaluated orders; exploratory plug-in independence null',
                    validation_fdr_family='all locked discovery candidates across orders',
                    reference_validation_scope=payload['reference_validation_scope'],
                    stop_uses_validation=False, reference_test_values_accessed=False,
                    feature_selection_scope='discovery detection filter; caller-specified module must not use heldouts')
    order_columns = ['order', 'candidates_generated', 'candidates_evaluated', 'stable_in_discovery',
                     'replicated_in_reference_validation', 'replication_rate', 'median_pattern_support',
                     'median_state_table_occupancy', 'median_zero_state_fraction', 'expandable_candidates']
    return ReferenceResult(table(rows, BASE_COLUMNS), table(logs, LOG_COLUMNS), table(checks, VALIDATION_COLUMNS),
                           catalogue, table(summaries, order_columns), qc, metadata)
