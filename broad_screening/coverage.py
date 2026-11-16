"""Audit manually supplied cases; never choose cases or rank biological importance."""
from pathlib import Path
import json
import pandas as pd


def evaluate_case_set_coverage(case_ids, pool_path=None):
    if pool_path is None:
        pool_path=Path(__file__).resolve().parents[1]/'outputs/broad_screening_v01/tables/case_triage_table.csv'
    table=pd.read_csv(pool_path,keep_default_na=False)
    ids=list(case_ids)
    if len(ids)!=len(set(ids)): raise ValueError('Duplicate case IDs are not silently counted twice')
    unknown=sorted(set(ids)-set(table.case_id))
    if unknown: raise ValueError(f'Unknown case IDs: {unknown[:5]}')
    chosen=table.loc[table.case_id.isin(ids)]
    result=dict(n_cases=len(chosen),pool_cases=len(table),selected_case_ids=ids,
                evidence_status='day6_exploratory',selected_for_deep=False)
    for field,key in [('module_id','modules'),('direction','directions'),('target_cluster','target_clusters'),
                      ('target','targets'),('redundancy_group_id','redundancy_groups')]:
        values=sorted(set(chosen[field])); total=len(set(table[field]))
        result[key]=dict(values=values,covered=len(values),available=total,fraction=len(values)/total if total else None)
    core=table.loc[table.core_or_boundary=='stable_core','module_id']
    selected_core=sorted(set(chosen.loc[chosen.core_or_boundary=='stable_core','module_id']))
    result['stable_cores']=dict(values=selected_core,covered=len(selected_core),available=len(set(core)))
    for frame,name in [(table,'available'),(chosen,'covered')]:
        tags=set(t for raw in frame.strata for t in json.loads(raw))
        result.setdefault('strata',{})[name]=sorted(tags)
    result['overlapping_stratum_counts']={s:sum(s in json.loads(v) for v in chosen.strata)
                                         for s in result['strata']['available']}
    return result


def candidate_coverage_by_module(k, output=None):
    return _coverage(k,'module',output)


def candidate_coverage_by_pattern(k, output=None):
    return _coverage(k,'pattern',output)


def _coverage(k,unit,output):
    output=Path(output or Path(__file__).resolve().parents[1]/'outputs/broad_screening_v01')
    curve=pd.read_csv(output/'tables/candidate_concentration.csv')
    curve=curve.loc[curve.unit==unit]
    if not isinstance(k,int) or not 1<=k<=len(curve): raise ValueError('k outside coverage curve')
    return float(curve.loc[curve['rank']==k,'cumulative_fraction'].iloc[0])
