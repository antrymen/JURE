# Evidence Investigator v0.1

Investigator 接收 Explorer 建立的 Case File，选择当前最有区分力且可由工具回答的 Evidence Question，获得可追溯的证据，再交给未来的 Critic。实现限定在 Phase 1–5：全部外部证据来源均为显式标记的离线 Mock。

## 运行

```bash
.venv/bin/python -m jure.agents.investigator.demo
.venv/bin/python -m jure.agents.investigator.demo --input-case path/to/case_file.json --output outputs/investigator_input
.venv/bin/python -m pytest tests/test_investigator_*.py tests/test_casefile_investigator.py -q
```

默认 demo 输出到 `outputs/evidence_investigator_demo/`，其中 `network_first/`、`dataset_first/`、`literature_first/` 分别从不同 Case State 选择相应工具。第三个 Case 已有 network evidence，下一步优先验证新发现的共同上游关系。每个目录包含：

- `input_case_file.json`、`updated_case_file.json`：完整、可重新加载的 Case File。
- `investigator_run.json`：排序理由、QueryPlan、工具调用、创建或关联的证据 ID、warnings 和 routing。
- `investigator_history.jsonl`：该 Case 的完整审计历史导出，SQLite 中的事件始终 append-only。
- `raw_evidence/`：原始工具结果与 SHA-256 引用；Case File 只保存归一化证据。
- `case_store.sqlite`：权威状态。`demo_summary.json` 汇总三个 demo。

## API 与固定协议

```python
from jure.agents.investigator import EvidenceInvestigator, InvestigatorConfig
from jure.agents.investigator.demo import mock_registry

agent = EvidenceInvestigator(registry=mock_registry(), config=InvestigatorConfig(
    max_questions_per_run=1, max_tool_calls_per_run=3,
    min_conditional_support=20, max_new_followup_questions=2,
))
result = agent.run(store, case_id, run_id="INVESTIGATION_001", artifact_dir="outputs/run_001")
```

I1 READ 只读取必要 context，并保持全部 active competing hypotheses 和 weakening conditions。I2 OPERATIONALIZE 将生物学问题转成 `QueryPlan`。I3 PRIORITIZE 使用可解释的 high/medium/low 规则排序；每一轮重新读取证据与缺口，无固定 FIFO 或工具顺序。I4 ACQUIRE 检查 capability、availability、输入和预算。I5 RECORD 通过原有 CaseStore API 写入 EvidenceRecord、EvidenceAssessment、EvidenceGap、follow-up、状态和历史。

Question 经 `selected → in_progress` 后成为 answered、partially_answered、unresolved，或在可重试工具错误时回到 pending。所有中间状态在隔离 CaseStore 内执行，最终通过版本比较和逐事件边界验证一次提交。验证失败无半更新；同一个已完成 `run_id` 重复调用返回原 run artifact。尚无租约式多 worker 调度，进程中断的旧状态可显式调用 `recover_stale_in_progress_questions`。

Mock reasoning backend 支持常见明确查询和 `EvidenceQuestion.query_spec` 中的结构化 operation/inputs；复杂问题若无法操作化会留下 gap。它不能代替通用生物学语言理解。`JSONInvestigatorBackend(transport)` 提供严格结构化四方法接口，模型与传输由宿主注入；不含具体 LLM 名称、SDK 或外部连接。

## 完整示例

已观测 Clue 为 `A+ B- C+`。Explorer 提出 H1 shared upstream、H2 cascade、H3 cell-state composition，给出对应 prediction 和问题。初始 Q1 询问 A/B/C 的共同上游，Q2 询问 cascade 的实验支持，Q3 询问细胞组成解释。

Investigator 判断 Q1 既能区分假说，也能由低成本网络查询回答，优先调用 Network Mock。结果包含 X→A、X→B、X→C，逐边保存来源、方向、版本与查询参数，并注明网络连接本身不证明当前扰动背景下的因果调控。它为 H1 记录局部一致性关系，不修改任何 hypothesis verdict。

随后创建 verification 问题：“X 对 A/B/C 的调控是否有直接实验证据？”问题关联原 Q1 和三条网络证据，进入动态 queue。Case 变为 `critique_needed` / `next_actor="critic"`。若宿主再次调用 Investigator，新问题可先于旧 Q2/Q3 被选中；文献查询分别核实各原子实验，避免用一条 X→A 实验声称整个 X→A/B/C 已验证。这里结束于 evidence acquisition，不模拟 Critic verdict。

## 科学边界与兼容

Dataset wrapper 复用 Clue Discovery 的经验频率/shift，实现计数、条件比较、Fisher 检验和 Wilson 区间；支持量阈值可配置，分母不足会保留不稳定性。统计关联不解释为因果机制。Network 输出为候选连接。Literature 的 RetrievedItem 与 VerifiedEvidenceCandidate 分开；共现不能提升为 direct。实验直接性和背景匹配分别记录；未知/不足支持不擅自升为 sufficient。未检索到结果与显式有充分检验能力的 null result 分开。可比实验发生冲突时保留各证据和 open contradiction，交由 Critic 判断。

复用 Shared Case File `0.1.1`，保留 `0.1.0` 读入兼容和原审计事件。单问题 `question_id` 保留，`related_question_ids` 支持多对多链接；支持/挑战关系复用 `EvidenceAssessment`，含 hypothesis revision / prediction 引用。Question 和 evidence 指纹用于去重；重复问题取消并保留历史，重复证据仅追加链接。人工优先、取消和新增问题通过 `manually_*` 接口记录 `actor="human"`。

Investigator 无权创建、删除或修改 hypothesis，无权修改 clue、原 prediction、mechanistic question 或 scientific verdict，也不能停止 Case。后端只能返回受 schema 限制的决策，无法直接写入 CaseStore。

完整设计正文与验收要求见 [设计文档](../../../docs/agents/evidence_investigator_v0.1.md)。测试报告和三个真实执行的 demo 见 `outputs/evidence_investigator_demo/`。

Evidence Investigator v0.1 的核心是选择当前最能区分 competing hypotheses 的 Evidence Question，调用合适工具，获得可追踪、可审计的 Evidence Record。Explorer 管理 hypothesis space；Investigator 管理 evidence acquisition；未来 Critic 负责 evidence evaluation 和 investigation routing。
