# JURE Clue Discovery：方法定位、组合设计与扰动处理

日期：2026-09-28。用途：论文 Introduction、Methods overview 和方法图 caption 的讨论稿。描述当前已实现设计，不宣称未经共同任务 benchmark 验证的性能优势。本文的 mTRIM 是 Awad & Chen 2014，不是另一个名为 TRAM 的方法。

## 1. 推荐的核心定位

**JURE 将高阶联合状态识别、参考引导的扰动关联检验，以及跨扰动的响应结构组织结合起来，把单细胞联合表达模式转化为可追溯的机制调查线索。**

关键是将任务从“识别表达依赖或组合规则”推进到“确定哪些固定联合状态与哪些扰动相关，并组织这些关联的共享结构与差异”。高阶统计和组合搜索的来源应正面引用，论文重点解释额外环节为何必要、具体解决什么问题，以及通过什么实验验证。

## 2. 原方法是否考虑扰动：应区分数据角色

不能笼统写“Stator 和 mTRIM 都不考虑扰动”。

- **Stator** 从单细胞高阶依赖和 d-tuples 构建可重叠细胞状态，已有条件/疾病富集比较，正式论文还讨论状态投射到独立数据。它的主要任务不是本项目定义的、大规模 perturbation × frozen signed-state 的 matched-shift 扫描与 response-profile landscape。
- **mTRIM** 结合 TF–DNA binding 与表达数据推断 TF 协作；原文使用单 TF knockout、双基因 genetic interaction 和 synthetic 数据检验不同阶的推断。扰动相关数据确实出现，主要是作为规则验证证据。不能把其论文描述成完全没有扰动或没有实验验证。
- **JURE** 中 condition/perturbation 是核心分析轴：对每个 perturbation 与每个固定 reference state 配对，计算 matched-control shift 并保留候选/非候选/不可评估状态，然后依据跨 perturbation 的效应曲线组织 response groups。

因此更准确的差异是 **扰动在推断流程中的角色、分析单位和输出目标**，而不是论文里是否出现过 perturbation 数据。

来源：[Stator 正式论文](https://doi.org/10.1038/s44320-024-00074-1)、[Stator 项目采用的预印本](https://www.biorxiv.org/content/10.1101/2023.12.18.572232v1)、[mTRIM 原论文](https://pmc.ncbi.nlm.nih.gov/articles/PMC4080427/)。原论文整理见 Stator_mTRIM_Methods_and_Datasets (historical source, not bundled: `../../dataset_audit/methods/Stator_mTRIM_Methods_and_Datasets.md`)。

## 3. 继承、增加、动机与验证

| 出发点/已有思想 | JURE 的组合或扩展设计 | 为什么需要 | 解决的问题与边界 | 对应图/验证 |
|---|---|---|---|---|
| Stator 的检测二值化、MFI 与 d-tuples | 保留完整 signed state，先在 control 中发现并验证，然后冻结 reference catalogue | 如果各扰动独立挑出不同的“最佳状态”，后续比较的对象不一致；小扰动组也可能无法支撑完整高阶发现 | 为所有 perturbations 建立相同的比较对象，将 reference 支持与扰动关联支持分开。冻结是标准设计原则，不声称独有发明 | Stage I 状态条 + 冻结标识；crossfold/estimability 结果 |
| mTRIM 的 bottom-up 组合搜索思路 | 结合依赖引导、固定预算探索和直接三阶 fingerprint 通道，不要求候选先有显著 pairwise edge | 全局高阶枚举昂贵；只依赖低阶关系可能漏掉 pure higher-order structure | 在固定预算内兼顾计算效率与额外搜索覆盖；不保证找全，fingerprint 偏好强 parity | 候选路径 inset；pure-three-way recovery、通道消融、资源曲线 |
| 高阶依赖评价与既有 lower-order maximum-entropy 思想 | MFI、lower-order Gain、完整状态表 estimability 和锁定验证分别记录 | 具体 state 的高频出现不足以证明存在额外高阶结构；稀疏格会使估计不稳 | 区分候选生成、低阶解释、可估计性和验证资格。MFI/Gain 不是独立证据，不是新造统计量 | pairwise-only/independent 阴性对照，支持度及稳定性分析 |
| 已知 state 的条件比较 | 将冻结 state 与每个 perturbation 配对，使用 batch-matched control prevalence、支持/效应门槛和既有 selected-family Holm | 需要回答某个 perturbation 对整个 signed state 的频率有什么关联，同时处理批次构成和样本支持差异 | 生成明确的 `perturbation + state + shift`；保留低支持和缺失原因。当前 reused-control selection 未消除，结果仍为 exploratory | Stage II matched-frequency 对照 + shift/candidate 总览 |
| Stator 按 cells × d-tuples 的共现分组 | Stage III 按 perturbations × signed-state effects 的 response profile 分组 | 大量候选可能反复反映共同响应，也可能是同 genes 的不同状态产生反向变化 | 找到 shared response、stable cores、state-specific differences 与 gene-disjoint co-response；不自动确认为 biological program | 连续效应热图、signed-state contrast、disjoint co-response、bootstrap/消融 |
| 显著候选列表 | 带 condition/state/effect、原始证据、group/core、样本量与来源的 structured clue pool | 单靠 p-value 排序容易重复挑同类响应，且无法独立表示结构背景和证据范围 | 为有原则的后续选例与机制调查提供输入；具体选例和机制调查属于下游 | 输出具体 clue card，连接 Triage / Deep Investigation |

“增加”在此指 JURE 相对所借鉴流程的任务和组合设计；不能由这张表推出任何组成技术此前无人使用，也不能替代系统性的相关工作检索。

## 4. 我们具体怎样处理扰动

### 4.1 Stage I：对照中建立比较对象

从明确的 control/NT population 中识别具有高阶支持、可估计且通过既定验证的状态，例如 `A+ B− C+`。当前验收后端是三阶。

输出包含 genes、逐 gene 的检测状态、reference prevalence、MFI/Gain、support/estimability、bootstrap、crossfold 和来源。reference 冻结后，Stage II 不按照各 perturbation 的效果重新定义状态。

这使得每个 perturbation 都在同一组坐标上比较；也把需要丰富 joint-state observations 的 reference discovery 与逐 perturbation 的 state prevalence 检验分开。

### 4.2 Stage II：计算同一状态的 matched prevalence shift

令 `r` 为一个冻结 signed state，`c` 为 perturbation，`b` 为 batch。扰动中携带该完整状态的细胞比例为 \(\widehat p(r\mid c)\)。以该 perturbation 的 batch 构成为权重，构建 control baseline：

\[
\widehat p_{\mathrm{matched}}(r\mid control,c)
=\sum_b\frac{n_{c,b}}{\sum_{b'}n_{c,b'}}\widehat p(r\mid control,b),
\]

\[
\Delta_{c,r}=\widehat p(r\mid c)
-\widehat p_{\mathrm{matched}}(r\mid control,c).
\]

正 Δ 表示完整状态变常见，负 Δ 表示变少。`A+` 仍仅表示 A 被检测到，不能把这个符号解释成扰动令 A 上调。

随后使用原 exact stratified test、预设 effect/support 门槛和 selected-family Holm。保留完整 condition × state family；未计算比较仍在既定 multiplicity accounting 中。control 匹配缺失、参考基因不可测或样本量不足时标为不可评估，不能补零或当作阴性。

**当前可成立的主张：某扰动与一个已具有参考高阶支持的联合状态的 prevalence shift 相关。** 这不同于证明扰动改变了最高阶 interaction coefficient。后者需要另行定义并检验高阶交互强度的差异，本流程不作此主张。

同时，Stage I 与 Stage II 当前复用 NT/control，因此不能写成“冻结后已完全消除选择性偏差”或“获得全局确认性 FDR”。现有候选的等级为 exploratory association。

### 4.3 Stage III：把成千关联组织成响应结构

形成 \(M_{c,r}=\Delta_{c,r}\)，并另存 candidate、tested、support 和 reason。聚类使用 signed continuous effects；未入选不等于零。

这一分析能同时暴露：

- 不同 perturbations 推动相似的 state changes；
- 同一 gene set 的不同 signed states 响应不同；
- 不重叠 gene sets 的 states 在相同 perturbations 下共同变化。

因此，一条线索仍是 `condition + exact state + Δ`，response group 提供上下文。样本量与候选负担的关系必须保留，不能由候选多直接推断生物学影响广。

## 5. 可用于论文的中文段落

> 我们开发了面向扰动实验的三阶段高阶联合状态线索发现流程。该流程借鉴了 Stator 对联合检测状态及高阶表达依赖的表示，以及 mTRIM 的自下而上组合搜索思想，并将其与固定预算的直接高阶候选生成、低阶参照模型、可估计性检查和锁定验证结合。首先，在 control population 中建立冻结的 signed-state reference catalogue；随后，对每个扰动与参考状态配对，计算批次匹配对照下的联合状态频率变化，形成探索性 perturbation-associated clues；最后，在跨扰动的 signed-effect 空间中组织共享响应、稳定核心及状态特异性差异。输出保留具体扰动、完整联合状态、效应和证据来源，为后续案例筛选与机制调查提供结构化输入。

> 这一设计改变了分析的中心对象：Stator 的状态构建依据联合表达模式在细胞中的共现，而 JURE 的响应组织依据冻结状态在不同扰动条件下的共同变化。我们关注的不是仅凭相关结构直接推断调控机制，而是将可测量的扰动关联组织成可调查的线索。该定位不否认既有方法中的条件富集、状态投射或扰动验证功能；这些设计的增益仍需通过任务一致的对照、消融和外部验证评估。

## 6. Methods overview 英文讨论稿

We developed a three-stage workflow for reference-guided discovery of perturbation-associated higher-order state shifts. Building on signed joint-state representations and model-free interaction statistics used in Stator, and inspired by bottom-up combinatorial search in mTRIM, the workflow combines bounded candidate generation with lower-order reference models, estimability checks, and locked validation. It first establishes a frozen catalogue of joint detection states in control cells, then quantifies their prevalence shifts under each perturbation using batch-matched controls. The resulting signed condition-by-state effects are organized into shared response groups, stable cores, and state-specific contrasts. Each candidate retains its perturbation identity, exact signed state, effect, support, and provenance for downstream case selection and mechanistic investigation. The current shifts are exploratory associations; they do not by themselves establish a perturbation-induced change in higher-order interaction strength or a causal mechanism.

## 7. 方法图上怎样体现这些增加

方法图主线保持三列：**Find reference states → Associate shifts with perturbations → Organize shared responses**。

- Stage I 上方画 control cells；内部保留 state 的 `+/-`。下方画低阶引导与直接高阶候选两条入口，共同进入质量/验证步骤。
- Stage I → II 的箭头写 `frozen signed states`；在 Stage II 另接 perturbation cells 和 batch-matched controls，明确扰动数据从哪里进入。
- Stage II 用同一状态的两组频率和 Δ 表示检验对象，避免画成“perturbation → gene regulation”的因果箭头。
- Stage III 画 perturbation × state effect matrix，接 core/boundary 与两个对照：same genes / different states；different genes / shared response。
- 最右侧输出一张具体 clue card，包含 perturbation、signed state、Δ、support 和 group context；下游 Triage / Agents 独立框出。

在框架下用短文字标出每个环节的动机：**Comparable states / Matched condition effects / Shared structure with retained specificity**。结果图使用真实热图和已冻结例子；验证图用 recovery、阴性对照、搜索与表示消融支持方法价值。热图自身不能证明优于原方法。
