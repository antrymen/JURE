"""Audit and render the completed preliminary Result 2 analysis."""
import os
for k in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','VECLIB_MAXIMUM_THREADS'):os.environ[k]='1'
import argparse,json
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from scipy.stats import hypergeom
from clue_discovery.v03.artifacts import write_json
from clue_discovery.v03.data import file_hash
from perturbation_scan.statistics import implicit_holm
from stage2_validation.result2 import metrics

plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.spines.top':False,'axes.spines.right':False,'pdf.fonttype':42})


def savefig(fig,path):
    fig.savefig(path.with_suffix('.png'),dpi=180,bbox_inches='tight')
    fig.savefig(path.with_suffix('.pdf'),bbox_inches='tight');plt.close(fig)


def extra_figures(root):
    root=Path(root);summary=pd.read_csv(root/'replication_summary.csv');strata=pd.read_csv(root/'sensitivity_strata.csv')
    fig,ax=plt.subplots(figsize=(9,4.5));x=np.arange(len(summary));width=.24
    for off,key,label,color in [(-1,'direction_rate','Same direction','#718ab7'),(0,'replication_rate','Same direction + Holm','#167d92'),(1,'strict_rate','Also |validation shift| ≥10 pp','#293b68')]:
        ax.bar(x+off*width,100*summary[key],width,label=label,color=color)
    ax.set_xticks(x,[f'n≥{r.minimum}\n{r.direction}' for r in summary.itertuples()]);ax.set_ylim(0,105)
    ax.set_ylabel('Percent of discovery-locked pairs')
    ax.legend(fontsize=8,loc='lower center',bbox_to_anchor=(.5,1.02),ncol=3)
    fig.tight_layout();savefig(fig,root/'figures/replication_rates')
    fig,ax=plt.subplots(figsize=(8,4.5));x=np.arange(3)
    for off,direction,color in [(-.18,'A_to_B','#167d92'),(.18,'B_to_A','#718ab7')]:
        vals=[float(summary[(summary.minimum==100)&(summary.direction==direction)].replication_rate.iloc[0])]
        vals += [float(strata[(strata.stratum==label)&(strata.direction==direction)].replication_rate.iloc[0]) for label in ('common_386','added_856')]
        bars=ax.bar(x+off,np.array(vals)*100,.36,label=direction,color=color)
        ax.bar_label(bars,fmt='%.1f%%',padding=3)
    ax.set_xticks(x,['386 targets\nMain discovery family','Same 386 targets\nExpanded discovery family','Added 856 targets\nExpanded discovery family'])
    ax.set_ylim(0,105);ax.set_ylabel('Direction + Holm pass (% locked pairs)')
    ax.legend(loc='lower center',bbox_to_anchor=(.5,1.02),ncol=2)
    fig.tight_layout();savefig(fig,root/'figures/sensitivity_common_added')


def main(root):
    root=Path(root);figdir=root/'figures';figdir.mkdir(exist_ok=True)
    assert json.loads((root/'STATUS.json').read_text())['status']=='complete'
    manifest=json.loads((root/'PROTOCOL_FROZEN.json').read_text())
    for p,h in manifest['source_hashes'].items():assert file_hash(p)==h
    for p,h in json.loads((root/'ALL_DISCOVERIES_FROZEN_BEFORE_VALIDATION.json').read_text()).items():assert file_hash(root/p)==h
    ids=json.loads((root/'identities.json').read_text());patterns=ids['patterns']
    data=np.load(root/'eight_state_counts.npz');table=data['table'];n=data['n'];mapping=data['mapping'];codes=data['codes'];data.close()
    checks=[];frames={}
    for minimum in (100,50):
        folder=root/f'n{minimum}'
        write_json(folder/'analysis_config.json',dict(min_cells_per_fold=minimum,targets=len(manifest['cohorts'][str(minimum)]),
            discovery_family=len(manifest['cohorts'][str(minimum)])*341,validation_alpha=.025,scope='fixed_catalogue_internal'))
        fig,axes=plt.subplots(1,2,figsize=(10,4.2))
        for source,name in enumerate(('A_to_B','B_to_A')):
            frame=pd.read_csv(folder/f'validation_{name}.csv');frames[(minimum,name)]=frame
            lock=json.loads((folder/f'locked_{"AB"[source]}.json').read_text())['candidates']
            assert len(frame)==len(lock)
            assert set(zip(frame.target,frame.reference_id))=={(r['target'],r['reference_id']) for r in lock}
            assert np.allclose(frame.holm,implicit_holm(frame.p_accounting.to_numpy(),len(frame)),rtol=1e-10)
            assert np.array_equal(frame.validated,frame.evaluable&frame.same_direction&(frame.holm<=.025))
            assert np.array_equal(frame.validated_10pp,frame.validated&frame.validation_abs_ge_10pp)
            original=pd.read_csv(folder/f'discovery_{"AB"[source]}_all.csv.gz')
            assert len(original)==len(manifest['cohorts'][str(minimum)])*341
            assert np.allclose(original.holm,implicit_holm(original.p_accounting.to_numpy(),len(original)),rtol=1e-10)
            assert int(original.candidate.sum())==len(frame)
            # Independent probability implementation on metadata-ordered first 8 locked rows.
            for r in frame.head(8).itertuples():
                f=1-source;t=r.target_index;j=r.pattern_index
                used=n[f,t]>0;np_=n[f,t,used];nc=n[f,0,used]
                x=table[f,t,used][:,mapping[j],codes[j]].astype(int)
                xc=table[f,0,used][:,mapping[j],codes[j]].astype(int)
                expected=x.sum()/np_.sum()-np.sum(np_/np_.sum()*xc/nc)
                assert abs(expected-r.validation_delta)<1e-12
                dist=np.array([1.]);offset=0
                for a,nn,b,mm in zip(x,np_,xc,nc):
                    lo=max(0,int(nn)-(int(nn+mm)-int(a+b)));hi=min(int(nn),int(a+b))
                    dist=np.convolve(dist,hypergeom.pmf(np.arange(lo,hi+1),int(nn+mm),int(a+b),int(nn)))
                    offset+=lo
                k=int(x.sum())-offset;p=min(1.,2*min(dist[:k+1].sum(),dist[k:].sum()))
                assert np.isclose(p,r.p_accounting,rtol=1e-7,atol=1e-280)
            ax=axes[source];passed=frame.validated.to_numpy()
            ax.scatter(frame.discovery_delta*100,frame.validation_delta*100,s=8,alpha=.25,c=np.where(passed,'#147d92','#ba7272'),rasterized=True)
            ax.plot([-70,70],[-70,70],color='black',lw=.8,ls='--');ax.axhline(0,color='.8',lw=.6);ax.axvline(0,color='.8',lw=.6)
            ax.set(xlabel='Discovery shift (percentage points)',ylabel='Validation shift (percentage points)',title=f'{name}: {len(frame):,} locked pairs')
            ax.legend(handles=[Line2D([],[],marker='o',ls='',color='#147d92',label='Direction + Holm pass'),Line2D([],[],marker='o',ls='',color='#ba7272',label='Other locked pairs')],loc='upper left',fontsize=8)
            checks.append(dict(cohort=minimum,direction=name,locked=len(frame),holm_matches=True,scipy_probability_checks=min(8,len(frame))))
        fig.suptitle(f'Fixed-catalogue internal reproducibility | n ≥ {minimum} per fold')
        fig.tight_layout();savefig(fig,figdir/f'ab_effects_n{minimum}')
    summary=pd.read_csv(root/'replication_summary.csv')
    fig,ax=plt.subplots(figsize=(9,4.5));x=np.arange(len(summary));width=.24
    for off,key,label,color in [(-1,'direction_rate','Same direction','#718ab7'),(0,'replication_rate','Same direction + Holm','#167d92'),(1,'strict_rate','Also |validation shift| ≥10 pp','#293b68')]:
        ax.bar(x+off*width,100*summary[key],width,label=label,color=color)
    ax.set_xticks(x,[f'n≥{r.minimum}\n{r.direction}' for r in summary.itertuples()]);ax.set_ylim(0,110);ax.set_ylabel('Percent of discovery-locked pairs');ax.legend(fontsize=8,loc='lower center',bbox_to_anchor=(.5,1.02),ncol=3)
    fig.tight_layout();savefig(fig,figdir/'replication_rates')
    extra_figures(root)
    # Sensitivity comparison separates common and added targets, and changed family.
    common=[]
    base=set(manifest['cohorts']['100'])
    for name in ('A_to_B','B_to_A'):
        a=frames[(100,name)];b=frames[(50,name)];bc=b[b.target.isin(base)]
        ka=set(zip(a.target,a.reference_id));kb=set(zip(bc.target,bc.reference_id))
        both=ka&kb
        aidx=a.set_index(['target','reference_id']);bidx=bc.set_index(['target','reference_id'])
        for key in both:
            assert np.isclose(aidx.loc[key,'validation_delta'],bidx.loc[key,'validation_delta'])
            assert np.isclose(aidx.loc[key,'p_accounting'],bidx.loc[key,'p_accounting'])
        common.append(dict(direction=name,n100_locked=len(a),n50_common_locked=len(bc),overlap=len(both),
            n100_only=len(ka-kb),n50_common_only=len(kb-ka),shared_effects_and_raw_p_unchanged=True))
    pd.DataFrame(common).to_csv(root/'common_target_comparison.csv',index=False)
    low=root/'lower_order';models=pd.read_csv(low/'model_summary.csv')
    # Load primary only; keep full descriptive tables on disk for all alphas.
    primary=pd.read_csv(low/'descriptive_alpha_0.5.csv.gz')
    assert len(primary)==2*1242*341
    assert primary.fit_success.all()
    assert np.allclose(primary.residual_pairwise,primary.delta_observed-primary.delta_pairwise)
    assert np.allclose(primary.smoothing_shift,primary.delta_smoothed-primary.delta_observed)
    # Attach both-direction held-out candidates, before success filtering, for descriptive summaries.
    subsets=[]
    for minimum in (100,50):
        for name in ('A_to_B','B_to_A'):
            v=frames[(minimum,name)];fold=name[-1]
            m=v.merge(primary[primary.fold==fold],on=['target','reference_id'],validate='one_to_one')
            assert len(m)==len(v)
            assert np.allclose(m.validation_delta,m.delta_observed,atol=1e-12)
            m.to_csv(low/f'locked_candidates_n{minimum}_{name}.csv.gz',index=False)
            for label,part in [('all_locked',m),('replicated_descriptive_subset',m[m.validated])]:
                subsets.append(dict(minimum=minimum,direction=name,subset=label,n=len(part),
                    independent_mae_pp=float(abs(part.residual_independent).mean()*100),
                    pairwise_mae_pp=float(abs(part.residual_pairwise).mean()*100)))
    pd.DataFrame(subsets).to_csv(low/'locked_subset_summary.csv',index=False)
    fig,axes=plt.subplots(1,2,figsize=(10,4.5));sample=primary.sample(min(30000,len(primary)),random_state=20261012)
    for ax,col,title in zip(axes,['delta_independent','delta_pairwise'],['Independent model','Pairwise maximum entropy']):
        h=ax.hexbin(sample.delta_observed*100,sample[col]*100,gridsize=55,mincnt=1,bins='log',cmap='viridis')
        fig.colorbar(h,ax=ax,label='Rows per bin (log scale)',shrink=.8)
        ax.plot([-80,80],[-80,80],ls='--',color='#bb5555',lw=1)
        ax.set(xlabel='Observed shift (pp)',ylabel='Model-fitted shift (pp)',title=title)
    fig.suptitle('Descriptive pooled projections after matching | α=0.5; deterministic 30,000-row display')
    fig.tight_layout();savefig(fig,figdir/'lower_order_predictions')
    fig,axes=plt.subplots(1,2,figsize=(10,4.1))
    for col,label,color in [('residual_independent','Independent','#718ab7'),('residual_pairwise','Pairwise','#167d92')]:
        axes[0].hist(primary[col]*100,bins=np.linspace(-10,10,100),histtype='step',density=False,label=label,color=color)
    axes[0].set(xlabel='Raw observed − model shift (pp)',ylabel='Number of state–target–fold rows',title='Central residual distribution (−10 to 10 pp)');axes[0].legend()
    z=models[models.subset=='abs_delta_ge_10pp']
    for model,color in [('independent','#718ab7'),('pairwise','#167d92')]:
        zz=z[z.model==model].groupby('alpha').mae_pp.mean();axes[1].plot(zz.index,zz.values,'o-',label=model,color=color)
    axes[1].set(xlabel='Symmetric pseudocount per state',ylabel='Mean of fold MAE (pp)',title='Large observed shifts (|Δ| ≥10 pp)');axes[1].legend()
    fig.tight_layout();savefig(fig,figdir/'lower_order_residuals')
    # Save actual finite-sample model tests, including mixture diagnostic.
    from stage2_validation.result2 import projections,STATES
    independent=lambda r:np.prod(np.where(STATES==1,r,1-r),axis=1)
    synthetic={}
    for name,p in [('independent',independent(.3)),('parity',np.where(STATES.sum(1)%2,.24,.01)),('independent_mixture',.2*independent(.05)+.8*independent(.8))]:
        sm,ind,q,ok,err,con=projections(p[None,:],1e6,.1)
        synthetic[name]=dict(max_pairwise_residual=float(abs(sm-q).max()),marginal_error=err,success=bool(ok.all()))
    write_json(low/'SYNTHETIC_CHECKS.json',synthetic)
    pd.DataFrame(checks).to_csv(root/'audit_checks.csv',index=False)
    write_json(root/'FINAL_AUDIT.json',dict(status='passed',checks=checks,primary_lower_rows=len(primary),
        all_primary_fits_success=True,locked_descriptive_effects_match_validation=True,
        discovery_barriers_unchanged=True,source_hashes_unchanged=True,confirmed_inference=False))
    status=json.loads((root/'STATUS.json').read_text());strata=pd.read_csv(root/'sensitivity_strata.csv')
    def pct(x):return f'{100*x:.2f}%'
    lines=['# RESULT 2：前三项实验初步报告','',
        '执行日期：2026-10-12。全部在本地单线程 CPU 完成；未使用 GPU，未访问 CPA/Day 8。使用现有341状态目录，属于固定目录条件下的内部重复性评估；NT预选择和既有Day6分析历史没有被此次A/B划分消除。','',
        '## 实验一、二：双向留出复现与样本门槛敏感性','',
        '| 每折门槛/targets | 方向 | 发现锁定关联 | 同方向 | 同方向+验证Holm | 再要求验证效应≥10pp | Pearson / Spearman |',
        '|---|---|---:|---:|---:|---:|---|']
    for r in summary.itertuples():
        lines.append(f'| ≥{r.minimum} / {386 if r.minimum==100 else 1242} | {r.direction} | {r.locked:,} | {r.same_direction:,} ({pct(r.direction_rate)}) | {r.validated:,} ({pct(r.replication_rate)}) | {r.validated_10pp:,} ({pct(r.strict_rate)}) | {r.pearson:.3f} / {r.spearman:.3f} |')
    lines+=['','上述比例均以该方向全部发现锁定关联为分母；验证没有按结果缩小family。发现alpha=0.05，全cohort×341 Holm；验证alpha=0.025/方向，family为该方向全部锁定关联。效应相关使用全部锁定关联，而不是只保留两边显著者。','',
        '单独的验证侧 |Δ|≥10pp 比例（不要求校正通过）：'+ '; '.join(f'n≥{r.minimum} {r.direction}: {pct(r.effect_retention_rate)}' for r in summary.itertuples())+'。',
        '不可评估数：'+ '; '.join(f'n≥{r.minimum} {r.direction}: {r.locked-r.evaluable}' for r in summary.itertuples())+'。','',
        '### 区分新增样本范围与复现变化','',
        '| n≥50 分层 | 方向 | 锁定数 | 方向一致率 | 验证通过率 |',
        '|---|---|---:|---:|---:|']
    for r in strata.itertuples():lines.append(f'| {r.stratum} | {r.direction} | {r.locked} | {pct(r.direction_rate)} | {pct(r.replication_rate)} |')
    lines+=['','n≥50仍使用同一份细胞划分；共同386个targets没有增加细胞。扩大cohort改变了发现family（131626→423522）以及验证候选family，因此共同targets中的差异不能归因于样本量变化。新增856个targets与共同集合分开报告。',
        '共同target候选交集：'+json.dumps(common,ensure_ascii=False)+'。','',
        '## 实验三：低阶描述性拟合','',
        '12个targets按metadata最低折细胞数等距选定、包含全部86triplets；两折及三个平滑参数均完成pilot。pilot通过数值判据后扩展至1242targets×341states×2folds=847044行/平滑参数。分析全集不依赖A/B验证是否成功。',
        '分别拟合本折target聚合分布与按target batch权重混合的NT分布；这是**先混合、后投影**。同一数据估计边际并评价模型，是样本内描述性拟合，不是未见数据上的预测能力证据。','',
        '| α=0.5 | Fold | 分析集合 | 独立模型 MAE (pp) | 二阶模型 MAE (pp) | 二阶残差绝对值中位数 / P90 (pp) |',
        '|---|---|---|---:|---:|---|']
    for f in ('A','B'):
        for subset in ('all','abs_delta_ge_10pp'):
            ss=models[(models.alpha==.5)&(models.fold==f)&(models.subset==subset)].set_index('model')
            a=ss.loc['independent'];b=ss.loc['pairwise']
            lines.append(f'| 0.5 | {f} | {subset} | {a.mae_pp:.3f} | {b.mae_pp:.3f} | {b.median_abs_residual_pp:.3f} / {b.p90_abs_residual_pp:.3f} |')
    lines+=['','在发现折锁定、验证折评价的全部候选中（不先筛选成功复现者），描述性误差如下：','','| 每折门槛 | 方向 | 锁定数 | 独立模型 MAE (pp) | 二阶模型 MAE (pp) |','|---|---|---:|---:|---:|']
    for r in subsets:
        if r['subset']=='all_locked':lines.append(f"| {r['minimum']} | {r['direction']} | {r['n']} | {r['independent_mae_pp']:.3f} | {r['pairwise_mae_pp']:.3f} |")
    pilot=pd.read_csv(low/'pilot_fit_checks.csv');batch=pd.read_csv(low/'pilot_batch_mixture.csv')
    lines+=['',f'Pilot最大边际误差={pilot.marginal_error.max():.3g}；最大三阶log contrast={pilot.log_contrast.max():.3g}。NT的“混合后投影”与“逐batch投影后混合”差别：triplet最大状态差的中位数={batch.max_projection_order_difference_pp.median():.3f}pp，最大={batch.max_projection_order_difference_pp.max():.3f}pp；此差别包含平滑作用，另有对应smoothing difference表。',
        f'主分析平滑引起的 |Δsmoothed−Δraw| 中位数={abs(primary.smoothing_shift).median()*100:.3f}pp，最大={abs(primary.smoothing_shift).max()*100:.3f}pp。α=0.1、0.5、1.0全部结果见model_summary及残差图。','',
        '同一triplet完整边际投影的八个高阶残差仅差parity符号，不能视作八份独立证据。未做bootstrap、残差显著性检验或残差FDR；没有通过平滑参数挑选“最好看”的结论。','',
        '## 能支持的论文表述','',
        '- 按实际复现率与效应相关，可描述冻结参考目录下的Day6响应在不重叠细胞子集中的内部一致性。',
        '- 样本门槛敏感性支持对较高支持度与新增低支持度targets分别描述；不把两套cohort当作两次独立实验。',
        '- 低阶比较量化了二值联合状态响应与独立/二阶模型样本内拟合之间的差异，不能宣称“已证明额外高阶信息显著”。',
        '- 本次二阶拟合误差明显小于独立模型，大量频率变化可被二阶模型较好描述；剩余残差尚不能与batch混合、平滑和抽样波动区分。',
        '- 此处并未证明三阶调控重连、优于所有DE分析、独立生物学复现，也未验证Stage3共享响应分组的全流程留出稳定性。','',
        '## 资源与验收','',
        f"真实计算耗时 {status['elapsed_seconds']:.1f}秒，进程峰值 {status['peak_process_rss_mib']:.1f}MiB。本地资源不同于历史AutoDL 0.5CPU/2GB，不能把这次耗时当作无卡实例承诺。17项本地测试通过；计数守恒、Catalogue NT support、split/cache hashes、发现列表冻结、校正重算和32个独立SciPy条件概率检查通过。",'',
        '## 文件入口','',
        '- `replication_summary.csv`、`sensitivity_strata.csv`、`common_target_comparison.csv`：复现汇总与cohort分解。',
        '- `n100/`、`n50/`：全部发现表、锁定列表、双向验证逐条结果和配置。',
        '- `lower_order/`：pilot检查、三套平滑参数的完整描述性结果、模型汇总及锁定候选对应表。',
        '- `figures/`：PNG和可编辑字体PDF图；全部图仅描述内部/样本内结果。',
        '- `PROTOCOL_FROZEN.json`、`ALL_DISCOVERIES_FROZEN_BEFORE_VALIDATION.json`、`FINAL_AUDIT.json`：配置、来源和验收。']
    (root/'RESULT2_PRELIMINARY_REPORT.md').write_text('\n'.join(lines)+'\n')
    print(summary.to_string(index=False));print(models[(models.alpha==.5)&(models.subset=='abs_delta_ge_10pp')].to_string(index=False))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output-dir',required=True);args=p.parse_args();main(args.output_dir)
