"""Same frozen v0.4 discoveries and raw validation, with auditable family gates."""
from dataclasses import dataclass
import hashlib
from pathlib import Path
import time

import numpy as np

from ..v02.populations import assert_disjoint
from ..v03.artifacts import ArtifactStore, code_hashes, digest, write_csv, write_json
from ..v03.multiple_testing import MultipleTestingAudit
from ..v03.validation import validate_locked
from ..v04.bottom_up import discover
from .policy import freeze_family, evaluate_family


class CompactArtifactStore(ArtifactStore):
    """Keep counts, parameters and summaries; hash reproducible simulation arrays.

    Only storage changes. Simulations are still executed with the exact frozen
    counts, seeds and draw counts. Returned paths explicitly point to audit JSON,
    never pretend to contain the omitted arrays.
    """
    def save_arrays(self, category, role, candidate_id, arrays):
        relative = f'{category}/{role}/{candidate_id}_array_audit.json'
        description = {name: dict(shape=value.shape, dtype=str(value.dtype),
            sha256=hashlib.sha256(np.ascontiguousarray(value).tobytes()).hexdigest())
            for name, value in arrays.items() if isinstance(value, np.ndarray)}
        write_json(self.root/relative, dict(arrays_persisted=False, arrays=description,
            reconstruction='saved_state_counts_and_frozen_config_stage_seed',
            numerical_computation_changed=False))
        return relative


@dataclass
class ExperimentResult:
    discoveries: dict
    raw_validations: dict
    families: dict
    corrected_sets: list
    corrected_states: list
    manifest: dict


def run_experiment(population_a, population_b, config, output_dir, *, compact=True, dataset_manifest=None):
    if (dataset_manifest or {}).get('real_data_used') is True:
        raise ValueError('this experiment is reserved for synthetic validation')
    assert_disjoint(population_a, population_b)
    path = Path(output_dir)
    if path.exists() and any(path.iterdir()):
        raise FileExistsError('refuse to overwrite a frozen experiment')
    store = (CompactArtifactStore if compact else ArtifactStore)(path)
    store.freeze_config(config)
    hashes = code_hashes()
    started = time.monotonic()
    audit = MultipleTestingAudit()
    manifest = dict(experiment_version='v04_validation_family_v1', config=config.to_dict(),
        config_hash=config.sha256, code_hashes=hashes, dataset=dataset_manifest or {},
        search_and_statistical_kernels='unchanged_frozen_v04a', compact_storage=compact,
        status='running', real_data_used=(dataset_manifest or {}).get('real_data_used'),
        eligible_for_agent_investigation=False)
    write_json(path/'experiment_manifest.json', manifest)
    try:
        discoveries = {fold: discover(population, config, store, audit, fold=fold)
                       for fold, population in [('A', population_a), ('B', population_b)]}
        families = {fold: freeze_family(discoveries[fold].locked,
            source_fold=fold, validation_fold=other) for fold, other in [('A', 'B'), ('B', 'A')]}
        write_json(path/'validation_families_frozen.json', dict(
            families={fold: family.to_dict() for fold, family in families.items()},
            validation_started=False, both_discoveries_frozen=True))
        frozen_paths = [path/'validation_families_frozen.json', path/'config_frozen.yaml']
        frozen_paths += [path/f'discovery_{fold}_frozen.json' for fold in ('A', 'B')]
        barrier = {str(p.relative_to(path)): hashlib.sha256(p.read_bytes()).hexdigest() for p in frozen_paths}
        write_json(path/'both_discoveries_and_families_frozen_before_validation.json', barrier)
        validations, corrected_sets, corrected_states, family_results = {}, [], [], []
        for source, destination, population in [('A', 'B', population_b), ('B', 'A', population_a)]:
            rows, sets = validate_locked(population, discoveries[source].locked, config, store, audit,
                                         source_fold=source, validation_fold=destination)
            validations[source] = rows
            result, states, info = evaluate_family(families[source], discoveries[source].locked, sets, rows)
            corrected_sets.extend(result); corrected_states.extend(states); family_results.extend(info)
        for relative, expected in barrier.items():
            if hashlib.sha256((path/relative).read_bytes()).hexdigest() != expected:
                raise RuntimeError('discovery/family lock changed during validation')
        if hashes != code_hashes():
            raise RuntimeError('source code changed during experiment')
        write_csv(path/'corrected_gene_sets.csv', corrected_sets,
                  ['family_id', 'candidate_id', 'arm', 'family_size', 'p_gain', 'adjusted_p', 'family_gain_rejected'])
        write_csv(path/'corrected_states.csv', corrected_states,
                  ['reference_id', 'candidate_id', 'arm', 'qualified'])
        write_json(path/'family_results.json', family_results)
        write_json(path/'raw_multiple_testing_audit.json', audit.manifest(
            generation_complete=all(d.status == 'complete' for d in discoveries.values())))
        manifest.update(status='complete', runtime_seconds=time.monotonic()-started,
            original_sources_unchanged_during_run=True, families_frozen_before_validation=True,
            discovery_status={fold: d.status for fold, d in discoveries.items()},
            correction_changes_no_raw_statistics=True)
        write_json(path/'experiment_manifest.json', manifest)
        return ExperimentResult(discoveries, validations, families, corrected_sets, corrected_states, manifest)
    except BaseException as error:
        manifest.update(status='failed', error=str(error), error_type=type(error).__name__)
        write_json(path/'experiment_manifest.json', manifest)
        raise
