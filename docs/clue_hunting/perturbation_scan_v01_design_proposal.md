# Perturbation Scan v0.1：问题与实施方案草案

> 决策更新（2026-09-27）：用户已选择 Day 6 探索性扫描、Day 8 后续外部验证。当前执行协议为 [perturbation_scan/PROTOCOL.md](/Users/mac/Documents/ChatGPT/JURE/perturbation_scan/PROTOCOL.md)。下文保留为先前方案讨论记录，潜在全集校正不作为本轮默认方法。

**原讨论时状态：讨论稿，不是已冻结的执行协议。** 按用户要求，先讨论设计，不继续实现、读取新的 perturbation 表达或运行扫描。已有本地代码仅是未验收原型。

## 一、目标与输入保持不变

本轮目标是判断：扰动某个 target 后，已经冻结的 NT 联合状态是否发生足够大、具有支持证据的 prevalence shift。

固定输入是 1000-gene NT Catalogue：86 个三元基因组、341 个具体 states，涉及 57 个不同基因；其中 124 个 states 通过双向验证。Catalogue payload SHA256 为 `23f7840ad7e9b14347b0101e2f8fddbc93f31f524033fb1f64368609cef6bf68`。

不重新选 HVG、不再搜索组合、不调整 MFI/Gain、bootstrap 或 NT 筛选规则。341 个 states 都保留；双向验证是证据字段，不能自动替代后续 shift 的统计设计。

最终输出必须区分：

1. **描述性 shift**：观察到多少命中数和多大的频率差。
2. **探索性候选**：值得提出问题，但 NT 复用等限制尚未解决。
3. **通过指定推断规则的 perturbation-associated clue**：满足预先规定的 support、effect 和错误率控制要求，仍不是机制或因果结论。

## 二、必须先解决的问题

### 问题 1：全部 NT 已参与 Catalogue 筛选，没有现成的独立 NT 留出集

341 个 patterns 的入选使用了全部 10,691 个 NT：A/B 两侧 discovery、validation、bootstrap 和 Holm qualification 都参与了最终筛选。

因此，“现在锁定了 patterns”只代表后续不能改定义，并不意味着用于筛选它们的 NT 突然变成独立对照。即使 perturbation cells 尚未查看，reference frequency 的选择效应仍可能影响两组比较。

直接执行 `341 patterns × targets → Fisher/比例检验 → Holm`，只处理了报告出来的多个检验；它没有自动处理 patterns 本身是用同一 NT 挑选的事实。不能由此宣称确认性的错误率控制已经成立。这里不是断言每个结果必然错误，而是现有 nominal p/adjusted p 缺少相应保证。

下列操作也不能自动解决问题：事后将这些 NT 再随机拆一次、把 A 或 B 改名为 test、对同一批 NT 做更多 bootstrap、只保留 124 个双向 states。它们已经参与原 Catalogue 的选择。

### 问题 2：跨 fold 重现与 perturbation shift 是不同命题

NT cross-fold 验证回答的是“这个高阶 reference 是否稳定”；shift 检验回答的是“某 target 与这个状态的 prevalence 是否不同”。前者的 Holm 校正单位是 gene set，不能继承为后者的 state×target 错误率控制。

一个三元组可对应多个 +/- states，这些是不同的 shift 问题，后续 family 需要按具体 state 计数。

### 问题 3：pooled NT 的频率可能不是合适的比较基线

现有 NT metadata 含 48 个 batch，每 batch 116–281 个 NT cells。target 在这些 batch 中的分布仍需 metadata 审计。batch 不等于 biological replicate。

如果 target 的细胞大多来自某些 batch，而某状态在这些 batch 中本来就更常见，直接比较 target 与全部 pooled NT，可能把 batch 构成差异当成扰动信号。

建议主效应使用配套 batch 的全部 NT，并按 target 的 batch 构成加权：

`w_b = n_target,b / n_target`

`p_NT,matched = sum_b w_b × p_NT,b`

`delta_matched = p_target - p_NT,matched`

同时保留 Catalogue pooled frequency 和 `delta_vs_pooled_NT`，但标为描述性结果。加权频率不是简单的一个整数命中数除以总细胞数，所以还要保存每 batch 的完整分子、分母。

### 问题 4：support 不能只设一个“命中数至少 10”的统一条件

增加方向的 2/20 很不稳定，应该被样本量门槛阻断。但减少到 0/300 可能是非常明确的 depletion，不能因为命中数为零而一律丢弃。

建议同时检查 total cells 和方向相关的证据量，而不是让增加、减少机械地共用正状态命中数门槛。阈值是工程取舍，必须在结果之前确定。

### 问题 5：family 不能随筛选结果缩小

假设实际为 2034 targets，341×2034 是 693,594 次潜在比较；2034 目前只是示例，真实 target 数需要 metadata 确认，并保留既有 CPA/external-benchmark 隔离。

不能每个 target 各给一份 0.05，再把所有发现汇总成整体受控的 Clue 集合。也不能先剔除低 support、效应小、无法估计的比较，再用缩小后的分母校正。

建议以预定的全部可访问 targets×states 为一个报告 family，未执行的比较保留 accounting p=1，并明确标记“未检验”。但这个 family 定义本身仍不能替代问题 1 的 NT 复用处理。

### 问题 6：state prevalence shift 不等于高阶 interaction 改变

例如 `AURKA+ PIF1+ PLK1+` 增加，可能来自联合依赖改变，也可能来自单基因表达、细胞周期组成、检测深度或其他状态比例改变。

第一版可以把它称为“一个已验证高阶 reference state 的 perturbation-associated prevalence shift”，不能直接声称高阶调控被重连、比 DE 多解释了多少信息，或某条机制已经成立。

## 三、处理 NT 复用的路线选择

| 路线 | 如何使用 341 patterns | 可以支持什么结论 | 代价或限制 |
|---|---|---|---|
| A：探索性扫描 | 原样冻结，与现有 NT 做分层比较；selected-family 校正只作排序和筛查 | 形成明确标注限制的候选与开发 case | 不能把 adjusted p 当成已解决选择效应的确认性证据；不能自动升级为可靠机制输入 |
| B：真正独立的 NT/control | 341 原样保留，比较使用从未参与 Catalogue/调参的匹配 control | 最清楚的固定-pattern 推断路径 | 目前尚未确认存在；其他研究的 K562 NT 也可能有平台/培养/批次混杂，独立不等于可直接混用 |
| C：重新设计 discovery/validation/test | 用 discovery/validation 生成新的 Catalogue，保留 test controls | 对新流程建立更清楚的内部隔离 | 改变当前 341 入口、牺牲 discovery 样本；原数据已被查看，不能宣传为全新盲测证据。本轮不优先 |
| D：显式 selection-aware 保守推断 | 341 不变，对更大的预定潜在全集控制错误率 | 在细胞抽样模型成立的前提下，允许同一 NT 参与选择 | 方法与数值实现需要验证；校正很重，可能只有极强 shift 通过，甚至没有结果 |

### 路线 D 的一个可审查候选：潜在全集校正

以原始输入的 8,563 个基因为范围，所有三基因二值状态共有：

`U = 8 × choose(8563,3) = 836,882,335,688`。

主 family 为 `M = U × number_of_prespecified_targets`，数量级约 10^15。只计算冻结的 341 patterns，其他未选或未测假设按 p=1 计入 implicit Holm，不枚举全集。将未选检验的 p 提升为 1 不会增加误拒绝风险；它可以在有效 fixed-hypothesis p 值的前提下处理数据驱动选择。

**它不是免费的修复。** 这比只对 341 patterns 校正大约多出 24.5 亿倍的状态范围；首个显著性门槛约为 10^-17 量级。弱、中等 shift 可能大量漏检，因此不能未经功效评估就把它锁为默认，更不能做完后为凑 case 缩小分母。

另一些 selective-inference 或“重新选择整个 Catalogue 的重采样”方法需要重新推导或重复昂贵 discovery，不适合作为本轮未经验证的快捷替代。

## 四、建议进入比较的 v0.1 具体设置（均为待讨论建议）

| 项目 | 建议值/方法 | 说明 |
|---|---|---|
| Pattern 范围 | 全部 341 个；保留原双向验证标记 | 不因 perturbation 结果增删 pattern |
| Target 范围 | metadata 确定的单-target cells；保持既有外部 benchmark 隔离 | 冻结 target 清单与 aliases；不先假设确有 2034 个 |
| 主 effect | batch-matched delta，单位百分点 | pooled delta 仅描述性并列报告 |
| 最小 total support | target≥100 cells；占用 batch 中 NT≥20；matched NT effective n≥100 | 是待评估工程阈值，不是普适定理 |
| 最小 effect | abs(delta)≥10 个百分点 | 与显著性同时满足，不以 p 小替代效应大 |
| 增加方向 support | target 命中≥10，并有足够 NT 预期未命中机会 | 防止极少数正状态驱动增加结论 |
| 减少方向 support | target 未命中≥10，NT 基线下 target 预期命中≥10 | 允许有足够 total cells 的 0 命中 depletion |
| 基础检验 | batch 内固定 2×2 边际，独立超几何分布直接卷积；双侧为两倍较小的含端点尾概率 | 与 pooled Fisher、渐近 CMH、Fisher probability-ordering 双侧定义区分 |
| CI 候选 | 与 batch 权重一致的保守有界变量区间；正式路线须处理选择/多重性 | 常规 bootstrap/95% 区间不能自动修复 NT 复用；很保守的同时区间可能较宽 |
| 正式多重性 | 有真正独立 control 时：全 target×341 的 Holm；复用 NT 时：需先验证路线 D 或其他明确 selection-aware 方法 | 依赖条件不明时不把 BH 当成自动解决方案 |
| 其他质量字段 | 每 batch support、guide 构成、检测深度/检测基因数、是否 biological replicate | 先审计 guide 层级；多个 guide 不能自动视为 biological replicate |

上述条件只产生关联证据，不消除未测混杂或 guide-specific 效应。下游 Clue 必须携带这些证据边界。

## 五、建议执行顺序与验收

**阶段 0：讨论并确定结论标准。** 本轮是先形成探索性真实 case，还是必须先得到处理 NT 选择效应后的严格 Clue？如果要求后者，应接受当前样本量下可能为零。这个取舍应在看真实 shift 之前决定。

**阶段 1：metadata-only 审计。** 确认实际 target 数、cells/target、target×batch 覆盖、NT 配套、guide 层级与锁定基因隔离。没有合适对照的 target 不能靠换标签解决。

**阶段 2：新 synthetic 验证与功效评估。** 预先生成/冻结独立平衡 null、batch-heterogeneous null、pairwise-only null；加入 NT 选择偏差压力测试、正向/反向 shifts、小样本、缺失 control。比较 selected-family 与 selection-aware 路线，分别报告假阳性和 power，不用同批结果反复改门槛后宣称通过。

**阶段 3：冻结真正的运行协议。** 保存方法、阈值、清单、family、源代码与 Catalogue hashes。开发失败修复和统计规则变化要区分；改变规则须另开协议版本。

**阶段 4：预定小规模 pilot，然后完整扫描。** pilot targets 根据 metadata 规则提前选定，不按未知真实效应挑选。先验证计数、batch matching、资源和输出，再按冻结的全 family 运行；不为得到首个 case 动态放宽标准。

**阶段 5：导出 case。** 按预先规定的排序导出，明确 `exploratory_candidate` 或 `selection_adjusted_association`；未通过正式路线的不伪装为正式 Clue。NT reference、perturbation evidence 与机制假说分开保存。

## 六、Clue 文件应保存什么

`clue_id, target, reference_id, genes, exact +/- states, reference Catalogue hash, NT reference validation evidence, target hits/n, matched NT per-batch hits/n, pooled and matched prevalence, delta, uncertainty method and interval, raw p, correction method, full family size, adjusted p, support flags, NT selection handling, batch/guide limitations, evidence status`。

Explorer 收到的不是“ABC 有机制”，而是“target X 与某个冻结状态的频率变化相关，以及这条关联通过了哪一级证据标准”。Investigator/Critic 仍需独立证据；本阶段不训练 TN、不自动生成机制结论。

## 七、我的建议与需要你决定的一点

保留 341 个 patterns，不再动 NT 主算法。先完成设计审查、metadata 审计与局部 synthetic 对照，再决定是否采用潜在全集等 selection-aware 方法。刚才提出的全集校正目前只是候选方案，不应未经比较就变成默认。

**需要先决定：第一轮产物允许是明确标注局限的探索性 case，还是必须是处理 NT 复用之后的严格关联 Clue？** 我倾向于保留探索性结果供审计，但进入“可信 Clue”入口必须满足独立 control 或已验证的 selection-aware 条件；找不到就报告没有，不用漂亮机制故事补足统计证据。

## 依据与现有结果

- 当前输入与资源证据：[REAL_NT_REPORT.md](/Users/mac/Documents/ChatGPT/JURE/outputs/real_nt_v04_holm_20260927/REAL_NT_REPORT.md)。
- 精确条件超几何检验：[R Fisher 文档](https://www.stat.ethz.ch/R-manual/R-devel/library/stats/html/fisher.test.html)。
- Holm 的任意依赖控制：[R p.adjust 文档](https://stat.ethz.ch/R-manual/R-devel/library/stats/html/p.adjust.html)。前提仍是输入 p 值有效。
- 有界独立变量的保守区间依据：[Hoeffding 1963](https://www.tandfonline.com/doi/abs/10.1080/01621459.1963.10500830)。

这里提出的 batch 加权、潜在全集与实施顺序是本项目的设计建议，不把它们说成原论文已经替本数据验证完毕。
