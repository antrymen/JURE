"""Landscape-only import: canonical reference/candidate JSON and effect tables."""
import numpy as np
import pandas as pd
from clue_discovery.reference import import_frozen_catalogue
from clue_discovery.schemas import ConditionAssociation
from clue_discovery.perturbation_scan import AssociationBundle
from clue_discovery.integration.io import read_jsonl, artifact

def load_external_bundle(config):
    paths=config.paths;cat=import_frozen_catalogue(paths['reference_catalogue'],config)
    effects=pd.read_csv(paths['effect_matrix'],index_col=0);effects.index=effects.index.astype(str)
    if effects.index.duplicated().any() or list(effects.columns)!=[r.reference_id for r in cat.records]:
        raise ValueError('effect table must have unique conditions and frozen reference order')
    def aligned(name,kind):
        df=pd.read_csv(paths[name],index_col=0);df.index=df.index.astype(str)
        if not df.index.equals(effects.index) or not df.columns.equals(effects.columns):
            raise ValueError('matrix axes differ: '+name)
        if kind is bool and not np.isin(df.to_numpy(),[0,1,False,True]).all():raise ValueError('mask must be binary')
        return df.to_numpy(dtype=kind)
    metadata=pd.read_csv(paths['condition_metadata'],dtype={'condition_id':str}).set_index('condition_id')
    if metadata.index.duplicated().any() or set(metadata.index)!=set(effects.index): raise ValueError('condition support identities differ')
    candidates=[ConditionAssociation.model_validate(r) for r in read_jsonl(paths['condition_associations'])]
    return AssociationBundle(config.dataset_id,cat,effects.index.tolist(),effects.to_numpy(float),
        aligned('candidate_mask',bool),aligned('tested_mask',bool),aligned('reason_matrix',str),
        aligned('support_matrix',int),metadata.loc[effects.index,'condition_n'].to_numpy(int),candidates,
        {'adapter':'canonical_external_tables','effect_units':'prevalence_difference',
         'inputs':{k:artifact(p) for k,p in paths.items()}}).validate()
