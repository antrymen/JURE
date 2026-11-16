# Clue Hunting v0.3：Scalable Incremental Higher-Order Discovery

本设计依据本轮三份用户规格，范围为 NT-only reference discovery。实现、测试、资源使用和 benchmark 的事实以对应输出目录中的冻结配置、运行 manifest 和报告为准；本设计不是已经完成真实千基因实验的证明。旧 `clue_discovery/v02` 与 Top12 two-fold 实验保留为基线。

## 1. 问题与方法边界

Top12 适合调试完整统计链，不能代表大基因空间的搜索覆盖率。12 基因只有 220 个三阶、495 个四阶组合；1,000 基因对应 166,167,000 个三阶、41,417,124,750 个四阶组合，每组另有 `2^k` 个状态。增加进程数不能消除组合增长。v0.3 扩大候选基因池，限制昂贵计算的候选数量，分别审计搜索覆盖、统计功效和资源成本。

方法来源必须准确区分：

| 来源 | 本实现采用的思想 | 没有据此宣称的内容 |
|---|---|---|
| Stator-inspired | 检测/未检测二值表示、marginal MFI、具体 d-tuple、bootstrap 稳定性 | 不复制其完整 Markov Blanket / PC / MCMC 搜索，不称完整复现 Stator |
| mTRIM-inspired | 从低阶组合逐步扩展的 bottom-up combinatorial search | 不复现 TF–target inference，不采用“低阶显著即停止更高阶”的原剪枝语义 |
| JURE-specific organization | dependency + bounded exploration 提案、增量低阶解释检验、完整状态表可估计性、候选冻结与交叉验证、面向后续 perturbation 的只读目录 | 不把已有统计量改名当新算法，也不把组合重组直接当作已经验证的创新 |

论文身份、原数据和代码差异见已经核对的原方法笔记 (historical source, not bundled: `../../dataset_audit/methods/Stator_mTRIM_Methods_and_Datasets.md`)。本轮没有重写原方法的历史或把 NT 状态解释成因果调控。

## 2. 三层对象与三个统计问题

| 层次 | 对象 | 合法含义 |
|---|---|---|
| Level 1 | `Candidate Gene Set`，如 `(A,B,C)` | 一条合法提案，值得评价；不是 interaction 结论 |
| Level 2 | `Reference Higher-order Pattern`，如 `A+ B- C+` | 经完整状态表、MFI、Gain、support 和 bootstrap 筛选的参考状态；通过锁定验证后才称 `Cross-fold Reproducible Higher-order Reference Pattern` |
| Level 3 | `Perturbation-associated Clue` | 未来参考状态加上扰动频率变化、扰动侧支持和复现证据；本轮不生成 |

`+` 只表示 raw count > 0，`-` 表示 raw count = 0，不是上调/下调。NT/control 细胞不能被描述成绝对没有实验处理的天然细胞。

三个统计问题分别保存：

- **MFI**：完整二元联合分布中的最高阶 log contrast 有多大、方向是否稳定？
- **Set-level Gain**：相对于保留所有较低阶边缘分布的模型，整体分布还剩多少差异？
- **Pattern-level Gain / d-tuple**：这些差异落在哪一个具体状态，频率和效应有多大？

它们的语义不同，但并非独立统计证据。在严格正概率的完整 binary `k`-way table 中，去掉唯一最高阶 log-linear 项、保留所有 `<k` 阶项时，`MFI=0` 与对应最大熵投影 `KL=0` 描述同一个最高阶项缺失。一般不能把 MFI 和 Gain 当作两次相互独立的发现来累加置信度；多个 d-tuples 也共享一个 gene-set-level interaction。Gain 补充的是分布加权效应量、具体状态差值及 null calibration，不保证新增一条独立的科学证据。

## 3. 数据隔离与基因选择

沿用互斥 two-fold NT 设计。GEM batch 用作分层键，cell IDs 冻结后才读表达。每个细胞只属于一个 fold；重复 barcode、重叠 IDs、缺失的基因或非法 counts 显式报错。GEM batch 不是 biological replicate。

两个方向预先规定：`A discovery → B locked validation`，以及 `B discovery → A locked validation`。A/B 各自独立选择 HVG、图和候选；两个 discovery 的结果均写盘并冻结后才开始任何 validation。另一方向也做 discovery，不授权它修改本方向已冻结的候选。

HVG pool 支持 50/100/250/500/1000。第一版延续 discovery 内的 raw-count Fano 排序，记录检测率过滤、方差约定、并列处理及选择参数，不把名称 HVG 暗示成另一种 Scanpy 归一化流程。按块累积和、平方和与检测数，避免为基因筛选载入整个表达矩阵。随后只保留分析所需的基因池/模块。

每方向输出完整 HVG 选择表，至少包含 `gene, rank, selection_metric, fold, selection_parameters`。组合审计另记录每个基因是否在本方向和对侧基因池，以及该组合实际上有没有进入对侧候选列表。基因都在池内不等于组合被搜索。

## 4. Candidate Proposal：效率与覆盖分开

`DependencyGraphBuilder` 只在 discovery 内计算可配置的轻量二元依赖统计，生成节点、候选边、统计值和选择原因。它不判定 higher-order interaction，不是 Stator 的 Markov Blanket 实现。图审计包括边数、密度、度分布、连通分量和重叠 neighborhood 大小。

`CandidateProposalEngine` 使用两条预定路径：

1. **Dependency-guided**：在重叠的局部 neighborhoods 中生成二阶候选，再通过实际父组合和局部邻居扩展。禁止将 1,000 基因切成不重叠固定块，也不做全局三/四阶枚举。
2. **Exploration**：按冻结 seed、抽样规则、每阶预算和 exploration fraction 提案。允许三阶候选直接进入评价，从而不会因没有显著 pairwise edge 而在规则上必然遗漏 pure three-way signal。

纯三阶 parity 分布可以满足 `P(A,B)=P(A)P(B)` 等全部二阶独立，同时具有非零最高阶项。有限 exploration 只提供非零被抽到的机会，不保证恢复任意 planted tuple。随机预算很小时，多次完全未命中是真实的 search failure。禁止直到出现阳性才加抽候选。

候选 identity 使用 canonical gene tuple，全局去重；合并所有 `proposal_sources`、实际 `generation_parent_ids`、抽样 seed、proposal round、sampling probability 和 fold。相同 tuple 来自多个 neighborhoods 只计算一次。抽样概率必须说明是单次抽样概率、固定预算下的纳入概率，还是条件抽样概率；不能把它用作未经推导的统计权重。

## 5. Bottom-up 与生命周期

主链为 `L2 → L3 → L4`。L3 的合法来源可为 graph neighborhood、实际二阶父组合、exploration；不要求所有 pair parents 显著。L4 的依赖扩展由已获得资格且允许扩展的三阶父组合产生，另允许预先分配的四阶 exploration。记录哪些路径实际生成了 child，而不是事后把所有子集都伪装成生成父组合。

每个候选独立记录 `keep`、`expand` 和 `prune_reason`，不得用一个标签隐去生命周期。

- `KEEP=True, EXPAND=True`：当前结构满足预定支持/增量/稳定规则，并且仍可合理尝试加一个基因。
- `KEEP=True, EXPAND=False`：当前参考模式有价值，但达到最高阶、预算边界或后续状态表可估计性边界。
- `KEEP=False, EXPAND=False`：没有资格成为 reference，也不沿该统计路径扩展；其他预先允许的 exploration 路径仍可产生更高阶组合。

是否扩展采用可审查规则，综合 estimability、gain qualification、bootstrap、proposal support；不建立 `MFI + Gain + Support` 加权总分。二阶到三阶的提案资格和三阶到四阶的正式扩展资格可以不同，必须在日志中明确，避免用二阶显著性过滤掉纯三阶信号。

## 6. 完整状态表与 Estimability

在昂贵 calibration/bootstrap 前计算每个 gene set 的完整 `2^k` counts，包括零格。共享 state table、MFI、低阶拟合及 bootstrap，不按每个 concrete state 重复估计。

必存诊断：`total_cells, state_counts, min_state_count, max_state_count, zero_state_count, zero_state_fraction, states_below_5/10/20, state_table_occupancy`，以及各 pattern support。低于 5/10/20 的格数包括零格；最小非零格与含零的最小格分别记录。

`EstimabilityAssessment` 返回 `good / borderline / poor` 和具体原因。阈值是可配置的开发设置，不是普适可靠性定理。明显 poor 的状态表可在 bootstrap 前剪枝；borderline 候选保留质量标记，在 primary/exploratory 目录中明确区分。不能因为目标 d-tuple 有大量细胞就忽略其他格的零计数。

关闭 estimability filter 是 ablation 开关，不能把平滑后有限的数值当作数据已支持所有状态。Bootstrap 不产生新的实验信息，也不会使原本稀疏的真实状态变得可估计。

## 7. Marginal MFI 与最大熵 Lower-order Null

继续采用 detected/undetected 二值矩阵，`smoothing_alpha=0.5`。对原始 counts `n_s`：

\[
\widetilde p_s=(n_s+\alpha)/(N+2^k\alpha),\quad
I_k=\sum_{s\in\{0,1\}^k}(-1)^{k-|s|}\log\widetilde p_s.
\]

这是 marginal MFI；没有 Markov Blanket conditioning、因果识别或 TN。状态位序与 MFI 符号约定必须固定。

对三阶，`LowerOrderNullModel` 拟合保留全部一阶、二阶 marginals 的最大熵分布；四阶对应保留至三阶 marginals。完整二元表只剩一维自由度：令 `v_s=(-1)^(k-|s|)`，所有保持这些低阶 marginals 的分布都可写成 `q_s=p_s+t v_s`。在所有 `q_s>0` 的可行区间求根 `sum(v_s log q_s)=0`，得到没有最高阶 log-linear 项的最大熵分布。拟合必须检查非负、归一化、边缘匹配和求根精度，不能把独立模型冒充 pairwise-only null。

三阶是主要验证目标。默认 `quad_gain_enabled=False`；即使数值接口已支持四阶，四阶仍需独立 synthetic/资源/真实 NT 验证，结果保持 exploratory；实现四阶公式不等于证明真实四阶估计可靠。若某次 run 没有计算四阶 Gain，明确 `higher_order_gain_status=not_evaluated`，不能填 0。

## 8. Gain、校准与 bootstrap

同一张平滑后的经验表和低阶拟合给出：

\[
G_{set}=D_{KL}(\widetilde p\|q),\quad
G_{abs}(s)=\widetilde p_s-q_s,\quad
G_{ratio}(s)=(\widetilde p_s+\epsilon)/(q_s+\epsilon),\quad
G_{log}(s)=\log G_{ratio}(s).
\]

同时输出 raw observed frequency `n_s/N`，不要将其与平滑概率混淆。若实现中的 pattern gain 使用 raw probability，schema 必须明确这一选择，不能把两种定义混在一列。Deviance 是否采用 raw likelihood 或平滑近似也应明确；不自动将 `2N·KL` 当成严格的 raw-data likelihood-ratio test。

`GainNullCalibration` 从 discovery 拟合的 lower-order model 按原样本量模拟 multinomial state tables，并对每张模拟表重新拟合 lower-order model，再运行相同的 MFI/Gain 统计。重拟合很关键；与固定原始 null 的 KL 不是相同统计量。Monte Carlo `p_gain=(1+#null≥observed)/(B_null+1)`、模拟数、seed、null parameters 和原始模拟分布必须可审计。`B_null` 限制 p 值分辨率；小次数校准下 BH 无阳性不授权自动扩大模拟数。

资格规则分别包含合法提案、非 poor 的完整表、预定 MFI 预筛、set-level gain 校准、至少一个有支持且方向可解释的具体状态，再对 unique gene sets 进入 bootstrap shortlist。当前 `gain_qualification=p_gain_exploratory` 使用 candidate-level 校准 p 的开发门槛，q 另作完整家庭审计；这不是经 BH 控制的全局发现规则。预筛阈值不叫已校准科学真值。

当前 concrete-state 资格要求足够 support 且 `pattern_absolute_gain>0`；Gain 关闭时使用相对独立性期望的正富集。即目录聚焦状态的额外出现，不完整覆盖相对低阶预期减少的 deficit states。完整表仍保存所有状态的 signed Gain，可用于后续预先定义的拓展，不能运行后挑负向状态补阳性。

Bootstrap 只对 shortlist 运行，正式计数可配置为 1,000；输出 MFI 原始分布/CI/符号稳定率、set-level Gain 分布及状态 Gain CI/方向稳定率。KL 非负，因此 `mean(KL>0)` 不能当作有意义的 Gain 方向稳定性或显著性；方向只对 signed pattern gain 有意义。多个状态引用同一 gene-set-level bootstrap 文件，逐块保存后释放数组。

`gain_mode=off` 或默认未开启四阶 Gain 的路径，只保留 MFI bootstrap 与具体状态的 support / independence enrichment 点估计；该路径没有独立的 d-tuple enrichment bootstrap CI，也没有用状态 q 作为目录资格门槛。因此不能称其复现了 v0.2 的完整 d-tuple enrichment 稳定性筛选。此类结果留在 exploratory，不能进入 primary。

## 9. Locked Validation 与三个复现标签

两个 discovery 的 genes、concrete states、bit order、参考概率、低阶 null 参数、各阈值、seed 及选用统计量全部冻结。对侧不得重新选 HVG、图、候选、pattern 或调整 threshold；对侧自身另一个 discovery 的结果不影响这一锁定检验。

验证重新计算锁定 gene sets 的完整表、MFI、bootstrap、support、estimability 和自身的 beyond-lower-order Gain `KL(p_V || q_V)`。`q_V` 是在冻结组合内估计效应量所需的低阶投影，不参与选择基因、状态、阈值或拟合校准分布。若使用固定 discovery 的 `q_D` 计算 `KL(p_V || q_D)`，结果还会混入 validation 的低阶 marginals 漂移，因此主验证不采用该差异来代表纯最高阶 Gain。

**Discovery 与 validation 的 Gain 显著性程序预先分开**：discovery 使用上一节的参数 bootstrap；validation 使用不需要拟合 nuisance 参数的 exact conditional test。设 validation 的原始表为整数向量 `n`，`v_s=(-1)^(k-|s|)`。固定所有 `(k−1)` 阶 marginals 后，全部可行表构成一维整数 fiber：

\[
\mathcal F(n)=\{n+t v:t\in\mathbb Z,\ n_s+t v_s\ge 0\ \forall s\}.
\]

在没有最高阶项的 hierarchical log-linear null 下，全部低阶充分统计被条件化；其未知参数在条件 likelihood 中消去。每张 fiber 表的权重为：

\[
P(n'\mid\text{lower-order margins},H_0)
\propto\prod_s\frac{1}{n'_s!}.
\]

用冻结的 Gain 定义计算整条 fiber 的 statistic，并对 `T(n')≥T(n)`（包含 ties）求条件右尾概率。以 `log-gamma` 和 `log-sum-exp` 计算权重，避免阶乘溢出。固定 raw lower margins 的同时，各格加相同 alpha 后的 smoothed lower margins 也固定；因此这一统计量的低阶投影可以复用，且应有数值测试核对。

该验证使用 V 的 lower-order sufficient statistics 来定义条件样本空间，不从 V 拟合 null calibration 参数，不进行图/候选搜索，也不修改阈值。它是预先规定的锁定组合检验，满足“真实数据参数校准只能来自 discovery”的约束；不能把 D 的 Monte Carlo p 与 V 的 exact conditional p 写成完全相同的计算过程。输出须明确 `calibration_method`、fiber 大小、可行整数区间、tail 定义及统计量。若 fiber 很短或退化，报告离散性和低 power，不把平滑数值稳定误当作验证信息充分。

两个阶段均是最高阶项缺失的 null；显著性与 signed pattern gain 方向、MFI 方向、support/estimability/bootstrap 门槛分别报告。完整验证结果保留失败项。

三个结果字段不能相互替代：

| 字段 | 定义 |
|---|---|
| `within_discovery_stable` | 本方向发现和 bootstrap 通过预先定义的全部条件 |
| `cross_fold_replicated` | 同一 canonical genes + states + order 至少一个预定方向的锁定验证通过 |
| `bidirectionally_rediscovered` | 同一具体状态在 A/B 的独立 discovery 都出现，且两个锁定方向均通过 |

双向 discovery 不是两个独立实验。NT 曾用于 v0.2 与审计，整体研究属于开发阶段；互斥细胞验证不应称 untouched、独立 biological replicate 或 external validation。

## 10. Multiple Testing 与 ablation

保存候选生成 universe、去重后 tested gene sets、tested concrete patterns、未评价/剪枝成员及原因。family 至少区分 MFI、Gain 和 d-tuple，并明确 fold、direction、order、stage、metric、成员 IDs、检验数与 hash。没有 MFI p 值时将该 family 标成 descriptive/unadjusted，不能把符号稳定率伪装成 p 值。

禁止每个 neighborhood 各自 BH 后合并声称 global FDR。即便对一方向的全部已评价候选做 BH，数据驱动 HVG/图/shortlist、相关检验和 adaptive expansion 仍可能影响有效性。因此默认结果标为 exploratory，报告 `q_gain` 的具体检验家庭，不宣称 transcriptome-wide FDR。两方向并集、交集或 catalogue 再筛选也不自动继承严格全局 FDR。

不采用未校准的固定 `KL>0.1` 或 `G_abs>0.05` 作为“高阶成立”标准；若使用最小效应量预筛，必须与 null p 值及 multiple-testing 资格分开标注。

Ablation hooks：`candidate_mode=dependency_only/exploration_only/hybrid`；`gain_mode=off/on`；`estimability_filter=off/on`；`bootstrap=off/on`；`cross_fold_validation=off/on`。关闭必要证据的 ablation 不获得与完整 primary catalogue 相同的科学标签。本轮不自动运行所有组合。

## 11. 预算、流式输出与审计

分别限制 pairs、triplets、quads、exploration 和 bootstrap gene sets。达到限制时显式 `status=budget_exhausted`，保存 generated/evaluated/pruned/remaining；未知剩余组合数不能伪造成 0，也不能暗示已枚举完整 universe。区分“图/抽样规则限定的覆盖范围”与“已合法提出、但因预算未评价的候选”。

候选和 bootstrap 上限按 **每个 discovery fold** 计。默认 `max_bootstrap_gene_sets=128, max_order=4` 时，固定每阶 quota 为 25 pairs、76 triplets、27 quads；未用完的份额不看结果后重分配。两方向 discovery 合计最多 256 个 gene sets，两个 validation 各最多评价对应已锁定集合，因此全 run 最多 512 次 gene-set bootstrap，不能把 128 误报为整次 run 上限。降低 max_order 时使用冻结配置对应的预定配额规则，实际次数逐方向/阶段记录。

块读取表达；候选去重缓存按 canonical tuple；中间状态表、bootstrap、gain、search logs 逐阶段写盘，不能为了审计长期保留全部大数组。资源审计给出 wall time、进程 peak RSS、磁盘输出量；只测 Python 进程时不得称整个容器峰值。

内存限制应同时有 runner 外层监测与内部阶段检查；单独的 `max_process_rss_mib` 配置值不等于操作系统硬限制。使用同一进程连续运行多个规模时，`ru_maxrss` 是进程寿命的 high-water mark，不能按规模假称为独立峰值；正式资源比较优先每规模使用独立子进程。

配置冻结为 `config_frozen.yaml`，保存 canonical config hash；正式运行开始后不得改变。新参数建立新 run_version、输出目录，不覆盖已有结果。真实 NT 中候选减少、sentinel 丢失或四阶变零时，只报告结果和原因；不得自动放宽阈值、增抽 exploration 或扩大预算追阳性。

主要产物及审计用途：

| 产物 | 用途 |
|---|---|
| `hvg_selection_A/B.csv` | 各 discovery 的基因池和选择依据 |
| `dependency_graph_A/B.csv`、graph summary | 边来源、图稠密度及 neighborhoods |
| `candidate_proposals_A/B.csv` | 去重 tuple、全部来源、抽样参数和父组合 |
| `candidate_search_log_A/B.csv` | 每个候选的 KEEP/EXPAND/PRUNE 生命周期 |
| `estimability_summary.csv` | 完整表支持和可估计性 |
| `gain_summary.csv`、`bootstrap_summary.csv` | 独立的效应量、校准、稳定性 |
| `state_tables/`、`bootstrap/`、`gain/`、`search_logs/` | 可重查的逐组合明细与数组 |
| `frozen_candidates_A/B.csv` | 验证前锁定的具体状态 |
| `locked_validation_A_to_B.csv`、`locked_validation_B_to_A.csv` | 对侧锁定结果，含失败者 |
| `cross_fold_summary.csv` | 三层复现标签与对侧搜索资格 |
| `sentinel_recovery.csv` | 旧版本经验候选的阶段化追踪 |
| `reference_catalogue_primary.csv`、`reference_catalogue_exploratory.csv` | 正式预定资格与有限证据分开 |
| `multiple_testing_manifest.json` | 家庭范围、成员、缺失/未执行检验和解释限制 |
| `run_manifest.json`、`config_frozen.yaml` | 输入/代码/config hash、cell assignments、软件、seed 和资源 |
| `scale_benchmark.csv`、`BENCHMARK_REPORT.md` | 规模、恢复、资源与限制，不仅阳性数 |

文件名若因实现布局改变，运行报告应给出明确对应关系。空结果仍输出带 schema 的空表和运行状态，不能因没有阳性而省略审计。

## 12. Synthetic 与 Search Recovery

统计层至少覆盖：pairwise-only（存在二阶结构但无最高阶项）、pure three-way、redundant extension、useful extension；四阶接口另以纯四阶分布核对。Pairwise-only 在理论总体 MFI 应为 0；有限样本、平滑和多个比较可能使估计偏离 0，不能把理论非零 MFI 写成该 null 的预期。

搜索层另在有 null genes 的 universe 植入这些模块，对 `dependency_only / exploration_only / hybrid` 比较 candidate recall、qualified recovery、false candidate proposal、proposal 数、时间。弱 pairwise 信号的 pure-three-way 是否进入列表与进入后能否统计通过分开：

| failure_stage | 含义 |
|---|---|
| `search_failure` | planted tuple 从未被提出，或受提案/评价预算影响未评价 |
| `estimation_failure` | 提出后完整表不可估计 |
| `statistical_failure` | 可估计但 MFI/Gain/support 资格未过 |
| `stability_failure` | 发现通过后 bootstrap 或锁定验证未过 |
| `recovered` | 满足预先定义的目标恢复条件 |

Planted tuples 用于事后评分，不能偷偷注入 candidate engine。单次正例证明代码路径可走通，不代表测得普遍检出率；正式 false-positive rate 和 power 需要预定多 seed/多参数 simulations。

## 13. Scale-up Benchmark 与 Sentinels

按 50 → 100 → 250 的完整合成/集成检查推进，再做 500、1000 的 candidate-count dry-run；不直接启动千基因 × 1000-bootstrap 全流程。dry-run 不能提前知道未执行的 gain/bootstrap 通过率，也不能把提案上界写成正式 evaluated count。

每规模记录 gene pool、图边数/密度、2/3/4 阶 generated/evaluated、estimability/gain/budget 剪枝、bootstrap gene sets、分阶复现数、wall time、peak RSS、输出磁盘量和 budget_exhausted。dry-run 另列候选数、bootstrap 工作量/磁盘量的估计方法与上下界。1000 仅 dry-run 时必须自动写入 limitations。

既有经验 sentinels：`HBD/HBZ/VGF`、`HIST1H1C/HIST1H4C/TMEM158`、`HIST1H1C/TMEM158/VGF`、`HIST1H4C/TMEM158/VGF` 和 `HBG1/HBZ/HIST1H4C/VGF`。它们是旧 Top12 实验中的经验候选，不是 biological ground truth。旁路记录每阶段是否可搜索、提出、评价、可估、Gain 通过、bootstrap 稳定、跨 fold 通过。不能为找回它们调整参数或强制提出。

报告自动检查：预算耗尽、图过密/过稀、exploration 覆盖低、poor 表过多、null calibration 不稳定或分辨率不足、验证稀疏、family 不完整以及只做 dry-run 的限制。不能把“候选更多”或“程序未崩溃”写成方法更好。

## 14. 未来接口与本轮停止条件

`JointDistributionEstimator` 保留 `fit / joint_probability / marginal / conditional_probability / state_table / uncertainty`。默认 empirical counts 延续 v0.2 的概率与平滑语义；TN 只是将来的可替换实现，不是 mandatory component。未来需要在 held-out probability error、MFI/Gain recovery、conditional query 上证实收益，才考虑引入正式方法。

`FrozenReferenceCatalogue` 是后续 perturbation 模块的只读入口：至少包含 reference_id、genes/order/states、frequency、MFI、Gain、state support、estimability、bootstrap、cross-fold status、proposal provenance、testing family 与 quality flags。Primary 只收预先定义的完整资格；exploratory 接收 sparse_boundary、gain_not_evaluated 或其他证据不足的候选，不能承担主结论。Primary 表示证据质量层级，**并不消除本版本 selected-candidate exploratory inference 的限制，也不表示已控制全局 FDR**。默认要求 primary 有 dependency source；是否将 exploration-only 列为 exploratory 是冻结的目录政策，不能事后按结果变更。

下一阶段只有在 500-gene 搜索可控、1000 dry-run 无组合爆炸、synthetic 可以区分 pairwise-only/pure-three-way、真实 NT 存在可靠三阶参考模式、来源和家庭完整、无 validation 调参、sentinel 去留可解释之后，再经人工审阅冻结 Catalogue v1。当前开发不接入 perturbation scan、Explorer/Investigator/Critic、TN training 或新的生物学解释。完成本轮代码、synthetic 和 scale-up 报告后停止。

## 15. 验收状态

逐项验收索引见 [v03_acceptance_checklist.md](v03_acceptance_checklist.md)。README 提供最小例子和实际运行入口；完成状态只能由测试输出与 benchmark 产物支撑，不依据本文件中的需求描述推定。

实际命令模块为 `clue_discovery.v03.synthetic`（统计）、`clue_discovery.v03.recovery`（搜索恢复）与 `clue_discovery.v03.benchmark`（`--mode synthetic/real`）。[README](../../clue_discovery/v03/README.md) 给出参数与新目录示例。Scale runner 在读数据前冻结 50/100/250 full、500/1000 proposal-only dry-run 的整套计划；完整流程默认 1,000 bootstrap、1,999 null draws，不根据某规模阳性数改动配置。每规模独立子进程，Linux 外层监控默认 1,400 MiB RSS，worker 阶段检查；这不是对绝对瞬时峰值的 cgroup 保证。

真实准备阶段只读取已核对的 Replogle raw source、10,691 NT 行和自身 fold moments。一次保存各 fold top1000 基因并集，仅为可复用的计数投影；各规模使用各自 discovery 排名的前缀，并不在准备阶段执行 1000-gene discovery。合成资源数据与真实 NT 输入分别带类型/hash，报告不得混用。

综合报告约定为 `outputs/clue_hunting_v03_benchmark/BENCHMARK_REPORT.md`；其中应明确每项是实际完成、未执行、受预算限制还是只做 dry-run。本文件在代码冻结前描述协议与执行入口，不提前填写结果数字。最终结果可追加至输出目录或本设计目录的独立验收记录，不修改已经被 run code hash 覆盖的 README 来追溯性改变协议。
