# Evidence Investigator v0.1 设计与实现契约

实现范围：Phase 1–5。工具均为离线 Mock；未连接真实 Dataset / GRN / Literature 服务。

## 实现索引

| 设计内容 | 实现 |
| --- | --- |
| Role / Inputs / I1–I5 Protocol | `jure/agents/investigator/agent.py`, `context.py` |
| Evidence Queue / Prioritization Policy | `queue.py`, `prioritization.py`, `priority_policy.py` |
| QueryPlan / reasoning backend | `query_plan.py`, `backend.py` |
| Tool Registry | `jure/tools/evidence/registry.py`, `base.py` |
| Dataset Evidence / Network Evidence / Literature Evidence | `dataset.py`, `network.py`, `literature.py`, `mock.py` |
| EvidenceRecord / EvidenceGap / Follow-up Questions | 原有 `jure/casefile/models.py` 及 `investigator/recording.py` |
| Agent Boundaries / Audit / Provenance | `validation.py`, `artifacts.py`, `jure/casefile/store.py` |
| Synthetic Tests / Acceptance Criteria | `tests/test_investigator_*.py`, `tests/test_casefile_investigator.py` |

## 兼容性与具体决策

- Case File schema 版本为 `0.1.1`，兼容读入 `0.1.0`，旧审计事件不重写。保留 `EvidenceRecord.question_id`，增加 `related_question_ids` 与 `question_ids` 视图。
- 支持/挑战关系继续存入现有 `EvidenceAssessment`，含 hypothesis revision 和 prediction 引用；不再复制一组 hypotheses/evidence 模型。
- Network 每个原子 edge 一个证据，避免同一边被不同查询反复复制。共同上游 follow-up 关联该次取得的全部边证据。
- 新 Investigator history 的 actor 为 `evidence_investigator`；保留旧 `investigator` actor 兼容现有消费者。
- 原始结果是独立带 SHA-256 的 JSON 文件。数据库先写 run started，后续在隔离的内存 CaseStore 中进行；验证、版本比较通过后一次提交。失败会丢弃暂存写入，保留失败 run artifact 中的工具调用和 raw 引用。进程崩溃时 authoritative queue 不会因暂存状态永久卡在 in_progress；已有陈旧状态另有显式恢复接口。
- ordinal policy 每轮按实时状态重排。Mock operationalizer 对不支持的细胞组成匹配等问题返回 unresolved，不擅自换成更简单的统计查询。
- 文献实验的 directness 与 context_match 分开；完整回答需要具体 claim 全部关系有足够支持且匹配所需 context。未找到、工具错误、低支持量均不会作为反证。
- 人工接口通过 CaseStore 写入 `actor="human"` 的历史，无新增 UI。真实 JSON backend 只接收纯数据和 schema，由调用方注入 transport，未绑定任何模型或外部服务。

## 用户提供的完整设计正文

你现在需要为 JURE 实现第二个 reasoning agent：

Evidence Investigator v0.1

前提：

1. Shared Case File v0.1 已存在；
2. Mechanism Explorer v0.1 已存在；
3. Explorer 已经能够在 Case File 中写入：
   - mechanistic question
   - competing hypotheses
   - predictions
   - initial evidence questions
4. 必须复用现有 Case File schema/API；
5. 不要重新实现第二套 hypotheses / evidence schema。

本任务只实现：

Evidence Investigator

不要实现：

- Mechanism Explorer
- Mechanism Critic
- hypothesis generation
- hypothesis final verdict
- reinforcement learning
- autonomous long-horizon workflow
- Tensor Network
- Clue Discovery
- 自动修改 hypothesis
- 自动停止整个 case

==================================================
一、Evidence Investigator 的核心职责
==================================================

Evidence Investigator 不负责“想机制”。

Explorer 已经负责：

Clue
  ↓
Mechanistic Question
  ↓
Competing Hypotheses
  ↓
Discriminating Predictions
  ↓
Evidence Questions

Investigator 从这里接手。

它负责：

Evidence Questions
        ↓
Operationalize
        ↓
Prioritize
        ↓
Select Next Question
        ↓
Choose Evidence Source / Tool
        ↓
Acquire Evidence
        ↓
Normalize Evidence
        ↓
Write Evidence Record
        ↓
Update Evidence Queue
        ↓
Return Case for Critique

核心问题是：

“What evidence should be acquired next
to distinguish the current competing hypotheses?”

而不是：

“What information can I find about these genes?”

==================================================
二、Investigator 的五步 Protocol
==================================================

实现固定的宏观 protocol：

I1. READ
I2. OPERATIONALIZE
I3. PRIORITIZE
I4. ACQUIRE
I5. RECORD

注意：

宏观 protocol 固定，
但具体调查路径必须动态。

不能写成：

statistics
→ GRN
→ literature
→ END

每个 case 都固定调用全部工具。

Investigator 应根据当前 Case File
动态决定下一步获取哪一类 evidence。

==================================================
三、I1：READ
==================================================

Investigator 从 Case File 读取最小必要 context：

mechanistic_question

active hypotheses

predictions

pending / unresolved evidence questions

existing evidence records

evidence gaps

contradictions

action_state

Investigator 不允许修改：

ClueRecord
MechanisticQuestion
Hypothesis mechanism statement
Prediction statement

这些属于 Explorer / future Critic 的职责。

Investigator 可以更新：

EvidenceQuestion status
EvidenceRecord
EvidenceGap
InvestigationHistory
ActionState

==================================================
四、Evidence Question 是 Investigator 的基本工作单位
==================================================

Investigator 不直接以整个 hypothesis 为工具调用单位。

例如：

H1:
shared upstream mechanism

H2:
A → B → C cascade

Explorer 产生：

Q1:
Is there a candidate upstream regulator/pathway
connecting A, B and C?

Q2:
Is there regulatory or experimental evidence
supporting A → B?

Q3:
Does B state alter the response of C
in the observed single-cell data?

Investigator 每次优先处理：

一个 EvidenceQuestion

而不是：

“调查 H1 的所有证据”。

==================================================
五、I2：OPERATIONALIZE
==================================================

Explorer 产生的 EvidenceQuestion
可能仍然偏 biological / conceptual。

Investigator 必须把它转换成：

Tool-answerable Query Plan

例如：

EvidenceQuestion:

“Is there a shared upstream regulator of A/B/C?”

Operationalized plan 可以是：

Step 1:
query candidate regulatory network for nodes
with outgoing relationships to A/B/C

Step 2:
if candidate X exists,
record X and network provenance

Step 3:
do NOT yet claim X is causal

----------------------------------

EvidenceQuestion:

“Is A→B experimentally supported?”

Operationalized plan：

search literature for experiments in which
A was perturbed/manipulated and B was measured

优先寻找：

A knockout
A knockdown
A CRISPRi
A overexpression
A inhibition

followed by measurement of B.

----------------------------------

EvidenceQuestion:

“Does B state alter C response?”

Operationalized plan：

use dataset statistics to compare:

P(C+ | B+)
vs
P(C+ | B-)

and if relevant:

P(C+ | A+, B+)
vs
P(C+ | A+, B-)

with support counts and uncertainty.

==================================================
六、QueryPlan schema
==================================================

实现内部结构：

QueryPlan

字段至少：

plan_id
question_id

objective

evidence_type

candidate_tool_types[]

required_inputs{}

planned_operations[]

expected_output

failure_conditions[]

created_at

注意：

QueryPlan 是 Investigator 内部 action plan。

不要把它当 EvidenceRecord。

==================================================
七、Evidence Types
==================================================

v0.1 先支持三大 evidence families：

1. dataset
2. network
3. literature

预留：

other

暂时不要加入：

Tensor Network

如果以后确实发现高阶条件概率需要 TN，
再作为 dataset evidence backend 扩展。

==================================================
八、Dataset Evidence
==================================================

Dataset evidence 回答：

“What does our own experimental dataset show?”

第一版支持的统计查询可以包括：

pattern frequency

conditional frequency

marginal frequency

control vs perturbation shift

support counts

contingency table

Fisher exact test

bootstrap confidence interval

simple conditional comparison

已有 Clue Discovery statistic lookup

不要在 Investigator 内重新实现整套 Clue Discovery。

优先复用项目已有 statistics / clue_discovery functions。

例如：

P(C+ | A+, B-)

必须同时返回：

numerator
denominator
probability
support

如果 denominator 太小：

不要给出看起来很精确的结论。

EvidenceRecord 应明确：

“insufficient support”

或：

“estimate unstable”

==================================================
九、Dataset Evidence 的重要边界
==================================================

Investigator 不得把：

P(C|A,B)

解释成：

A/B cause C

也不得把：

conditional association

写成：

regulatory mechanism

Dataset evidence 只能记录：

observed statistical relationship

以及：

support / uncertainty / limitations

==================================================
十、Network Evidence
==================================================

Network evidence 用于回答：

- A 与 B 是否存在候选 regulatory relation？
- 是否存在 shared upstream regulator？
- 是否存在候选 path connecting genes？
- 某 hypothesis topology 是否与已有 GRN compatible？

定义抽象接口：

NetworkEvidenceTool

例如：

query_edge(source, target, context=None)

query_shared_regulators(targets, context=None)

query_paths(source, target, max_hops, context=None)

不要把某个具体 GRN 数据库硬编码在
Investigator 核心逻辑中。

每个 network result 必须保留：

network_name
network_version
edge_type
direction
context
source_reference
query_parameters

==================================================
十一、Network Evidence 的边界
==================================================

GRN edge 不等于 causal truth。

例如查询得到：

X → A
X → B
X → C

EvidenceRecord 可以写：

“Network evidence is consistent with
a shared upstream architecture.”

不能写：

“X is the causal regulator explaining the clue.”

必须自动添加 limitation：

“Network connectivity alone does not establish
causal regulation in the current perturbation context.”

==================================================
十二、Literature Evidence
==================================================

Literature evidence 的目标不是：

“找到提到这些 genes 的文章。”

而是尽可能寻找：

experiment-level evidence

优先级：

1. direct perturbation evidence
2. direct biochemical/regulatory evidence
3. context-matched functional evidence
4. indirect association
5. generic co-mention

例如验证：

A → B

优先寻找：

A knockout → B changes

A knockdown → B changes

A overexpression → B changes

A inhibition → B changes

A binding assay + B regulation

而不是：

“A and B are both associated with cancer.”

==================================================
十三、Literature Query Plan
==================================================

对于一个 regulatory claim：

A → B

生成 query plan 时至少考虑：

A AND B AND knockout
A AND B AND knockdown
A AND B AND CRISPR
A AND B AND overexpression
A AND B AND regulation

如果 Case File 有：

cell_context

例如 K562，

优先加入 context：

A B K562 CRISPR

但：

没有 context-matched evidence
不等于 hypothesis automatically false。

==================================================
十四、Literature Evidence Record
==================================================

每条文献证据尽量结构化：

paper_id
title
year

claim_tested

experiment_type

perturbed_entity
measured_entity

observed_effect

biological_context

cell_type_or_model

directness

source_excerpt_or_summary

source_reference

limitations

例如：

claim_tested:
A → B

experiment_type:
CRISPR knockout

perturbed_entity:
A

measured_entity:
B

observed_effect:
B decreased

context:
K562

directness:
direct

注意：

如果论文只共现 A/B，
directness 不能写 direct。

==================================================
十五、禁止把 Literature RAG 摘要直接当 Evidence
==================================================

例如检索结果：

“Gene A and Gene B are involved in pathway X.”

这只能作为：

contextual / indirect evidence

不能升级成：

A → B

Investigator 必须区分：

retrieved text

和：

verified experimental claim

如果文献无法支持具体 claim：

EvidenceQuestion 可以标记：

partially_answered

或：

unresolved

==================================================
十六、I3：PRIORITIZE
==================================================

这是 Investigator 最重要的 agentic component。

如果 Evidence Queue 有：

Q1
Q2
Q3
Q4

不要固定按创建顺序执行。

Investigator 应选择：

Q* = next most informative question

第一版不要实现 RL。

不要设计虚假精确的：

information_gain = 0.8734

使用可解释的 ordinal policy。

每个 pending question 评估：

1. discriminative_value

high
medium
low

问：

这个结果是否可能区分两个或以上 active hypotheses？

2. answerability

high
medium
low

问：

当前已有工具是否有机会回答？

3. evidence_directness_potential

high
medium
low

问：

是否可能获得 direct evidence？

4. estimated_cost

low
medium
high

例如：

simple network lookup = low

simple dataset contingency query = low

targeted literature verification = medium

broad literature exploration = high

5. redundancy

none
partial
high

已有 evidence 是否已经回答类似问题？

==================================================
十七、Priority Policy
==================================================

第一版使用规则式排序。

优先：

high discriminative
+
high answerability
+
low/medium cost

其次：

high discriminative
+
medium answerability

降低优先级：

low discriminative

high redundancy

无法由当前工具回答

不要用复杂加权总分。

允许生成：

priority_class:
high
medium
low

以及：

priority_reason

例如：

“Q1 is prioritized because a low-cost network query
could directly distinguish H1 shared-upstream architecture
from H2 cascade architecture.”

==================================================
十八、不要调查“不区分假说”的问题
==================================================

例如：

“Is perturbation gene X associated with cancer?”

即使答案很好找，

如果：

H1
H2
H3

都兼容这个事实，

那么：

discriminative_value = low

不应优先。

Investigator 的目标不是：

collect maximum information

而是：

reduce uncertainty between current hypotheses

==================================================
十九、I4：SELECT TOOL
==================================================

选中 Q* 后，

Investigator 再决定具体 evidence source。

这是 Investigator 的职责，
不是 Explorer 的职责。

Explorer 的：

suggested_evidence_type

只能作为 hint。

Investigator 可以覆盖。

例如：

Q:
“Is there a shared regulator of A/B/C?”

Explorer suggested:
network

Investigator 可以决定：

先 network

如果找到候选 X，
再产生 follow-up literature question。

==================================================
二十、Tool Registry
==================================================

实现抽象 Tool Registry：

EvidenceToolRegistry

至少支持：

register_tool(...)
get_tools_for_evidence_type(...)
execute(...)

Tool metadata：

tool_id
tool_type
capabilities
required_inputs
cost_class
availability

不要把 Agent 核心逻辑和某个具体 API 绑定。

==================================================
二十一、v0.1 可以先使用 Mock Tools
==================================================

为了先验证 protocol，

实现：

MockDatasetTool
MockNetworkTool
MockLiteratureTool

后续再连接真实：

statistics
GRN
literature retrieval

所以：

Investigator reasoning layer

和：

external evidence backend

必须解耦。

==================================================
二十二、Tool Failure Handling
==================================================

如果工具：

timeout

no result

insufficient support

malformed response

source unavailable

不要让 Investigator hallucinate answer。

创建：

ToolExecutionResult

status:

success
no_result
insufficient_data
failed

并记录：

failure_reason

如果 no_result：

不能自动解释为：

evidence against hypothesis

例如：

“No paper retrieved”

不等于：

“A→B is false.”

==================================================
二十三、I5：NORMALIZE AND RECORD
==================================================

每次工具调用结束后，

不能把 raw tool output 直接塞进 Case File。

必须转换为：

EvidenceRecord

至少：

evidence_id

question_id

source_type

claim_tested

result_summary

supports_hypotheses[]

challenges_hypotheses[]

neutral_to_hypotheses[]

directness

context_match

limitations[]

provenance{}

raw_result_reference

created_at

created_by="evidence_investigator"

==================================================
二十四、Supports / Challenges 的边界
==================================================

Investigator 可以写：

“Evidence E1 is consistent with H1.”

或者：

“E2 challenges prediction P3.”

但是不能写：

“H1 is correct.”

“H2 is rejected.”

“H1 wins.”

Hypothesis verdict 属于未来 Mechanism Critic。

所以：

supports_hypotheses

和：

challenges_hypotheses

表示：

evidence-hypothesis relation

不是最终 verdict。

==================================================
二十五、Evidence Strength 暂时不要综合打分
==================================================

不要输出：

EvidenceScore = 0.87

Confidence = 92%

第一版使用结构化维度：

directness:
direct
indirect
contextual
unknown

context_match:
matched
partial
mismatched
unknown

source_quality:
primary_experiment
curated_database
secondary_source
unknown

support_quality:
sufficient
limited
insufficient
unknown

以后 Critic 可以根据这些字段判断。

==================================================
二十六、Evidence Queue 状态更新
==================================================

Investigator 开始处理 Q1：

pending
→ selected
→ in_progress

成功回答：

→ answered

部分回答：

→ partially_answered

没有足够 evidence：

→ unresolved

工具失败但未来可重试：

→ pending

不要删除 question。

保留完整状态变化 history。

==================================================
二十七、Follow-up Evidence Questions
==================================================

Investigator 允许在工具结果产生新的明确证据缺口时，
创建 follow-up EvidenceQuestion。

例如：

Q1:
Is there a shared regulator of A/B/C?

Network tool：

找到 candidate X。

这不能直接证明 H1。

Investigator 可以新增：

Q4:
“Is there direct experimental evidence that X regulates
A, B and C in a relevant context?”

Q4 来源必须记录：

derived_from_evidence_ids=[E1]

以及：

derived_from_question_ids=[Q1]

这样 investigation trajectory 可追踪。

==================================================
二十八、但 Investigator 不允许扩张 Hypothesis Space
==================================================

如果查询结果发现：

“现有 H1/H2/H3 都解释不了 X。”

Investigator 不应自己创建：

H4

而应：

创建 EvidenceGap：

“Current hypotheses do not explain evidence E7.”

然后设置：

ActionState.current_phase =
"critique_needed"

未来由 Critic 决定：

继续 Investigator

还是：

回 Explorer reframe。

==================================================
二十九、Investigator 的内部循环
==================================================

Investigator 一次 run 不一定只允许一个 tool call，
但必须有 budget。

实现配置：

max_questions_per_run
max_tool_calls_per_run

默认建议：

max_questions_per_run = 1

max_tool_calls_per_run = 3

也就是说第一版偏保守：

一次主要解决一个 EvidenceQuestion。

为了回答该 question，
允许最多几个必要 tool calls。

例如：

network lookup
→ candidate X
→ one targeted verification

不要一次 run 把整个 Evidence Queue 全部扫完。

==================================================
三十、什么时候交给 Critic
==================================================

虽然 Critic 尚未实现，
Investigator 必须能够设置：

ActionState.next_actor = "critic"

满足任一情况即可：

1. 一个 high-priority discriminating question
   获得了实质 evidence；

2. evidence 明显 challenges 某 hypothesis prediction；

3. 新 evidence 暴露 hypothesis space gap；

4. 当前问题 unresolved，
   且需要重新评估调查策略；

5. 达到本轮 tool budget。

Investigator 不决定 Critic 下一步怎么路由。

==================================================
三十一、什么时候继续 Investigator
==================================================

如果：

当前 tool result 只是中间结果，
还不足以形成可解释 EvidenceRecord，

可以继续完成同一个 QueryPlan。

例如：

Network query
→ 找到 X

但当前 Q 是：

“Is there experimental evidence for shared regulation?”

那么 network result 可以成为 intermediate result，

接着做 targeted literature query。

但不要无限 chain。

受：

max_tool_calls_per_run

限制。

==================================================
三十二、Evidence Gap
==================================================

如果问题无法回答，

创建 EvidenceGap。

例如：

“No direct perturbational evidence was found
for A→B in the queried context.”

注意措辞：

“was not found”

不是：

“does not exist”

EvidenceGap 关联：

question_id
prediction_id
hypothesis_id

==================================================
三十三、Provenance 必须完整
==================================================

所有 EvidenceRecord 必须可追踪：

谁查的
查了什么
用了什么工具
工具版本
查询参数
返回什么
什么时候查的

dataset evidence 还要记录：

dataset
cell subset
filters
support counts

network evidence：

==================================================
三十三、Provenance 必须完整（续）
==================================================

所有 EvidenceRecord 必须能够追踪：

谁执行的
为什么执行
回答哪个 EvidenceQuestion
使用哪个工具
工具版本
查询参数
返回什么结果
何时执行

不同 evidence type 至少保存：

----------------------------------
Dataset evidence
----------------------------------

dataset_id
dataset_version
cell_context
condition
cell_subset
filters
n_cells
support_counts
statistical_method
parameters
code_version
run_id

如果计算：

P(C+ | A+, B-)

必须保存：

conditioning_pattern
numerator_count
denominator_count
estimated_probability
uncertainty
support_warning

不能只保存：

"P = 0.73"

----------------------------------
Network evidence
----------------------------------

network_name
network_version
context
edge_type
query_type
query_parameters
source_reference

例如：

query_type:
shared_regulator

targets:
[A, B, C]

返回的每条 edge
必须保留原始 provenance。

----------------------------------
Literature evidence
----------------------------------

paper_id
title
year
source
query
retrieval_timestamp

claim_location
experiment_type
biological_context
source_reference

如果使用原文摘录，
必须保留定位信息。

EvidenceRecord 中的总结
必须能够追溯到原始 source。

==================================================
三十四、Raw Result 与 Evidence Record 必须分离
==================================================

不要把：

GRN 返回的整个 JSON

PubMed / literature retrieval 的全部文本

dataset statistics 的大表

直接写进 Case File 主结构。

实现：

RawEvidenceArtifact

用于保存原始结果。

Case File 只保存：

EvidenceRecord

以及：

raw_result_reference

这样：

Case File 保持简洁，

但每条 evidence 都可以追溯到原始结果。

==================================================
三十五、Investigation History
==================================================

每个 Investigator action
必须写入 append-only history。

至少支持：

INVESTIGATOR_STARTED

QUESTION_PRIORITIZED

QUESTION_SELECTED

QUERY_PLAN_CREATED

TOOL_SELECTED

TOOL_CALL_STARTED

TOOL_CALL_COMPLETED

TOOL_CALL_FAILED

EVIDENCE_RECORDED

EVIDENCE_GAP_CREATED

FOLLOWUP_QUESTION_CREATED

QUESTION_STATUS_UPDATED

INVESTIGATOR_COMPLETED

每条 history event：

event_id
timestamp
actor="evidence_investigator"
action
object_type
object_id
summary
metadata

禁止覆盖旧 history。

==================================================
三十六、Investigator Backend
==================================================

Investigator reasoning backend
做成抽象接口：

InvestigatorBackend

至少支持：

prioritize_questions(...)

operationalize_question(...)

select_tool(...)

interpret_tool_result(...)

不要在核心逻辑中硬编码具体 LLM。

支持：

MockInvestigatorBackend

用于 deterministic unit tests。

真实 backend 使用：

structured JSON output

所有输出必须经过 schema validation。

==================================================
三十七、LLM 和 deterministic logic 的边界
==================================================

不要让 LLM 决定所有事情。

适合 LLM 的：

1. 将 biological prediction
   operationalize 成 evidence question plan；

2. 判断一个问题更适合
   dataset / network / literature；

3. 根据当前 hypotheses 判断
   哪个问题更有 discriminative value；

4. 将 raw evidence
   规范化成简洁的 evidence summary；

5. 判断是否出现新的 evidence gap。

适合 deterministic code 的：

1. question status transition；

2. ID/reference validation；

3. tool availability；

4. budget enforcement；

5. support threshold；

6. statistics computation；

7. provenance capture；

8. Case File mutation；

9. history logging；

10. schema validation。

LLM 不得直接绕过 Case File API 修改状态。

==================================================
三十八、Context Builder
==================================================

实现：

build_investigator_context(case_file)

不要把整个 Case File
和全部 history 全塞进 prompt。

只提供：

mechanistic question

active hypotheses

relevant predictions

pending evidence questions

与当前 question 相关的 existing evidence

relevant evidence gaps

tool capabilities

当前 action budget

如果当前处理 Q3，
不要默认把与 Q3 无关的大量 evidence
全部塞进去。

==================================================
三十九、Question Prioritization 输出
==================================================

定义：

QuestionPriorityAssessment

字段：

question_id

discriminative_value:
high
medium
low

answerability:
high
medium
low

directness_potential:
high
medium
low

estimated_cost:
low
medium
high

redundancy:
none
partial
high

priority_class:
high
medium
low

priority_reason

Investigator 选择一个：

selected_question_id

必须保存：

为什么选它。

不要只输出：

Q3 selected

必须例如：

“Q3 was selected because it directly distinguishes
H1 from H2, can be answered with the available dataset,
and requires a low-cost statistical query.”

==================================================
四十、优先级不要变成复杂打分器
==================================================

v0.1 禁止：

priority_score =
0.3 * discriminative
+ 0.2 * cost
+ ...

第一版使用可解释规则。

例如：

Rule 1:
high discriminative
AND high answerability
→ high priority

Rule 2:
high discriminative
AND medium answerability
→ high/medium

Rule 3:
low discriminative
→ low

Rule 4:
high redundancy
→ lower one level

Rule 5:
no available tool
→ low / unresolved

规则写入：

priority_policy.py

方便未来替换。

==================================================
四十一、Dataset Tool 的最低实现
==================================================

如果当前项目已经有可复用 statistics functions，
优先调用已有实现。

如果需要增加 Investigator-facing wrapper，
实现：

DatasetEvidenceTool

至少支持：

joint_frequency(pattern)

conditional_frequency(
    target_state,
    conditions
)

compare_conditional_frequency(
    target_state,
    condition_a,
    condition_b
)

compare_pattern_between_conditions(
    pattern,
    condition_a,
    condition_b
)

get_support(pattern)

所有统计查询必须返回：

estimate
counts
denominator
uncertainty
warnings

不要只返回一个概率。

==================================================
四十二、Dataset Query 的 support guard
==================================================

定义配置：

min_conditional_support

不要现在把具体数字硬编码为科学结论。

如果：

denominator < min_conditional_support

返回：

status="insufficient_data"

而不是正常 EvidenceRecord 中写：

“C probability is 0.75.”

可以创建 EvidenceRecord：

result_summary:
“Conditional estimate is not considered reliable
because only 8 cells satisfy the conditioning state.”

support_quality:
insufficient

==================================================
四十三、不要在 v0.1 使用 TN
==================================================

Dataset Evidence 第一版使用：

empirical statistics
+
simple uncertainty estimates
+
bootstrap / contingency statistics where appropriate

不要接入：

Tensor Network
Born-MPS

未来如果 Clue Discovery
产生稳定的 5+ gene clue，
且 empirical high-order conditional queries
因 support 不足无法估计，

再单独 benchmark：

empirical / smoothing / TN

TN 不属于 Evidence Investigator v0.1
的固定工具。

==================================================
四十四、Network Tool 的最低实现
==================================================

如果当前项目暂时没有真实 GRN backend，

先实现接口和 MockNetworkTool。

接口至少：

query_edge(
    source_gene,
    target_gene,
    context=None
)

query_shared_regulators(
    target_genes,
    context=None
)

query_paths(
    source_gene,
    target_gene,
    max_hops=2,
    context=None
)

返回：

NetworkQueryResult

包含：

status
edges[]
paths[]
candidate_regulators[]
context
provenance
warnings

不要在 mock 阶段假装接入真实数据库。

==================================================
四十五、Literature Tool 的最低实现
==================================================

同样先抽象：

LiteratureEvidenceTool

至少：

search_claim(
    claim,
    context=None
)

search_regulatory_relation(
    source_gene,
    target_gene,
    context=None
)

search_perturbation_evidence(
    perturbed_gene,
    measured_gene,
    context=None
)

返回：

LiteratureQueryResult

包含：

papers[]
candidate_evidence[]
query
provenance
warnings

真实文献检索 backend
后续再接。

v0.1 单元测试使用 MockLiteratureTool。

==================================================
四十六、Evidence Extraction 必须区分 retrieval 和 verification
==================================================

实现两个概念：

RetrievedItem

和：

VerifiedEvidenceCandidate

RetrievedItem：

只是搜索命中。

例如：

paper mentions A and B

不能直接写入：

direct evidence

VerifiedEvidenceCandidate：

必须包含足够信息支持：

具体 claim
实验类型
扰动对象
测量对象
观察结果
context

如果无法提取这些信息，

directness 只能是：

indirect
contextual
unknown

==================================================
四十七、Evidence 冲突不要由 Investigator 消解
==================================================

例如：

Paper 1:
A knockout → B decreases

Paper 2:
A knockout → B unchanged

Investigator 不应该自己说：

“Paper 1 is more convincing,
therefore A activates B.”

应该分别创建：

E1
E2

并记录：

potential_conflict=True

可以创建：

ContradictionRecord

但不要裁决。

未来交给 Critic。

==================================================
四十八、同一个问题允许多个 Evidence Records
==================================================

EvidenceQuestion：

Q2:
Does A regulate B?

可能产生：

E1:
network evidence

E2:
direct perturbation literature

E3:
dataset conditional association

这些都是：

Q2

的不同 evidence。

不要把它们覆盖成一个结果。

EvidenceQuestion status 可以：

partially_answered

直到已有足够 evidence
交给 Critic。

==================================================
四十九、Investigator Run Result
==================================================

每次运行返回：

InvestigatorRunResult

至少：

run_id
case_id

selected_question_id

priority_assessment

query_plan_id

tool_calls[]

created_evidence_ids[]

created_gap_ids[]

created_followup_question_ids[]

question_final_status

recommended_next_actor

warnings[]

validation_errors[]

注意：

recommended_next_actor
通常是：

critic

但只是 routing suggestion。

==================================================
五十、Investigator 不得做的事情
==================================================

明确禁止：

1. 创建新的 mechanistic hypothesis；

2. 删除 hypothesis；

3. 将 hypothesis 设置为 retained/rejected；

4. 修改 hypothesis mechanism statement；

5. 修改 ClueRecord；

6. 修改原始 Prediction statement；

7. 把 network edge 当因果事实；

8. 把 literature co-mention 当 direct evidence；

9. 把 absence of retrieved evidence
   当 evidence of absence；

10. 在 support 很低时输出高精度概率结论；

11. 自行调用 TN；

12. 无限搜索直到找到支持某个 hypothesis 的证据；

13. 只搜索 supporting evidence，
    忽略 potential counter-evidence；

14. 把工具失败解释成 hypothesis 被反驳；

15. 给 hypotheses 排名或最终 verdict。

==================================================
五十一、Evidence Search 必须允许反证
==================================================

Investigator 不应该只问：

“What supports H1?”

对于每个 hypothesis prediction，
如果适合，应同时允许：

supporting query

和：

challenging query

例如 H2：

A → B → C

除了：

“Is A→B supported?”

也可以：

“Is there experimental evidence inconsistent with A→B?”

但第一版不要强制每次都做两次搜索。

应由 evidence question / query plan
决定是否需要 counter-evidence search。

==================================================
五十二、Deterministic Validation
==================================================

实现：

validate_investigator_action(...)

至少检查：

1. selected question 必须存在；

2. question status 必须允许被选择；

3. QueryPlan 必须指向该 question；

4. tool 必须已注册；

5. tool capability 必须能回答该 plan；

6. tool call 不超过 budget；

7. EvidenceRecord 必须关联 question；

8. EvidenceRecord provenance 非空；

9. dataset evidence 必须包含 support；

10. literature direct evidence
    必须包含实验信息；

11. network evidence
    必须自动保留 causal limitation；

12. Investigator 不得创建 hypothesis；

13. Investigator 不得修改 hypothesis verdict；

14. Investigator 不得修改 ClueRecord；

15. follow-up question 必须有 lineage；

16. unresolved query 不能被写成 negative evidence。

==================================================
五十三、Synthetic Test 1：
Question Prioritization
==================================================

构造 Case：

Clue:
A+ B- C+

Hypotheses:

H1:
shared upstream mechanism

H2:
A → B → C cascade

H3:
cell-state composition shift

Evidence Queue：

Q1:
Is there a shared regulator of A/B/C?
discriminates H1 vs H2

Q2:
Is perturbation gene X associated with cancer?
does not discriminate hypotheses

Q3:
Does B state alter C response?
discriminates H2 vs H3

Mock tools：

Q1:
network tool available, low cost

Q3:
dataset tool available, low cost

验证：

Q2 必须低优先级。

Q1/Q3 应高于 Q2。

selected question 必须给出
priority_reason。

==================================================
五十四、Synthetic Test 2：
Network Evidence
==================================================

Q1：

“Is there a shared regulator of A/B/C?”

MockNetworkTool 返回：

X → A
X → B
X → C

Investigator 应创建 EvidenceRecord：

source_type="grn"

result_summary:

“A network-derived candidate X connects
to A, B and C.”

supports_hypotheses=[H1]

但 limitations 必须包含：

“Network connectivity does not establish causal regulation.”

不得写：

“X causes the clue.”

==================================================
五十五、Synthetic Test 3：
Dataset Evidence
==================================================

Q3：

“Does B state alter C response?”

Synthetic dataset：

B+:
C+ = 80 / 100

B-:
C+ = 20 / 100

Dataset tool 返回：

P(C+|B+) = 0.8

P(C+|B-) = 0.2

support counts
effect
uncertainty

EvidenceRecord 可以写：

“C+ frequency differs conditional on B state
in the observed dataset.”

禁止写：

“B regulates C.”

==================================================
五十六、Synthetic Test 4：
Insufficient Support
==================================================

Synthetic query：

P(C+ | A+, B-, D+)

denominator = 6

min_conditional_support = 20

应返回：

status="insufficient_data"

EvidenceRecord：

support_quality="insufficient"

limitations：

“Only 6 cells satisfy the conditioning state.”

不得输出：

“P=0.83 therefore strong evidence.”

==================================================
五十七、Synthetic Test 5：
Literature Direct Evidence
==================================================

Q：

“Is A→B experimentally supported?”

MockLiteratureTool 返回：

Paper P1

experiment:
A CRISPR knockout

measurement:
B expression

result:
B decreases

context:
matching cell model

Investigator 应创建：

directness="direct"

context_match="matched"

supports H2 prediction

并保留：

paper provenance

==================================================
五十八、Synthetic Test 6：
Literature Co-mention 不能升级
==================================================

Mock literature：

“Genes A and B are both associated with pathway X.”

没有 perturbation experiment。

EvidenceRecord：

directness="contextual" 或 "indirect"

不能写：

“A regulates B.”

==================================================
五十九、Synthetic Test 7：
No Result
==================================================

Literature search 返回：

0 verified evidence

Investigator：

question_status="unresolved"

创建 EvidenceGap：

“No direct evidence was identified
in the queried sources.”

不得：

challenges_hypotheses=[H1]

仅因为没有搜到论文。

==================================================
六十、Synthetic Test 8：
Follow-up Question
==================================================

Q1：

shared regulator?

Network tool 找到 X。

生成 E1。

Investigator 创建 follow-up：

Q4:

“Is there direct experimental evidence that
X regulates A/B/C?”

验证：

Q4.derived_from_evidence_ids
包含 E1

Q4.derived_from_question_ids
包含 Q1

Q4 进入 Evidence Queue。

==================================================
六十一、Synthetic Test 9：
Conflicting Evidence
==================================================

Q2：

A → B?

Mock literature：

P1:
A KO → B decreases

P2:
A KO → B unchanged

生成两个 EvidenceRecord。

不得合并成：

“A regulates B.”

创建：

potential contradiction

或 ContradictionRecord。

ActionState：

critique_needed

next_actor="critic"

==================================================
六十二、Synthetic Test 10：
Agent Boundary
==================================================

Mock backend 尝试：

create H4

set H1 retained

set H2 rejected

modify clue delta

全部必须被拒绝。

Investigator 只能：

select question
plan query
call tool
record evidence
create evidence gap
create follow-up evidence question
update evidence-question status
update action state

==================================================
六十三、Synthetic Test 11：
Budget
==================================================

配置：

max_questions_per_run=1
max_tool_calls_per_run=3

Mock backend 尝试调用 5 次工具。

第 4 次必须被阻止。

history 中记录：

BUDGET_REACHED

然后：

recommended_next_actor="critic"

或根据配置结束本轮。

==================================================
六十四、Synthetic Test 12：
Case File Round-trip
==================================================

运行：

Explorer
→ Investigator

保存：

case_file.json

重新 load。

验证：

hypotheses
predictions
evidence questions
evidence records
gaps
history
action state

全部保持 reference integrity。

==================================================
六十五、建议代码结构
==================================================

在现有项目中增加：

jure/
  agents/
    investigator/
      __init__.py
      agent.py
      backend.py
      context.py
      prioritization.py
      query_plan.py
      evidence_normalizer.py
      validation.py
      result.py

  tools/
    evidence/
      __init__.py
      registry.py
      base.py
      dataset.py
      network.py
      literature.py
      mock.py

不要把所有逻辑写进：

investigator.py

一个文件。

==================================================
六十六、配置
==================================================

InvestigatorConfig 至少：

max_questions_per_run = 1

max_tool_calls_per_run = 3

min_conditional_support = configurable

allow_followup_questions = True

allow_counter_evidence_search = True

priority_policy = "rule_based_v0.1"

不要把具体模型名称写进 config 核心 schema。

==================================================
六十七、CLI / Demo
==================================================

实现一个最小 demo：

python -m jure.agents.investigator.demo

输入一个已经由 Explorer 填好的

==================================================
六十七、CLI / Demo（续）
==================================================

实现一个最小 demo：

python -m jure.agents.investigator.demo

输入一个已经由 Mechanism Explorer 填好的 synthetic Case File。

例如 Case 中已有：

Clue:
Perturbation X
A+ B- C+

Mechanistic Question:
Why does perturbation X change the prevalence
of A+ B- C+?

Hypotheses:

H1:
shared upstream mechanism

H2:
A → B → C cascade

H3:
cell-state composition explanation

Predictions:

P1:
A shared upstream regulator should connect A/B/C.

P2:
Evidence should support A→B and B→C.

P3:
The pattern should track a broader cell-state program.

Evidence Queue:

Q1:
Is there a shared regulator of A/B/C?

Q2:
Is A→B experimentally supported?

Q3:
Does the observed dataset show a conditional relationship
between B and C?

Demo 使用 Mock tools。

要求 Investigator：

1. 读取 Case File；

2. 对 Q1/Q2/Q3 做 priority assessment；

3. 选择一个 Q*；

4. 创建 QueryPlan；

5. 选择合适 Mock Tool；

6. 执行查询；

7. 创建 EvidenceRecord；

8. 更新 EvidenceQuestion status；

9. 如有必要创建 follow-up EvidenceQuestion；

10. 更新 ActionState；

11. 写入 InvestigationHistory；

12. 保存更新后的 Case File。

输出：

investigator_run.json

updated_case_file.json

investigator_history.jsonl

raw_evidence/
    ...

==================================================
六十八、Demo 必须展示“动态选择”而不是固定工具顺序
==================================================

至少提供三个 demo case。

----------------------------------
Demo A：Network-first
----------------------------------

Q1：
shared regulator?

high discriminative
high answerability
low cost

Investigator 应优先选择：

NetworkEvidenceTool

不能因为代码固定顺序而先跑 dataset。

----------------------------------
Demo B：Dataset-first
----------------------------------

构造另一个 Case：

最有区分力的问题是：

“Does C response depend on A/B joint state?”

dataset evidence 可直接回答。

Investigator 应优先选择：

DatasetEvidenceTool

不能固定 network-first。

----------------------------------
Demo C：Literature-first
----------------------------------

已有 network evidence 已经表明候选 edge，
真正缺口是：

“Is this regulatory step experimentally supported?”

此时 literature question：

high discriminative
low redundancy

Investigator 应优先：

LiteratureEvidenceTool

这三个 demo 用于证明：

Investigator 不是固定 workflow：

Network → Dataset → Literature

而是：

Case State
   ↓
Evidence Question
   ↓
Dynamic Tool Selection

==================================================
六十九、必须测试 Evidence Queue 的动态变化
==================================================

初始：

Q1 pending
Q2 pending
Q3 pending

Investigator 选择 Q1：

Q1 selected
→ in_progress
→ answered

工具结果产生新的 gap：

需要实验验证 X→A/B/C

于是：

Q4 pending

更新后：

Q1 answered
Q2 pending
Q3 pending
Q4 pending

下一轮 Investigator
必须重新进行 prioritization。

不能默认：

Q2 是下一个，
只因为它创建得更早。

==================================================
七十、不要把 Evidence Queue 当 FIFO
==================================================

Evidence Queue 不是：

first in
first out

而是：

dynamic scientific investigation queue

每轮都根据：

current hypotheses

existing evidence

new evidence gaps

question discriminative value

tool availability

重新决定：

Q*

所以：

Q1 → Evidence E1

之后，

Q4 可能比原来的 Q2/Q3 更重要。

允许：

Q4

直接成为下一轮 highest-priority question。

==================================================
七十一、Investigator 必须支持 Evidence-aware Reprioritization
==================================================

例如：

初始：

H1:
shared upstream

H2:
cascade

Q1:
shared regulator?

Q2:
A→B?

Q3:
B→C?

Q1 查完以后：

发现 X 同时连接 A/B/C。

那么 Case File 中新增：

E1

和：

Q4:
Is X→A/B/C experimentally supported?

下一轮 prioritization 时，

Q4 可能比 Q2/Q3 优先，

因为它直接验证刚刚获得的
highly discriminating evidence。

实现：

reprioritize_pending_questions(case_file)

不能缓存第一次排序后永远不变。

==================================================
七十二、避免 Confirmation Bias
==================================================

Investigator 不允许：

发现 E1 支持 H1 后，

后续只搜索支持 H1 的 evidence。

Context Builder 必须继续提供：

all active competing hypotheses

以及：

relevant weakening conditions

如果当前 question 的结果：

支持 H1

同时可能挑战 H2，

正常记录。

如果存在合理 counter-evidence question，
允许进入 queue。

==================================================
七十三、Evidence Question 去重
==================================================

不同 Agent / 不同轮次
可能产生语义相同的问题。

例如：

Q4:
Does X regulate A?

Q9:
Is there evidence for X→A?

不要无限增加重复问题。

实现：

deduplicate_evidence_questions(...)

第一版可以：

canonical entity relation extraction
+
normalized text
+
optional backend semantic check

如果判断重复：

不要删除旧问题。

新 question 可以：

status="cancelled"

reason="duplicate_of:Q4"

并写入 history。

==================================================
七十四、Evidence Record 去重
==================================================

同一篇论文或同一 GRN edge
可能通过不同 query 被多次检索。

不要创建完全重复的 EvidenceRecord。

实现：

evidence_fingerprint

例如 literature：

paper_id
+
claim_tested
+
experiment identifier

network：

network_name
+
source
+
target
+
edge_type

dataset：

dataset_id
+
query specification
+
cell subset

如果 evidence 已存在：

建立新的 question→evidence link，

不要复制 evidence body。

==================================================
七十五、Evidence 与 Question 应为多对多关系
==================================================

一个 EvidenceRecord
可能回答多个 EvidenceQuestions。

例如：

实验：

X knockout simultaneously changes A/B/C

可能同时回答：

Q4:
Does X regulate A?

Q5:
Does X regulate B?

Q6:
Does X regulate C?

因此 Case File 应允许：

EvidenceRecord.question_ids[]

而不是强制只有：

question_id

如果当前 Case File v0.1
只支持单 question_id，

不要直接破坏 schema。

优先增加兼容字段：

primary_question_id

related_question_ids[]

并做好 schema migration/version bump。

==================================================
七十六、不要让 Investigator 无限自动扩张 Queue
==================================================

Follow-up question 很容易爆炸。

所以每个 Investigator run：

max_new_followup_questions

默认：

2

一个 EvidenceRecord
最多产生少量最关键 follow-up questions。

生成 follow-up 前必须回答：

“Does this question directly address a newly exposed
evidence gap relevant to current competing hypotheses?”

如果只是：

“顺便还可以看看 gene D”

不要创建。

==================================================
七十七、Evidence Depth
==================================================

为 EvidenceQuestion 增加可选：

investigation_depth

例如：

screening
verification

----------------------------------
screening
----------------------------------

用于快速判断：

有没有候选关系？

例如：

GRN shared regulator query。

----------------------------------
verification
----------------------------------

用于验证：

这个具体关系是否有更直接证据？

例如：

targeted literature experiment verification。

这样一个典型 trajectory 可以是：

Q1 screening:
Is there a shared regulator?

↓ GRN

X identified

↓

Q4 verification:
Is X→A/B/C experimentally supported?

↓ Literature

Evidence

避免一开始就对所有可能 regulator
做昂贵的深度文献搜索。

==================================================
七十八、Negative / Null Evidence
==================================================

必须区分：

1. evidence of absence

和：

2. absence of evidence

例如：

实验明确报告：

A knockout does not change B
with sufficient power

这可以成为：

potential challenging evidence

而：

literature search did not find A→B

只能是：

absence of retrieved evidence

不能自动 challenge H。

EvidenceRecord 可增加：

negative_evidence_type:

explicit_null_result
not_found
not_applicable

==================================================
七十九、Context Match
==================================================

同一个 regulatory relation
在不同 context 可能不同。

例如：

A→B

在：

HEK293

有直接证据，

当前 case：

K562

那么：

directness = direct

但：

context_match = partial / mismatched

不要因为 context 不同
把 directness 改成 indirect。

这两个维度必须分开。

==================================================
八十、Claim Granularity
==================================================

EvidenceRecord 的 claim
必须尽量具体。

不好：

“Pathway X supports H1.”

好：

“CRISPR knockout of X reduced A expression
in K562 cells.”

Investigator 再记录：

supports_hypotheses=[H1]

不要把 hypothesis 本身
直接当 evidence claim。

==================================================
八十一、Case File Mutation Transaction
==================================================

一次 Investigator run
可能同时：

更新 question status

增加 EvidenceRecord

增加 EvidenceGap

增加 follow-up question

更新 ActionState

写 history

这些操作应尽量作为一个事务提交。

如果中途 validation failure：

不要出现：

EvidenceRecord 已写入
但 question 仍然 in_progress

这种半更新状态。

实现：

CaseFileTransaction

或等价的：

copy → validate → commit

机制。

==================================================
八十二、Crash Recovery
==================================================

Tool call 可能失败。

如果：

TOOL_CALL_STARTED

之后进程崩溃，

重新 load Case File 时：

question 不应永久卡死。

支持：

recover_stale_in_progress_questions(...)

根据 run_id / transaction state
恢复为：

pending

或：

unresolved

并写 history。

第一版做简单实现即可。

==================================================
八十三、可重复运行
==================================================

如果同一个 Investigator run_id
被重复提交，

不要重复创建：

EvidenceRecord
Follow-up Question
History Event

实现基本 idempotency guard。

==================================================
八十四、人工介入接口
==================================================

v0.1 预留：

human_override

但不要实现复杂 UI。

允许用户：

manually_prioritize_question(question_id)

manually_cancel_question(question_id)

manually_add_evidence_question(...)

这些操作必须：

actor="human"

写入 history。

Investigator 下一轮读取新的 Case State。

==================================================
八十五、不要自动替用户做最终科学判断
==================================================

Evidence Investigator 的输出应该是：

“这里获得了什么证据”

而不是：

“因此机制就是 H1。”

例如最终输出：

Evidence E17:
A direct perturbation experiment is consistent with
X regulating A in K562.

Evidence E18:
No context-matched direct evidence was identified for X→B.

Evidence Gap G4:
Shared regulation of B remains unresolved.

而不是：

“H1 is probably correct.”

==================================================
八十六、建议 README 中解释一个完整例子
==================================================

README 用一个 synthetic case 展示：

Clue:
A+ B- C+

↓

Explorer:

H1:
shared upstream

H2:
cascade

↓

Evidence Queue:

Q1:
shared regulator?

Q2:
A→B?

↓

Investigator prioritizes Q1

↓

Network query:

X→A
X→B
X→C

↓

Evidence E1:

network architecture consistent with H1

↓

Follow-up Q3:

Is X regulation experimentally supported?

↓

Case becomes:

critique_needed

这个例子只展示 Investigator 的职责，
不要在 README 中继续模拟 Critic verdict。

==================================================
八十七、最终验收标准
==================================================

Evidence Investigator v0.1
只有满足以下条件才算完成：

1. 能读取 Explorer 已建立的 Case File；

2. 能识别 pending Evidence Questions；

3. 能对 questions 做结构化 priority assessment；

4. 不使用固定 FIFO；

5. 能动态选择 Q*；

6. 能将 Q* operationalize 为 QueryPlan；

7. 能根据问题选择：
   dataset / network / literature；

8. 三类工具接口彼此解耦；

9. 至少有 MockDatasetTool、
   MockNetworkTool、
   MockLiteratureTool；

10. 能执行 tool call 并处理：
    success
    no_result
    insufficient_data
    failed；

11. 能将 raw result
    转成结构化 EvidenceRecord；

12. EvidenceRecord 有完整 provenance；

13. Dataset evidence 保留 support / uncertainty；

14. Network evidence 不被升级成 causal fact；

15. Literature co-mention
    不被升级成 direct evidence；

16. No result
    不被升级成 negative evidence；

17. 可以创建 EvidenceGap；

18. 可以根据新 evidence
    创建少量 follow-up questions；

19. follow-up 有完整 lineage；

20. Evidence Queue 可以动态 reprioritize；

21. 支持 question/evidence 去重；

22. 有 tool-call budget；

23. 不允许 Investigator 创建 hypothesis；

24. 不允许 Investigator修改 hypothesis verdict；

25. 不允许 Investigator 修改 ClueRecord；

26. 能在关键 evidence 获得后
    设置：

    ActionState.current_phase =
    "critique_needed"

    ActionState.next_actor =
    "critic"

27. Critic 即使尚未实现，
    Investigator 也能正常结束；

28. 所有关键操作写入 append-only history；

29. Case File 保存/重新加载后
    reference integrity 保持；

30. 所有 synthetic tests 通过。

==================================================
八十八、当前版本的设计原则
==================================================

README / design doc 最后明确写：

Evidence Investigator v0.1 的核心不是：

“给每个 hypothesis 搜很多资料。”

而是：

“选择当前最能区分 competing hypotheses 的
Evidence Question，
调用最合适的证据工具，
获得可追踪、可审计的 Evidence Record。”

整个职责链为：

Mechanism Explorer
    ↓
What could explain the clue?
    ↓
Hypotheses + Predictions
    ↓
Evidence Questions
    ↓
Evidence Investigator
    ↓
What evidence should we acquire next?
    ↓
Dynamic Question Selection
    ↓
Dynamic Tool Selection
    ↓
Evidence Record
    ↓
Case File
    ↓
Mechanism Critic（未来实现）

特别强调：

Explorer 管理 hypothesis space。

Investigator 管理 evidence acquisition。

Critic 未来负责 evidence evaluation
和 investigation routing。

不要让三个角色互相吞并职责。

==================================================
八十九、设计文档
==================================================

实现代码的同时保存设计正文：

docs/agents/evidence_investigator_v0.1.md

内容至少包括：

1. Role
2. Inputs
3. I1–I5 Protocol
4. Evidence Queue
5. Prioritization Policy
6. QueryPlan
7. Tool Registry
8. Dataset Evidence
9. Network Evidence
10. Literature Evidence
11. EvidenceRecord
12. EvidenceGap
13. Follow-up Questions
14. Agent Boundaries
15. Audit / Provenance
16. Synthetic Tests
17. Acceptance Criteria

不要只把设计留在代码注释里。

==================================================
九十、实现顺序
==================================================

不要一开始连接真实外部数据库。

按下面顺序开发：

Phase 1:
Case File compatibility
+
Question Prioritization
+
QueryPlan

Phase 2:
Tool Registry
+
三个 Mock Tools

Phase 3:
Evidence Normalization
+
EvidenceRecord
+
EvidenceGap

Phase 4:
Dynamic Queue Reprioritization
+
Follow-up Questions
+
Budget

Phase 5:
Synthetic end-to-end tests

Phase 6:
再考虑接真实 Dataset / GRN / Literature backend

完成 Phase 1–5 后先停止。

输出测试报告和 demo，
不要未经确认继续连接真实外部 evidence sources。
