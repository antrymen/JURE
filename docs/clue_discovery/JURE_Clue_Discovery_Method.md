# JURE Clue Discovery：三阶段方法与接口

## 1. Overview

JURE Clue Discovery 在明确的 reference/control population 中发现高阶联合状态，检验这些冻结状态在其他条件下的频率变化，再将关联组织成可追溯的共享响应结构，为后续案例筛选和机制调查提供输入。

```text
DatasetAdapter + DatasetConfig
    → Stage I   Higher-order Reference Discovery
    → Stage II  Perturbation/Condition-associated Shift Discovery
    → Stage III Broad Response Landscape Organization
    → StructuredClueLandscape + TriageInput
    → optional Triage (human / rules / model)
    → SelectedCase
    → Explorer → Investigator → Critic
```

前三个阶段是可复现的统计流程。Stage III 对应已验收的 Broad Screening；它不调用模型，不属于 Agent。Triage 是后续可替换的案例筛选层，Deep Investigation 调查具体关联的可能解释。后续新增的 4-case pilot preparation 只完成 deterministic selection 和事实型 CaseFile 初始化，见第 10 节。

主入口为 `python -m clue_discovery.run`。旧版本统计代码、原冻结结果和旧 CLI 保留；新入口通过薄封装调用现有实现。当前数据集的规模、组数、PCA 方差和生物学猜测均不属于方法默认假设。

## 2. Stage I: Higher-order Reference Discovery

输入为经过显式基因映射和检测规则转换的细胞数据，只从配置声明的 control population 建立 reference。当前后端复用 `clue_discovery.v04`、`v04_validation` 和 `real_nt_v04_holm.run.run_reference`：固定预算的高阶候选发现、MFI、低阶模型 Gain、estimability、bootstrap 和双折 held-out validation-family Holm。

两折 cell IDs 不重叠，两边 discovery 和检验 family 在 validation 前冻结。按既有策略输出合格 reference，不回溯修改旧 primary veto。Holm 的既定 family 语义保持原样；它不构成 state-level FDR 声明。cell split 的 crossfold 稳定性也不等于生物重复验证。

输出 `ReferenceCatalogue` 和 `ReferenceState`。保留完整 genes/states、prevalence、MFI/Gain、支持度、可估计性、bootstrap、单向/双向资格与 source hash；原始某折证据为 `null` 时保留缺失。完整原证据可通过 record ID 和带哈希文件定位。

当前接口的 Stage I/II 后端能力限定为三阶。schema 和 Stage III 可表达、组织任意阶 signed state；不能将 schema 的泛化能力写成各阶统计方法均已验收。

若 control 缺失或总支持不足，输出 `reference_population_unavailable`，不以 perturbation cells 替代 control。参考发现的具体搜索预算、support 与统计阈值必须针对新数据预先校准。

## 3. Stage II: Perturbation/Condition-associated Shift Discovery

输入为冻结 reference catalogue 和目标数据集的条件分组。适配器只进行细胞对齐、binary state matching 和 condition × batch 的整数计数，检验仍使用原 `perturbation_scan.scan` 后端。

每个 condition/reference 的效应为：

\[
\Delta_{c,r}=\widehat p(r\mid c)-\sum_b w_{c,b}\widehat p(r\mid control,b),
\qquad w_{c,b}=n_{c,b}/\sum_b n_{c,b}.
\]

正负方向分别是整个 signed state 的 enrichment/depletion。`+/-` 是每个基因被检测/未检测的状态；两者不可混淆。频率变化也不等于高阶交互强度变化。

使用既有 exact stratified test、预设支持度/效应门槛和 selected-family Holm。原 family 包含所有配置 conditions × 冻结 states，未计算比较按既有 p=1 accounting 处理。缺少映射基因时，相应 state 仍留在 family 中，并在通用视图标为 `NOT_EVALUABLE`、效应 NA；不作为负结果删除。control 匹配失败和低支持亦保留原因及分母。

reference discovery 复用 control 带来的选择性未被本方法消除，因此现有候选仍是 `EXPLORATORY_ASSOCIATION`。原 nominal pointwise interval 保留原定义，不能改称 simultaneous、selection-adjusted 或 bootstrap interval。

输出 `ConditionAssociation`、连续效应矩阵、candidate/tested/support/reason/evaluability 视图，以及细胞成员和 batch 计数来源。Stage II 不重新搜索或挑选 states。

## 4. Stage III: Broad Response Landscape Organization

输入是 condition × reference-state 的连续 signed effect 和独立的候选、已检验及支持度标记。数值零、未入选、未检验和不可评估分别保存。统计和聚类复用已验收的 `broad_screening.analysis`、`sensitivity` 与 `landscape_analysis.core`。

流程包括：

1. candidate burden、enrichment/depletion、逐 state/逐 group concentration curve。
2. 连续效应的中心化 PCA，完整导出 variance、scores、loadings；不预设必须低维。
3. Pearson response-profile distance、average linkage 和冻结 cut 产生任意数量 response groups。conditions 的辅助层次聚类沿用 cosine 定义。
4. condition bootstrap、co-assignment、组匹配及阈值敏感性；stable core 使用已验收的 complete-link block 规则，boundary 保留。
5. 同 gene set 的不同 signed states 对照；连续、state-preserving binary、signed binary、gene-only OR 等表示的消融，保留共同可评估 pair domain。
6. gene-disjoint 与 overlapping-gene co-response，Pearson/Spearman、方向一致性和共享候选 conditions。
7. candidate burden 与 cell count 的描述性关联，以及支持度、不可评估范围和样本量上下文。
8. 结构标签、condition × group × direction sampling blocks、未选定的 `TriageInput` 池。

通用入口主 profile cohort 与旧 Broad 一致：有候选且所有输入 states 支持充分的 conditions；排除的 conditions 和分母显式记录。常量/不可评估 profile 不强行聚类。一个条件、没有足够变化的 states 或没有候选均允许输出空组；已有候选仍保留于 pool。

组代表是 response-correlation medoid；group activity 为成员 signed effects 的中位数，以 percentage points 表示。canonical association/matrix 的效应单位是 prevalence difference，转换显式乘 100。

stable core 仅表示内部重采样稳定性。没有稳定核心就报告空核心；没有 gene-disjoint 强相关也报告空集。组 ID 是当前运行局部编号，跨数据集同名不表示同一组。统计组统一标记 `NOT_ANNOTATED`，不自动命名为通路或生物程序。

对于极小合成数据，binary OR profile 可能恒定，common pair domain 为空。既有 kernel 产生的不可定义值在 JSON 中为 `null`，警告进入 quality audit 和 run manifest；不补成零或“表现良好”。

## 5. Generic Data Schema

契约集中在 [`clue_discovery/schemas`](../../clue_discovery/schemas/__init__.py)，采用可导出 JSON Schema 的 Pydantic 类型；dataset 对象与配置见 [`adapters/base.py`](../../clue_discovery/adapters/base.py)。

| 对象 | 含义与关键约束 |
|---|---|
| `ClueDiscoveryDataset` | canonical cell metadata、condition/control/batch/replicate、映射基因、detection matrix、provenance；metadata-only 不能冒充可分析矩阵 |
| `ReferenceState` | dataset/reference ID、任意阶 genes/states、reference population、prevalence、MFI/Gain/estimability/stability/qualification |
| `ReferenceCatalogue` | reference 集合、来源 dataset、兼容性定义及 hash；ID 唯一 |
| `ConditionAssociation` | condition + frozen signed reference + nonzero matched shift + support + evidence；target 可选，不等于 condition ID |
| `ResponseGroup` | 全部 signed members、medoid、core/boundary、方向/数量、内部稳定性与敏感性；无生物标签 |
| `CoResponseRelation` | 两个完整 reference IDs、gene overlap、response correlation、共享 conditions 和描述性 scope |
| `ConditionProfile` | condition type、样本量、候选负担、组活动、质量字段 |
| `StructuredClueLandscape` | 三阶段版本、groups/profiles/cores/boundaries/relations/strata/blocks/audits、annotation inputs、未选 pool 和 provenance |
| `TriageInput` | 一个条件下的一个 signed reference 及 shift；原始证据、group/core/co-response/contrast/support 上下文 |
| `SelectedCase` | 一个完整 `TriageInput` + 明确 selector/method/reason/time/provenance；group ID 单独不能构成 case |

顺序一致的 genes/states 不可替换为无符号 gene set。相同基因但不同 states 必须有不同 reference identity。序列化时所有不可定义数值写为 JSON `null`，不输出 NaN/Infinity。

## 6. Dataset Adapters and configuration

`TableDatasetAdapter` 接受 metadata CSV 和 counts CSV。metadata 各字段、control 标签和每个输入 gene 的映射全部显式配置；矩阵 cell IDs 必须与 metadata 一一对应。当前 detector 接受非负整数 counts，并使用 `count > 0`。其他 modality/detection 需新适配与方法校准，不能静默套用。

`ReplogleFrozenAdapter` 是应用专用的只读结果适配器：校验冻结 Broad 输入/输出 hashes，从 reference catalogue、scan statistics/candidates 和已验收的 module/core/triage tables 转换新 schema。它不重新计算 Day 6 检验、PCA、bootstrap、聚类或消融。

配置分为：

- `GLOBAL_METHOD_DEFAULTS`：保留 signed state、Stage II 禁止 state search、Stage III 不提升证据、NA 不等于零等原则。
- `DATASET_CALIBRATION`：字段、control、gene mapping、检测、min cells、matching、candidate budget、bootstrap、multiplicity 和 landscape 参数。
- `RUN_FROZEN_CONFIG`：运行开始前写入完整解析后的后端配置、随机种子、mode/stop。后端 preset 也是计算配置，不是跨数据集已经验证的阈值。

示例配置在 [`configs/clue_discovery`](../../configs/clue_discovery)。新的数据集至少须重新考虑检测定义、reference population、HVG/候选预算、estimability/support、batch/control matching、bootstrap 数量、multiple-testing family、聚类 cut、core 阈值与结构标签阈值。

三种模式：

```bash
# 同一新数据集发现 reference → shift → landscape
python -m clue_discovery.run --mode full \
  --dataset-config path/to/dataset_config.yaml --output path/to/new_run

# 使用已冻结 catalogue；先做兼容性检查，不重新找 states
python -m clue_discovery.run --mode transfer \
  --dataset-config path/to/transfer_config.yaml --output path/to/new_transfer

# 导入本地已验收 Day 6 结果；只读转换
python -m clue_discovery.run --mode landscape \
  --dataset-config configs/clue_discovery/replogle_day6_frozen.yaml \
  --output path/to/new_import
```

`--stop-after reference|perturbation_scan|landscape` 支持阶段终点；landscape-only 模式只接受最后一种。已有非空输出目录不覆盖。

Transfer 检查 modality、detection、mapping、cell context、condition/control 语义、batch/replicate、timepoint 和每个 state 可测性。modality/detection/matching 冲突直接拒绝；context/time/control/condition-type 差异需配置内预先写明 `transfer_compatibility` 理由并保存，不静默接受。理由是设计假设，不能代替实际方法或外部验证。

未来 Day 8 验证应使用冻结 reference transfer 并另行冻结 validation family/rules。本轮只读取已有 Day 8 汇总计数元数据作部分 smoke audit；没有 expression、cell/batch metadata，因而 `full_adapter_ready=false`，未做 Day 8 shift 或验证。

### Landscape-only external tables

使用 `adapter: table`，`paths` 指向 canonical `reference_catalogue` JSON、`condition_associations` JSONL、`effect_matrix`、`candidate_mask`、`tested_mask`、`reason_matrix`、`support_matrix` CSV，以及 `condition_metadata` CSV。矩阵首列是 condition ID，其余列必须为 catalogue 顺序的 reference IDs。效应是 prevalence difference，mask 为 0/1，support 为命中细胞数。condition metadata 至少有 `condition_id, condition_n`。所有矩阵必须相同轴；不根据行号猜对应关系。四阶 state 的 landscape-only round-trip 已在 synthetic 测试中覆盖。

## 7. Evidence Levels

| 等级 | 可以表达 | 不自动表示 |
|---|---|---|
| `REFERENCE_PATTERN` | reference population 中统计合格的联合状态 | condition effect 或机制 |
| `EXPLORATORY_ASSOCIATION` | 条件相关的探索性状态频率变化 | 已消除 selection bias、外部复现或因果机制 |
| `EXTERNALLY_VALIDATED_ASSOCIATION` | 经指定独立验证流程通过的关联 | 机制或调控方向成立 |
| `MECHANISTICALLY_INVESTIGATED` | 已完成有记录的机制调查 | 调查成功、机制证实或因果关系 |

Stage III 原样传递每个 association 的等级。成组、核心稳定、PCA 集中或 co-response 都不会升级证据。每阶段输出 `EVIDENCE_SCOPE.json`。Unified manifest 保存输入/代码/config/catalogue hashes、种子、阶段完成状态、输出 hashes、资源与警告。

## 8. Structured Clue Landscape

`structured_clue_landscape.json` 是统一结果；`triage_inputs.jsonl` 便于逐案例读取；`annotation_inputs.jsonl` 保留 group 的全部 signed states/core/representative；`deep_case_pool.json` 明确该池尚未选例。原冻结 Broad 的全分布、消融、PCA、样本量和其他质量产物以带 hash 的源文件引用保持可追溯。

追溯链为：case → association ID/原 JSONL 行及 hash → reference ID/原 catalogue → condition/batch counts → cell IDs/source metadata rows。generic full 模式还写入 control folds 和 condition/batch 的细胞成员表。sampling block 只组织冗余和覆盖，不将组内候选视为同一机制。

## 9. Interface to Triage

`TriageInput` 是 Clue Discovery 的终点数据对象，不是 prompt。后续可用人工、规则或经过评估的模型做 annotation/prioritization/selection。Jev 若采用，只在这一可替换层使用；不参加 reference 定义、p-value、聚类或 core 的计算。

Triage 应保留方向、完整 signed state、support、sample-size dependence、core/boundary 和不同组上下文。标签不是一个黑箱优先级分数。既有 Day 6 分层结果原样导入；generic 层提供代表、core/boundary、enrichment/depletion、cross-group、signed contrast、disjoint co-response、高效应/高支持及样本量上下文标签，不实际选赢家。

## 10. Interface to Deep Investigation

`SelectedCase` 明确一个 condition + signed state + shift，group/core 只是背景。现有 `clue_from_selected_case()` / `initialize_selected_case()` 保留 matched-control estimand、逐 batch counts、selected-family Holm 名称和原 interval 类型；`q_value_shift`、`bootstrap` 和旧 `support` 留空。Reference 各 fold 的证据、缺失值及 group/core/context 原样保存在 `clue.upstream_context`，完整 SelectedCase 和原 association 保存在不可变 source payload。

2026-09-28 新增 [pilot preparation 协议与命令](../../triage/README.md)：从 6,129 个输入按冻结规则选 A/B/C/D，实例化为 4 个 revision-1 Case Files 后停止。规则在已有 Day6 结果之后、首次 pilot 排序之前冻结；不称为 discovery 的事前注册。这里没有运行 Explorer/Investigator/Critic，没有机制问题、假说、预测、Evidence Queue、Agent EvidenceRecords、审计或最终 case report。Case 状态为 `clue_ready / next_actor none`；准备流程结束不等于 Critic STOP。

Codex builds the system; Agents conduct the investigation. Mechanistic question、competing hypotheses 和 discriminating predictions 由 Explorer 自己提出；Investigator 自己决定取证问题和工具；Critic 自己完成 hypothesis audit、claim-level audit、failure attribution 和路由。Deep 的调查结论不能反向覆盖 discovery 或 group assignment；如需 feedback，必须新版本、显式 manifest 和独立评估。

`align_landscapes` 仅保留 request/result 契约，调用会显式 `NotImplementedError`。跨数据集应依据完整 signed state、overlap 和 response profile 对齐，不能依据 M01 等局部编号。

## 11. Limitations and generality

**Software generality**：已实现可配置 adapters、三个运行模式、任意阶 state 契约、synthetic 正/负例和 canonical table round-trip；不是对所有格式的开箱即用支持。当前 table adapter 面向小型/已提取 CSV 的 dense 数据，大型原始矩阵仍需内存受控的专用 adapter。

**Methodological generality**：三阶段问题分解适用于具备合理 reference、conditions、可比检测与充分支持的数据，但原三阶统计后端和参数需要数据集校准，transfer 的可比性也需设计论证。

**Empirical generality**：当前真实数据结果仍来自既有 Replogle Day 6。synthetic 和 Day 8 汇总元数据 smoke 不能证明跨细胞类型、平台或数据集的生物学有效性。未开展新的真实数据集分析。

旧 `verify_frozen_engine()` 是整目录文件清单相等检查，新增接口文件会导致不相等；其 packaging 哈希在本轮前亦已不同。为保留历史审计语义，本轮没有改写该 guard 或 frozen manifest。新回归单独检查所有原统计源文件与冻结结果的逐文件 hashes，并报告新增接口/包装配置与统计 kernel 的区别；不宣称旧 whole-inventory 测试通过。

当前应用结果另见 [Day 6 application](JURE_Day6_Application.md)；本轮完成与验证证据见 integration report (historical source, not bundled: `../../CLUE_DISCOVERY_INTEGRATION_REPORT.md`)。
