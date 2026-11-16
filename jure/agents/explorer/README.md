# Mechanism Explorer v0.1

Explorer 将一个现有 Case File 的 clue 转成机制问题、竞争假说、区分性预测和初始取证问题。它只管理假说空间，不检索证据、不执行统计、不裁决假说，也不调用下一位 Agent。

## 使用

```python
from jure.casefile import CaseStore
from jure.agents.explorer import MechanismExplorer, MockExplorerBackend
from jure.agents.explorer.demo import synthetic_clue, initial_output

with CaseStore("outputs/explorer.sqlite") as store:
    case = store.create_case_from_clue(synthetic_clue(), cell_context="K562")
    explorer = MechanismExplorer(MockExplorerBackend([initial_output(case)]))
    result = explorer.run(store, case.metadata.case_id,
                          artifact_dir="outputs/explorer_runs")
    assert result.success, result.validation_errors
    updated = store.load_case(case.metadata.case_id)
    store.export_case(case.metadata.case_id, "outputs/explorer_case")
```

`python -m jure.agents.explorer.demo --output outputs/mechanism_explorer_demo` 运行三个假说的离线 synthetic demo。Mock 使用预先编写的响应，只验证执行与持久化契约，不代表已完成真实模型的科学质量评测。

## Backend 与临时输出

`ExplorerBackend.generate_initial(context, *, feedback=())` 与 `generate_reframe` 返回 JSON 对象或 JSON 字符串。核心代码不依赖模型厂商、SDK 或模型名称。

`JSONExplorerBackend(transport)` 将指令、上下文、输出 JSON Schema 和上轮校验错误传给调用方注入的 transport。transport 负责连接实际模型、设置超时，并将模型的结构化 JSON 响应返回。Explorer 不提供网络／检索工具，也不向 transport 提供 CaseStore。没有配置 transport 时，不会调用真实服务。

`ExplorerOutput` 是未经信任的临时写入提案，不是第二套共享状态。它包括观察陈述、机制问题、假说与结构描述、预测、取证问题和逐对假说差异说明。所有模型拒绝未知字段；`EvidenceRecord`、评分、tool 选择、路由和 final verdict 不属于输出契约。正式内容仅通过现有 `jure.casefile` API 写入。

默认 initial 生成 2–4 个假说；机制类别不是固定模板。`structure` 明确描述因果结构、直接性、细胞组成解释、条件依赖和候选边，用于基本去重；`contrasts` 要求 backend 解释每对假说的实质区别。每个新建／修订假说必须带削弱条件和至少一个能区分其他假说的预测，每个预测应产生有 ID 关联的取证问题。

`interpret_observation(case)` 直接使用 clue 的频率、Delta、统计阶段、原始证据和编码含义生成 observational 文本。上下文给出该文本，backend 必须原样回填。原始统计缺失就保持缺失，不重新计算 MFI，不从 bootstrap 或 reference validation 推断生物学重复。具体机制仍只能作为待检验假说；新命名 regulator/pathway 必须有 Case 中的来源可追溯。

## Reframe

```python
result = explorer.run(
    store, case_id, mode="reframe",
    reframe_reason="已有假说不能解释新增的 observation D。",
    artifact_dir="outputs/explorer_runs",
)
```

reframe 需要已存在的机制问题、假说和非空理由。它可以只新增或修订一个假说，不要求每轮重新生成 2–4 个；每轮变更数量受 `max_hypotheses` 限制，历史假说数量不会触发删除。新假说使用新的 ID，`operation="add"`；修订使用现有 ID，`operation="revise"` 和具体 `reason`。`derived_from_clue_id` 必须匹配当前 clue；reframe 的 lineage 还需引用已有假说、证据、缺口或矛盾等调查对象。

Case File 的 `derived_from` 保存 clue／调查对象引用，`supersedes_revision_id` 串联假说版本。新预测绑定写入后的当前版本；旧预测、旧取证问题、旧证据与旧 verdict 原样保留。修订版本从 `proposed` 开始，不自动改变旧版本裁决。reframe 不删除、取消或重新回答既有取证问题。

## 校验、上下文与运行记录

`validate_explorer_output` 检查数量、ID、lineage、结构重复、预测可检验性、区分对象、削弱条件和编码／因果陈述边界。backend 的逐对差异说明是自查材料，不是独立科学证据。结构与语言检查是 v0.1 的启发式防线，不能保证识别所有自然语言同义表达、所有无依据机制或证明一个预测确实具有实验区分力；这些仍需真实 backend 评测与人工抽查。

`build_explorer_context` 的 initial 输入不包含 audit history 或完整 source payload；reframe 只补充当前假说、相关预测与证据、缺口、矛盾和理由。上下文超过预算会明确失败，不静默截掉证据。默认上下文和响应上限均为 60,000 字符，最多重试 2 次（共 3 次尝试）；超时由 transport 实施。

每次调用返回 `ExplorerRunResult`。`success` 表示最终输出是否通过校验并成功提交；`validation_errors` 保留之前失败尝试，因此有限重试恢复后也可能非空。失败不留下部分机制问题、假说或预测，但会保留开始／失败审计记录。

SQLite history 是权威运行记录：`summary` 和 `metadata.explorer_event` 标识 `EXPLORER_STARTED`、`OBSERVATION_INTERPRETED`、`HYPOTHESIS_CREATED`／`HYPOTHESIS_REVISED`、`PREDICTION_CREATED`、`EVIDENCE_QUESTION_CREATED`、`EXPLORER_COMPLETED`／`EXPLORER_FAILED` 等事件。完成／失败事件的 `metadata.run_artifact` 保存完整返回结果。结构描述附在对应假说版本的审计 metadata 中。传入 `artifact_dir` 时额外导出独立 JSON；导出失败不撤销已经提交的 Case File，返回 warning。

模型生成发生在数据库事务外。持久化使用 `CaseStore.atomic` 组合现有角色 API，按读取版本检查并整体提交。并发更新导致版本冲突时，本轮结果失败，不用旧推理覆盖新状态。成功后由可信执行层使用 controller 接口设置 `evidence_needed → investigator`；不会启动 Investigator。其他 Agent 的权限没有放宽。

## 验证

```bash
python -m pytest -q tests/test_explorer_agent.py tests/test_explorer_validation.py tests/test_explorer_contract.py
```

测试覆盖 initial、因果过度解释、重复假说、空泛预测、问题 lineage、越权输出、reframe 与 clue 不变，以及有限重试、上下文限制、整体回滚和并发冲突。
