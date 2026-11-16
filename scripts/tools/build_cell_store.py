"""Build a local, auditable bit store on the data host. No network/LLM calls.

Input metadata is the frozen Day6 allowed-cell table, not an arbitrary selection.
This standalone script can run on the existing low-memory data server.
"""
import argparse,hashlib,json,time
from pathlib import Path
import anndata as ad
import h5py
import numpy as np
import pandas as pd
from scipy import sparse

def sha(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for b in iter(lambda:f.read(2**20),b''):h.update(b)
    return h.hexdigest()

def build(source,metadata,output,expected_source_sha,expected_metadata_sha):
    source=Path(source); metadata=Path(metadata);out=Path(output)
    if sha(source)!=expected_source_sha or sha(metadata)!=expected_metadata_sha:raise ValueError('source/allowed-metadata hash mismatch')
    if out.exists() and any(out.iterdir()):raise FileExistsError('refuse overwrite of cell store')
    out.mkdir(parents=True,exist_ok=True)
    reader=ad.read_h5ad(source,backed='r');meta=pd.read_csv(metadata,dtype={'cell_id':str,'batch':str,'scan_target':str})
    rows=meta.source_row.to_numpy(dtype=np.int64)
    if (np.diff(rows)<=0).any() or rows[0]<0 or rows[-1]>=reader.n_obs:raise ValueError('invalid source rows')
    if list(reader.obs_names[rows])!=meta.cell_id.tolist():raise ValueError('source cell identity mismatch')
    genes=list(map(str,reader.var_names))
    if len(set(genes))!=len(genes):raise ValueError('ambiguous gene symbols')
    obs=reader.obs.iloc[rows]
    if not np.array_equal(obs['batch'].astype(str).to_numpy(),meta.batch.to_numpy()):raise ValueError('batch mismatch')
    encoded=np.lib.format.open_memmap(out/'states.npy',mode='w+',dtype=np.uint8,shape=(len(rows),(len(genes)+7)//8))
    # The canonical dense HDF5 uses (1213, 67) gzip chunks. Cache an entire
    # row band so short allowed slices do not repeatedly decompress all columns.
    # Logical selections still contain only the frozen allowed rows.
    reader.file.close()
    rawfile=h5py.File(source,'r',rdcc_nbytes=256*1024**2,rdcc_nslots=100003)
    matrix=rawfile['X']
    if isinstance(matrix,h5py.Group):
        from anndata.io import sparse_dataset
        matrix=sparse_dataset(matrix)
    start=0
    while start<len(rows):
        stop=start+1
        while stop<len(rows) and stop-start<512 and rows[stop]==rows[stop-1]+1:stop+=1
        block=matrix[int(rows[start]):int(rows[stop-1])+1]
        if sparse.issparse(block):block=block.toarray()
        if not np.isfinite(block).all() or (block<0).any() or not np.equal(block,np.floor(block)).all():raise ValueError('raw counts required')
        encoded[start:stop]=np.packbits(block>0,axis=1);start=stop
    encoded.flush();rawfile.close()
    meta.to_csv(out/'cells.csv.gz',index=False);(out/'genes.json').write_text(json.dumps(genes))
    manifest=dict(dataset_id='replogle_k562_essential_day6',encoding='raw_count_gt_0',source_file=str(source),
        source_sha256=expected_source_sha,allowed_metadata_sha256=expected_metadata_sha,source_shape=[reader.n_obs,reader.n_vars],
        retained_cells=len(meta),retained_genes=len(genes),source_mode='REAL',created_at=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
        script_sha256=sha(__file__),files={n:sha(out/n) for n in ('states.npy','cells.csv.gz','genes.json')})
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2));print(json.dumps(manifest),flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--metadata',required=True);p.add_argument('--output',required=True)
    p.add_argument('--source-sha',required=True);p.add_argument('--metadata-sha',required=True);a=p.parse_args()
    build(a.source,a.metadata,a.output,a.source_sha,a.metadata_sha)
