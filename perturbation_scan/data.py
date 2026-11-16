"""Read only allowed cells and frozen genes, aggregate integer state counts."""
import json
from pathlib import Path
import numpy as np
import pandas as pd
from scipy import sparse
from clue_discovery.v03.artifacts import digest
from nt_reference_experiment.low_memory import _allowed_chunks
from .scan import Counts

CATALOGUE_SHA='23f7840ad7e9b14347b0101e2f8fddbc93f31f524033fb1f64368609cef6bf68'


def load_catalogue(path):
    doc=json.loads(Path(path).read_text())
    if doc.get('sha256')!=CATALOGUE_SHA or digest(doc['payload'])!=CATALOGUE_SHA:
        raise ValueError('frozen catalogue hash mismatch')
    records=doc['payload']['records']
    if len(records)!=341 or any(r['order']!=3 for r in records):
        raise ValueError('frozen catalogue dimensions mismatch')
    return records


def plan_metadata(obs,genes,patterns,isolation):
    needed={'gene','nperts','batch','guide_id'}
    if not needed<=set(obs) or obs[list(needed)].isna().any().any() or not obs.index.is_unique:
        raise ValueError('missing or duplicate source identities')
    if len(set(genes))!=len(genes):raise ValueError('duplicate genes')
    aliases=isolation['aliases'];excluded={r['canonical'] for r in isolation['rows']}|set(aliases)
    labels=obs.gene.astype(str).replace(aliases).to_numpy()
    batch=obs.batch.astype(str).to_numpy()
    nt=labels=='non-targeting'
    if not (obs.nperts.to_numpy()[nt]==0).all():raise ValueError('NT nperts mismatch')
    allowed=nt|((obs.nperts.to_numpy()==1)&~np.isin(labels,list(excluded)))
    targets=tuple(sorted(set(labels[allowed])-{'non-targeting'}))
    batches=tuple(sorted(set(batch[allowed])))
    tmap={'non-targeting':0,**{t:i+1 for i,t in enumerate(targets)}}
    bmap={b:i for i,b in enumerate(batches)}
    rows=np.flatnonzero(allowed)
    pairs=sorted(set((tmap[labels[k]],bmap[batch[k]]) for k in rows))
    groupmap={p:i for i,p in enumerate(pairs)}
    row_groups=np.array([groupmap[(tmap[labels[k]],bmap[batch[k]])] for k in rows])
    selected=set(g for p in patterns for g in p['genes'])
    if not selected<=set(genes):raise ValueError('source lacks catalogue genes')
    columns=np.array([i for i,g in enumerate(genes) if g in selected])
    return dict(targets=targets,batches=batches,rows=rows,row_groups=row_groups,pairs=pairs,
                columns=columns,genes=tuple(genes[i] for i in columns),excluded_targets=sorted(excluded),
                excluded_cells=int((~allowed).sum()),nt_cells=int(nt.sum()),source_cells=len(obs))


def aggregate(reader,plan,patterns,n_genes,chunk_rows=256):
    if chunk_rows<1:raise ValueError('invalid chunk size')
    G=len(plan['pairs']);P=len(patterns)
    hits=np.zeros((G,P),dtype=np.int64)
    n=np.bincount(plan['row_groups'],minlength=G).astype(np.int64)
    lookup={g:i for i,g in enumerate(plan['genes'])}
    idx=np.array([[lookup[g] for g in p['genes']] for p in patterns])
    states=np.array([p['states'] for p in patterns],dtype=bool)
    if any(v not in (0,1) for p in patterns for v in p['states']):raise ValueError('invalid binary state')
    for start,stop,sl in _allowed_chunks(plan['rows'],chunk_rows):
        # Contiguous slices contain only allowed rows; dense HDF5 reads only frozen columns.
        block=reader.X[sl,plan['columns']]
        if sparse.issparse(block):block=block.toarray()
        block=np.asarray(block)
        if block.shape!=(stop-start,len(plan['genes'])) or not np.isfinite(block).all() or (block<0).any() or (block!=np.floor(block)).any():
            raise ValueError('expected finite integer raw counts')
        encoded=block>0
        matched=np.all(encoded[:,idx]==states[None,:,:],axis=2)
        np.add.at(hits,plan['row_groups'][start:stop],matched)
    result=Counts(plan['targets'],plan['batches'],np.array([p[0] for p in plan['pairs']]),
                  np.array([p[1] for p in plan['pairs']]),n,hits,patterns,n_genes)
    result.validate()
    return result


def metadata_tables(obs,plan,out):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    frame=obs.iloc[plan['rows']].copy()
    frame.insert(0,'cell_id',frame.index.astype(str))
    frame.insert(1,'source_row',plan['rows'])
    frame['group_index']=plan['row_groups']
    frame['scan_target']=[('non-targeting' if plan['pairs'][i][0]==0 else plan['targets'][plan['pairs'][i][0]-1]) for i in plan['row_groups']]
    keep=['cell_id','source_row','scan_target','batch','guide_id','nperts','group_index']
    keep += [c for c in ('ncounts','ngenes','UMI_count','percent_mito') if c in frame]
    frame[keep].to_csv(out/'allowed_cell_metadata.csv.gz',index=False)
    frame.groupby(['scan_target','batch','guide_id'],observed=True).size().rename('n_cells').to_csv(out/'target_batch_guide_counts.csv.gz')
    frame.groupby('scan_target',observed=True).size().rename('n_cells').to_csv(out/'target_counts.csv')
