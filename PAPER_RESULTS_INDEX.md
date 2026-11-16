# 最新论文结果—代码—配置—产物索引

日期：2026-11-15。核对最新版 `OUP_General_Template (1).pdf`，18页。PDF SHA256和页码索引保存在本地docs/audit/20261115，不把未发表论文自动放进公开仓库。

## 新版已确认的修订

Results4.2及FigS1内部验证阈值均已写为每方向0.025；S1.2明确Holm作用于三基因组合、同组合状态共享Gain检验；S2.1明确确定性Case File写入是当前Python实现，历史角色档案独立保存。Results4.2的Day8名称也已改为K562 GWPS。这些项不再作为当前待修正问题。旧的2026-11-14审计报告保留历史记录，以本文件更新为准。

## 关键结果索引

| 论文位置/结果 | 实现 | 冻结配置/产物（副本内） | 现在可以检查什么 |
|---|---|---|---|
| Results4.1；341状态、86组合 | real_nt_v04_holm/run.py::export_catalogue；clue_discovery/v04_validation/policy.py | evidence/discovery/reference_catalogue.json、config_frozen.yaml | 逐记录计数、genes去重、来源哈希 |
| Results4.2；内部两方向 | stage2_validation/result2.py::validation,metrics | evidence/validation/day6_A_to_B.csv、day6_B_to_A.csv、internal_analysis_config.json、internal_locked_A/B.json | 完整family Holm、同向、2148/2175、分母2502/2481、r |
| Results4.2；跨集两方向 | experiments/reference_scripts/outputs/result2_cross_dataset/下两个验证脚本 | evidence/validation/day6_to_day8.csv、day8_to_day6.csv及冻结记录 | 6129/6427 locked、4753/5221 evaluable、1647/3201通过、两种分母 |
| Results4.3；五个重点模块 | landscape_analysis/core.py::hierarchy；broad_screening/analysis.py::choose_core；sensitivity.py | evidence/modules/config_frozen.yaml、effect_matrix.csv.gz、co_clustering_matrix.csv.gz、module_summary.csv | 419×341矩阵、完整144个簇中选取M01–M05；重建核心21/10/28/9/4 |
| Results4.4；PHB2线索 | perturbation_scan/scan.py及jure/casefile/selected_adapter.py | evidence/discovery/day6_candidates.csv；cases/additional10/M01_03/ | 6.45%→50.84%，44.40pp；区分原始线索与候选机制 |
| Results4.4/Figure3；11反馈案例 | 历史三批协议；当前Critic代码仅作实现对应 | evidence/CASE_INDEX.md、cases/index.json、逐案request_source/executed_source/reviewed_source | 旧9+新2条链；EIF2B3只有C1修订，不计入11 |
| S2.3–S2.4；18例 | 三个批次5+10+3 | evidence/cases/*_protocol.json；18个case_id及科学角色档案 | 批次顺序与模型请求记录；不声称当前GLM执行了这些历史案例 |

## 可直接运行的核验

```bash
python scripts/verify_paper_results.py --output runs/paper_verification.json
```

命令拒绝覆盖已有报告；重新运行可不指定output或选择新文件。它完全使用副本内evidence，不访问原研究目录、不联网、不调用模型。

源文件路径/哈希→导出路径/哈希见evidence/source_manifest.json。病例阅读入口为[evidence/CASE_INDEX.md](evidence/CASE_INDEX.md)。归档包含原科学角色输出；论文图是这些记录的概括，不能把图中路径视为已验证因果链。

核验边界：验证原始P值计算仍需要原始/汇总分层计数；本脚本从保存P值复算Holm。重建稳定核心仍使用保存的共聚类矩阵，不等于重做bootstrap。11条链的机器检查确认三类记录完整，科学解释需阅读对应原文。
