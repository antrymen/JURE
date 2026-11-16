# NT Higher-Order Reference Experiment：two-fold 固定方案

本文件在本轮真实 NT 结果产生前固定。完成本地验收后，用户授权在 2 GB 无卡实例试跑；仅调整数据读取和内存管理，科学参数保持不变。v0.1、v0.2 的代码和结果保持原样。

## 问题和范围

仅研究 Replogle K562 Essential day 6 的 10,691 个 NT cells：Q1 三阶 MFI 能否跨约 5,300/5,300 cells 复现；Q2 四阶是否存在可估计且可复现的候选；Q3 完整状态表的稀有格支持数与 MFI 稳定性有何关系。二阶作为参照。无 perturbation testing、CPA、机制解释、TN 或 Agent 推理。

输入仍是已验证的 `ReplogleWeissman2022_K562_essential.h5ad`，MD5 `d8cba17576d1a8afc0f7d71b79cad0f7`，形状 310,385 × 8,563。只将精确 `gene=non-targeting` 且 `nperts=0` 的 NT 行纳入表达分析。原数据和旧输出不覆盖。

## 预先固定的拆分与参数

- 根随机种子 `20260927`。仅用 cell IDs 与 GEM batch 分层拆分，表达值不参与。奇数 batch 的额外细胞在两份间预定随机分配，使全局 A=5,345、B=5,346；并集必须是全部 NT，交集必须为空。
- 两方向均预定运行：A discovery → B locked validation；B discovery → A locked validation。各自只在 discovery fold 内进行基因过滤和选择。
- 基因选择沿用 raw-count Fano（样本方差/均值）top12，检测率范围 `[0.01,0.99]`，并列按基因名。A/B 可以得到不同模块；完整特征表和模块交集都报告。不根据 validation 替换模块。
- 正式 bootstrap=1,000，搜索 max_order=4，保持既有 bottom-up compatible merges、support-only expansion 和 max_candidates=100,000。
- 保持 marginal MFI、表达二值化阈值 0、smoothing_alpha=0.5、enrichment epsilon=0.5。
- 保持现有 MFI `abs>=0.5`、95% bootstrap CI 不包含零、符号一致率 `>=0.95`；保持表质量 `occupancy>=0.9`、最小非零状态数 `>=3`，以及状态 support、enrichment bootstrap 和 enrichment q 的原门槛。
- 单列 `mfi_lambda = mean(sign(bootstrap) != sign(point))` 与 `mfi_lambda_below_005`，作为附加诊断，不替换原门槛。point MFI=0 不称稳定。`>=0.95` 与 `lambda<0.05` 边界不同。
- 不新增 `min_state_count>=20` 门槛。记录所有低计数指标供描述性审计。预算不足时显式失败，不截取候选、放宽阈值或看结果后更换模块。

`ReferenceConfig` 仅复用原统计实现；其中旧三分比例和 perturbation testing 设置不用于新实验。新 manifest 明确记录 two-fold 设计及实际 IDs，不将遗留配置当成有效拆分。

2 GB 运行使用两遍流式读取：第一遍按 NT 行和已冻结 fold 标签累积原始计数的和、平方和、检测数，分别计算同一 Fano 公式；第二遍仅保留两个模块的并集。浮点累加顺序与整矩阵实现可能有舍入差异，模块与数值等价性以测试记录为准。块大小为 128 行、HDF5 cache 为 64 MiB。仅载入 obs 和 gene index，不载入无关表达层或嵌入；不减少细胞、不减少 bootstrap、不新增阈值。

## 执行顺序与证据冻结

1. 在读取表达前冻结 A/B IDs、batch、根 seed、代码/协议 hash 和软件版本。
2. 各 fold 只用自身表达选择模块；保存各自完整 Fano 表，并冻结两个模块。
3. 完成两个独立 discovery。任何 validation 开始前，将两个 discovery 表、搜索日志、锁定 genes+states+order 及其 hash 保存为 checkpoint。
4. A→B 只对 A 已锁定的状态原样验证；B→A 同理。验证只计算对应模块的既定基因组合和状态，不重新搜索、不换状态、不反过来更改 discovery。
5. 保存每个阶段完整状态表、MFI bootstrap 原始分布及 seed/namespace。不同 evaluation role 明确标记；验证失败仍保留。
6. 在结果全部产生后生成描述性报告，代码和协议 hash 必须与运行前一致。

## 三层标签和统计家庭

`mfi_only_stable` 单独表示基因组合的 MFI 估计通过既定质量、幅度和 bootstrap 门槛；`within_fold_stable` 表示某个具体状态还通过原有 support/enrichment 门槛。Discovery 中据此锁定候选，validation 中还需与对侧 discovery 的 MFI 同号才算跨 fold 通过。

`cross_fold_replicated` 表示至少一个预定方向中，锁定的同一状态在另一 fold 通过全部验证且 MFI 同向。`bidirectionally_rediscovered` 要求完全相同的 canonical genes、states、order 在 A/B 各自独立 discovery 中出现，并且 A→B、B→A 均通过。只有 gene set 相同而 states 不同不能算双向重发现；不要求全部参考候选都达到第三层。

每方向 discovery BH 覆盖其全部实际评估状态；validation BH 覆盖该方向全部锁定状态，包含验证失败者。四个 family 分别记录成员数和 hash。它们校正的是 plug-in independence 状态富集，**不是 MFI 搜索层面的 FDR**。合并或交集两方向结果，不自动获得新的全局 FDR 保证。结果仍是探索性的内部复现候选。

## 输出

用户要求的主文件：`nt_fold_manifest.json`、`fold_A_discovery.csv`、`fold_B_validation.csv`、`fold_B_discovery.csv`、`fold_A_validation.csv`、`cross_fold_summary.csv`、`state_table_estimability.csv`、`order_reproducibility_summary.csv`。

额外保存冻结 checkpoint、两方向 search logs、Fano/QC 表、逐细胞 NT metadata、bootstrap NPZ（每行引用具体 key）、统计 metadata、环境和代码 hash、退出状态、报告和图。

完整表指标含 total_cells、全部 `2^k` counts、min/max count、zero count/fraction、below5/10/20 count/fraction（包括零格）、occupancy、MFI、bootstrap CI/符号稳定性/λ、完整 bootstrap 数组索引。无合格 bootstrap 时记缺失及原因，不伪造零分布。

## 解释边界

这些 NT 已在 v0.2 和审计中使用。本轮是预先规定流程内的互斥细胞验证，但研究整体仍为开发阶段，不称 untouched benchmark、独立实验重复或外部验证。两个方向共享同一 A/B 数据，不是两项独立实验。

相较旧版，同时改变了 validation 容量、bootstrap 200→1000、最高阶数7→4及其 BH family、重新划分的细胞和各方向实际模块。即使结果改善，也不能单独归因于样本数。bootstrap 不能产生新细胞或补齐真实零格；support—stability 关系带有搜索与筛选偏差，不是因果关系或已校准的 power 曲线。

没有通过的候选就报告零，不启动自动补救实验。看过 A/B 结果后若再修改设计，仍应明确视作新的开发实验。

## 本地验收

验证 cell IDs 的互斥、全集覆盖、确定性和 batch 平衡；双向表达扰动不影响另一方 discovery；锁定验证不生成新候选；完整表求和与稀疏指标正确；bootstrap 原始分布与摘要一致；四个统计 family 无遗漏；双向重发现要求状态精确匹配；空候选和无可估计状态也能输出完整报告。合成数据验证显著标记为 synthetic，不能当成真实 NT 成功结果。
