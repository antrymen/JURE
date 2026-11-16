"""Immutable NT-reference export; no perturbation or Agent entry point."""
from dataclasses import dataclass
import json
from pathlib import Path

from .artifacts import canonical, digest, write_csv, write_json


@dataclass(frozen=True)
class FrozenReferenceCatalogue:
    payload_json: str
    sha256: str

    @classmethod
    def freeze(cls, records, *, config_hash, run_version):
        payload = dict(schema_version=1, object_type='NTReferenceCatalogue',
                       run_version=run_version, config_hash=config_hash, records=records,
                       eligible_for_agent_investigation=False, perturbation_evidence_present=False)
        return cls(canonical(payload), digest(payload))

    @property
    def records(self):
        # Return copies: downstream code cannot mutate the frozen payload.
        return json.loads(self.payload_json)['records']

    def write(self, directory):
        directory = Path(directory)
        write_json(directory/'frozen_reference_catalogue.json',
                   dict(payload=json.loads(self.payload_json), sha256=self.sha256))
        for tier in ('primary', 'exploratory'):
            write_csv(directory/f'reference_catalogue_{tier}.csv',
                      [r for r in self.records if r['catalogue_tier'] == tier],
                      ['reference_id', 'genes', 'order', 'pattern', 'quality_flags', 'catalogue_tier'])

    @classmethod
    def load(cls, path):
        data = json.loads(Path(path).read_text())
        if digest(data['payload']) != data['sha256']:
            raise ValueError('frozen reference catalogue checksum mismatch')
        return cls(canonical(data['payload']), data['sha256'])


def build_catalogue(discoveries, validations, cross_summary, config):
    by_reference = {r['reference_id']: r for r in cross_summary}
    records = []
    for rid, cross in sorted(by_reference.items()):
        origins = {fold: next((r for r in d.locked if r['reference_id'] == rid), None)
                   for fold, d in discoveries.items()}
        # A fixed alphabetical tie-breaker, never a validation-effect ranking.
        chosen_fold = next(f for f in ('A', 'B') if origins[f] is not None)
        chosen = origins[chosen_fold]
        valid = {f: next((r for r in validations[f] if r['reference_id'] == rid), None) for f in ('A', 'B')}
        successful = [f for f in ('A', 'B') if valid[f] is not None and valid[f]['cross_fold_replicated']]
        flags = []
        if chosen['within_discovery_stable']:
            flags.append('stable')
        if any(r and r['estimability_status'] != 'good' for r in list(origins.values())+list(valid.values())):
            flags.append('sparse_boundary')
        sources = {s for r in origins.values() if r for s in r['proposal_sources']}
        dependency = any('dependency' in s or 'bottom_up' in s for s in sources)
        flags.append('dependency_supported' if dependency else 'exploration_only')
        if cross['bidirectionally_rediscovered']:
            flags.append('bidirectionally_rediscovered')
        elif successful:
            flags.append('cross_fold_only')
        gain_ok = any(origins[f]['higher_order_gain_status'] == 'evaluated'
                      and origins[f]['p_gain'] is not None and origins[f]['p_gain'] <= config.alpha_gain
                      and valid[f]['p_gain'] is not None and valid[f]['p_gain'] <= config.alpha_gain
                      for f in successful)
        flags.append('gain_supported' if gain_ok else 'gain_not_evaluated' if chosen['higher_order_gain_status'] == 'not_evaluated' else 'gain_not_qualified')
        incomplete = any(d.status != 'complete' for d in discoveries.values())
        if incomplete:
            flags.append('incomplete_search_budget')
        if any(r and r.get('gain_calibration_unstable') for r in origins.values()):
            flags.append('gain_calibration_unstable')
        all_hooks = all(getattr(config, name) == 'on' for name in
                        ('gain_mode', 'estimability_filter', 'bootstrap', 'cross_fold_validation'))
        primary = (chosen['order'] == 3 and bool(successful) and gain_ok and all_hooks and not incomplete
                   and 'gain_calibration_unstable' not in flags
                   and (not config.primary_requires_good_estimability or 'sparse_boundary' not in flags)
                   and (not config.primary_requires_dependency_source or dependency))
        records.append(dict(chosen, reference_frequency=chosen['frequency'],
            reference_type='CrossfoldHigherOrderReferencePattern' if gain_ok and successful else 'CandidateHigherOrderReferenceState',
            reference_frequency_source_fold=chosen_fold, quality_flags=flags,
            catalogue_tier='primary' if primary else 'exploratory',
            cross_fold_status=cross, discovery_evidence=origins, validation_evidence=valid,
            testing_families=[f'{role}:order{chosen["order"]}:{kind}'
                for f in origins if origins[f]
                for role in (f'{f}_discovery', f'{"B" if f == "A" else "A"}_validation_from_{f}')
                for kind in ('mfi', 'gain', 'state')],
            inference_scope='exploratory_selected_universe', global_search_fdr_controlled=False,
            complete_search=incomplete is False, eligible_for_agent_investigation=False))
    return FrozenReferenceCatalogue.freeze(records, config_hash=config.sha256, run_version=config.run_version)
