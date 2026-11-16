# JURE 科学内容接口（实施版）

Agents author scientific content; software assembles scientific records.

JURE 从 perturbation-associated signed higher-order clue 出发，由 competing hypotheses 引导主动取证，再由 Critic 区分 hypothesis defects 与 evidence gaps 并动态路由。主顺序固定为 Explorer → Investigator → Critic；Critic 内部 C1 通过后才执行 C2。POPPER/VCR 的借鉴限于职责分离，不替换 JURE 的科学协议。

## 活跃接口

`ScientificContentBackend` 同时处理 initial/reframe。Explorer 提交科学字段的增量；已有字段缺省时保留原值。软件分配新 ID、绑定原假说版本、保留历史 prediction，并生成全部 comparison slots。旧的 initial-content / typed-reframe 分叉类已经删除；旧 benchmark 和旧适配器仅保留作历史回放，不再用于 pilot。

Explorer 为每一对选择 RELEVANT_TO_DISTINGUISH 或 NOT_CURRENTLY_INFORMATIVE，并给理由。仅前者提交详细 observable、双方预期及三个互斥 outcome 分支。程序不填实验设计，不强制每个 prediction 本轮都获得调查问题。pair decisions 随 proposal admission 保存，Investigator 和 Critic 均可读取。

内容提取先保留原始回复，再提取唯一完整 JSON 或显式区块；外围文本保存在可逆审计中。重复键、第二份结构化对象、截断或不存在的引用不会被猜测补全。已有 prediction 按 Case File 全量对象空间解析，保留原版本。涉及旧版本的适用性成为 Critic flag；Investigator 上下文包含问题实际引用的旧 prediction 和对应版本。

## 唯一的科学补充通道

完整 proposal 自动重写已从新的 Explorer 路径移除。每次 Explorer 最多一次 missing-field semantic patch，只允许补原本不存在的字段。请求只带缺项、受影响的原始片段及必要的假说输入；不能替换已有内容。P01 的原始回答、base/result hashes 和缺项路径保留，patch 原文进入审计历史。机器格式错误不启动 semantic patch。

Explorer 的上下文不再重复提供完整观察字符串、存储 schema、lineage catalog 和全部历史修订；真实 evidence、assessments、gaps、contradictions 不作 LLM 摘要或科学筛选。内部对象仍存在于持久化层，不再由模型生成。

## 本次验证与恢复

只回放 run_022 的两个已付费 Explorer 回答，没有新的 contract benchmark。两份回答在独立 CaseStore 中完成完整原子写入，并逐字段检查 hypothesis、prediction 和 evidence question 科学内容未改写。按“最早通过者”固定规则恢复第一份，不按机制质量挑选。

恢复本身不发出模型/工具调用，不撤销历史失败和费用，不重置科学轮次或额度。剩余主流程从 Investigator 开始，仍遵循 Critic 的 C1/C2 与动态路由。此恢复属于工程接口更新后的继续执行，不可计成原版本原生成功或新的独立 benchmark 样本。

Investigator 的选择必须属于当前可调查队列；额外优先级注释保留，不要求一次回答恰好覆盖整个队列。调查计划可把比较范围扩展到当前有效假说，原问题不改写，扩展记录为 `COMPARISON_SCOPE_EXPANDED`，科学适用性由 Critic 判断。不存在的假说、不可执行的工具操作和无效参数仍被机器门拒绝。

中断的 Investigator 可从固定顺序的已付费回答与真实工具结果恢复。恢复清单锁定文件哈希、方法顺序、工具、参数、问题和案件；不命中就停止，不静默重做。历史调用保留在累计预算中，恢复完成后才进入未完成步骤。该机制仅用于工程恢复，不作为新的实验样本或科学迭代。

POPPER focuses on autonomous hypothesis validation through iterative experiment design and statistical testing, while VCR-Agent focuses on grounded mechanistic explanation and verification. JURE instead starts from perturbation-associated higher-order response clues and organizes a multi-agent investigation in which competing mechanisms guide active evidence acquisition, while a critic distinguishes hypothesis defects from evidence gaps and dynamically redirects the investigation.

来源：[POPPER](https://github.com/snap-stanford/POPPER)、[VCR-Agent](https://github.com/valence-labs/VCR-Agent)。固定版本源码核查见 `outputs/reference_interface_audit_20260928/FINDINGS.md`。未引入它们的执行依赖或收费提取循环。
