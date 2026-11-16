"""Small, prespecified integration fixture; not a new statistical benchmark."""
from pathlib import Path
import numpy as np
import pandas as pd
import yaml
from clue_discovery.integration.io import write_json


def make_fixture(output,negative=False):
    out=Path(output);out.mkdir(parents=True,exist_ok=True)
    states=np.array([[int(x) for x in f'{i:03b}'] for i in range(8)],dtype=np.uint8)
    baseline=np.where(states.sum(1)%2,70,330)
    perturb=np.array([200,0,0,200,0,-200,-200,0])
    matrices=[];metadata=[];counter=0
    for condition,change in [('vehicle',0),('Condition_A',1),('Condition_B',-1),('Condition_C',0)]:
        for batch,fold in [('plate_alpha','A'),('plate_beta','B')]:
            counts=baseline+(0 if negative else change)*perturb
            values=np.repeat(states,counts,axis=0);matrices.append(values)
            for _ in values:
                metadata.append({'barcode':f'cell_{counter:06d}','exposure':condition,'plate':batch,
                    'donor':'synthetic_same_source','reference_partition':fold});counter+=1
    meta=pd.DataFrame(metadata);meta.to_csv(out/'cells.csv',index=False)
    genes=['feature_a','feature_b','feature_c']
    pd.DataFrame(np.vstack(matrices),index=meta.barcode,columns=genes).to_csv(out/'counts.csv',index_label='barcode')
    config=dict(data_origin='synthetic',dataset_id='synthetic_negative' if negative else 'synthetic_full',adapter='table',
        control_labels=['vehicle'],condition_field='exposure',cell_id_field='barcode',batch_field='plate',
        replicate_field='donor',condition_type='treatment',gene_mapping=dict(zip(genes,['SYN_A','SYN_B','SYN_C'])),
        binarization_rule='count_gt_zero',modality='RNA_detection',cell_context='synthetic_parity',timepoint='fixture',
        min_cells={'condition':100,'control_per_batch':20,'effective_control':100,'directional_support':10},
        matching_strategy='within_batch_control',candidate_budget={'max_order':3,'hvg_pool_size':3,
            'fingerprint_bands':4,'n_null_simulations':99},
        bootstrap_config={'reference_repetitions':40,'landscape_repetitions':12},
        multiple_testing_config={'reference':'validation_family_holm_025_per_direction',
            'association':'selected_family_holm_exploratory','alpha':.05,'min_abs_delta':.1},
        landscape_config={'context_shared_candidates_min':1},seed=20260927,
        paths={'cell_metadata':'cells.csv','expression':'counts.csv'},
        expected_conditions=['Condition_A','Condition_B','Condition_C'],reference_fold_field='reference_partition')
    (out/'dataset_config.yaml').write_text(yaml.safe_dump(config,sort_keys=False))
    write_json(out/'prespecified_truth.json',{'negative':negative,'reference_only_control':True,
        'higher_order_control_distribution':baseline.tolist(),'effect_by_state_A':((0 if negative else 1)*perturb/baseline.sum()).tolist(),
        'effect_by_state_B':((0 if negative else -1)*perturb/baseline.sum()).tolist(),
        'Condition_C_effect':0,'same_gene_set_different_signed_states':True,'shared_response_states':['000','011'],
        'opposing_response_states':['101','110'],'cell_split_is_biological_replication':False,
        'expected_associations':0 if negative else 'A/B only; enrichment and depletion; C unchanged'})
    return out/'dataset_config.yaml'
