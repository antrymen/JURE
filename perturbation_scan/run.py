"""Run the frozen Day 6 exploratory scan; never opens Day 8 or CPA expression."""
import os
for _k in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ[_k]='1'
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import resource
import sys
import time
import h5py
import numpy as np
from clue_discovery.v03.artifacts import digest,write_json,software_versions
from clue_discovery.v03.data import file_hash
from nt_reference_experiment.run import read_source_metadata
from real_nt_v04_holm.run import verify_frozen_engine
from .data import CATALOGUE_SHA,load_catalogue,plan_metadata,aggregate,metadata_tables
from .scan import scan,ScanConfig

ROOT=Path(__file__).resolve().parents[1]
SOURCE_MD5='d8cba17576d1a8afc0f7d71b79cad0f7'
SOURCE_SHA='412fd0df8c4ccea9f4db91cd88033c49200838b29d40945e48574be588b48789'


def hashes():
    return {str(p.relative_to(ROOT)):file_hash(p) for p in sorted((ROOT/'perturbation_scan').glob('*'))
            if p.suffix in ('.py','.md')}


def run(source,catalogue,output):
    out=Path(output)
    if out.exists() and any(out.iterdir()):raise FileExistsError('refuse to overwrite run')
    out.mkdir(parents=True,exist_ok=True);started=time.monotonic();frozen_hashes=hashes()
    status={'status':'running','phase':'source_verification','confirmatory':False}
    def event(phase,**kw):
        status.update(phase=phase,**kw);write_json(out/'run_status.json',status)
        print(json.dumps(status),flush=True)
    try:
        event('source_verification')
        verify_frozen_engine()
        patterns=load_catalogue(catalogue)
        if file_hash(source,'md5')!=SOURCE_MD5 or file_hash(source)!=SOURCE_SHA:
            raise ValueError('Day 6 source hash mismatch')
        config=ScanConfig()
        isolation=json.loads((ROOT/'dataset_audit/combined_audit.json').read_text())
        with h5py.File(source,'r',rdcc_nbytes=64*1024**2,rdcc_nslots=100003) as handle:
            obs,genes,reader=read_source_metadata(handle)
            if reader.X.shape!=(310385,8563):raise ValueError('source shape mismatch')
            plan=plan_metadata(obs,genes,patterns,isolation)
            if plan['nt_cells']!=10691:raise ValueError('NT count mismatch')
            metadata_tables(obs,plan,out/'metadata')
            manifest=dict(protocol='perturbation_scan/PROTOCOL.md',config=asdict(config),source_sha256=SOURCE_SHA,
                catalogue_payload_sha256=CATALOGUE_SHA,source_hashes=frozen_hashes,software=software_versions(),
                source_shape=list(reader.X.shape),targets=plan['targets'],batches=plan['batches'],
                nt_cells=plan['nt_cells'],allowed_cells=len(plan['rows']),excluded_cells=plan['excluded_cells'],
                excluded_targets=plan['excluded_targets'],genes=plan['genes'],family_size=len(plan['targets'])*len(patterns),
                allowed_rows_digest=digest(plan['rows']),isolation_digest=digest(isolation),
                metadata_sha256={p.name:file_hash(p) for p in sorted((out/'metadata').iterdir())},
                expression_read_started=False,prior_v01_v02_perturbation_access=True,
                v04_catalogue_used_perturbation_expression=False,nt_selection_adjusted=False,confirmatory=False)
            write_json(out/'PROTOCOL_FROZEN.json',manifest)
            event('aggregate_allowed_cells',targets=len(plan['targets']),allowed_cells=len(plan['rows']))
            counts=aggregate(reader,plan,patterns,len(genes))
        control=counts.group_target==0
        if int(counts.n_cells[control].sum())!=10691 or not np.array_equal(counts.hits[control].sum(0),[p['nt_support'] for p in patterns]):
            raise ValueError('recount does not reproduce frozen NT catalogue support')
        counts.save(out/'counts')
        write_json(out/'counts_frozen.json',{p.name:file_hash(p) for p in sorted((out/'counts').iterdir())})
        event('testing_exploratory_shifts')
        summary=scan(counts,out/'scan',config)
        verify_frozen_engine()
        if hashes()!=frozen_hashes:raise RuntimeError('scan code changed during execution')
        elapsed=time.monotonic()-started
        peak=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/(1024**2 if sys.platform=='darwin' else 1024)
        resources=dict(elapsed_seconds=elapsed,peak_process_rss_mib=peak,threads=1,gpu_used=False)
        for name in ('cpu.max','memory.max','memory.peak','memory.events'):
            path=Path('/sys/fs/cgroup')/name
            if path.exists():resources[name]=path.read_text().strip()
        write_json(out/'resources.json',resources)
        event('complete',status='complete',summary=summary,resources=resources)
        return summary
    except BaseException as exc:
        event('failed',status='failed',error=repr(exc));raise


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',required=True);parser.add_argument('--catalogue',required=True)
    parser.add_argument('--output-dir',required=True)
    args=parser.parse_args();run(args.source,args.catalogue,args.output_dir)

if __name__=='__main__':main()
