# Shared Case File v0.1.1

Case File = **shared structured investigation state**。围绕一条 perturbation-associated clue，保存机制问题、假设及版本、预测、待调查问题、已有证据、证据解释、缺口、矛盾和外部决策。

Evidence Queue = Case File 中的 pending evidence questions；Evidence Records = 已获得证据；Investigation History = append-only audit trail。模块不生成假设或问题，不执行 LLM、GRN、检索或 Agent reasoning，也不选择工具、下一位 Agent 或停止条件。

## 数据契约

| 区域 | 内容和边界 |
|---|---|
| `metadata` | Case ID、schema `0.1.1`（兼容读取 `0.1.0`）、单调递增 `case_revision`、带时区时间、可选数据集/细胞背景 |
| `clue` | 冻结的上游观察、统计阶段、来源及原始 payload；不解释为因果机制 |
| `mechanistic_question` | 当前问题与包含旧文本、新文本、理由、作者的修订记录 |
| `hypotheses` | 稳定 hypothesis ID、当前版本、完整版本序列、指向具体版本的 predictions |
| `evidence_questions` | 预测关联、跟进问题 lineage、screening/verification depth、可选结构化 query hint 和执行状态 |
| `evidence_records` | 实际结果、独立的 quality/directness/context 维度、negative evidence 类型、fingerprint、多问题关联和不可覆盖的 provenance |
| `evidence_assessments` | 对指定假设版本/预测的 supports、challenges、neutral 或 inconclusive 解释 |
| `evidence_gaps` / `contradictions` | 尚缺证据、证据冲突及记录状态 |
| `action_state` | 外部控制器明确提交的阶段、next actor、selected question、停止理由 |
| `investigation_history` | 有序事件、作者、理由及可重放的结构化 before/after 变更 |

每类实体有唯一 ID；引用在整个 Case 内验证，拒绝悬空引用、重复 ID、错误版本归属和无效状态。Pydantic 模型冻结，集合使用 tuple；`FrozenJSON` 内部保存规范 JSON，读取嵌套值返回副本。读到的 Case 是快照，所有持久化变更都通过 `CaseStore` 命令。

`HypothesisRecord.current_revision` 返回当前版本。Explorer 修改机制内容会生成新 revision，并以 `proposed` 开始；旧 revision、prediction 和 assessment 保留。Critic 显式修改指定版本的 status，变化记录在 audit 中；本模块不判断哪个 verdict 合理。EvidenceRecord 修正通过新增记录并填写 `supersedes_evidence_id`，不覆盖旧来源。

`EvidenceAssessment` 取代原草案 EvidenceRecord 上的 supports/challenges/neutral ID 数组，保留作者与理由，允许 Investigator 和 Critic 留下不同解释。检索没有结果可记录 inconclusive 和 gap；不会自动变成 challenges。没有综合评分。

## 对接 Clue Discovery

`clue_from_v01()`、`clue_from_v02()` 接受 row dict 或 pandas Series，也支持 CSV 中 JSON 编码的 genes/states。必须提供 `source_run_id` 和 `source_artifact`；只拷贝上游输出，不重新计算统计量。

- v0.1：`legacy_control` / `legacy_perturbation` 保存各组 MFI/null evidence。
- v0.2：`reference_evidence.discovery` / `.validation` 分别保存 reference MFI；`perturbation_shift` 保存 reserved NT 与 perturbation 的 frequency/count/Delta/q-value/CI。不会创建 perturbation MFI，也不会把 reference MFI 改称 test-control MFI。
- v0.2 可额外传 `catalogue=FrozenCatalogue` 或已保存的 `{"payload": ..., "sha256": ...}`，校验 catalogue 身份与 pattern 后拷贝 reference null/bootstrap evidence。
- `None` 表示源输出缺失或未计算；bootstrap 的 MFI、enrichment 和 shift 指标分别存储。源 payload 保留原始缺失信息及 metadata。held-out reference validation 不改标为 biological replication。
- `pattern.genes/states` 是机器标识，`pattern_string` 用于展示；1/0 表示 detected/undetected，不表示相对对照上调/下调。

```python
from jure.casefile import CaseStore, MechanisticQuestion, clue_from_v02

clue = clue_from_v02(
    shifts.shifts.iloc[0],
    source_run_id="run_20260927",
    source_artifact="outputs/run/perturbation_state_shifts.csv",
    source_metadata=shifts.metadata,
    catalogue=reference.catalogue,
)
with CaseStore("outputs/investigations.sqlite") as store:
    case = store.create_case_from_clue(clue, cell_context="K562")
    case = store.add_mechanistic_question(
        case.metadata.case_id,
        MechanisticQuestion(question_text="What might explain this state shift?",
                            derived_from_clue_id=case.clue.clue_id),
        actor="explorer", expected_revision=case.metadata.case_revision,
    )
    store.export_case(case.metadata.case_id, "outputs/my_case")
```

每次创建生成独立 case ID；调用方可显式提供稳定 case ID，重复创建会被拒绝，不静默合并调查。源 clue ID 由 adapter 基于来源身份确定。同一 clue 可以用于多个独立 case。

## 写入与权限

所有变更返回新的 `CaseFile`，并要求 `actor` 和 `expected_revision`。角色由可信调用端传入；这不是用户认证，也不能阻止持有 SQLite 文件写权限的人篡改数据库。

| Actor | 可调用的写入 |
|---|---|
| `explorer` | `add_mechanistic_question`、`revise_mechanistic_question`、`add_hypothesis`、`update_hypothesis` 的内容修订、`add_prediction`、`add_evidence_question` |
| `investigator` | `update_evidence_question_status` / `mark_selected` / `mark_answered` / `mark_unresolved`、`update_prediction_status`、`add_evidence_record` |
| `investigator` / `critic` | `add_evidence_assessment`、`update_evidence_gap_status` |
| 三个 Agent | `add_evidence_gap`、`append_history_event` 注记 |
| `critic` | `update_hypothesis(..., status=..., reason=...)`、`add_contradiction`、`update_contradiction_status` |
| `controller` | `create_case_from_clue`、`set_action_state`、审计注记 |
| `evidence_investigator` | 受控问题状态/优先级更新；新增证据、assessment、gap、open contradiction 和有完整 lineage 的 follow-up；更新 gap 状态；追加 question→evidence link；移交 `critique_needed` |
| `human` | `manually_prioritize_question`、`manually_cancel_question`、`manually_add_evidence_question`；所有操作写入人工审计 |

`system` 只用于初始化。新 EvidenceQuestion 必须是 pending，新 Prediction 必须是 untested，新 EvidenceGap 必须是 open，防止通过创建接口绕过执行状态的写入权限。Question 状态变更不自动生成证据，也不自动裁决假设。`selected_question_id` 若非空，只能指向 selected/in_progress/partially_answered 问题；问题退出这些状态会自动清空该引用，阶段和 next actor 仍由控制器决定。stopped 状态必须有 stop_reason，且 next actor 为 none、无 selected question；其他阶段不能保留 stop_reason。这里只验证结构，未实现科学 workflow 转换图。

假设/预测/证据等新增对象可以使用模型默认生成的 ID。`add_hypothesis` 接收 title、mechanism_statement、mechanism_type 及可选 derived_from 等关键字；其他 `add_*` 接收对应模型。`derived_from` 使用 `ObjectReference(object_type=..., object_id=...)`。自由文本 reasoning 如需保存，可作为有对象引用的审计注记，不修改 clue。

新 `evidence_investigator` actor 保留独立边界：不能修改 clue、mechanistic question、hypothesis 或 prediction，不能设置最终 hypothesis verdict、解决 contradiction 或停止 Case。旧 `investigator` actor 保留 v0.1.0 接口兼容；新 Agent 使用完整名称。新 actor 的问题执行路径为 `pending → selected → in_progress → answered/partially_answered/unresolved`，失败恢复允许回到 `pending`。已回答或取消的问题不重新进入执行。其路由仅允许 evidence 阶段与 `critique_needed → critic`。

跟进问题必须记录 `derived_from_question_ids` 和 `derived_from_evidence_ids`，校验全部引用并拒绝 question lineage 环。`EvidenceRecord.question_id` 保留主问题；`related_question_ids` 保存新增关系，`question_ids` 属性返回两者合并结果。`link_evidence_to_question` 只追加关系，不复制或覆盖证据正文。`query_spec` 是不可变 JSON 查询提示，实际工具选择属于 Investigator。支持/挑战关系继续使用 `EvidenceAssessment`。

## 持久化与恢复

SQLite 是唯一权威数据源，`cases` 保存当前快照，`events` 保存事件。每次写入在 `BEGIN IMMEDIATE` 内核对版本、验证新状态并一起提交；中途失败全部回滚。数据库触发器拒绝修改、删除或替换已有审计事件。读取时对照 snapshot、事件表及重放结果，发现不一致则拒绝加载。

并发客户端须各用一个 `CaseStore` 实例。过期 `expected_revision` 抛出 `RevisionConflict`；调用方应重新读取并重新判断自己的操作，不能自动把旧整份快照覆盖回去。SQLite 保证本地事务一致性，本版不提供跨机器协作或自动冲突合并。

`with store.atomic(case_id, expected_revision=revision):` 可将多个现有命令组合成一次整体提交。各命令仍检查角色权限、版本并记录独立事件，任一步骤失败时整批回滚。模型生成、网络请求等耗时工作应放在事务外；进入时的版本检查用于拒绝过期结果。该能力不增加新的共享状态或科学决策规则。

`temporary.import_case(case)` 可将已验证的快照及原始事件导入空 store，重复 Case ID 被拒绝，不生成伪造事件。工具调用和状态更新可在这个独立 store 中运行，然后用 `store.commit_investigator_case(case_id, staged_case, expected_revision=revision)` 原子提交。提交逐事件检查原 history 前缀、actor、状态转换和写入白名单；旧 evidence 正文与 protected sections 不可修改，旧 question 只允许状态和优先级变更。任何并发 revision、非法修改或写入失败都使整个增量回滚。

`store.export_case(case_id, directory)` 导出：

- `case_file.json` / `case_file.yaml`：带完整 history 和 revision 的当前快照，各文件单独原子替换。
- `case_history.jsonl`：验证已有内容是该 Case 的审计前缀后，只追加缺失事件；重复导出不会重复追加。

这三份文件是可重建的导出视图，不是一个跨文件事务。导出中断后，数据库不受影响；重新导出可以更新快照和补齐完整事件。若 JSONL 出现截断行或内容被改写，明确报错，应从数据库导出到新目录，保留旧文件供检查。不要编辑导出 JSON/YAML 后写回权威状态。

`save_case(case, path)` / `load_case(path)` 用于 JSON/YAML 快照 round-trip，会验证 schema、引用和审计重放；不会导入或替换数据库中的 case。`validate_case` 验证模型和关系；`case_json_schema()` 提供通用 JSON Schema，跨实体引用仍由 Python validator 检查。只接受 `0.1.0` 与 `0.1.1`：旧快照读取时补齐新增字段的默认值，原 history JSON 保持不变；回放比较仅规范化这些已知默认字段。下一次命令将 schema version 升至 `0.1.1` 并在新审计事件记录版本变化。

## Demo 与验证

```bash
python -m jure.casefile.demo --output outputs/shared_case_file_demo
python -m pytest -q tests/test_casefile_models.py tests/test_casefile_adapters.py tests/test_casefile_store.py tests/test_casefile_investigator.py
```

Demo 使用显式提供的 synthetic row 和手写记录，演示角色接口与导出，不执行 discovery、Agent reasoning 或证据获取。测试另有真实 v0.2 synthetic pipeline 的适配检查，覆盖冻结、引用、版本、权限、失效并发写入、事务回滚、审计及序列化。

## SelectedCase pilot adapter

`clue_from_selected_case()` / `initialize_selected_case()` 接受已由 `VerifiedPilotSource` 核验的规则选择结果。与旧 v0.1/v0.2 adapter 并存；新 `MatchedControlShiftEvidence` 保留 batch-weighted NT estimand、逐 batch counts、原始 selected-family Holm 和 nominal pointwise interval。旧 q-value/bootstrap/support 不作语义替换。

`ClueRecord.upstream_context` 保存各 fold 的完整 reference evidence、缺失值、group/core、sample-size context、关系和 Day8 状态；不包含机制解释。旧快照读取时仅补齐该字段为 null，原审计载荷保持不变。Schema 保持 additive `0.1.1` 兼容；旧字段不改义。

Initializer 只通过 `CaseStore.create_case_from_clue` 创建 revision-1 状态，不调用 Agent、生成问题或路由。完整规则和命令见 [Triage pilot preparation](../../triage/README.md)。
