# Explorer admission v1：三层职责与 C1 入口

> 历史版本：其前置 C1 顺序已由 [v2](EXPLORER_ADMISSION_V2.md) 纠正。以下保留当时实现与验证记录，不代表当前正式流程。

状态：实现与离线验证。所有真实模型调用和 A/B/C/D 调查继续暂停。

## 行为

`Explorer → Machine Gate → Completeness Gate → 带 flags 的 Critic C1 → Investigator → Critic C1/C2`。

| 检查层 | 结果 | 示例 |
| --- | --- | --- |
| Machine | `REJECT` | schema/type、ID/reference、lineage、不可变观察、未知 capability、互相矛盾的 outcome labels |
| Completeness | `RETURN_TO_EXPLORER` | 缺 prediction/question/contrast/expectation、缺 neutral 或 directional outcome、缺 capability mapping |
| Scientific audit | `ADMIT_TO_C1`，附 flags | 因果措辞、新实体、可观测性、机制区分度、重复 expectation prose、已登记但当前不可用的能力 |

这些结果在检查发生处直接标记分类，不通过解析错误文字决定是否放行。程序不生成、补写或删除假说、预测、comparison targets 或 outcome branches。缺少必填字段仍是机器合同错误；已提供集合中的设计缺项归 completeness。

未采用“每个问题必须区分其全部 targets 的所有两两组合”这一额外规则。仍要求整个工作假说集合中涉及新提案/修订的 pair contrast、每个 target 的 expectation、至少一个 directional outcome 和一个 neutral outcome。语义上是否真正可区分由 C1 判断。

## 持久化与路由

Explorer 每次尝试在 `admission_checks` 记录 decision 和 findings。成功提交在同一事务中追加 `PROPOSAL_ADMITTED`，记录 policy version、source revision、proposal hash、hypothesis revision IDs 和 audit flags。失败只留下诊断，不写入半份 proposal。

Critic context 携带这一记录及事件 ID；版本化系统指令明确 flags 不是证据、不是已成立缺陷，也不是自动通过/拒绝依据。新具名 mediator 可以作为待验证假说，但不能被当作已知事实。

新流程初始提交后固定交给 C1。C1 是否通过、是否要求修订仍由 Critic 输出决定。首次取证前不执行 claim decomposition/C2/synthesis，不把设计审查计为 evidence audit。C1 通过后仍由 Critic 进行 failure attribution 与 routing；预算和 STOP 规则继续有效。

Investigator 验证最近 proposal 对应的 C1 pass 和当前 Investigator route，直接调用也不能绕过。修订的 targeted acceptance 只解决指定 defects；`RESOLVED` 后先回 Critic 做完整 C1，再决定取证。没有伪造一个 route_to=critic 的科学路由记录；该中间步骤记录为 `REVISION_ACCEPTED_C1_PENDING`。

## 接口与启用

显式设置 `ExplorerConfig(protocol_v3=True, validation_policy="three_layer")`。旧配置默认 `legacy`，继续将旧诊断全部视为阻断；历史输入、输出、配置均未改写。

Pilot runtime 在新 policy 下，initial 使用 deterministic content adapter，reframe 显式保留现有 typed contract；三层检查同时覆盖两种模式。**当前 adapter 仍只装配 initial proposal，尚未实现 content-only reframe adapter。** 模型仍须遵守 revision ID/lineage 合同，不能把初始接口改进表述为已消除所有 revision 工程风险。

共享持久化 comparison schema 不再用“expectation 文字完全相同”判定科学不合格。该项由 admission 产生 `DISCRIMINATION_UNCLEAR`；旧 Explorer proposal parser 保留原拒绝规则。状态/引用/neutral label 等硬约束保留。

`configs/explorer_admission_v1.json` 是暂停状态的接口与模型配置，不是可直接运行的 pilot 配置。没有生成自动重启 A 的命令，也没有重置其已用调用、阶段尝试或科学预算。未来运行需明确技术恢复或新 evaluation 的预算口径。

## 模型费用偏好

后续准备采用 `configs/agent_runtime_glm47_flash.json`，模型 `glm-4.7-flash`；没有昂贵模型回退。智谱[官方发布公告](https://www.zhipuai.cn/zh/news/148)标明免费调用，[官方模型文档](https://docs.bigmodel.cn/cn/guide/models/free/glm-4.7-flash)提供模型 ID、JSON 支持与接口示例。2026-09-28 查阅；本次没有进行账号可用性或真实输出质量测试。

模型切换与 protocol 改动同时发生时，后续结果不能单独归因于 validator 改动。当前已有输出回放固定原科学内容，仅验证新的入口和路由。

## 验证与边界

`scripts/tools/replay_explorer_admission.py` 只读取原始 benchmark 的 14 份输出，并写入临时内存 CaseStore。没有 provider、evidence registry、Investigator 或 Critic 调用。原 271 个文件 SHA256 前后校验一致。

- Adapter：E01/E02/E03/E04/E07 在临时库提交，下一 actor 为 Critic；E05 缺 neutral outcome，E06 缺 H2/H4 contrast，均拒绝提交。
- 旧结构输出：0/7 提交；机器错误及真实完整性缺项仍阻断。
- 合成测试验证 C1 可拒绝已 admission 的 proposal、C1 pass 后交给 Investigator、revision acceptance 后仍需 C1、有证据后 C2 可执行，以及无效输入不产生半份科学对象。

回放的 5 次临时提交不是新的真实 Explorer 成功率，也不是 5 次真实 C1 通过。当前没有真实模型科学有效性结论。
