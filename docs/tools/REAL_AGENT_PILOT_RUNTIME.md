# Real Agent pilot runtime v0.1

本阶段由用户授权接线和运行。选择规则与四个初始 Case File 沿用已冻结版本；所有问题、假说、预测、查询计划、工具选择、科学审计和路由由 JURE 的模型 backend 产生。Codex 只实现和检查执行层。

固定配置：`configs/agent_pilot_v1.json`。启动器：`python -m jure.runtime.pilot --prompt-key`。密钥通过隐藏输入进入内存和 Authorization header，不保存。每次运行先保存代码、基础 prompt、配置和初始文件哈希。A 必须通过技术门槛才能执行 B–D；门槛不要求得到任何特定科学结论。

## 接口范围

- Investigator 的既有 JSON reasoning backend 连接 Real ToolRegistry。保留原始 EvidenceEnvelope、统计量、原文、来源、独立性标识及 artifact 哈希。批次加权 matched NT 与 pooled NT 分开保留。
- 搜索命中不能自动变成 EvidenceRecord；PMID 检索结果返回 Investigator context，由它决定是否及如何获取论文。文献摘要作为待审查的 contextual source，不自动升级为实验支持。查询失败产生 gap。
- 原 Critic prompt 禁止直接调工具。新增单独的 `plan_rechecks` 接口，只在该方法允许最多两次只读来源复查；完整接口文本写入冻结 manifest。原 C1、claim-level audit、failure attribution 和 routing prompt 字符串保持不变。该扩展属于本次运行架构版本，应在 benchmark 中披露。
- Critic 复查由模型决定，可返回空队列。复查不自动建立新 EvidenceRecord，也不被当作独立实验；新证据仍需 Investigator 正式获取。
- 控制器只遵循 Case File 持久化路由。schema 重试只回传验证器报错，不替模型改写内容。阶段失败保存原始输出；不能伪造 STOP。

## 预算和结果解读

每 case 最多 80 次 provider 请求；3 个 Critic 轮次、3 个 Investigator 轮次、1 次 Explorer reframe；全局真实工具预算为 18 次，含 Critic 复查。原 Critic 内部工具计数仅覆盖 Investigator，最终报告使用 registry 全量 trace，并单列复查。缓存命中也消耗工具预算。重试及失败保留在报告。

本次是工程 pilot，不是无调试干预的正式 benchmark。任何运行后接口修复都创建新的显式运行目录，保留之前失败记录。不得按机制结论筛选成功案例。

## 模型切换记录（2026-09-28）

`run_001` 使用 glm-4.6v-flash：5 次 HTTP 429/1305，另一次返回非合法 JSON；0 次科学状态提交。用户随后明确允许更贵的 GLM 模型。

下一运行使用 `configs/agent_pilot_glm5_v1.json`：glm-5，输出上限 16384，超时 300 秒；仅对 429、指定 5xx 或连接失败按 15/30 秒固定退避重发同一请求。仍保留每个失败响应，不修改模型内容。原 schema/阶段重试预算不变。官方型号和定价分别见 https://docs.bigmodel.cn/cn/guide/models/text/glm-5 与 https://docs.bigmodel.cn/cn/guide/start/pricing ；价格快照保存在 `configs/glm_pricing_snapshot_20260928.json`。

## Validator v1.1 工程修复

`run_002_glm5` 在没有科学提交的情况下由 host 中止。已复现的通用问题：否定句被正则识别为因果证明；typed upstream clue 中已有名称被视为新编造名称；已知基因的负号/连字符被当成新名称。修复同时保留正向过度声称和未知名称的拒绝测试。额外接受 “hypothesized” 作为假设性限定词，并使边限定报错更明确；基础 prompt 不变。

新冻结配置 `configs/agent_pilot_glm5_v11.json` 从四个原始初始文件重新开始。之前返回的内容只作只读校验诊断，不复用为新运行输出；原始请求、回复和中止记录仍在原目录。该阶段明确属于工程调试，不用于宣称未经调试的 benchmark 成功率。

## Retry context v1.2 工程修复

`run_003_glm5_v11` 无科学提交。发现原有语义重试只有错误信息，缺少产生错误的原始模型输出；同一问题 ID 的报错因此无法稳定定位。v1.2 在同一 Agent / case / method 的验证重试中附上该模型自己的上一份未提交回复，内容原样保留并明确为不可信数据；跨 case 和无错误的新调用不附带旧回复。模型自行修正，host 不改写输出。仍从原始初始 Case File 开始，保留此前调试运行。

## Validator v1.3 工程修复

`run_004_glm5_v12` 中模型经过重试后只剩统计缩写 `FDR` 的误判；不应为了通过检查而删除统计边界说明。补齐统计/逻辑缩写识别，同时明确既有契约的报错：把一个未提供的分子名称称为 hypothetical，并不会自动提供来源。该规则来自既有 Explorer README 和测试，不在本轮放宽。此前运行无科学提交，全部保留；新运行仍从初始 Case File 重新生成。

## Native operation compatibility / checkpoint continuation v1.4

`run_005_glm5_v13` 的 Explorer 已真实提交 4 个假说；Investigator 选定 data_experiment，却将 operation 写成 `data_experiment.query`。新适配层声明并接受 canonical / tool-qualified 两种等价写法，仅剥离已选工具自身的命名空间，保留全部参数与真实查询日志；不选择或替换科学操作。

配置 `agent_pilot_glm5_v14.json` 明确引用上述已提交 Case A 快照及 SHA256，原样保留假说、预测和完整历史，从持久化 Investigator 路由继续。没有复用未提交回复，也不重新编写 Explorer 输出。继承的 stage 标记来源目录；工具和模型预算扣除前序调用。此前失败 Investigator 轮次仍按原 Critic 规则计入轮次预算，可能使 Case A 更早触及工程预算；应在结果解释中披露。B–D 仍从各自原始初始文件开始。

## Completed A / real context capacity v1.5

Case A 于 `run_006_glm5_v14` 完成：4 个假说、4 次真实统计调用及 4 条 EvidenceRecord，Critic 提议回 Explorer，但原预算守卫因 3 次 Investigator 启动（含 2 次早先格式失败）结束为 EVIDENCE_LIMITED。C1 未通过，因此未进行 claim-level audit 或来源复查，不得宣称已完成该分支。

只读容量检查测得 Explorer reframe context 为 207844 字符，旧上限 60000 无法容纳。v1.5 将其提升至 750000（与 Critic 相同，保留全部证据）；既有命名来源检查读取 Agent 实际可见的 EvidenceRecord 原始结构化 provenance，避免真实工具中的新名称仅因摘要简略而被误判为无来源。

B 在无科学提交时中止并保留记录。v1.5 原样携带 A 的已提交 STOP；控制器检测 stopped 后不执行任何新科学动作。B–D 从原始事实文件启动。携带同一 A 不是新的独立案例或重复实验。

v1.5 的新 dataset EvidenceRecord 在 `provenance.parameters.tool_result` 保留完整统计原文，兼容字段 `dataset.statistics_location` 指向该位置，避免同一统计对象在单条记录中复制两份；原始 envelope artifact 也完整保留。该调整不影响已提交 A 的任何记录。

## Per-operation context and deadline v1.6

B 的 Explorer 已提交四个假说。Investigator 在同一计划的第二步仍选择第一步工具；旧 `focused` context 未刷新，缺少前一步已完成的状态。v1.6 每步重新构建 evidence / recent acquisition context，并附当前 operation 和已完成调用。选择结果按当前操作、工具 family 和 registry capabilities 检查，错误原样回交同一个 Agent 修正；host 不替它挑工具。

该等待的墙钟跨度约 20 分钟，而记录的单调计时为 274.858 秒，尚未达到旧 300 秒 timeout；不能由此断言旧超时失效。GLM 请求新增明确的总时长 deadline（180 秒），同时限制整个响应读取过程；对暂时性错误只再等待 15 秒重试一次。schema/语义内容仍不由 host 修复。

恢复 B 时保留全部原始假说、历史和未提交 acquisition trace。对 checkpoint 之前未成功提交的 Investigator 启动，固定最多补偿 2 次轮次额度（本次 B 的有效上限 5 = 原 3 + 2）；工具和 token 调用不豁免、不删记录。C/D 没有补偿；A 的既有 STOP 不重开。此规则用于工程续跑，不构成正式 benchmark 的统一预算对照。

## A/B repair preparation v1.7（未重新运行模型）

用户要求先解决 A/B 技术问题，C 已中断、D 未启动。完整诊断见项目根目录 `A_B_TECHNICAL_ISSUES_AND_REPAIR.md`。

显式配置 `round_budget_basis=completed` 将成功提交的调查轮次与技术尝试分开。三角色采用同一计数定义，工具调用仍包含失败期间的实际消耗；provider、stage 和 controller 的有限尝试不取消。不再使用 checkpoint 的个案追加额度。旧配置默认 `started` 保持兼容。

Explorer 来源对象索引补齐 Case File 原本就支持的 Critic 对象；有已验证假说/证据关联的 `revision_request` 可作为修订的设计来源，不能作为新增科学证据或分子名称的来源。动态 JSON schema 和两个角色的共享接口约束写明 batch 数量、追加式 ID 与命名边界；基础 SYSTEM_INSTRUCTIONS 字符串未改动。

`scripts/tools/prepare_ab_repair.py` 只重放历史并生成恢复配置，不调用模型。A 精确恢复原 Critic 输入 revision 98，旧 STOP 和完整旧结果保留；B 原样使用完整 checkpoint。所有既有模型消耗仍扣除。修复分支不是新的独立重复实验。

## v1.7 实际续跑与 v1.8 格式接口

`run_009_glm5_v17_ab_repair` 中 A 的 Critic 已成功提交回 Explorer 的路由：真实预算为 1 次成功 Investigator、2 次失败尝试、4 次工具调用，未再提前 STOP。Explorer 第一轮失败后可以进入第二轮有限重试，验证了失败修订不会耗尽成功轮次。随后模型仍漏掉与未修改 H4 的比较，并有两次不合法 JSON，达到有限尝试上限；科学内容未提交，B 尚未启动。

v1.8 继续 A 的完整 revision 114 checkpoint，保留上述成功 Critic 审计和失败历史。启用官方 `response_format={"type":"json_object"}`（[智谱结构化输出文档](https://docs.bigmodel.cn/cn/guide/capabilities/struct-output)），原始响应仍严格解析，不手工修补。给 Explorer 明确列出已有工作假说 ID，缺失对比的报错列出具体 ID 对；不提供比较内容，也不放宽数量、来源或科学检查。122 项相关回归检查通过。B checkpoint、案例选择、基础角色 prompt 和其余预算保持不变，C/D 继续暂停。

## GLM-5.3 fallback v1.9

v1.8 的 GLM-5 即使带有原生 JSON 参数，仍连续两次返回非 JSON，其中一份包含正文前的解释段落。host 保留原响应并中断第三次请求，没有截取正文、修补 JSON 或提交科学修订。

按照用户允许其他 GLM 模型的授权，v1.9 改用 `glm-5.3`。依据[官方接口说明](https://docs.bigmodel.cn/cn/guide/models/text/glm-5.3)，设置必需的 `thinking=enabled` 和显式 `reasoning_effort=low`，输出上限 32768，总请求 deadline 300 秒。模型的 reasoning_content 不作为科学结果写入；只接收通过严格验证的最终结构化响应。33 项运行器/传输检查通过。

A 从 v1.8 原样导出的当前 checkpoint 继续，B 仍使用此前完整 checkpoint；累计 provider/tool 预算不重置。模型和格式接口变化均保留在冻结 manifest，不能将混合模型工程续跑称作独立、统一模型的正式 benchmark。价格依据[官方价格页](https://docs.bigmodel.cn/cn/guide/start/pricing)保存快照，已报告 usage 按模型分别估算，未返回 usage 的请求计费未知。

## v2.0：语义检查的两个假阳性

GLM-5.3 已返回合法 JSON 并补齐假说对比。随后两份相同的原始回复只剩两个误判：`no statistic establishes causation` 被识别为证明因果；对未修改旧假说的 `retained unchanged;` 被识别为科学保留裁决。

修复仅识别明确的否定主语，以及确实未在本批次修改的已有假说之完整“保持不变”分句；正向因果证明、实际 retained/confirmed 裁决、对新假说的伪装保留仍拒绝。120 项回归通过。两个原始回复的 SHA256 相同，修复后只读验证均无错误，记录在 `run_011_glm53_v19_ab_repair/READ_ONLY_REVALIDATION.json`；未提交或改写它们。新运行从完整 checkpoint 继续，仍由 Agent 生成并提交输出。

## v2.1：提前返回接口错误并分别续跑 A/B

run_012 中 A 的 Explorer 已提交修订（revision 148），Investigator 因计划将 clue_query 误标为 dataset 而失败；3 次真实工具调用保留，其中 1 次 INVALID_QUERY，未提交新 EvidenceRecord。累计 53 次模型调用，checkpoint revision 152。

v2.1 在模型重试接口校验全部队列 ID 与计划的 operation/evidence_type 绑定，让 Agent 自行改正后再执行；跨 checkpoint 保留最后阶段的技术错误反馈。没有替 Agent 选问题、工具、参数或修改科学文本。未修复的 INVALID_QUERY 仍作为真实失败记录，不转成反证。

显式配置 independent_existing_checkpoints 仅允许已有 A/B checkpoint，检查哈希、完整历史、不变 clue 及既有 E/I/C 提交和 Critic 路由；每个 case 独立恢复，不再要求 A 的修复分支先完成科学 STOP 才能恢复 B。新 case 默认顺序门槛不变，C/D 继续暂停。修复控制器最后一步成功 STOP 被误标 transition_limit 的边界情况。

36 项 runtime/transport 回归检查通过（与旧组有重叠）。配置 agent_pilot_glm53_v21_ab_repair.json，运行 run_013_glm53_v21_ab_repair；科学及消耗预算不变，旧输出不提升为提交状态。

## v2.2：事实复制字段的精确报错

run_013：A 完成，4H/7E，Critic evidence_limited STOP，累计 69 次模型调用、11 次真实工具调用；C1 未通过，未进入 C2。B 第 2、3 份 Explorer 回复仅在不可变 observation_interpretation 的一个引号和末尾引号上不同；仍严格拒绝。第 4 次请求被中断后保留 checkpoint（累计 29 次模型调用），未提交修订。

v2.2 返回确定性的字符区间差异，并在已有 JSON Schema 中把 observation_interpretation_required 标为 const。保留原始字符串相等规则，不修改模型科学输出，不提升旧回复。B 在 run_014_glm53_v22_ab_repair 从 checkpoint 重试；A 不重跑。

## A/B 续跑收尾

A：run_013 / revision 230，4H、8 个假说版本、7E、11 次真实工具调用，累计 69 次模型调用。B：run_014 / revision 246，4H、8 个假说版本、7E、9 次真实工具调用，累计 49 次模型调用。两例由 Critic 以 hypothesis_space_unresolved 正式 evidence_limited STOP；科学修改额度按完成轮次计量，本次均已完成允许的一轮 reframe。C1 未通过，C2 和来源复查未执行。不得宣称证据工具已全部耗尽或机制验证成功。

两例 FINAL_ARTIFACT_AUDIT.json 通过。汇总 AB_RESUME_RESULT.md/JSON，仅取已提交状态；版本混用和调试保留为工程 pilot，C/D 暂停。v2.2 最终相关回归 124 项通过（组间重叠）。
