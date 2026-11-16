import json,csv,hashlib
from pathlib import Path
from collections import Counter
root=Path('/Users/mac/Documents/ChatGPT/JURE'); out=Path(__file__).parent
spec=[('Day6 A → B','outputs/result2_preliminary_20261012/n100/summary_A_to_B.json','outputs/result2_preliminary_20261012/n100/validation_A_to_B.csv',.025,'evaluable','validated','holm'),('Day6 B → A','outputs/result2_preliminary_20261012/n100/summary_B_to_A.json','outputs/result2_preliminary_20261012/n100/validation_B_to_A.csv',.025,'evaluable','validated','holm'),('Day6 → Day8','outputs/result2_cross_dataset/day6_to_day8_summary.json','outputs/result2_cross_dataset/day6_to_day8_validation.csv',.05,'day8_status','validation_supported','day8_holm'),('Day8 → Day6','outputs/result2_cross_dataset/day8_discovery/reverse_summary.json','outputs/result2_cross_dataset/day8_discovery/day8_to_day6_validation.csv',.05,'status','supported','holm')]
main=[]; reasons=[]; sources=[]
labels={'insufficient_target_cells':'验证集扰动细胞数不足100','target_absent':'验证集靶点缺失','missing_genes':'验证集缺少联合状态所需基因','target_unavailable_after_fixed_cell_rules':'固定细胞规则后靶点不可用'}
for title,sp,cp,alpha,ec,pc,hc in spec:
 s=json.loads((root/sp).read_text()); rows=list(csv.DictReader((root/cp).open())); ok=lambda r:r[ec] in ['True','true','OK']; yes=lambda v:v.lower()=='true'
 N=len(rows); e=sum(ok(r) for r in rows); same=sum(ok(r) and yes(r['same_direction']) for r in rows); passed=sum(yes(r[pc]) for r in rows)
 assert (N,e,passed)==(s['locked'],s['evaluable'],s.get('validated',s.get('supported')))
 assert all(yes(r[pc])==(ok(r) and yes(r['same_direction']) and float(r[hc])<=alpha) for r in rows)
 rate=s.get('direction_rate',s.get('direction_agreement_evaluable',s.get('direction_agreement')))
 assert abs(same/e-rate)<1e-12
 main.append([title,N,e,N-e,s.get('pearson',s.get('pearson_r')),same,rate,alpha,N,passed,passed/N,passed/e])
 counts=Counter(r[ec] for r in rows if not ok(r))
 assert sum(counts.values())==N-e
 if 'status_counts' in s:assert dict(Counter(r[ec] for r in rows))==s['status_counts']
 if not counts: reasons.append([title,'无不可评价关联',0,'全部锁定候选均可评价'])
 for k,n in counts.items():reasons.append([title,k,n,labels.get(k,k)])
 sources.append([title,sp,cp,'summary: locked/evaluable/pearson or pearson_r; CSV: '+ec+', same_direction, '+pc+', '+hc,hashlib.sha256((root/sp).read_bytes()).hexdigest(),hashlib.sha256((root/cp).read_bytes()).hexdigest()])
notes=[['指标或规则','说明'],['候选数 / Holm家族大小','每个方向验证前锁定的完整候选关联数；四个方向分别校正。'],['可评价数','具有有效验证效应且满足该流程验证侧支持条件的关联数。内部验证采用已有n100主分析结果。'],['Pearson r','直接引用原始汇总文件。内部两方向全部候选均可评价；跨数据集仅使用可评价关联。'],['方向一致率','同向关联数 / 可评价关联数。'],['验证通过数','可评价且发现与验证效应同向，并满足该方向Holm-adjusted P阈值。'],['通过率（全部）','验证通过数 / 全部锁定候选数。'],['通过率（可评价）','验证通过数 / 可评价关联数。'],['显著性阈值','内部A→B和B→A：Holm-adjusted P ≤ 0.025；跨数据集两方向：≤ 0.05。'],['效应门槛','本表的验证通过标准不要求验证侧 |ΔP| ≥ 10 pp；内部已有的validated_10pp严格指标不用于本表。'],['跨数据集可评价条件','扰动细胞≥100，每个匹配批次NT≥20，有效NT样本量≥100；靶点及状态基因须可匹配。'],['不可评价处理','留在完整锁定检验家族中，以p=1计入Holm校正；跨数据集验证效应记为缺失。'],['不可评价分类','按已有脚本检查顺序互斥计数；反向850条为固定细胞规则后不可用，不等同于原始数据全部没有对应靶点。'],['数据集','Day6：K562 Essential；Day8：K562 GWPS。内部A/B使用固定Day6参考目录；反向从Day8独立发现候选。'],['记录时间差异','前向summary中的reverse_status=NOT_RUN为当时状态；本表反向结果取后续完成的reverse_summary.json。'],['整理方式','逐行核对已有CSV的可评价、同向及通过标记与JSON汇总；未重跑检验、相关分析或模型。比例由已有计数汇总。'],['代码依据','stage2_validation/result2.py::validation,metrics；outputs/result2_cross_dataset/validate_day6_to_day8.py；run_day8_scan_and_validate.py。'],['整理日期','2026-11-02']]
(out/'data.json').write_text(json.dumps(dict(main=main,reasons=reasons,sources=sources,notes=notes),ensure_ascii=False,indent=2))
print(main)
