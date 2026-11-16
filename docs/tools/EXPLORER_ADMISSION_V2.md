# Explorer admission v2：恢复三 Agent 主顺序

正式主流程：`Explorer → Machine / Completeness Gate → Investigator → Critic(C1 → C2)`。
本次只完成代码与离线验证，没有重新运行真实 Case A，也没有解冻 B/C/D。

## 入口职责

| 层 | 决定 | 边界 |
| --- | --- | --- |
| Machine | 不合法则拒绝 | schema、ID/reference、lineage、必需字段、类型、真实存在的 capability ID |
| Completeness | 缺项则返回 Explorer | competing hypotheses、prediction、必需 comparison/contrast、expectation 和 outcome branches |
| Scientific audit flags | 允许交给 Investigator | 新 mediator、因果措辞、可观测性、区分度等待审问题 |

结构检查不证明科学有效性。程序不补写 hypothesis、prediction 或 outcome；新实体也不因未出现在原始 Clue 中而自动被拒绝。成功 decision 为 `ADMIT_TO_INVESTIGATOR`。

## 调查与审查

Investigator context 包含 `proposal_admission.audit_flags`。flags 是未核实的提示，不是证据或判决；Investigator 根据假说与预测选择问题、工具和顺序。

v2 proposal 必须先有完成的 Investigator round，并且当前 route 指向 Critic，才能运行 Critic。完成调查可以包含工具不可用、无结果等限制，不强制捏造 EvidenceRecord。

Critic 的 C1 context 同时包含 hypotheses、已取得的 EvidenceRecords、provenance 和 gaps。C1 不通过则跳过 C2，按现有预算与路由规则处理 hypothesis issue；C1 通过才进行 claim decomposition、C2 和 mechanism synthesis，之后决定追加取证或 STOP。

Explorer 修订后同样先交给 Investigator。调查后的 Critic 先针对原 defect 做 revision acceptance；`RESOLVED` 才计为成功修订，并在同一次 Critic 调用中继续完整 C1/C2。未解决则返回 Explorer 或在固定预算耗尽时 STOP。验收不替代 C1，也不增加预算。

## Critic 引用修复

`attribute_failure` 使用按实际 context 绑定的 typed reference catalog 和 response schema：hypothesis、claim、EvidenceRecord、gap 各自只能引用对应集合。EvidenceRecord 集合为空时，`related_evidence_ids` 只能为 `[]`。

检验依据对象类型与实际成员关系，不依据 ID 前缀。原 Case A 中把 `Q1.1/Q2.1/Q3.1` 放入 `related_evidence_ids` 的输出仍会被拒绝。程序不删链接、不把 question 转为 evidence，也不改写科学内容。

错误在模型 transport 边界被发现，并进入已有、有上限的 schema retry；反馈包含字段、对象类型和合法 ID。只有模型能返回修正的 attribution。`schema_retries=0` 仍然不重试，CaseStore 的最终硬校验保留。

## 版本与后续运行

启用方式仍是 `ExplorerConfig(protocol_v3=True, validation_policy="three_layer")`，新提交标记 `explorer-admission-v2`。初始 proposal 使用 content adapter；reframe 仍使用现有 typed contract，不能声称已消除全部 revision ID/lineage 风险。

`configs/explorer_admission_v2.json` 是暂停的接口描述，不是可直接启动的 pilot 配置。模型偏好保留 `glm-4.7-flash`，不自动升级昂贵模型。

历史 v1 报告、CaseFile 与预算不改写。run_018 的 A 仍有 3 个已提交假说、0 个 EvidenceRecord，停在旧流程的 Critic 引用失败处。它不是新流程验证成功的案件。未来续跑需显式迁移其路由/版本并保留历史和已耗预算，不能直接运行旧 recovery 配置。

runtime freeze 记录新流程与 E/I/C 接口文本；跨不同接口的旧错误保留在历史中，不再作为当前模型的活动修正指令。

### 已授权的 Case A 续跑

2026-09-28 用户授权按恢复后的流程运行 A。`configs/agent_pilot_glm47_admission_v2_a.json` 指向 run_018 的精确 checkpoint，继承 12 次调用、原科学内容和所有已耗预算。运行目录为 `outputs/agent_pilot_v1_20260928/run_019_glm47_admission_v2_a`。

迁移由 `jure/runtime/admission_migration.py` 在新库中完成：仅适用于已经通过 v1 gate、尚未调查且无已提交 Critic 审查的 initial proposal。追加 controller annotation（`controller_event=PROTOCOL_ADMISSION_MIGRATED`）并恢复 Investigator route，保留旧事件，不伪造 Explorer/Critic 科学决定。旧 checkpoint 不写入。三个已有假说不重新生成，下一次真实 Agent 调用是 Investigator。

这是保留历史的技术续跑；新顺序的执行结果以该目录的实际 trace 和完成报告为准，不能因迁移成功就宣称 C1/C2 已通过。

## 离线验证

回放使用已有 14 份输出，没有模型或真实证据调用。adapter 5/7 可以提交并进入 Investigator；E05 缺 neutral outcome、E06 缺 H2/H4 contrast，仍拒绝。legacy 0/7。原 271 个来源文件哈希不变。

合成测试覆盖先调查后审查、C1 拒绝时跳过 C2、调查后 revision acceptance、flags 传递和引用错误的有界反馈。合成结果仅验证工程控制流，不能当作真实 C1/C2 成功率或机制调查结论。
