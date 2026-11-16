from pathlib import Path
import pandas as pd,json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
ROOT=Path(__file__).resolve().parents[1];O=ROOT/'outputs/result2_independent_residual_20261013'
s=pd.read_csv(O/'paired_summary.csv');b=pd.read_csv(O/'bootstrap_summary.csv');audit=json.loads((O/'RUN_AUDIT.json').read_text());assert audit['all_inputs_unchanged']
def tab(d):
 def fmt(x):return f'{x:.4f}' if isinstance(x,float) else str(x)
 return '| '+' | '.join(d.columns)+' |\n| '+' | '.join(['---']*len(d.columns))+' |\n'+'\n'.join('| '+' | '.join(map(fmt,r))+' |' for r in d.itertuples(index=False,name=None))
main=s[(s.cohort==100)&(s.alpha==.5)&(s.subset=='all')]
cols=['direction','residual_type','n','pearson','spearman','same_sign','median_abs_validation_pp','validation_mae_pp','median_abs_fold_difference_pp']
bs=b[(b['mode']=='raw')&(b.subset=='all')]
parts=['# Result 2：独立模型残差内部一致性补充结果','执行日期：2026-10-13。只复用冻结目录及方向锁定候选，不筛选验证通过者。主分析 n≥100/折，n≥50/折作敏感性。无 GPU，无 Day8，新结果单独保存。','## 1. 主要结果',tab(main[cols]),'same_sign 是比例；误差和残差均为百分点。raw 残差 = Δraw − Δind(smoothed marginals)；smoothed 残差 = Δsmoothed − Δind。两者必须区分，避免把平滑造成的差异全部解释为依赖信息。','原始 ΔP 跨折相关约 0.967/0.970；独立模型残差相关更低，说明原始变化的复现不等于残差全部复现。尚未估计这些相关系数的置信区间，不能将关联行视作独立样本计算普通相关显著性。','## 2. 验证折残差的重采样不确定性',tab(b),'在每个 fold × target × triplet 下对 perturbation/NT 各 batch 的八状态联合计数有放回 multinomial 重采样，保持 batch 样本数和权重，每次重算联合概率、边际和模型。对单条比较而言与 batch 内抽样细胞等价。1000 次，95% percentile pointwise 区间。','interval_in_discovery_direction 表示验证折区间完全落在发现折残差所指方向；此处仅报告描述性区间稳定性，不称残差显著率、FDR、独立验证通过率。不同 triplet/target 的抽样没有共享逐细胞权重，不提供总体比例 CI；同 triplet 内多个 states 不独立。未控制 guide 内相关性。','发现列表、NT reference 与先前数据探索的选择影响未被消除。区间由经验分布重采样得到，不是独立模型零假设的校准检验。不要根据离零区间事后宣称已发现若干显著额外响应。','## 3. 平滑与较小残差敏感性',tab(s[(s.cohort==100)&(s.residual_type=='raw')][['direction','alpha','subset','n','pearson','same_sign','validation_mae_pp']]),'1 pp 子集只在发现折残差上定义，阈值在补充协议固定。alpha=0 是未平滑独立模型；0.1/0.5/1.0 沿用既有敏感性参数，无参数优选。','## 4. 扩展 cohort',tab(s[(s.cohort==50)&(s.alpha==.5)&(s.subset=='all')][cols]),'n50 和 n100 使用同一划分，cohort/family 改变，不是独立重复；本次未对 n50 再做 bootstrap。','## 5. 与二阶模型的关系','已有锁定候选验证折二阶模型 MAE 为 A→B 0.618 pp、B→A 0.593 pp；相应独立模型为 3.553/3.462 pp。二阶模型对观测变化的描述误差更小，因此本次结果不能证明三阶特异性、调控重连或普遍优于差异表达。未重新拟合二阶模型。','当前独立模型采用先混合后投影；批次/细胞组成混合、平滑和抽样均可能影响残差。验证折模型使用验证折自身边际，属于该折的描述性投影；跨折配对检验的是残差一致性，而不是 A 训练预测 B 的学习泛化能力。','## 6. 可用于论文的中文表述']
vals={r.direction:r for r in main[main.residual_type=='raw'].itertuples()}
a=vals['A_to_B'];c=vals['B_to_A']
parts += [f'在固定参考目录下，我们对发现折锁定的全部候选关联比较了两折的独立模型残差。A→B 和 B→A 分析分别包含 {a.n:,} 和 {c.n:,} 个关联，其残差 Pearson 相关系数分别为 {a.pearson:.3f} 和 {c.pearson:.3f}，方向一致率分别为 {100*a.same_sign:.1f}% 和 {100*c.same_sign:.1f}%。验证折残差绝对值中位数分别为 {a.median_abs_validation_pp:.2f} 和 {c.median_abs_validation_pp:.2f} 个百分点。这些结果显示，单基因边缘概率独立组合未解释的响应成分在不同细胞子集中存在一定一致性，但其稳定性弱于原始状态频率变化。', '批次内重采样区间进一步描述了各关联残差的不确定性。该分析仍属于固定目录下、选择后的内部评价；不能将区间离零比例作为已校准的额外高阶发现率。','## 7. 资源和检查',json.dumps(audit,indent=2),'补充代数检查通过：未平滑的独立联合分布变化得到零残差；含 parity 偏离的已知分布保留相应残差。这些仅为实现检查，不加入真实数据统计。','## 8. 文件与复现','- paired_residuals.csv.gz：所有 cohort/direction/alpha 的逐关联配对值。\n- paired_summary.csv：方向、相关、误差与敏感性。\n- bootstrap_intervals.csv.gz：主分析所有候选的 raw/smoothed 双折区间。\n- bootstrap_summary.csv：区间的描述性汇总。\n- residual_crossfold.png/pdf：主分析跨折残差散点。\n- residual_interval_summary.png/pdf：区间方向稳定性。\n- INPUTS_FROZEN.json / PROTOCOL.md / RUN_AUDIT.json：来源、规则和审计。','复现：`MPLCONFIGDIR=/tmp/jure-mpl .venv/bin/python -m stage2_validation.independent_residual_followup`，随后 `.venv/bin/python -m stage2_validation.report_independent_residual`。复现会更新本补充目录，不触碰原实验输出。']
(O/'RESULT2_RESIDUAL_REPORT.md').write_text('\n\n'.join(parts)+'\n')
plt.rcParams.update({'pdf.fonttype':42,'font.size':10,'axes.spines.top':False,'axes.spines.right':False})
fig,ax=plt.subplots(figsize=(7,3.8));rates=bs.fraction_in_discovery_direction.to_numpy()*100
ax.barh(bs.direction,rates,color=['#8065A6','#338E80'],height=.5)
for i,r in enumerate(bs.itertuples()):ax.text(rates[i]+1,i,f'{r.interval_in_discovery_direction}/{r.n} ({rates[i]:.1f}%)',va='center')
ax.set(xlim=(0,100),xlabel='Validation interval entirely in discovery residual direction (%)');fig.suptitle('Nominal pointwise 95% intervals · descriptive, not FDR-controlled',fontsize=10)
fig.tight_layout()
for ext in ['png','pdf']:fig.savefig(O/f'residual_interval_summary.{ext}',dpi=300)
print(bs.to_string(index=False))
