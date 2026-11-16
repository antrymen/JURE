"""Render only after reverse validation completes; retain all locked associations."""
from pathlib import Path
import json
import numpy as np,pandas as pd
from scipy.stats import pearsonr
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
P=Path(__file__).resolve().parent;D=P/'day8_discovery'
d=pd.read_csv(D/'day8_to_day6_validation.csv');a=d[d.status=='OK'];M=len(d)
p=d.p_value.to_numpy();o=np.argsort(p,kind='stable');q=np.empty(M);q[o]=np.minimum(1,np.maximum.accumulate(p[o]*(M-np.arange(M))))
assert np.allclose(q,d.holm) and not d.duplicated(['target','reference_id']).any()
assert d.loc[d.status!='OK','day6_delta_pp'].isna().all()
s=json.loads((D/'reverse_summary.json').read_text());st=json.loads((D/'genes_1000_full/summary.json').read_text());sc=json.loads((D/'day8_scan/summary.json').read_text())
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'pdf.fonttype':42})
fig,ax=plt.subplots(figsize=(6.1,6.1));x=a.day8_delta_pp;y=a.day6_delta_pp;v=np.r_[x,y];pad=np.ptp(v)*.06;limits=(v.min()-pad,v.max()+pad)
ax.scatter(x,y,s=10,alpha=.25,color='#8065A6',edgecolors='none');ax.plot(limits,limits,'--',color='#999999',lw=1)
ax.set(xlim=limits,ylim=limits,xlabel='Day8 joint-state change (pp)',ylabel='Day6 joint-state change (pp)',title='Day8 discovery → Day6 validation');ax.set_aspect('equal');ax.spines[['top','right']].set_visible(False)
ax.text(.04,.96,f'n = {len(a):,} evaluable associations\nPearson r = {s["pearson_r"]:.3f}\nSame direction = {s["direction_agreement"]:.1%}',transform=ax.transAxes,va='top',linespacing=1.5)
fig.tight_layout()
for ext in ['png','pdf']:fig.savefig(D/f'day8_to_day6_scatter.{ext}',dpi=350)
plt.close(fig)
report=f'''# Day8 独立发现 → Day6 验证

本次从Day8的75,328个NT细胞独立建立参考目录。内部两折按batch分层、每折各自Fano排名前1000基因，沿用原搜索和统计规则。主统计配置相同，工程内存上限由1400调整为4096 MiB，失败记录保留。Day8全量扰动筛选后锁定候选，再读取Day6验证，不用Day6状态作为发现范围。

## Day8发现
```json
{json.dumps(st,ensure_ascii=False,indent=2)}
```

## Day8扰动筛选
```json
{json.dumps(sc,ensure_ascii=False,indent=2)}
```

## Day6验证
```json
{json.dumps(s,ensure_ascii=False,indent=2)}
```

验证同向且全Day8候选家族Holm≤0.05，缺失/样本不足项p=1记账、效应缺失；不按Day6效应筛选。两个方向候选集合不同，分母不能混用，不能把相关行当独立生物学重复。较早的Day6→Day8结果独立保留。Day6曾用于方法开发，反向验证不能称完全未触及的盲测或预注册确认性实验。跨时间点与不同筛选规模的复现不证明高阶特异性或机制。

## 复现
run_day8_reference.py → run_day8_scan_and_validate.py → report_reverse.py。输入/目录/候选锁定文件位于本目录。未改变历史结果。
'''
(D/'REVERSE_REPORT.md').write_text(report)
print(json.dumps(s,indent=2))
