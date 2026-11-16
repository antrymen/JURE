# Clue Discovery：三阶段 benchmark 与 ablation 安排

日期：2026-09-28。状态：**实验设计讨论稿，未启动新实验**。现有产物只读核查；不重跑或覆盖 Day 6，不读取 Day 8 expression，不启动 Agents。本文件不能追溯称为已有实验的事前注册。

## 1. 三个阶段各自需要证明什么

| 阶段 | 实际使用的方法 | Benchmark 的问题 | 最重要的 ablation |
|---|---|---|---|
| I Reference Discovery | 检测二值化；依赖引导 bottom-up + 固定预算随机探索 + 直接三阶 fingerprint；marginal MFI、lower-order maximum-entropy Gain、完整状态表 estimability、bootstrap、双折锁定验证与 validation-family Holm | 能否在可承受预算内找到真实高阶 reference，并控制错误发现？ | 同预算去掉直接高阶通道；相同候选/统计结果下比较 validation-family 校正规则 |
| II Condition-associated Shift Discovery | frozen signed states；condition-by-batch state counts；matched control prevalence difference；分层精确检验、effect/support gates、全预设 family 的 selected-family Holm | 扰动效应估得准吗？批次不平衡、低支持时是否误判？ | matched vs pooled control；固定/独立 reference 与复用 control 的完整流程设计比较 |
| III Broad Screening | 连续 signed-effect 矩阵；Pearson distance + average linkage；condition 辅助 cosine grouping；bootstrap co-assignment、stable core、参数匹配、signed-state ablation、co-response、样本量审计 | 是否保留真实共同响应及状态差异，并为有限 case budget 提供有用的覆盖？ | signed state vs gene-only OR；continuous vs binary；core vs whole group 在留出数据上的比较 |

Benchmark 衡量任务表现；ablation 判断具体设计的增益；参数敏感性检查结果对设定的依赖；实现单元测试检查代码正确。四类证据不互相替代。

## 2. 现有证据清点：复用已有结果

### Stage I：已有较完整的 synthetic 证据

- v04 search benchmark (historical source, not bundled: `../../outputs/clue_hunting_v04_benchmark/BENCHMARK_REPORT.md`)：候选覆盖、纯三阶恢复、不同基因规模、弱/强信号和原阴性结果。早期随机候选对照与 fingerprint 的预算不同，不能直接当成严格等预算的完整方法胜负比较。
- validation-family review (historical source, not bundled: `../../outputs/clue_hunting_v04_validation_family_v1/VALIDATION_REVIEW.md`)：232 个主实验数据集（180 null + 52 positive），另有 20 个独立补充异质阳性数据集。四种 multiplicity arms 使用相同候选及原始统计量。
- 原 180 个 null 中，raw arm 在 58 个数据集出现假 reference clue，预指定 Holm arm 为 1 个。统计单位是完整数据集上的至少一次假 gene-set 发现，不是“state-level FDR=1/180”。
- 1000-gene 阳性每强度主实验仅 6 份，medium 检出 4/6，strong 6/6；这些是有限样本结果，不能当作精确总体 power。既有 weak 失败必须保留。

优先整理这些结果；只对“直接高阶候选通道的独立价值”补充公平的等预算比较。若更改方法/参数或反复使用已看过的 seed 作开发，再准备新的独立评价 seeds。

### Stage II：已有实现与小型 fixture 检查，需要加强任务级证据

synthetic RESULTS (historical source, not bundled: `../../outputs/perturbation_scan_v01_synthetic_20260927/RESULTS.json`) 共 7 类 × 8 份 = 56 份：balanced null、batch-heterogeneous null、pairwise-only null，以及中/强 enrichment/depletion。已有精确概率、批次构成混杂、0-hit depletion、低样本和缺对照单元测试。

这些检查验证了具体实现和指定案例；没有完成全面 power/calibration 曲线，也没有覆盖真实流程中 reference selection 与复用 control 的全部影响。Stage II 是当前最应优先补强的环节。

### Stage III：已有真实数据消融，但主要是同数据描述

已完成 continuous Pearson/Spearman、state-preserving binary、signed binary、gene-only OR、core on/off、clustering cuts、模块对齐和样本量分析。见 signed-state ablation (historical source, not bundled: `../../outputs/broad_screening_v01/tables/signed_state_ablation.csv`)、core ablation (historical source, not bundled: `../../outputs/broad_screening_v01/tables/stable_core_ablation.csv`)、Results (historical source, not bundled: `../../outputs/broad_screening_v01/RESULTS_DRAFT.md`)。

共同可评估 binary pair domain 有 24,753 对；state-preserving 与 gene-only OR 的相关性重建 MAE 分别约 0.229/0.303。现有结果说明特定表示折叠丢失信息，不证明所有指标、所有数据集都更好。

用 Pearson 聚类后再报告同数据内 Pearson coherence，或用 bootstrap 选 core 后再报告同一批 bootstrap 的 core stability，会受到选择影响。因此现有值保留为描述；方法有效性需已知真值或独立留出评价。

## 3. 优先执行的最小实验包

### P1：Stage II matched-control shift benchmark

**目的**：支撑“我们把扰动可靠地纳入线索发现”这一核心主张。

**主对照**：完整 Stage II vs 不作 batch matching 的 pooled-control baseline。两者使用相同的 reference states、condition universe、effect/support thresholds、multiplicity family 和双侧检验约定；批次信息的处理是预定差异。分别导出实际效应 estimand，不将 pooled effect 标成 matched effect。

**数据情景**：

1. 真正无 shift、batch 均衡。
2. batch 内无 shift，但 control/perturbation 的 batch 比例不同；应区分构成差异与 batch 内效应。
3. 已知正/负 shift，覆盖接近预定 effect gate 的效应及更强效应。
4. 低样本、稀有状态、部分 batch 缺对照；不可评估须单列。
5. 批次间效应方向/大小异质，明确当前加权总体效应可能抵消；不把异质性自动解释成无生物作用。

**指标**：Δ bias/MAE、方向错误率、满足既定支持条件的 power、全流程 recall、无真实 shift 时出现任何误报的概率、混合真/假关联中的经验 FDP/FWER、不可评估率。分别给数据集/条件级分母及独立重复置信区间。

真值来自生成的 joint-state distribution；同一 gene set 的所有 state probabilities 必须和为 1，重叠 gene sets 也应来自一致的 cell-level distribution。不能独立给各 state 随意加 shift 后当作合法细胞数据。

**额外的重要区分**：Stage II 的 null 是 state prevalence 不变。单基因 marginal 改变也可引起联合状态频率改变；此类 Δ 不应被当成 Stage II 假阳性，只能说尚未证明新增高阶 interaction rewiring。

**图**：左为只有 batch imbalance 的例子；中为 true Δ vs estimated Δ；右为 effect × sample size 下的 power/误报表现。所有 effect gate 固定，不为画更好看的曲线逐格调阈值。

### P2：Stage I 搜索通道的等预算比较

**目的**：支撑“加入直接高阶通道可弥补只依赖低阶关系的搜索遗漏”。

主 arms：完整 v04；去掉 fingerprint、按预先规则把释放预算分配回原 dependency/exploration；依赖引导 baseline；随机候选 baseline。候选总预算和下游 expensive evaluation/calibration/bootstrap 上限统一。实际未用满的名额如实记录，不因是否找到真值而追加。另报实际 runtime/RSS，避免把预算上限相同当作成本完全相同。

场景涵盖：pure-three-way、pairwise-supported higher-order、heterogeneous marginals、稀疏/弱信号、independent/pairwise-only 阴性。100-gene 做完整主体，1000-gene 做规模与覆盖补充；具体组合和独立数据 seeds 在新实验前冻结，避免全因子穷举浪费预算。

指标分开：proposal recall、estimability/锁定率、end-to-end reference recall、额外假 gene sets、runtime/RSS。搜索没提到的真值仍在 end-to-end 分母中；只比较被提出候选会高估成功率。

校正 raw/BH/Holm 的作用优先引用已有 paired validation-family 实验，不必再把每种校正与每个搜索 arm 做大规模全交叉。MFI 与 Gain 不是独立证据，不能预设“多一个 gate 必然提高所有指标”。若专门主张 Gain 增量，再做固定候选、固定 family 下的明确 gate ablation，并承认其与 MFI 的数学关联。

**图**：proposal → locked → validated 的恢复分解，加上相同预算下的成本/恢复率。

### P3：Stage III 状态表示与 core 的独立评价

**目的**：支撑“保留 signed state 和稳定结构有助于组织线索”，而不是证明一个聚类算法重新发现自己优化的指标。

使用两类输入：

- 已知 latent response groups 的 synthetic；包含同 genes 不同 signed states、disjoint genes 的同步响应、不同噪声/支持量和弱/无结构对照。若只直接模拟 effect matrix，明确它是矩阵组织层 benchmark，不能替代 cell-level end-to-end 验证。
- 已冻结 Day 6 effect matrix 的预先固定 train/held-out perturbation splits。仅在训练条件上重新计算 grouping 和 core，之后在未参与分组的条件上计算 within/between response agreement；不把全数据既有 groups 称为这些划分的 out-of-sample groups。由于真实数据已看过，这属于内部泛化评估，仍不是新数据集盲测。

优先比较三对：

1. state-preserving binary vs gene-only OR：专门隔离 state collapse；同时保留 continuous 与 signed-binary arms 说明连续效应/方向的作用。
2. continuous signed Δ vs candidate-only/binary：检验只保留显著性标签丢失多少响应信息。
3. training-derived stable core vs whole group：在留出条件或独立生成数据中评价；加入同规模随机子集参照，并报告丢弃的状态/候选覆盖，避免仅靠少留成员取得高一致性。

指标：有真值时 group recovery（ARI 或 pairwise grouping precision/recall）、common-domain correlation reconstruction error、held-out within/between coherence、state-contrast 保持率、disjoint co-response 恢复与误连、core 留出稳定性及覆盖率。ARI 不用单独奖赏“全部 singleton”，须与覆盖/precision/recall 一起解释。

bootstrap condition rows 衡量对 condition 集合的敏感性，不自动反映 state prevalence 的采样不确定性或独立生物重复。后续若研究这些误差，应采用独立生成 cell counts、within-batch cell resampling 或真实独立对照/replicates；当前共享 control 引起的相关误差也不能由行重采样自动去除。

**图**：两组有科学含义的例子 + 表示消融/留出表现。原三张热力图保留为真实数据发现图，不作为单独的准确性证明。

### P4：小而完整的 end-to-end benchmark

现有 synthetic_full/negative 集成测试已验证接口走通；进一步验证全链效果时，从 cell-level 数据生成已知 reference states、正/负 condition shifts 和共同 response groups，完整执行 I → II → III。

专门区分两种 reference/control 设计：

- **Independent/locked-reference benchmark**：reference 来自独立 discovery/control 数据或事先固定真值目录，用于隔离 Stage II 性能。oracle reference 只作组件上限，不冒充完整方法。
- **Current reused-control workflow**：按当前实际设计重新发现 references，并复用相应 control 做 shift，完整重复 selection 和 testing；在无条件差异的数据上审计选择造成的误报风险。

比较 independent 与 reused 设计时预定总 control-cell budget，并说明分割造成的 power 代价；不能给独立方案额外数据后把改善全归因于 selection independence。独立配置与当前配置的结果分开，不把前者的 calibration 保证移给后者。

指标是真实 `condition × exact state × direction` clue 的 end-to-end recall/precision、错误 clue、正确/错误 group relations、失败阶段归因和资源。不能把相关的多个 state 或 pair 当作独立数据集来缩窄置信区间。

## 4. Stator / mTRIM 外部比较怎样放

- **Stator 可作 Stage I 的可选外部 frontend baseline**：在同一基因空间、相同 reference cells 上运行已锁定版本，使用其完整 signed d-tuples 而非直接把 OR 聚合的 Stator cell states 当作同一单位；随后接相同的 Stage II/III。报告这是“不同 reference frontend + common downstream”，不是 Stator 原生 perturbation scanner。限三阶等配置变更需明确，原生配置与任务适配配置分开。
- **mTRIM 不宜直接作为整个 Perturb-seq pipeline 的主 baseline**：它需要 TF binding/target module 输入，输出 TF 协作规则。可以将其启发的 bottom-up/search constraint 做组件对照，但必须标为 mTRIM-inspired variant；没有运行原方法就不能把结果栏命名为 mTRIM。
- **单基因 DE/检测率变化可作为附加表示 baseline**，但要预先定义如何映射到同一个 state/clue 任务，并保留其原有输出目标。仅凭“我们找到了 DE 没排名靠前的基因”不能证明有增量高阶信息；尤其 state prevalence shift 可能由 marginal effects 解释。

Stator 已有 state enrichment/projection，mTRIM 使用过 perturbation-related 验证；比较的核心是推断对象、扰动角色与同一任务表现，不是把原方法描述成从不考虑条件或扰动。论文身份和原方法功能见 [方法定位](JURE_Clue_Discovery_Positioning.md)。

## 5. 实施顺序与论文篇幅

| 顺序 | 工作 | 优先理由 | 主文/补充 |
|---|---|---|---|
| 0 | 汇总现有 Stage I 252 份主/补充 synthetic、Stage II 56 份 fixture、Stage III 消融；标记版本与评价单位 | 已有合格证据直接复用，避免重复运行 | 汇总表与方法验证图 |
| 1 | P1 Stage II matched-control effect benchmark | 直接支撑加入 perturbation 的核心任务 | 主文 |
| 2 | P2 等预算搜索消融；P3 signed-state/common-domain/held-out core 评价 | 分别支撑搜索覆盖和 Broad 组织两项设计 | 主文关键 arms，其他补充 |
| 3 | P4 小型完整 cell-level end-to-end，与 reused-control 风险审计 | 连接三个阶段，暴露单独组件测试看不到的问题 | 主文摘要 + 补充细节 |
| 4 | 有独立实验设计后，再做 Day 8/external replication 或任务适配的外部 baseline | 增加真实外部证据 | 独立 validation 章节 |

不为每一行工程实现设置一个 ablation，也不需要对每种 representation、cut、bootstrap 次数和 search arm 做全交叉。围绕论文要主张的增益安排最小有解释力的对照。

独立 seed 数按所需置信区间精度和预算预定；不要把“做了几个 seed”当作统计功效充分。少量小样本用于 pilot/runtime 估计，开发和最终评价 seeds 分开；不得看到失败后重抽、追加到成功或只报最好的一组。

## 6. 统计表述与验收边界

- Holm 与 BH 对应的错误率目标不同；Holm 面向 family-wise error，BH 面向 FDR，均需要相应有效 p-values 等条件。不能把配置写了 Holm 等同于整个有选择性的流程已受控。参考 [R p.adjust 官方文档](https://stat.ethz.ch/R-manual/R-devel/library/stats/html/p.adjust.html)。
- 分层精确检验的双侧定义必须冻结。本项目使用各 batch 超几何分布卷积后的 doubled-smaller-tail；不能无说明地换成另一种 Fisher two-sided definition 再称数值回归。不同双侧定义见 [SciPy Fisher exact 文档](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.fisher_exact.html)。
- Stage I 统计单位主要是 gene set 的高阶资格；Stage II 是 condition × signed state prevalence association；Stage III 是描述性 grouping/context。不要用同一个“accuracy”混合三个单位。
- Stage III 不改变 Stage II 的 candidate identity、p-value 或 evidence level。消融写到新版本输出，既有 Day 6 结果保持冻结。
- 当前 Stage II 仍属探索性；外部验证和机制质量分别评价，热图、内部稳定或 selected-case 调查都不能自动升级全部候选。
