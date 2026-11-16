# Replogle K562 Day 6：冻结应用实例

本文只引用已验收结果，不是本轮重新分析。通用方法见 [三阶段定义](JURE_Clue_Discovery_Method.md)。

既有 Stage II 得到 6,129 条探索性关联，涉及 419 个有候选 targets 和 341 个 reference states。完整 scan universe 为 2,034 个 targets；419 不是全部受检 targets。enrichment/depletion 分别为 4,202 / 1,927。

Stage III 的主要发现是共享响应结构与 signed-state 差异共存。前四个 pattern groups 覆盖约 61.5% 候选，PCA 前三轴解释约 67.4% 连续效应方差，但覆盖 70% 候选仍涉及 66 个 states；不能概括为“四个生物程序”。

`PCK2+ PHGDH+ TRIB3+` 与 `CEBPB+ DDIT4+ SESN2+` 的基因集合不重叠，跨 targets 的连续效应 Pearson r≈0.950，共享 49 个候选 targets。这是 co-response，不是相同通路或机制证据。同 gene set 的不同 signed states 可呈反向响应，因而 gene-only 表示会丢失状态差异。

当前共有 144 个统计 groups、55 个非空 stable cores；核心稳定与跨 cut 鲁棒性是两项检查。candidate burden 与主 cohort cell count 的 Spearman ρ≈0.333，不能把候选数量直接解释为生物影响广度。

完整统计、代表 states、core/boundary、消融和证据限制以原 Broad report (historical source, not bundled: `../../outputs/broad_screening_v01/LANDSCAPE_REPORT.md`)、Results draft (historical source, not bundled: `../../outputs/broad_screening_v01/RESULTS_DRAFT.md`) 和 run manifest (historical source, not bundled: `../../outputs/broad_screening_v01/audit/run_manifest.json`) 为准。原统计结果、聚类和冻结文件在本轮均保持不变。局部 M01 等编号不能用于未经 alignment 的跨数据集比较。

只读统一格式输出在 `outputs/integration_tests/adapter_smoke/replogle_frozen/`；该目录只是 schema 转换，不是 Day 6 reproduction run。
