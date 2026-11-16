# Deterministic pilot preparation

Clue Discovery ends at `StructuredClueLandscape` / `TriageInput`. Stage III remains deterministic landscape organization. Optional Triage selects a concrete condition + signed reference + shift; a group cannot replace the case identity.

`Codex builds the system; Agents conduct the investigation.` 本模块只产出 4 个 `SelectedCase` 和 4 个 Initial Case Files，不调用 reasoning backend 或任何 Investigator 工具。

## 冻结选择规则

协议：[pilot_selection_v1.json](../configs/pilot_selection_v1.json)；冻结记录：[pilot_selection_v1.freeze.json](../configs/pilot_selection_v1.freeze.json)。这次冻结发生在已有 Day6 结果之后、首次 pilot 排序之前。它是 pilot 选择的事前固定规则，不是 discovery 的事前注册，也不声称数据在制定规则前从未被查看。

沿用已有 Broad 阈值：condition cells ≥300，|matched Δ|≥0.20；沿用 scan support gates：每个占用 batch 的 NT ≥20、effective matched NT ≥100、directional support ≥10、selected-family Holm exploratory ≤0.05。保留 `EXPLORATORY_ASSOCIATION` 和 `NOT_PERFORMED`。

| 顺序 | 类别 | 候选条件 |
|---|---|---|
| A | stable-core representative | M02/M03/M04 的 stable core 成员；方向不限 |
| B | strong enrichment | Δ>0 |
| C | strong depletion | Δ<0 |
| D | structural interest | 依次优先 signed-state contrast、gene-disjoint correlated context、cross-module |

A 的 representative 表示本次 pilot 的代表案例，不声称所选 reference 是 response-correlation medoid；原 group medoid ID 另行保留。M02/M03/M04 是这次 Day6 运行的局部组号。

每个类别内按 |Δ| 降序、condition cells 降序、directional support 降序，再按 condition ID、完整 signed reference ID、case ID 字典序排序。D 的 structural tier 优先于这些排序。Depletion support 使用 perturbation 占用 batches 内的 NT hits 总和；enrichment 使用 perturbation hits。

按 A→B→C→D 贪心选择。与已选 case 的 condition ID、reference ID 或 sampling block ID 任一相同则排除；每个候选只能入选一次。这个去重规则是抽样约束，不宣称不同病例生物学独立。D 的 relation 必须包含当前 reference，且当前 condition 属于该 relation 的 shared candidate conditions；不能只靠 reference 层面的关系 ID。Cross-module 使用冻结的原始标签。

任何类别为空就 `FAIL_CLOSED`，不改阈值、规则或补入其他类别；四类全部成功后才发布输出目录。每次运行都核验冻结协议哈希。

## 运行与输出

```bash
.venv/bin/python -m triage.pilot \
  --source-run outputs/integration_tests/adapter_smoke/replogle_frozen \
  --protocol configs/pilot_selection_v1.json \
  --output outputs/pilot_preparation_v1_20260928
```

来源目录名称中有 `adapter_smoke`，但它是已经验收的 6,129 条真实 Day6 结果只读转换；没有重跑统计，也没有使用 synthetic case 代替真实数据。输出目录已存在时拒绝覆盖；复现请使用新的目录。

正式产物：preparation report (historical source, not bundled: `../outputs/pilot_preparation_v1_20260928/PREPARATION_REPORT.md`)、initial case index (historical source, not bundled: `../outputs/pilot_preparation_v1_20260928/initial_case_index.json`)。

- `protocol.json` / `protocol.freeze.json`：实际执行规则及冻结时间/哈希。
- `candidate_eligibility.csv`：全部 6,129 个输入的资格和排除原因。
- `selection_trace.json`：每个类别的全部排名、平分键、去重理由和赢家。
- `selected_cases.jsonl`：4 个完整 `SelectedCase`，含来源行和规则 provenance。
- `case_store.sqlite`：权威初始状态。
- `initial_cases/A`–`D`：各自的 `selected_case.json`、`case_file.json`、`case_file.yaml`、`case_history.jsonl`。
- `integrity_audit.json` / `preparation_manifest.json`：来源哈希、代码哈希、输出哈希与校验范围。

同一协议和输入重复运行应得到相同 case identities、事实和排名；创建时间及审计 event ID 是每次运行独立的，不声称 SQLite 字节一致。

## CaseFile adapter 与停止边界

`jure.casefile.clue_from_selected_case()`、`initialize_selected_case()` 使用 `VerifiedPilotSource`，检查来源文件哈希、候选原始 JSONL 行、catalogue、全部 signed identities、原始 support/统计字段、batch arithmetic 和结构上下文。

`MatchedControlShiftEvidence` 单独声明 matched NT 的加权频率定义，以及 pooled NT count 的描述性作用；保留 Holm 名称、family size 和 nominal pointwise interval，不塞进旧 q-value/bootstrap 字段。`matched_nt_effective_n` 等只从已有 batch counts 验算，没有重做 hypothesis test。Scan patterns digest、catalogue payload digest、文件 SHA-256 分别保存和校验。

每个 CaseFile 都是 revision 1，只有一条 `controller / case.created` 事件，状态为 `clue_ready / next_actor none`。Mechanistic question 为 null；hypotheses、predictions、Evidence Queue、EvidenceRecords、claims、Critic audits 和 final reports 均为空。准备结束不是 Critic 的科学 STOP，也不是 `EVIDENCE_SUFFICIENT` 或 `EVIDENCE_LIMITED`。

后续运行必须由 JURE 的 Explorer → Investigator → Critic 自己生成调查内容；本命令没有 Agent launch 开关，不安排 GRN/statistics/literature 顺序，不生成调查报告。

```bash
.venv/bin/python -m pytest -q tests/test_pilot_preparation.py
```
