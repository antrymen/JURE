"""Extract original A/C Stage I evidence and independently replay fixed tables."""
import json,sys,hashlib,shutil
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import numpy as np
import pandas as pd
import yaml
from clue_discovery.v03.artifacts import digest,clean
from clue_discovery.v03.gain import HigherOrderGainEvaluator,conditional_gain_test
from clue_discovery.v03.bootstrap import bootstrap_gene_set
from clue_discovery.v03.evaluation import stage_seed
from clue_discovery.v04.config import ScalableConfig
from clue_discovery.v04_validation.policy import adjust_pvalues

ROOT=Path('outputs/real_nt_v04_holm_20260927/remote/outputs/real_nt/genes_1000_full')
OUT=Path('outputs/case_ac_stage1_audit_20260930')
RID={'A':'R2c25816f86029aa8ab80','C':'R9cf464d9b8c59de762d3'}
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,value):p.write_text(json.dumps(clean(value),ensure_ascii=False,indent=2)+'\n')
def main():
 OUT.mkdir(parents=True,exist_ok=True)
 cat=json.loads((ROOT/'holm_reference_catalogue_frozen.json').read_text())
 assert digest(cat['payload'])==cat['sha256']
 barriers=json.loads((ROOT/'both_discoveries_and_families_frozen_before_validation.json').read_text())
 assert all(sha(ROOT/k)==v for k,v in barriers.items())
 kernel_files=['clue_discovery/v03/gain.py','clue_discovery/v03/lower_order_null.py','clue_discovery/v03/bootstrap.py','clue_discovery/v03/evaluation.py','clue_discovery/v03/estimator.py','clue_discovery/v03/mfi.py','clue_discovery/v04_validation/policy.py']
 assert all(sha(k)==cat['payload']['source_hashes'][k] for k in kernel_files)
 cfg=ScalableConfig(**yaml.safe_load((ROOT/'config_frozen.yaml').read_text()))
 assert cfg.sha256==cat['payload']['config_hash']
 folds_path=Path('outputs/clue_hunting_v03_benchmark/scale_real/prepared/nt_fold_membership.csv')
 folds=pd.read_csv(folds_path,dtype={'cell_id':str,'batch':str})
 assert len(folds)==10691 and folds.cell_id.is_unique
 sets=pd.read_csv(ROOT/'corrected_gene_sets.csv.gz');holm=sets[sets.arm=='holm_025']
 for _,family in holm.groupby('family_id'):
  assert np.allclose(adjust_pvalues(family.p_for_accounting.to_numpy(),'holm'),family.adjusted_p,atol=1e-15,rtol=1e-12)
 rows=[];checks=[];availability=[]
 for letter,rid in RID.items():
  rec=next(r for r in cat['payload']['records'] if r['reference_id']==rid)
  save(OUT/f'case_{letter.lower()}_original_reference_record.json',rec)
  cells=pd.read_csv(f'outputs/case_{letter.lower()}_relationship_data_20260930/case_{letter.lower()}_cells_binary.csv',dtype={'cell_id':str,'batch':str})
  nt=cells[cells.group=='matched_NT'].merge(folds,on=['cell_id','source_row','batch'],how='inner',validate='one_to_one')
  assert len(nt)==10691
  for stage in ('discovery','validation'):
   for direction,ev in rec[stage+'_evidence'].items():
    if ev is None:continue
    fold=ev.get('validation_fold',direction);genes=rec['genes'];index=ev['state_index']
    part=nt[nt.fold==fold];codes=part[genes].to_numpy(dtype=int)@np.array([4,2,1]);counts=np.bincount(codes,minlength=8)
    gain=HigherOrderGainEvaluator(cfg.smoothing_alpha).evaluate(counts)
    assert len(part)==rec['nt_counts_by_fold'][fold]['n_cells'] and int(counts[index])==ev['support']
    assert int(counts.min())==ev['min_state_count']
    for field in ('mfi','set_level_gain'):
     assert np.isclose(gain[field],ev[field],atol=1e-12,rtol=1e-9),field
    for field in ('observed_probability','lower_order_expected_probability','pattern_absolute_gain'):
     assert np.isclose(gain[field][index],ev[field],atol=1e-12,rtol=1e-9),field
    seed=stage_seed(cfg,ev['evaluation_role'],genes,'bootstrap')
    boot=bootstrap_gene_set(counts,n_bootstrap=cfg.n_bootstrap,alpha=cfg.smoothing_alpha,seed=seed,ci_level=cfg.ci_level)
    boot_differences=[]
    for field in ('ci_low','ci_high','sign_stability'):
     for metric,original,replayed in [('mfi',ev['mfi_'+field],boot['summary']['mfi'][field]),('pattern_gain',ev['pattern_gain_bootstrap'][field],boot['summary']['pattern_absolute_gain'][index][field])]:
      if not np.isclose(original,replayed,atol=1e-11,rtol=1e-8):boot_differences.append(dict(metric=metric,field=field,original=original,replayed=replayed))
    assert boot['summary']['mfi']['ci_low']>0 and boot['summary']['pattern_absolute_gain'][index]['ci_low']>0
    hp=None;exact=None
    if stage=='validation':
     exact=conditional_gain_test(counts,alpha=cfg.smoothing_alpha)
     assert np.isclose(exact['p_gain'],ev['p_gain'],atol=1e-12,rtol=1e-8)
     test=next(x for x in rec['validation_family_tests'] if x['source_fold']==direction)
     actual=holm[(holm.candidate_id==rec['candidate_id'])&(holm.family_id==test['family_id'])].iloc[0]
     assert np.isclose(actual.adjusted_p,test['adjusted_p'])
     hp=test['adjusted_p']
    role=ev['evaluation_role'];np.savez_compressed(OUT/f'REPLAY_case_{letter}_{role}_bootstrap.npz',**boot['arrays'])
    save(OUT/f'REPLAY_case_{letter}_{role}_table.json',dict(not_original_artifact=True,scope='fixed-original-table numerical verification, no new discovery',counts=counts,genes=genes,fold=fold,role=role,seed=seed,n_bootstrap=1000,statistics={k:v for k,v in gain.items()},exact_p_gain=exact['p_gain'] if exact else None))
    checks.append(dict(case=letter,role=role,point_statistics_match=True,bootstrap_summaries_match=not boot_differences,bootstrap_differences=boot_differences,bootstrap_positive_ci_reproduced=True,exact_p_verified=stage=='validation'))
    for k in ('state_table_path','bootstrap_path','gain_path','gain_null_path'):
     if ev.get(k):availability.append(dict(case=letter,role=role,field=k,recorded_relative_path=ev[k],present_in_downloaded_subset=(ROOT/ev[k]).exists()))
    rows.append(dict(case=letter,reference_id=rid,candidate_id=rec['candidate_id'],stage=stage,role=role,fold=fold,
      n_cells=len(part),support=int(counts[index]),raw_frequency=ev['frequency'],observed_smoothed=ev['observed_probability'],pairwise_expected=ev['lower_order_expected_probability'],residual_pp=100*ev['pattern_absolute_gain'],residual_ci_low_pp=100*ev['pattern_gain_bootstrap']['ci_low'],residual_ci_high_pp=100*ev['pattern_gain_bootstrap']['ci_high'],mfi=ev['mfi'],mfi_ci_low=ev['mfi_ci_low'],mfi_ci_high=ev['mfi_ci_high'],mfi_sign_stability=ev['mfi_sign_stability'],set_level_KL_nats=ev['set_level_gain'],p_gain=ev['p_gain'],holm_adjusted_p=hp,min_state_count=int(counts.min()),bootstrap=1000))
 pd.DataFrame(rows).to_csv(OUT/'stage1_evidence_summary.csv',index=False)
 pd.DataFrame(availability).to_csv(OUT/'original_artifact_availability.csv',index=False)
 selected=sets[sets.candidate_id.isin([r['candidate_id'] for r in rows])]
 selected.to_csv(OUT/'original_corrected_gene_sets_rows.csv',index=False)
 for f in ('config_frozen.yaml','both_discoveries_and_families_frozen_before_validation.json','validation_families_frozen.json'):
  shutil.copyfile(ROOT/f,OUT/f)
 save(OUT/'VERIFICATION.json',dict(catalogue_payload_sha256=cat['sha256'],catalogue_hash_valid=True,prevalidation_freeze_hashes_valid=True,statistical_kernel_hashes_unchanged=True,checks=checks,
  folds_file=str(folds_path),folds_sha256=sha(folds_path),holm_recomputed_from_full_families=True,original_bootstrap_arrays_persisted=False,
  replay_arrays_label='Newly reconstructed from original fold membership, measured binary cells, frozen code/config/seeds; not downloaded original arrays.',
  original_numpy='2.3.2',local_numpy=np.__version__,bootstrap_replay_caveat='Summary differences retained; environment differs; replay arrays are not the original draws.',source_root=str(ROOT),audit_script_sha256=sha(__file__),models_called=0,agents_run=False,day8_read=False))
 print(pd.DataFrame(rows)[['case','stage','role','residual_pp','holm_adjusted_p']].to_string(index=False))
 print('Fixed-table point statistics, validation exact p-values and full-family Holm verified. Bootstrap replay differences recorded explicitly.')
if __name__=='__main__':main()
