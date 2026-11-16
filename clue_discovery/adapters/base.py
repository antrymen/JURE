"""Explicit dataset calibration and canonical cell-level adapter contract."""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
import numpy as np
import pandas as pd
import yaml
from pydantic import Field, model_validator
from clue_discovery.schemas import Contract
from clue_discovery.integration.io import artifact

GLOBAL_METHOD_DEFAULTS = {
    'signed_state_identity':'genes_and_states', 'state_search_in_stage_II':False,
    'stage_III_evidence_upgrade':False, 'missing_effect':'NA_not_zero',
    'reference_backend':'v04_crossfold_validation_family_holm',
    'shift_backend':'batch_matched_exact_stratified_selected_family_holm_exploratory',
    'annotation_status':'NOT_ANNOTATED',
}

class DatasetConfig(Contract):
    dataset_id: str
    data_origin: Literal['real', 'synthetic'] = 'real'
    adapter: Literal['table','replogle_frozen']
    control_labels: list[str] = Field(min_length=1)
    condition_field: str
    cell_id_field: str
    batch_field: str
    replicate_field: str | None
    condition_type: str
    gene_mapping: dict[str,str]
    binarization_rule: Literal['count_gt_zero']
    modality: str
    cell_context: str
    timepoint: str
    min_cells: dict[str,int]
    matching_strategy: Literal['within_batch_control']
    candidate_budget: dict[str,Any]
    bootstrap_config: dict[str,Any]
    multiple_testing_config: dict[str,Any]
    landscape_config: dict[str,Any]
    seed: int
    paths: dict[str,str]
    expected_conditions: list[str] = Field(default_factory=list)
    reference_fold_field: str | None = None
    transfer_compatibility: dict[str,str] = Field(default_factory=dict)

    @model_validator(mode='after')
    def explicit_calibration(self):
        if not {'condition','control_per_batch','effective_control','directional_support'} <= self.min_cells.keys():
            raise ValueError('min_cells calibration incomplete')
        if any(x<1 for x in self.min_cells.values()): raise ValueError('min_cells must be positive')
        if self.multiple_testing_config.get('reference')!='validation_family_holm_025_per_direction':
            raise ValueError('unsupported reference multiplicity policy')
        if self.multiple_testing_config.get('association')!='selected_family_holm_exploratory':
            raise ValueError('unsupported shift multiplicity policy')
        if not {'alpha','min_abs_delta'} <= self.multiple_testing_config.keys():
            raise ValueError('explicit shift alpha and effect threshold required')
        if not 0 < self.multiple_testing_config['min_abs_delta'] <= 1 or not 0 < self.multiple_testing_config['alpha'] < 1:
            raise ValueError('invalid frozen effect/significance threshold')
        if self.candidate_budget.get('max_order')!=3:
            raise ValueError('accepted Stage I/II backend supports order 3; schemas/landscape are order-agnostic')
        if not {'hvg_pool_size','fingerprint_bands','n_null_simulations'} <= self.candidate_budget.keys():
            raise ValueError('explicit candidate budget required')
        if not {'reference_repetitions','landscape_repetitions'} <= self.bootstrap_config.keys():
            raise ValueError('bootstrap calibration incomplete')
        return self

    @classmethod
    def load(cls,path):
        path=Path(path).resolve(); data=yaml.safe_load(path.read_text())
        data['paths']={k:str((path.parent/v).resolve()) for k,v in data['paths'].items()}
        return cls.model_validate(data)

@dataclass
class ClueDiscoveryDataset:
    dataset_id: str
    cell_metadata: pd.DataFrame
    conditions: tuple[str,...]
    control_labels: tuple[str,...]
    genes: tuple[str,...]
    detection_matrix: np.ndarray | None
    config: DatasetConfig
    provenance: dict[str,Any]
    metadata_only: bool = False
    raw_counts: np.ndarray | None = None

    def validate(self):
        required={'cell_id','condition_id','batch_id','replicate_id','is_control'}
        if not required <= set(self.cell_metadata): raise ValueError('canonical cell metadata incomplete')
        m=self.cell_metadata
        if m.cell_id.duplicated().any() or m.cell_id.isna().any(): raise ValueError('invalid cell ids')
        if any(m[k].isna().any() for k in ('condition_id','batch_id')): raise ValueError('missing condition/batch')
        if len(set(self.genes))!=len(self.genes): raise ValueError('ambiguous gene mapping')
        if self.detection_matrix is not None:
            if self.detection_matrix.shape!=(len(m),len(self.genes)): raise ValueError('matrix/metadata mismatch')
            if not np.isin(self.detection_matrix,[0,1]).all(): raise ValueError('non-binary detection matrix')
        elif not self.metadata_only: raise ValueError('detection matrix unavailable')
        return self

    @property
    def reference_available(self): return bool(self.cell_metadata.is_control.any())

class DatasetAdapter(ABC):
    @abstractmethod
    def load_dataset(self,config: DatasetConfig) -> ClueDiscoveryDataset: ...

class TableDatasetAdapter(DatasetAdapter):
    """CSV metadata plus CSV counts with cell_id as index; column mapping is explicit."""
    def load_dataset(self,config):
        meta=pd.read_csv(config.paths['cell_metadata'],dtype=str)
        needed=[config.cell_id_field,config.condition_field,config.batch_field]
        if config.replicate_field: needed.append(config.replicate_field)
        if config.reference_fold_field: needed.append(config.reference_fold_field)
        if not set(needed)<=set(meta): raise ValueError('configured metadata field missing')
        if meta[needed].isna().any().any(): raise ValueError('missing configured metadata values')
        canonical=pd.DataFrame({'cell_id':meta[config.cell_id_field],
            'condition_id':meta[config.condition_field], 'batch_id':meta[config.batch_field],
            'replicate_id':meta[config.replicate_field] if config.replicate_field else 'NOT_PROVIDED'})
        canonical['is_control']=canonical.condition_id.isin(config.control_labels)
        if config.reference_fold_field: canonical['reference_fold']=meta[config.reference_fold_field]
        raw=pd.read_csv(config.paths['expression'],index_col=0);raw.index=raw.index.astype(str)
        if raw.index.duplicated().any() or set(raw.index)!=set(canonical.cell_id):
            raise ValueError('expression must match cell metadata exactly')
        if set(raw.columns)!=set(config.gene_mapping): raise ValueError('gene_mapping must explicitly cover every input gene')
        values=raw.loc[canonical.cell_id].to_numpy(float)
        if not np.isfinite(values).all() or (values<0).any() or not np.equal(values,np.floor(values)).all():
            raise ValueError('count_gt_zero requires finite nonnegative integer counts')
        observed=set(canonical.loc[~canonical.is_control,'condition_id'])
        conditions=tuple(config.expected_conditions or sorted(observed))
        if not observed<=set(conditions) or set(conditions)&set(config.control_labels) or len(conditions)!=len(set(conditions)):
            raise ValueError('invalid expected condition universe')
        ds=ClueDiscoveryDataset(config.dataset_id,canonical,conditions,tuple(config.control_labels),
            tuple(config.gene_mapping[g] for g in raw.columns),(values>0).astype(np.uint8),config,
            {'adapter':'TableDatasetAdapter','inputs':{k:artifact(config.paths[k]) for k in ('cell_metadata','expression')},
             'gene_mapping':config.gene_mapping,'cell_id_field':config.cell_id_field})
        ds.raw_counts=values
        return ds.validate()
