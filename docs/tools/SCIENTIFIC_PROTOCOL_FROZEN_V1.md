# 冻结科学 Protocol：EIC-frozen-v1

正式流程固定为 **Explorer → Investigator → Critic**。不再把 C1 前置。

Critic 内部先 C1 Hypothesis Audit，通过才执行 C2 Evidence Audit；随后 Hypothesis issue 返回 Explorer、Evidence gap 返回 Investigator、Sufficient 生成报告、Limited/Stalled 停止。工具、修订和模型预算耗尽保留独立终止原因。

Explorer 拥有问题、假说、预测和 comparison/outcome 科学内容；Investigator 拥有取证问题优先级与工具选择；Critic 拥有科学审查和机制比较。Codex 只实现程序与工程验证。Figure 2 顺序与此一致，三个真实 example 区域在真实执行前保持空白。本轮不编造图中示例，也不启动 Agent ablation。

## Validator 权限

硬检查仅限 schema/type/required fields、enum、ID/reference/lineage、对象与来源记录一致性、角色写权限及冻结预算。已有对象不可冒充其他类型；未取得的 evidence 不可凭空生成。

科学设计的必要结构缺项（如 prediction、contrast、neutral outcome）单独记为 completeness，返回 Agent，程序不补写。科学合理性、措辞、mediator、alternatives 质量、证据说服力交给 Critic。相关启发式只能产生 flags。

Critic 自己输出的维度 fail 却总评 pass、claim status 与其 synthesis 不一致、统计覆盖计数不符，属于输出内部一致性；程序不得根据来源类型或预设质量阈值另作科学判决。来源缺失不能被写成“provenance complete”，这是记录一致性。

## 表示规范化：representation-v1 / v1.1

三个 Agent 共用 schema 驱动的 normalizer：完整 JSON fence、单对象包装、JSON 字符串包装；enum 的唯一大小写/分隔符拼写；明确 bool/integer 字面量；仅在对应对象类型中唯一匹配的 ID 拼写；确定性新记录 ID 与 authoritative case binding。已有 initial content adapter 继续负责局部 hypothesis positions、parent clue、nested prediction/question 和 lineage 装配。

按用户明确提出的规则，Investigator prioritization 的 ordinal 字段可将 `medium-high` 归档为 `high`。这是预先声明的离散化政策，不宣称两个值语义完全相同；不扩展到 Critic verdict/status、不修改所选 question、不重新排名。每次改动记录字段路径、规则、raw_value、normalized_value；保留完整原始响应。

不修补截断 JSON、不接受重复 JSON key、不猜测未知枚举、不删多余字段、不把 question ID 转成 evidence ID、不猜未知 lineage。缺 comparison/prediction/outcome 等科学内容必须仍失败。Day6/Day8 不作为分子名拦截。

第一轮真实 smoke 使用冻结的 representation-v1。全部真实调用结束后，v1.1 离线增加注册 capability ID→显示名映射，覆盖完整 OBSERVABLES 注册表，保持能力选择不变。原 smoke 结果不回写、不计作新版本在线通过；科学 Protocol 和 Agent 职责未改变。

## 执行顺序

先完成历史输出离线 replay 与剩余错误分类，再用冻结的 5 个多类型输入做最多 10 次 GLM contract 调用。只测试 Explorer 输出接口和已有 proposal 的 Investigator prioritization。无真实 evidence tools、无 Critic、无 Case A 调查；失败不在运行中改代码或补样本。

配置与验收见 `configs/contract_stabilization_v1.json`。通过后才评估重启 A，目标是取得 Agent 判定有区分力的证据并首次进入 C2；不以“找到胜出机制”为通过条件。B 仅在 A 成功后解冻，C/D 继续后置。小 smoke 不作为正式 benchmark 或单因素 ablation。
