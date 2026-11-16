from pathlib import Path
import json
import numpy as np,pandas as pd
from scipy.stats import pearsonr
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
P=Path(__file__).resolve().parent
f=pd.read_csv(P/'day6_to_day8_validation.csv');r=pd.read_csv(P/'day8_discovery/day8_to_day6_validation.csv')
cohorts=[('Day6 → Day8',f,f[f.day8_status=='OK'],'delta_percentage_points','day8_delta_pp','validation_supported'),('Day8 → Day6',r,r[r.status=='OK'],'day8_delta_pp','day6_delta_pp','supported')]
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'pdf.fonttype':42})
fig,axes=plt.subplots(1,2,figsize=(11,5.4));stats=[]
for ax,(title,d,a,xc,yc,flag) in zip(axes,cohorts):
 x=a[xc];y=a[yc];v=np.r_[x,y];pad=np.ptp(v)*.06;lim=(v.min()-pad,v.max()+pad);rr=float(pearsonr(x,y).statistic);agree=float((np.sign(x)==np.sign(y)).mean());n=int(a[flag].sum())
 ax.scatter(x,y,s=8,alpha=.25,color='#8065A6',edgecolors='none');ax.plot(lim,lim,'--',color='#999999',lw=1);ax.set(xlim=lim,ylim=lim,title=title,xlabel=title.split(' → ')[0]+' ΔP (pp)',ylabel=title.split(' → ')[1]+' ΔP (pp)');ax.set_aspect('equal');ax.spines[['top','right']].set_visible(False)
 ax.text(.04,.96,f'n = {len(a):,}\nPearson r = {rr:.3f}\nSame direction = {agree:.1%}',transform=ax.transAxes,va='top',linespacing=1.4)
 stats.append(dict(direction=title,locked=len(d),evaluable=len(a),supported=n,pearson=rr,direction_agreement=agree,proportion_evaluable=n/len(a),proportion_all=n/len(d)))
fig.suptitle('A   Cross-dataset consistency of independently discovered responses');fig.tight_layout()
for ext in ['png','pdf']:fig.savefig(P/f'Figure3A_bidirectional.{ext}',dpi=350)
plt.close(fig)
fig,ax=plt.subplots(figsize=(8.5,3.5))
for i,s in enumerate(stats):
 vals=[s['supported'],s['evaluable']-s['supported'],s['locked']-s['evaluable']];left=0
 for v,col,label in zip(vals,['#8065A6','#cbc1dc','#e1e4e8'],['Same direction + Holm ≤ 0.05','Evaluable, criterion not met','Not evaluable']):
  ax.barh(i,v,left=left,color=col,height=.45,label=label if i==0 else None);ax.text(left+v/2,i,f'{v:,}',ha='center',va='center',color='white' if left==0 else '#263238',fontsize=9);left+=v
 ax.text(s['locked']+100,i,f"{s['proportion_evaluable']:.2%}\nof evaluable",va='center',fontsize=9)
ax.set(yticks=[0,1],yticklabels=[s['direction'] for s in stats],xlabel='Number of locked candidate associations',title='B   Validation outcomes',xlim=(0,7700));ax.invert_yaxis();ax.spines[['top','right','left']].set_visible(False);ax.legend(loc='upper center',bbox_to_anchor=(.5,-.3),frameon=False,ncol=1,fontsize=9);fig.tight_layout();fig.subplots_adjust(bottom=.4)
for ext in ['png','pdf']:fig.savefig(P/f'Figure3B_bidirectional.{ext}',dpi=350,bbox_inches='tight')
plt.close(fig)
pd.DataFrame(stats).to_csv(P/'bidirectional_summary.csv',index=False)
(P/'BIDIRECTIONAL_CAPTION.md').write_text('''**图3｜联合状态响应的双向跨数据集验证。** A，左图为Day6发现并锁定的关联在Day8中的响应，右图为Day8独立发现并锁定的关联在Day6中的响应。每个点为一个在验证数据集中可评价的扰动—联合状态关联；两方向分别为4,753和5,221条。ΔP为相对于各自数据集内batch匹配NT对照的状态比例差，单位为百分点；灰色虚线为y=x。两方向使用不同的发现候选集合，不是对同一批点交换坐标。B，展示各方向所有锁定候选的结局；统计支持要求同方向且完整方向候选家族Holm校正后p≤0.05。Day6→Day8为1,647/4,753（34.65%），Day8→Day6为3,201/5,221（61.31%）；若使用全部锁定候选为分母，则分别为26.87%和49.81%。不可评价候选保留，以p=1参与校正但效应不补零。Day8 Stage1的内部NT两折仅用于发现质量控制，最终验证使用完整另一数据集。本图评估跨筛选数据集和时间点一致性，不证明高阶特异性或因果机制，也不将未达到统计标准解释为不复现。\n''')
print(pd.DataFrame(stats).to_string(index=False))
