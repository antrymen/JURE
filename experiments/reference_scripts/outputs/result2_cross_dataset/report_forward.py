"""Audit frozen forward results and render Figure 3A/B; no new discovery."""
from pathlib import Path
import json,hashlib
import h5py,numpy as np,pandas as pd
from scipy.stats import pearsonr,false_discovery_control
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
P=Path(__file__).resolve().parent;ROOT=P.parents[1]
d=pd.read_csv(P/'day6_to_day8_validation.csv');a=d[d.day8_status=='OK'].copy()
# Independent explicit full-family Holm computation (including unevaluable p=1).
p=d.day8_p_value.to_numpy();order=np.argsort(p,kind='stable');adj=np.empty(len(p));adj[order]=np.minimum(1,np.maximum.accumulate(p[order]*(len(p)-np.arange(len(p)))))
assert np.allclose(adj,d.day8_holm,rtol=1e-12,atol=1e-15)
assert len(d)==6129 and not d.duplicated(['target','pattern']).any()
assert d.loc[d.day8_status!='OK','day8_delta_pp'].isna().all()
assert np.allclose(a.day8_delta_pp,100*(a.day8_perturbation_frequency-a.day8_matched_nt_frequency))
assert ((a.day8_perturbation_frequency>=0)&(a.day8_perturbation_frequency<=1)).all()
assert ((a.day8_matched_nt_frequency>=0)&(a.day8_matched_nt_frequency<=1)).all()
# Metadata check and independent direct reconstruction for deterministic candidate sample.
with h5py.File(ROOT/'data/replogle_k562_gwps_day8/ReplogleWeissman2022_K562_gwps.h5ad') as f:
 cats=f['obs/perturbation/categories'].asstr()[:];labels=cats[f['obs/perturbation/codes'][:]];batch=f['obs/batch'][:]
 genes=json.loads((P/'extraction.json').read_text())['genes'];enc=np.load(P/'day8_candidate_detection.npy',mmap_mode='r');gi={g:i for i,g in enumerate(genes)}
 sample=a.iloc[np.linspace(0,len(a)-1,7).astype(int)];errors=[]
 for _,r in sample.iterrows():
  terms=r.pattern.split();yes=np.all(enc[:,[gi[t[:-1]] for t in terms]]==[int(t[-1]=='+') for t in terms],axis=1)
  pert=labels==r.target;freq=yes[pert].mean();base=0.
  for b in np.unique(batch[pert]):
   w=np.sum(pert&(batch==b))/pert.sum();base+=w*yes[(labels=='control')&(batch==b)].mean()
  errors.append(abs(100*(freq-base)-r.day8_delta_pp))
 assert max(errors)<1e-10
 meta={'cells':len(labels),'nt_cells':int(np.sum(labels=='control')),'batches':len(np.unique(batch)),'seven_direct_recounts_max_error_pp':max(errors),'h5ad_md5_verified_in_analysis':'13db594f8f1d2ccb88fec44a13e414dc'}
same=int(a.same_direction.sum());supported=int(a.validation_supported.sum());r=float(pearsonr(a.delta_percentage_points,a.day8_delta_pp).statistic)
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'pdf.fonttype':42})
fig,ax=plt.subplots(figsize=(6.1,6.1));x=a.delta_percentage_points;y=a.day8_delta_pp
lo=min(x.min(),y.min());hi=max(x.max(),y.max());pad=(hi-lo)*.06;lim=(lo-pad,hi+pad)
ax.scatter(x,y,s=10,alpha=.25,color='#8065A6',edgecolors='none');ax.plot(lim,lim,'--',color='#999999',lw=1)
ax.set(xlim=lim,ylim=lim,xlabel='Day6 joint-state change (pp)',ylabel='Day8 joint-state change (pp)',title='A   Day6 discovery → Day8 validation');ax.set_aspect('equal');ax.spines[['top','right']].set_visible(False)
ax.text(.04,.96,f'n = {len(a):,} evaluable associations\nPearson r = {r:.3f}\nSame direction = {same/len(a):.1%}',transform=ax.transAxes,va='top',linespacing=1.5)
fig.tight_layout()
for ext in ['png','pdf']:fig.savefig(P/f'Figure3A_day6_to_day8.{ext}',dpi=350)
plt.close(fig)
fig,ax=plt.subplots(figsize=(7,2.8));vals=[supported,len(a)-supported,len(d)-len(a)];colors=['#8065A6','#cbc1dc','#e1e4e8'];left=0
for v,col,label in zip(vals,colors,['Same direction + Holm ≤ 0.05','Evaluable, criterion not met','Not evaluable']):
 ax.barh(0,v,left=left,height=.45,color=col,label=label);ax.text(left+v/2,0,f'{v:,}',ha='center',va='center',color='white' if left==0 else '#263238');left+=v
ax.set(xlim=(0,len(d)),ylim=(-.45,.75),yticks=[],xlabel='Number of Day6-locked candidate associations',title='B   Day8 validation outcomes')
ax.spines[['top','right','left']].set_visible(False);ax.legend(loc='upper center',bbox_to_anchor=(.5,-.35),ncol=1,frameon=False,fontsize=9)
ax.text(0,.85,f'Supported: {supported/len(a):.2%} of evaluable; {supported/len(d):.2%} of all locked candidates',transform=ax.transAxes,fontsize=9)
fig.tight_layout();fig.subplots_adjust(bottom=.43)
for ext in ['png','pdf']:fig.savefig(P/f'Figure3B_day6_to_day8.{ext}',dpi=350,bbox_inches='tight')
plt.close(fig)
report=f'''# Result 2：Day6发现 → Day8验证

本次只完成单向验证。Day8没有重新发现候选，没有最终A/B划分；原有独立模型分析保留，不覆盖。

## 数据与质量检查
Day8文件MD5与保存的公开数据源记录一致，包含{meta['cells']:,}个细胞、{meta['nt_cells']:,}个control细胞、{meta['batches']}个batch。57个状态基因全部唯一匹配，读取的计数非负、有限、为整数值，以count>0编码。全量源文件采用float32存储不影响这些整数计数的检测定义。提取缓存与同一文件绑定。另选7条按固定行号直接从细胞检测表重算，最大误差{max(errors):.3g}pp。完整家族Holm独立复算通过。

## 预设定义
来自Day6的6,129条探索性候选完全锁定；它们源于341状态参考目录，实际候选覆盖223状态、419靶点。Day8每target≥100，所有占用batch NT≥20，有效NT≥100；NT用Day8自身对照按扰动batch细胞数加权。检验原分层超几何双侧精确检验，完整6,129条Holm≤0.05且Day6/Day8方向一致。不可评价项p=1参加记账，效应仍缺失。未按Day8效应、事件数、p值或方向选择散点。

## 实际结果
- 锁定：6,129；可评价：{len(a):,}（{len(a)/len(d):.2%}），涉及{a.target.nunique()}个靶点、{a.pattern.nunique()}个状态。
- 不可评价：细胞数不足1,371条；TREX2靶点缺失5条。
- 同方向：{same:,}/{len(a):,}（{same/len(a):.2%}）。
- Pearson r={r:.6f}；Spearman见day6_to_day8_summary.json。
- 同方向且Holm≤0.05：{supported:,}条；占可评价的{supported/len(a):.2%}，占全部锁定的{supported/len(d):.2%}。
- 可评价但不满足统计支持规则：{len(a)-supported:,}条。不满足规则不等于已经证明不复现。

## 可用于正文的中文初稿
为评估扰动相关联合状态响应的跨数据集一致性，我们将Day6发现的6,129条探索性候选关联锁定，并在K562 Day8数据中检验相同扰动与检测状态。Day8中共有4,753条关联满足预设可评价条件，其中{same:,}条（{same/len(a):.2%}）与Day6具有相同变化方向，效应量相关系数为r={r:.3f}。采用Day8内batch匹配对照和分层精确检验后，1,647条关联满足方向一致且完整候选家族Holm校正后p≤0.05的标准，占可评价关联的34.65%。这些结果支持部分Day6联合状态响应在另一筛选数据集和时间点具有一致性，同时区分了方向一致与统计支持。

## 解释边界
这是Day6 essential与Day8 genome-wide筛选间的跨数据集/时间点比较，不能未经原研究实验设计核对称为完全独立生物学重复。相关系数没有对依赖候选行做普通显著性推断。候选共享靶点、基因和NT；检测状态不等于调控方向。本实验不证明超越一阶/二阶模型的信息或因果机制。Day8→Day6未运行，不称双向验证。不能把支持率34.65%说成全部候选的通过率。

## 文件与复现
`validate_day6_to_day8.py`负责计算；`report_forward.py`负责复核、图和报告。使用项目.venv，设置PYTHONPATH或脚本内路径即可。输入哈希见forward_inputs_frozen.json；本次核对见forward_quality_audit.json。未依赖服务器，SSH失败未影响本地分析。CSV保留全部候选和不可评价原因。
'''
(P/'RESULT2_FORWARD_REPORT.md').write_text(report)
(P/'figure3_forward_caption.md').write_text(f'''**图3｜Day6发现的联合状态响应在Day8中的验证。** A，每个点为一条Day6锁定且Day8可评价的扰动—联合状态关联，共{len(a):,}条。横纵轴分别为Day6和Day8相对于各自batch匹配NT对照的状态比例差（pp）；灰色虚线为y=x。Pearson r={r:.3f}，方向一致率{same/len(a):.2%}。B，全部6,129条候选的验证结局：1,647条同方向且Holm校正后p≤0.05，{len(a)-supported:,}条可评价但未满足该标准，1,376条不可评价。支持率为可评价候选的34.65%，或全部锁定候选的26.87%。校正家族包括全部6,129条，不可评价项以p=1记账；不以验证侧效应大小筛选。该分析评估跨筛选数据集/时间点一致性，不证明高阶特异性或因果机制。\n''')
meta.update(all_holm_recomputed=True,all_candidate_rows_retained=True,plot_all_evaluable=True,scientific_direction='Day6_to_Day8_only')
(P/'forward_quality_audit.json').write_text(json.dumps(meta,indent=2));print(json.dumps(meta,indent=2))
