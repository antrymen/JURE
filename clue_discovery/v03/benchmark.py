"""Freeze a scale plan, then run 50/100/250 full and 500/1000 proposal dry-runs."""
import argparse
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import yaml

from .artifacts import code_hashes, digest, write_csv, write_json
from .config import ScalableConfig
from .data import load_prepared, prepare_real_nt, prepare_synthetic
from .pipeline import fit_twofold, peak_rss_mib
from .bottom_up import _bootstrap_quota


SCALE_PLAN = ((50, False), (100, False), (250, False), (500, True), (1000, True))


def scale_row(manifest, path):
    audits = [row for rows in manifest['order_audits'].values() for row in rows]
    result = dict(hvg_pool_size=manifest['config']['hvg_pool_size'], dry_run=manifest['dry_run'],
        source=manifest['dataset']['source'], status=manifest['status'],
        runtime_seconds=manifest['runtime_seconds'], peak_process_rss_mib=manifest['peak_process_rss_mib'],
        disk_usage_mib=manifest['output_bytes']/1024**2, config_hash=manifest['config_hash'],
        n_bootstrap_per_gene_set=manifest['config']['n_bootstrap'],
        bootstrap_discovery_gene_sets=sum(r['bootstrap_gene_sets'] for r in audits),
        bootstrap_discovery_shortlist=sum(r['bootstrap_shortlist'] for r in audits),
        estimability_pruned=sum(r['estimability_pruned'] for r in audits),
        gain_pruned=sum(r['gain_pruned'] for r in audits),
        proposal_budget_pruned_lower_bound=sum(r['pruned_budget'] for r in audits),
        bootstrap_budget_pruned=sum(r['bootstrap_budget_pruned'] for r in audits),
        gain_calibration_budget_pruned=sum(r['gain_calibration_budget_pruned'] for r in audits),
        primary_patterns=manifest['catalogue_counts'].get('primary', 0),
        exploratory_patterns=manifest['catalogue_counts'].get('exploratory', 0),
        crossfold_triplet_patterns=manifest['crossfold_counts'].get('3', manifest['crossfold_counts'].get(3, 0)),
        bidirectional_triplet_patterns=manifest['bidirectional_counts'].get('3', manifest['bidirectional_counts'].get(3, 0)),
        selected_graph_edges=sum(g['n_edges'] for g in manifest['graph_summaries'].values()),
        graph_densities={f: g['graph_density'] for f, g in manifest['graph_summaries'].items()},
        limitations=manifest['limitations'], path=str(path))
    for order in (2, 3, 4):
        own = [r for r in audits if r['order'] == order]
        for key in ('generated', 'proposed', 'evaluated'):
            result[f'order{order}_{key}'] = sum(r[key] for r in own)
        result[f'order{order}_generated_count_is_lower_bound'] = any(r['generated_count_is_lower_bound'] for r in own)
        result[f'order{order}_exploration_samples'] = sum(r['exploration']['n_sample'] for r in own)
        result[f'order{order}_exploration_probability_per_fold'] = {r['fold']: r['exploration']['inclusion_probability'] for r in own}
    import pandas as pd
    boot = pd.read_csv(Path(path)/'bootstrap_summary.csv')
    result['bootstrap_total_gene_set_calls_including_validation'] = int((boot.bootstrap_status == 'complete').sum())
    cfg = ScalableConfig(**manifest['config'])
    upper = {order: sum(min(r['proposed'], _bootstrap_quota(cfg, order)) for r in audits if r['order'] == order)
             for order in (2, 3, 4)}
    result['estimated_bootstrap_gene_set_calls_upper_bound_including_validation'] = 2*sum(upper.values())
    result['estimated_bootstrap_array_bytes_upper_bound'] = 2*sum(
        count*cfg.n_bootstrap*8*((2+2**order) if cfg.gain_mode == 'on' and (order <= 3 or cfg.quad_gain_enabled) else 1)
        for order, count in upper.items())
    result['estimated_disk_usage'] = dict(actual_existing_artifact_bytes=manifest['output_bytes'],
        additional_bootstrap_uncompressed_payload_upper_bytes=result['estimated_bootstrap_array_bytes_upper_bound'],
        excludes='future null calibration arrays, state-table JSON and CSV; compression and shortlist size unknown',
        estimate_type='component_bound_not_total_disk_forecast')
    if manifest['dry_run']:
        for key in ('crossfold_triplet_patterns', 'bidirectional_triplet_patterns', 'primary_patterns', 'exploratory_patterns'):
            result[key] = None
        result['statistical_qualification_status'] = 'not_evaluated'
    else:
        result['statistical_qualification_status'] = 'evaluated_with_explicit_budgets'
    return result


def worker(prepared, output, config_path, dry_run):
    config = ScalableConfig(**yaml.safe_load(Path(config_path).read_text()))
    folds, selections, metadata = load_prepared(prepared, config)
    if peak_rss_mib() > config.max_process_rss_mib:
        raise MemoryError('prepared-data RSS exceeds frozen process memory budget')
    result = fit_twofold(folds['A'], folds['B'], config, output, dataset_manifest=metadata,
                        selections=selections, dry_run=dry_run)
    if peak_rss_mib() > config.max_process_rss_mib:
        raise MemoryError('run exceeded frozen process memory budget; do not proceed to larger scale')
    print(json.dumps(dict(scale=config.hvg_pool_size, dry_run=dry_run, status=result.manifest['status'],
                          runtime_seconds=result.manifest['runtime_seconds']), ensure_ascii=False), flush=True)


def run_scale_benchmark(output_dir, *, mode='synthetic', source=None, config=None, n_cells=10691):
    root = Path(output_dir).resolve()
    if root.exists() and any(root.iterdir()):
        raise FileExistsError('scale benchmark output must be new; never overwrite a previous frozen plan')
    root.mkdir(parents=True, exist_ok=True)
    config = config or ScalableConfig()
    if mode not in ('synthetic', 'real') or mode == 'real' and source is None:
        raise ValueError('mode must be synthetic or real, with --source for real')
    configs = {size: replace(config, hvg_pool_size=size, run_version=f'{config.run_version}_{mode}_{size}') for size, _ in SCALE_PLAN}
    (root/'config_base_frozen.yaml').write_text(yaml.safe_dump(config.to_dict(), sort_keys=True))
    for size, cfg in configs.items():
        (root/f'config_{size}_frozen.yaml').write_text(yaml.safe_dump(cfg.to_dict(), sort_keys=True))
    plan = dict(run_version=config.run_version, dataset_mode=mode,
        stages=[dict(size=size, dry_run=dry, config_hash=configs[size].sha256) for size, dry in SCALE_PLAN],
        code_hashes=code_hashes(), no_real_result_retuning=True, scientific_thresholds_frozen_before_reading_data=True,
        stop_after_scale_plan=True, full_500_1000_not_authorized_by_this_plan=True,
        resource_limit_mib=config.max_process_rss_mib,
        bootstrap_budget_scope='128/default per discovery fold, fixed 20% pairs/60% triplets/remainder quads; validation only locked unique sets',
        dry_run_scope='HVG, pair graph, bounded proposals only; L4 uses unqualified L3 parents as workload upper-bound')
    write_json(root/'scale_plan_frozen.json', plan)
    started = time.monotonic()
    prepared = root/'prepared'
    try:
        print(json.dumps({'stage': 'prepare', 'mode': mode}), flush=True)
        prepare_command = [sys.executable, '-m', 'clue_discovery.v03.benchmark', '--prepare-worker',
            '--output-dir', str(prepared), '--mode', mode, '--config', str(root/'config_base_frozen.yaml'),
            '--n-cells', str(n_cells)]
        if source:
            prepare_command += ['--source', str(source)]
        if sys.platform.startswith('linux'):
            prepare_command = [sys.executable, '-m', 'nt_reference_experiment.measure', '--output', str(root/'preparation_resources.json'),
                               '--rss-limit-mib', str(config.max_process_rss_mib), '--'] + prepare_command
        with (root/'preparation.log').open('w') as log:
            completed = subprocess.run(prepare_command, stdout=log, stderr=subprocess.STDOUT,
                env={**os.environ, 'OPENBLAS_NUM_THREADS': '1', 'OMP_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1'})
        if completed.returncode:
            raise RuntimeError(f'preparation failed with exit {completed.returncode}; see preparation.log')
        data = json.loads((prepared/'data_manifest.json').read_text())
        rows = []
        for size, dry in SCALE_PLAN:
            stage = root/f'genes_{size}_{"dry" if dry else "full"}'
            command = [sys.executable, '-m', 'clue_discovery.v03.benchmark', '--worker', '--prepared', str(prepared),
                       '--output-dir', str(stage), '--config', str(root/f'config_{size}_frozen.yaml')]
            if dry:
                command.append('--dry-run')
            # Linux wrapper provides a sampled hard stop, cgroup observations and final kernel RSS.
            if sys.platform.startswith('linux'):
                command = [sys.executable, '-m', 'nt_reference_experiment.measure', '--output', str(root/f'resources_{size}.json'),
                           '--rss-limit-mib', str(config.max_process_rss_mib), '--'] + command
            with (root/f'run_{size}.log').open('w') as log:
                print(json.dumps({'stage': 'run_scale', 'size': size, 'dry_run': dry}), flush=True)
                completed = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT,
                    env={**os.environ, 'OPENBLAS_NUM_THREADS': '1', 'OMP_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1'})
            if completed.returncode:
                raise RuntimeError(f'scale {size} failed with exit {completed.returncode}; see run_{size}.log; larger stages not run')
            manifest = json.loads((stage/'run_manifest.json').read_text())
            row = scale_row(manifest, stage)
            rows.append(row)
            write_csv(root/'scale_benchmark.csv', rows)
            write_json(root/'scale_summary.json', dict(mode=mode, stages=rows, source=data['source'],
                plan_hash=digest(plan), runtime_seconds=time.monotonic()-started, completed_stages=len(rows),
                real_data_qualification=mode == 'real', full_500_1000_executed=False))
        if code_hashes() != plan['code_hashes']:
            raise RuntimeError('source code changed during scale plan')
        write_json(root/'execution_status.json', dict(complete=True, original_code_unchanged=True,
            wall_seconds=time.monotonic()-started, no_real_result_retuning=True))
        return rows
    except BaseException as exc:
        write_json(root/'execution_status.json', dict(complete=False, error=str(exc), error_type=type(exc).__name__,
            wall_seconds=time.monotonic()-started, no_results_overwritten=True))
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--mode', choices=('synthetic', 'real'), default='synthetic')
    parser.add_argument('--source')
    parser.add_argument('--config')
    parser.add_argument('--worker', action='store_true')
    parser.add_argument('--prepare-worker', action='store_true')
    parser.add_argument('--prepared')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--n-cells', type=int, default=10691)
    args = parser.parse_args()
    if args.prepare_worker:
        config = ScalableConfig(**yaml.safe_load(Path(args.config).read_text()))
        started = time.monotonic()
        data = (prepare_synthetic(args.output_dir, config, n_cells=args.n_cells) if args.mode == 'synthetic'
                else prepare_real_nt(args.source, args.output_dir, config))
        write_json(Path(args.output_dir)/'preparation_summary.json', dict(seconds=time.monotonic()-started,
            process_peak_rss_mib=peak_rss_mib(), source=data['source'], projection_is_not_discovery=True))
        if peak_rss_mib() > config.max_process_rss_mib:
            raise MemoryError('preparation exceeded frozen memory budget')
    elif args.worker:
        worker(args.prepared, args.output_dir, args.config, args.dry_run)
    else:
        config = ScalableConfig(**yaml.safe_load(Path(args.config).read_text())) if args.config else None
        run_scale_benchmark(args.output_dir, mode=args.mode, source=args.source, config=config, n_cells=args.n_cells)


if __name__ == '__main__':
    main()
