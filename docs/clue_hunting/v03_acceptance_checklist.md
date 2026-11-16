# v0.3 需求覆盖与验收索引

来源：本轮用户三份连续规格，共 86 节。此表把要求映射为可检查的证据，**不是自动勾选的完成声明**。测试与 benchmark 的通过/失败、未执行项和限制必须填入实际运行报告；设计文档不能代替实验。

| 原规格节 | 验收要求 | 应检查的证据 |
|---|---|---|
| 1–4 | 新 v03 namespace，保留 binary/MFI/d-tuple/bootstrap/twofold；大池有限搜索，默认2–4阶 | 新配置、旧路径回归、命令入口、搜索算法 |
| 5 | 每个 discovery 独立选50/100/250/500/1000 HVGs | A/B HVG表、参数、对侧表达变化不影响本侧测试 |
| 6–7 | 模块化dependency图、独立exploration、重叠neighborhood、canonical去重和所有来源 | 图构建器、proposal engine、重复提案测试 |
| 8–9 | L2→L3→L4；不以所有pair显著为必要条件；KEEP/EXPAND分离 | lifecycle日志、真实生成父组合、pure3提案测试 |
| 10–11 | 完整2^k表先于昂贵bootstrap；good/borderline/poor及可配置阈值 | estimability表、零格与低count字段、poor不bootstrap测试 |
| 12 | marginal MFI、alpha=.5、gene-set缓存 | MFI与v02数值回归、单gene-set多state复用测试 |
| 13–18 | 三阶低阶maxent/loglinear、完整gain、null calibration | lower-order拟合边缘一致/最高阶为零；simulation内refit；原始null数组 |
| 19–20 | 预先资格与规则式扩展，非总分 | explicit decisions、redundant/useful extension测试 |
| 21–22 | 只对unique shortlist bootstrap；MFI/Gain/状态CI | bootstrap计数与raw分布、summary匹配、共享文件 |
| 23–24 | 分阶/探索/bootstrap预算，显式exhaustion，分块读写 | generated/evaluated/pruned/remaining、RSS/磁盘、阶段目录 |
| 25–27 | 双向独立discovery，先冻结再validate；对侧searchable状态 | checkpoint时间顺序、ID互斥、无HVG/图/提案/状态leakage测试 |
| 28 | MFI/Gain/state家庭各有清单，禁止neighborhood-BH假global | multiple_testing_manifest、family IDs/hash、exploratory限定 |
| 29 | Pairwise-only、pure3、redundant、useful synthetic | statistical synthetic报告及显式种子/样本量 |
| 30–31 | 50/100/250/500/1000逐级benchmark，不能只报阳性数 | scale_benchmark.csv中图、候选、剪枝、负载、复现、runtime/RSS/disk |
| 32–34 | 保留旧经验sentinel，逐阶段解释去留，不注入/调参追回 | sentinel_recovery.csv、旧结果来源、无sentinel数据流入proposal |
| 35–38 | 独立图审计、threshold来源、exploration概率/seed、三类来源比较 | degree/component/neighborhood统计、source breakdown与配置 |
| 39–41 | 三阶主要验证；四阶如未实现Gain须not_evaluated；指标分开 | gain status、独立columns、无伪近似或加权总分 |
| 42 | candidate/gain/estimability/bootstrap/validation ablation hooks | 配置和开关测试；关闭证据不晋升primary |
| 43–45 | 默认empirical estimator，TN仅可替换接口 | fit/probability/marginal/conditional/table/uncertainty、v02语义回归 |
| 46–48 | 完整candidate生命周期、actual lineage、ExpansionDecision | search logs、KEEP不等于EXPAND、budget/prune原因 |
| 49–50 | 模块化实现，复用旧可信统计，保留v02 baseline | 源码结构和完整相关旧测试 |
| 51 | 用户列出的20类单元测试 | 测试名、运行命令、通过数、失败说明 |
| 52–55 | 50先验收再100/250，再500/1000 dry-run；说明资源和覆盖 | 串行benchmark状态、未执行统计列不填假零、estimated负载方法 |
| 56–57 | 指定结果文件、输入/代码/config hash、软件/seed/folds/资源 | 文件清单、run_manifest、空结果schema |
| 58–60 | NT结果仅reference；冻结catalogue只读；不调用Agent | 输出命名、FrozenReferenceCatalogue接口、调用边界 |
| 61–62 | 按Phase1–9推进，最终30条验收各有证据 | 本表+最终benchmark报告；没有证据的要求明确pending |
| 63–64 | 设计文档15项；准确区分借鉴组件和JURE组织/规则 | clue_hunting_v0.3.md、论文来源笔记 |
| 65–66 | 三层概念与MFI/Gain/dtuple语义分开，不声称独立证据 | 设计文档§2/§7/§8，schema与报告措辞 |
| 67–70 | README14个百分点示例、bottom-up示例、pure3与有预算exploration | README；示例标illustrative且不是可行jointtable实测结果 |
| 71–72 | search recovery独立于statistics，三candidate modes比较、failure_stage | 100gene universe模拟、recall/false proposals、分阶段失败 |
| 73–75 | 三阶coverage优先，NT-only，未满足条件不进入perturbation | 真实/合成区分、四阶exploratory、后续阶段门槛 |
| 76–78 | 完整高质量catalogue、quality flags、primary/exploratory分表 | catalogue schema、完整资格、稀疏/gainoff等不能承担主结论 |
| 79–81 | 不以阳性数量判优；报告A–J和自动limitations | BENCHMARK_REPORT.md、预算/图/探索/calibration/validation/family/dryrun提示 |
| 82–83 | 真数据后禁止自动追阳性调参；config冻结，新版本不覆盖 | config_frozen.yaml+hash、run_version、正式执行无config变化 |
| 84–86 | 代码+文档+synthetic/recovery/scale/resource/sentinel/log/config，完成后停止 | 交付索引；真实catalogue仅当资格成立；不自动继续TN/扰动/Agent |

## 需要防止的科学误读

1. MFI与去除唯一最高阶项的KL零假设相关，不能作为独立证据相乘或相加。
2. Pairwise-only分布总体最高阶MFI为零；有限样本误差不是理论高阶项。
3. Validation用自身低阶投影计算Gain，但采用预定exact conditional test；固定低阶充分统计消去nuisance参数。不得静默替换为对D固定分布的KL、用V拟合校准参数或调阈值。
4. 非负set-level KL没有正负方向；方向稳定性应针对signed pattern gain。
5. 弱pairwise的pure3有exploration入口不等于小预算保证恢复。
6. 模拟null应重拟合每张模拟表；不重拟合会校准另一种统计量。
7. Shortlist筛选后的BH不能无条件当全转录组FDR；列清未评价候选/测试。
8. `candidate_searchable_in_opposite_fold`需区分基因全在池内与tuple实际提案，不能仅凭HVG交集断言搜索过。
9. sentinel是旧经验候选，不是隐藏ground truth或强制seed；没恢复应报告阶段。
10. 500/1000 dry-run的无bootstrap结果只能证明该提案预算下的资源边界，不能证明完整规模检出力。

## 完成状态记录位置

`outputs/clue_hunting_v03_benchmark/BENCHMARK_REPORT.md` 应列出本次实际运行命令、配置版本、数据类型（synthetic/real）、测试数、失败/未执行项和上述每类关键证据。若实际输出根不同，最终交付索引应链接其绝对路径，不能把另一个run的证据当作当前版本结果。

已定义的执行入口（不表示已经运行完成）：

| 模块 | CLI | 独立证据 |
|---|---|---|
| Statistical synthetic | `python -m clue_discovery.v03.synthetic --output-dir OUTPUT` | `STATISTICAL_REPORT.md`、named cases、24 次 null audit、冻结配置 |
| Search recovery | `python -m clue_discovery.v03.recovery --output-dir OUTPUT` | `SEARCH_RECOVERY_REPORT.md`、三种 mode、100-gene 失败阶段与独立 3-gene positive path |
| Synthetic scale | `python -m clue_discovery.v03.benchmark --mode synthetic --output-dir OUTPUT` | 50/100/250 full、500/1000 dry-run、逐规模独立进程 |
| Real NT scale | `python -m clue_discovery.v03.benchmark --mode real --source RAW.h5ad --output-dir OUTPUT` | raw source/NT 身份校验、own-fold Fano prefix、配置冻结、资源监控、sentinels |

正式 full 配置默认 bootstrap=1000、null simulations=1999；Linux scale 子进程默认采样监控 RSS 1400 MiB。准备 top1000 计数投影不是提前执行 1000-gene 搜索。输出目录须新建且不能覆盖旧 run。README 与代码文件冻结后不应修改，以免本次 code hash 前后不一致；新结果应写到对应输出目录。

## 最终验收记录：v03b，预定合成与真实运行完成

更新依据为 2026-09-27 回传至本地的 综合报告 (historical source, not bundled: `../../outputs/clue_hunting_v03_benchmark/BENCHMARK_REPORT.md`)、统计汇总 (historical source, not bundled: `../../outputs/clue_hunting_v03_benchmark/statistical/summary.json`)、搜索恢复汇总 (historical source, not bundled: `../../outputs/clue_hunting_v03_benchmark/search_recovery/summary.json`)、合成规模汇总 (historical source, not bundled: `../../outputs/clue_hunting_v03_benchmark/scale_synthetic/scale_summary.json`)、真实规模汇总 (historical source, not bundled: `../../outputs/clue_hunting_v03_benchmark/scale_real/scale_summary.json`) 与 交付完整性核验 (historical source, not bundled: `../../outputs/clue_hunting_v03_benchmark/DELIVERY_VERIFICATION.json`)。这次更新只修改设计目录，不改冻结源码或 README。

**本轮工程实现、测试和预定 benchmark 交付完成；千基因完整统计能力与充分的纯高阶搜索覆盖尚未验收通过。** 真实 NT 在50/100/250 HVGs下获得跨fold三阶参考候选，但所有真实规模均为 `budget_exhausted`，primary catalogue为0；500/1000只执行proposal dry-run。100-gene recovery三种搜索模式均未提出植入的genuine higher-order组合，5组旧sentinels也全部未被当前真实搜索提出。因此不能以新候选数量证明方法已优于小模块基线，更不能将本轮结果升级为perturbation clues。

全仓回归已完成：**534 passed in 145.82s**，见 test_results.txt (historical source, not bundled: `../../outputs/clue_hunting_v03_benchmark/test_results.txt`)。这包含旧测试与 v0.3 的新增测试，不是仅统计新模块。冻结 source hash 为 `3851fe963130d3c86eb2ecfa840453bc603c915100d7787c78c5d09fe6b7786e`；本记录写入设计目录，不改变该 source hash。

### 版本与保留的失败尝试

- `scale_synthetic_v03a_incomplete` 保留原样：原合成源仅有 1,000 基因，其中一侧按冻结 QC 仅剩 999，1,000-HVG dry-run 显式拒绝继续；它不是成功的千基因 run。
- `v03b` 将**合成原始基因数**改为 1,200，为相同 QC 留出余量；全部 seed、统计阈值、探索规则、候选预算保持不变。源矩阵因此改变，不能把 v03a/v03b 当作同一输入的重复实验。该源生成修改发生在真实 NT 分析开始之前。
- 当前冻结的 v03b README 已在冻结前同步为1,200列并说明QC余量；旧archive中的1,000列描述属于v03a历史版本，不是当前文档勘误。
- 最终运行版冻结记录为 SOURCE_FREEZE.json (historical source, not bundled: `../../outputs/clue_hunting_v03_benchmark/SOURCE_FREEZE.json`)，本地规模配置的 run version 为 `v03b`。旧冻结记录、源包和未完成输出均保留，变更说明见 prior_attempts.json (historical source, not bundled: `../../outputs/clue_hunting_v03_benchmark/prior_attempts.json`)。

### 已得到的统计与搜索证据

| 检查 | 实际结果 | 可以得出的结论 / 不能得出的结论 |
|---|---|---|
| Pairwise-only | KL≈`1.82e-10`，parametric p=`0.998` | 在该预定样例中没有误判最高阶 Gain |
| Pure three-way | KL≈`0.105`，parametric p=`0.0005` | 已知候选进入评价后，统计计算能检出该三阶信号 |
| Redundant extension | KL≈`8.05e-17`，parametric p=`1` | ABC×独立D没有被当作 genuine 四阶增量 |
| Pure four-way | KL≈`0.105`，parametric p=`0.0005` | 数值接口在该已知样例正确；正式四阶仍 exploratory |
| 固定 pairwise-only null 的24次重复 | parametric与conditional均`0/24`拒绝；95%精确二项CI均`[0, 0.1425]` | 有限校准审计；区间较宽，不证明总体FPR≤5%或全局FDR受控 |
| 100-gene recovery：dependency-only / exploration-only / hybrid | genuine HO proposal recall和locked recovery均为`0` | 实际是search failure；不能据此判断进入统计层后的power，也不能称规模恢复成功 |
| 独立3-gene positive path | genuine HO proposal recall=`1`，locked recovery=`1` | 证明可通过exploration→统计→bootstrap→锁定验证；不能外推到100/1000gene覆盖 |

以上统计与 recovery 使用 1,999 null draws、1,000 bootstrap；不是以较少 resamples 冒充正式参数。100-gene exploration 每 fold 只抽 300 个三元组，目标三元组纳入概率约 `0.1855%`，两 fold 至少一次约 `0.371%`。没有重抽 seed 追求命中。

### 已完成的本地规模与资源证据

下表 candidate 数汇总 A/B 两方向。RSS 是每个独立本地 worker 的进程峰值，不是 Linux 容器实测；不得据此直接宣称 AutoDL 2GB 无 OOM。dry-run 的高阶统计和稳定性均未评价。

| HVGs | 执行范围 | 二/三/四阶proposed | 状态 | 含validation的bootstrap调用 | 分析秒数 | 峰值RSS MiB | 产物MiB |
|---:|---|---|---|---:|---:|---:|---:|
| 50 | full | `600 / 600 / 400` | `budget_exhausted`，bootstrap预算剪枝13组 | 51 | 2.58 | 469.6 | 19.2 |
| 100 | full | `600 / 600 / 400` | `budget_exhausted`，bootstrap预算剪枝9组 | 52 | 2.70 | 474.6 | 22.5 |
| 250 | full | `601 / 600 / 400` | `budget_exhausted`，bootstrap预算剪枝14组 | 84 | 3.65 | 483.3 | 47.7 |
| 500 | proposal-only dry-run | `974 / 738 / 1770` | `complete`；统计资格未评价 | 0（未执行） | 3.57 | 486.7 | 120.1 |
| 1000 | proposal-only dry-run | `1857 / 1206 / 2000` | `budget_exhausted`；生成计数是下界 | 0（未执行） | 12.28 | 557.2 | 446.2 |

v03b 五阶段执行完成，总墙钟约 33.47 秒；“执行完成”与各阶段的“预算覆盖完整”是两种状态。full 的三阶跨fold pattern数和 primary 数均为 0；250-gene有2个二阶跨fold状态。500/1000没有测三阶复现。较多 poor 表、bootstrap预算和小 exploration 覆盖均如实保留，未自动调整以制造阳性。

规模报告中的 bootstrap arrays 约 28.6 MiB 是冻结配额下的**未压缩数组上界**，不是整个输出目录的磁盘预测；图的全pair审计、null calibration、状态表和CSV另占空间。1000-gene dry-run 已有446.2 MiB产物，说明在计算候选受控之外还需要关注审计输出体积。

### 用户第62节的30项验收逐项状态

状态中的“实现”代表接口/代码已交付；“统计通过”限定到实际列出的样例或冻结候选，不代表全域覆盖充分。全仓534项测试通过；500/1000未做完整统计仍明确保留，不把未评价写成零阳性。

| # | 条件 | 当前状态与边界 |
|---:|---|---|
| 1 | large HVG pool | 已实现；合成和真实1,000-HVG提案dry-run均运行，不是完整千基因统计验证 |
| 2 | 无全局高阶暴力枚举 | 有限neighborhood与rank sampling；500/1000防全局枚举测试通过，实际proposal预算生效 |
| 3 | dependency-guided可用 | 已实现图、边审计、bounded neighborhoods；不代表能检出弱二阶的纯高阶信号 |
| 4 | exploration可用 | 固定seed/预算/概率实现；tiny positive path实际恢复 |
| 5 | pure HO不因pairwise规则必然丢失 | 独立入口与tiny恢复已证实；100-gene实际HO覆盖为0，此科学目标尚未达成 |
| 6 | bottom-up lineage | 已记录实际parents/proposal路径；去重及lineage测试覆盖 |
| 7 | KEEP/EXPAND/PRUNE分离 | 已实现规则式决定与生命周期字段，不使用加权总分 |
| 8 | 完整表先检查estimability | 已实现；规模报告有1537/1541/1134个estimability剪枝；poor不bootstrap测试覆盖 |
| 9 | 保留MFI | 已实现marginal MFI，保留alpha=.5并与v02数值对照 |
| 10 | 保留d-tuple | 已保存具体状态/support/Gain；只筛正Gain，Gain-off路径不声称旧完整状态bootstrap资格 |
| 11 | 三阶HigherOrderGain正确 | 预定pairwise-only/pure3两例统计通过；更广泛power未证实 |
| 12 | null无genuine三阶项 | 最大熵投影保留低阶边缘、最高阶contrast为零的数值测试覆盖；数学推导已记录 |
| 13 | pattern-level Gain | 三种效应量和CI有明细，raw frequency与smoothed probability分列 |
| 14 | set-level Gain | KL独立输出，与MFI不作独立证据累加 |
| 15 | Gain null calibration | D参数bootstrap、V exact conditional已实现；24次null审计完成，FPR证据仍有限 |
| 16 | bootstrap仅shortlist | unique gene set复用已实现；实际bootstrap调用数与预算单列 |
| 17 | 1000 bootstrap可配置 | 已实际按1000运行统计/recovery/50–250full |
| 18 | two-fold locked validation | 先双D冻结再V的barrier实际执行；真实full均有三阶锁定复现，含双向重发现 |
| 19 | validation无leakage | 只评价锁定组合；opposite-mutation/冻结顺序测试通过，全部真实run的source/frozen-D/catalogue hash核验通过 |
| 20 | bidirectional与locked分开 | 字段与报告分开；bootstrap-off不授正式replication标签 |
| 21 | sentinel追踪 | 已输出真实逐阶段审计；5组sentinels各fold均在HVG池内但未被提出，是明确search coverage缺口 |
| 22 | testing universe可审计 | 14个已汇总run的family一致性审计无问题；全部真实run为预算不完整，无global FDR声明 |
| 23 | candidate budgets生效 | 实际1000dry命中proposal预算，full命中bootstrap预算，未无限扩展 |
| 24 | exhaustion显式 | 实际status和prune计数已保存；未知remaining不伪装0 |
| 25 | 500/1000先dry-run | 合成与真实两阶段均已完成受预算约束的提案运行；未执行bootstrap或推断 |
| 26 | 不以程序跑完判成功 | 已分开执行完成、预算完整、search recall、统计qualification和资源结论 |
| 27 | 保留v0.2 baseline | 旧namespace/实验路径保留，完整回归已通过 |
| 28 | 所有旧测试继续通过 | **已通过**；完整全仓日志为534 passed，不仅新模块测试 |
| 29 | 新synthetic tests通过 | 命名统计样例期望全部满足；tiny集成恢复成功；100gene recovery明确未成功，不与unit test混同 |
| 30 | 完整run manifest | 合成与真实manifest、资源、配置/hash、阶段状态已齐全；1340份真实bootstrap NPZ的MFI均为1000 draws |

自动化覆盖文件包括 `tests/test_v03_statistics.py`、`test_v03_proposals.py`、`test_v03_pipeline.py`、`test_v03_isolation.py`、`test_v03_data.py`、`test_v03_synthetic.py`、`test_v03_recovery.py`、`test_v03_report.py`。独立审查发现并修复的 validation p 值浮点越界、bootstrap-off误标正式复现、无效epsilon配置已加入回归覆盖。此处不通过重复跑测试改变正在进行的验收流程。

### 真实NT五阶段结果

数据为10,691 NT cells，A=5,345、B=5,346；各自top1000的并集为1,092 genes。50/100/250执行全部分析阶段，但只评价冻结预算内的候选，并非完成全部可能组合搜索；bootstrap=1000、null draws=1999未降低。500/1000仅proposal dry-run。以下proposal计数合计两fold，states与gene sets严格区分：多个states可来自同一gene set，不能视作独立发现。

| HVGs | 范围 | 二/三/四阶proposed | 三阶跨fold gene sets / states | 三阶双向gene sets / states | Primary | 实际bootstrap调用含V | bootstrap预算剪枝 |
|---:|---|---|---|---|---:|---:|---:|
| 50 | full阶段，预算受限 | `742 / 815 / 714` | `59 / 231` | `23 / 90` | 0 | 415 | 485 |
| 100 | full阶段，预算受限 | `1011 / 1150 / 835` | `79 / 308` | `18 / 71` | 0 | 476 | 919 |
| 250 | full阶段，预算受限 | `1851 / 2158 / 765` | `47 / 174` | `11 / 44` | 0 | 449 | 1910 |
| 500 | proposal-only dry-run | `3232 / 3767 / 2000` | 未评价 | 未评价 | 未评价 | 0（未执行） | 不适用 |
| 1000 | proposal-only dry-run | `6092 / 7044 / 2000` | 未评价 | 未评价 | 未评价 | 0（未执行） | 不适用 |

五档状态均为 `budget_exhausted`。Primary为0主要由预先规定的“搜索预算不完整不得进入primary”规则决定，不等于全部候选缺乏统计信号；保留的跨fold参考状态仍属exploratory。100-HVG的308个states多于250-HVG的174个，不能据此宣称100优于250或扩池恶化：候选路径、shortlist和配额竞争共同影响实际覆盖。真实数据之后未修改阈值、预算、exploration比例或seed重跑追阳性。

三个full阶段的415+476+449=**1340份gene-set bootstrap NPZ**已逐文件检查，每份MFI数组长度均为1000。全部source、冻结discovery和catalogue hash核验通过，见 DELIVERY_VERIFICATION.json (historical source, not bundled: `../../outputs/clue_hunting_v03_benchmark/DELIVERY_VERIFICATION.json`)。

### 旧sentinel去留：搜索覆盖缺口

`HBD/HBZ/VGF`、`HIST1H1C/HIST1H4C/TMEM158`、`HIST1H1C/TMEM158/VGF`、`HIST1H4C/TMEM158/VGF`、`HBG1/HBZ/HIST1H4C/VGF`，在真实50/100/250的两个fold均全部处于HVG池内，但全部为 **`not_proposed`**；500/1000 dry-run也未提出这些组合。未发生Gain/estimability/bootstrap意义上的统计失败，因为它们根本没有进入评价。

这说明当前局部图加小预算随机探索不能保证恢复既有小模块候选；这是必须保留的coverage负结果。Sentinels不是ground truth，也没有注入引擎或用来调整阈值。完整字段见各规模的 `sentinel_recovery.csv` 与聚合表 (historical source, not bundled: `../../outputs/clue_hunting_v03_benchmark/sentinel_recovery.csv`)。

### AutoDL 2GB / 0.5CPU资源验收

真实执行总墙钟 **476.29秒**，含准备及五阶段；无GPU。Linux cgroup限制为2,147,483,648 bytes（2GiB），CPU quota对应0.5核心。每阶段退出码0，RSS guard未触发，全部cgroup `oom/oom_kill/max`事件增量为0。来源为 preparation_resources.json (historical source, not bundled: `../../outputs/clue_hunting_v03_benchmark/scale_real/preparation_resources.json`) 及 `resources_50/100/250/500/1000.json`。

| 阶段 | wrapper秒数（含启动） | 进程峰值MiB | cgroup观测峰值MiB | 产物MiB |
|---|---:|---:|---:|---:|
| NT准备 | 187.91 | 750.60 | 943.71 | 另见prepared目录 |
| 50 full | 42.21 | 392.02 | 800.16 | 63.45 |
| 100 full | 65.37 | 392.19 | 937.81 | 82.77 |
| 250 full | 91.44 | 392.09 | 1117.74 | 134.26 |
| 500 dry-run | 28.16 | 392.14 | 1268.23 | 142.69 |
| 1000 dry-run | 60.22 | 473.29 | 1771.25 | 478.08 |

全run最高**单worker进程峰值**为准备阶段750.60 MiB；最高**cgroup观测值**为1000dry的1771.25 MiB（约1.73 GiB），其中记录的file cache峰值约1031.21 MiB。二者不是同一种测量口径，也不能把进程峰值当容器总内存。页缓存随审计输出积累，解释了后段容器内存增长。当前预算下这套计划在2GB模式跑通；没有运行500/1000完整统计，因此不保证相同资源能承载该未执行任务。

### 本轮停止条件

本轮代码、文档、534项测试、统计与搜索恢复、合成/真实规模、资源、sentinel和冻结交付已完成；不再按阳性数量自动修改参数。下一轮若要提高覆盖，需要人工审阅：100gene pure-HO search recovery为0、全部旧sentinels未提出、显著bootstrap配额瓶颈、primary为0及千基因仅dry-run这些限制。

当前尚不足以宣称已完成充分的大规模统计coverage验收，也未进入Reference Catalogue v1的下游正式使用阶段。本轮结束后停止perturbation scan、Explorer/Investigator/Critic、TN training及新增生物学解释，等待人工决定下一版设计。
