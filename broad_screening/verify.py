"""Independent checks of scientific identities, exported values and scope."""
import json
from pathlib import Path
import numpy as np
import pandas as pd
from .io import sha
from .coverage import evaluate_case_set_coverage


def verify(out,d,cfg):
    checks={}
    def check(name,value):
        checks[name]=bool(value)
        if not value:raise AssertionError(name)
    effect=pd.read_csv(out/'matrices/effect_matrix.csv.gz',index_col=0)
    mask=pd.read_csv(out/'matrices/candidate_mask.csv.gz',index_col=0).values.astype(bool)
    tested=pd.read_csv(out/'matrices/tested_mask.csv.gz',index_col=0).values.astype(bool)
    support=pd.read_csv(out/'matrices/support_mask.csv.gz',index_col=0).values.astype(bool)
    check('main_effect_matches_scan_in_pp',np.allclose(effect.values,d['x'],atol=1e-12,rtol=1e-12))
    check('matrix_identities',list(effect.index)==list(d['targets']) and list(effect.columns)==list(d['refs']))
    check('candidate_mask_unchanged',np.array_equal(mask,d['mask']))
    check('candidates_have_support_and_were_tested',not np.any(mask&(~tested|~support)))
    candidate_only=pd.read_csv(out/'matrices/candidate_only_effect.csv.gz',index_col=0).values
    check('noncandidate_NA_distinct_from_observed_values',np.isnan(candidate_only[~mask]).all() and np.allclose(candidate_only[mask],d['x'][mask]))
    all_effect=pd.read_csv(out/'matrices/all_targets_effect_matrix.csv.gz',index_col=0).values
    all_support=pd.read_csv(out/'matrices/all_targets_support_mask.csv.gz',index_col=0).values.astype(bool)
    check('all_target_unsupported_values_are_NA',np.isnan(all_effect[~all_support]).all())
    check('all_target_supported_effects_preserved',np.allclose(all_effect[all_support],d['stats']['delta'][all_support]*100,atol=1e-12))
    table=pd.read_csv(out/'tables/case_triage_table.csv')
    source={(c['target'],c['reference_id']):c for c in d['candidates']}
    seen=set();pool=[]
    with (out/'agent_inputs/deep_case_pool.jsonl').open() as f:
        for line in f:
            c=json.loads(line);key=(c['target'],c['reference_id']);orig=source[key]
            check(f'candidate_row_{len(pool)+1}',key not in seen and c['genes']==orig['genes'] and c['states']==orig['states'] and
                  c['delta']==orig['delta'] and c['exploratory_adjusted_p']==orig['selected_family_holm_exploratory'] and
                  all(c['support'][k]==orig[k] for k in c['support']) and
                  c['source']['line']==orig['_source_line'] and c['original_interval']['ci_method']==orig['ci_method'])
            if not all(c['original_interval'][k]==orig[k] for k in c['original_interval']):raise AssertionError('Interval changed')
            if c['p_value']!=orig['p_value'] or c['family_size']!=orig['family_size']:raise AssertionError('Statistical context changed')
            if c['evidence_status']!='day6_exploratory' or c['selected_for_deep'] or c['selected_for_day8'] or c['day8_status']!='not_performed':
                raise AssertionError('Case scope escalation')
            seen.add(key);pool.append(c)
    check('all_candidates_traceable_exactly_once',len(seen)==int(d['mask'].sum())==len(table) and len(table.case_id.unique())==len(table))
    check('directions_preserved',int((table.direction=='enrichment').sum())==int(((d['x']>0)&d['mask']).sum()))
    refs=list(d['refs']);idx={r:i for i,r in enumerate(refs)}
    co=pd.read_csv(out/'matrices/co_clustering_matrix.csv.gz',index_col=0).values
    members=pd.read_csv(out/'tables/stable_core_membership.csv')
    if cfg.bootstrap_enabled:
        check('coassignment_bounds_symmetry',np.allclose(co,co.T) and np.nanmin(co)>=0 and np.nanmax(co)<=1)
        for g,subset in members.loc[members.core_or_boundary=='stable_core'].groupby('module_id'):
            ix=[idx[r] for r in subset.reference_id]
            check('core_pair_threshold_'+g,len(ix)>=cfg.stable_core_min_size and
                  co[np.ix_(ix,ix)][np.triu_indices(len(ix),1)].min()>=cfg.stable_core_pair_probability-1e-12)
    objects=[json.loads(line) for line in (out/'annotation_inputs/module_annotation_input.jsonl').read_text().splitlines()]
    check('whole_and_core_objects',len(objects)==2*members.module_id.nunique())
    for obj in objects:
        for p in obj['patterns']:
            original=d['patterns'][idx[p['reference_id']]]
            if p['genes']!=original['genes'] or p['states']!=original['states']:raise AssertionError('Annotation lost signed state')
    full=evaluate_case_set_coverage(table.case_id.tolist(),out/'tables/case_triage_table.csv')
    empty=evaluate_case_set_coverage([],out/'tables/case_triage_table.csv')
    check('case_coverage_full_and_empty',full['modules']['fraction']==1 and empty['n_cases']==0 and empty['modules']['covered']==0)
    pairs=pd.read_csv(out/'tables/pattern_pair_similarity.csv.gz')
    check('all_unordered_state_pairs_present',len(pairs)==len(refs)*(len(refs)-1)//2)
    example=json.loads((out/'figure_data/plot_metadata.json').read_text())['D']
    a,b=idx[example['reference_a']],idx[example['reference_b']]
    check('disjoint_example_verified',not(set(d['patterns'][a]['genes'])&set(d['patterns'][b]['genes'])) and
          np.isclose(example['pearson_r'],np.corrcoef(d['x'][:,a],d['x'][:,b])[0,1]) and
          example['n_shared_candidate_targets']==int((d['mask'][:,a]&d['mask'][:,b]).sum()))
    ab=pd.read_csv(out/'tables/signed_state_ablation.csv').set_index('representation')
    check('ablation_has_controlled_binary_bridge',{'continuous_pearson','candidate_binary_state_preserved','gene_only_any_candidate'}<=set(ab.index))
    collapsed=pd.read_csv(out/'matrices/gene_only_any_candidate.csv.gz',index_col=0)
    trips=np.array([p['candidate_id'] for p in d['patterns']])
    expected=np.stack([d['mask'][:,trips==t].any(1) for t in collapsed.columns],axis=1)
    check('gene_only_collapse_is_exact_OR',np.array_equal(expected,collapsed.values.astype(bool)))
    check('no_module_identifiers_in_methods','M01' not in (out/'METHODS_DRAFT.md').read_text())
    figure_frozen=json.loads((out/'figure_data/FROZEN.json').read_text())
    check('figure_data_frozen',all(sha(out/'figure_data'/p)==digest for p,digest in figure_frozen['files_sha256'].items()))
    check('graphics_deferred',not list((out/'figures').glob('*.png')) and not list((out/'figures').glob('*.svg')))
    check('inputs_unchanged',all(sha(Path(p))==digest for p,digest in d['hashes'].items()))
    # Compact the per-row proof while retaining the total verified count.
    compact={k:v for k,v in checks.items() if not k.startswith('candidate_row_')}
    return dict(status='passed',checks=compact,source_rows_verified=len(pool),all_preserved_source_fields_checked=True,
        acceptance_questions=json.loads((out/'audit/acceptance_questions.json').read_text()),
        graphics='deferred_by_user',models_called=0,day8_accessed=False,deep_cases_selected=0)
