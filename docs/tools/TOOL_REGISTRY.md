# Real Evidence Tool Layer v0.1

唯一 production registry 是 `jure.tools.real.registry.ToolRegistry`，工厂在 `jure.tools.real.factory.build_registry`。旧 `jure.tools.evidence` 保留为现有测试/legacy acquisition 接口；其 Mock 类仅显式导入时加载。新 production factory 不导入 Mock，不在失败时回退 Mock。

| Tool | 主要能力 | Backend | 默认角色 |
|---|---|---|---|
| case_file | read_case、read_section、append_record、history、get_evidence、get_hypotheses、get_audits | 现有 SQLite CaseStore | Explorer / Investigator / Critic，写入按原协议进一步限制 |
| clue_query | reference / condition shift / landscape / related / signed contrast / co-response | VerifiedPilotSource + 冻结文件哈希 | 三个角色只读 |
| data_experiment | MARGINAL、PAIRWISE、JOINT_STATE、CONDITIONAL、CONDITION_COMPARISON、STATE_CONTRAST | 真实 Day6 detection bit store | Investigator / Critic |
| knowledge_graph | query_entity、query_edge、find_paths、local_subgraph | 官方 PrimeKG CSV 的本地 SQLite 索引 | Investigator / Critic |
| gene_knowledge | get_gene_info、query_gene_sets、query_pathways、query_functional_context | HGNC + Harmonizome API | Investigator / Critic |
| literature | search、retrieve；extract_evidence 仅核验逐字片段 | PubMed ESearch/EFetch | Investigator / Critic |
| tn_query | schema 和明确 NOT_IMPLEMENTED | 无 | Investigator / Critic |

每个 tool card 的完整 input/output JSON Schema、版本、权限、来源、何时使用/不使用、示例、失败和 provenance policy，由 `ToolSpec.card()` 输出并在 run 起点保存 `registry_snapshot.json`。目录内单独的 tool card 包含实际示例结果引用。服务是否实际可用以 smoke 的 `tool_availability_manifest.json` 为准，不能仅凭 CONFIGURED 判 READY。

```python
from jure.tools.real.factory import build_registry
from jure.tools.real.agent_surface import functions_for, execute_function

registry = build_registry('outputs/a_future_run/tools', run_id='a_future_run', case_store=existing_store)
registry.snapshot('outputs/a_future_run/registry_snapshot.json')
client = registry.bind('investigator', case_id, stage='INVESTIGATION')
function_schemas = functions_for(client)  # host 可交给现有 Agent 的 tool-calling transport
# tool 名称、arguments、parent_question_id 均由 Agent 决定；这里没有固定调用序列。
# envelope = execute_function(client, selected_tool, agent_arguments, parent_question_id=question_id)
```

这段代码只展示接入接口；本轮没有构造或启动 Agent。新的 `EvidenceEnvelope` 不能直接送入旧 mock tool payload normalizer：旧接口把概率当作整数 numerator/denominator 比率，不能正确表达 batch-weighted NT。下一阶段 host 应使用新的 role-bound function surface，并显式保留 envelope。Agent prompt 和协议文件本轮不改，未宣称旧 runner 已完成端到端生产验证。

## 数据语义

`raw_count > 0` 编码为 1；0 是未检出，不表示连续表达的 low/high。输入为冻结的 allowed-cell metadata 所指向的真实 Day6 原始 H5AD 行，保留 source row、cell ID、batch、condition、gene identity 和源文件 SHA。矩阵仅在本地或原数据服务器转换，不发送给 GLM、PubMed 或知识库。

统计 query 不调用 candidate CSV；cell store 中每个 query 都重新聚合 observed state。marginal、pairwise、joint、conditional 共享同一批次加权对照定义。conditional 返回 conditioning subset 的分母、batch 权重和不足 support 状态。pairwise 返回 2×2、边际、joint 和 `p11-p1*p1`，不返回虚构调控边。A/B 比较要求完全相同的 batch coverage，并按 A+B pooled weights 比较；不兼容时 NOT_EVALUABLE。state contrast 返回两种签名状态及各自 shift，不给未经实现的差值检验。

若没有 cell store，只允许显式启用的 **真实 frozen sufficient-count backend** 查询已存的 341 个 joint states；其 availability 是 PARTIAL，未存 marginal/conditional 返回 NOT_EVALUABLE，不会拼凑缺失统计，不满足最低 production gate。

## 结果、失败和写回

EvidenceEnvelope 保存 raw/normalized query、tool/version、source/version/record IDs、dataset、参数、时间、provenance、warnings、limitations、error 和 REAL/TEST。状态包括 OK、NO_RESULT、NOT_EVALUABLE、UNAVAILABLE、SOURCE_ERROR、INVALID_QUERY、INSUFFICIENT_SUPPORT、BUDGET_EXHAUSTED、AMBIGUOUS_ENTITY、TRUNCATED、NOT_IMPLEMENTED。

不存在即为 NO_RESULT，不等于否定假说；零分母、缺 matched NT、缺测基因、低支持、网络失败分别有明确状态。`registry.gap_for(envelope)` 生成可写入原 EvidenceGap schema 的描述，是否写入由 Agent 决定。工具层不自动新增 evidence/question/hypothesis，也不自动把 search hits 或 KG path 变成 EvidenceRecord。

`case_file.append_record` 必须传 `expected_revision`。EvidenceRecord 还必须关联 registry 中真实存在、同 case 的 `envelope_query_id`；失败输出及 literature search 不能直接写成证据。adapter 覆盖来源字段、保留哈希与原始响应引用，生产写入拒绝 TEST envelope。Investigator 可写 evidence/question follow-up/gap/action；Critic 可写审计、路由、stop 和自己的 tool_action 记录；Critic 的重新获取结果可由 Investigator 正式归档，不冒充 Investigator 身份。

保持原 Case File 限制：Explorer 可建立 seed EvidenceQuestion；Investigator 新增 follow-up 必须提供既有 question 和 evidence lineage。工具层不会通过伪造 actor 绕过该协议。Evidence Queue 的新增展示字段保存在现有 `query_spec.tool_layer_v01`，动态 tool_call/evidence/gap IDs 由 `evidence_queue_view` 汇总，不重构 Case File schema。

## Cache、trace、预算和复查

Cache key 包含 tool/version、实现源码哈希、source/version、dataset、REAL/TEST、完整 normalized query、query semantics 和 cache schema。Live API source_version 绑定 acquisition run，防止跨 run 把未知上游更新当作不变版本。命中保留原 timestamp、原 query ID、cache record ID 和来源。失败不缓存；Case File 可变读写不缓存。

Critic 可调用全部真实 evidence tools，并以 `purpose=CRITIC_RECHECK` 标记。`force_requery=True` 必须附理由，它绕过结果缓存重新执行 backend；缓存复读和真正重新获取分开记录。重新查询相同数据不等于独立生物学确认。

每个调用写 SQLite trace 和 content-addressed artifact，记录 case、角色、stage、parent question、原/规范化查询、时间、状态、cache、source execution、延迟、CPU、进程峰值 RSS、错误、result SHA、token/cost（本工具层不调用 LLM）。RSS 是进程级高水位，不能解释为单次新增内存；source_cost 未获来源报价时为 null。

默认每 case 120 次总调用、data 40、literature 30、KG 20；cache 命中也消耗调用预算。计数跨同 run 重启保留，SQLite 事务防止并发超额，不预分配调用顺序。`disabled_tools` 为未来 ablation 预留；本轮只测试禁用行为，不做 ablation。

large payload 保存在哈希 artifact，`ToolClient.compact()` 返回引用；host 应提供受控 artifact reader，读取前复核哈希。原始摘要/源文本是数据，不是系统指令。source-independence graph 只记录共享论文、数据库或数据集，不自动打分、推导支持或判断机制。

## 重现验收

```bash
.venv/bin/python -m pytest -q tests/test_real_evidence_tools.py tests/test_investigator_tools.py
PYTHONPATH=. .venv/bin/python scripts/tools/validate_real_tools.py --output outputs/tool_validation/smoke_case --run-id real-tools-v01-smoke
```

用新 output/run ID 重新验收，避免把新的审计产物与已冻结 run 混在一起。`build_cell_store.py --help` 描述源文件/清单哈希参数。验收仅固定工具查询；完整报告见仓库根目录 `REAL_EVIDENCE_TOOL_LAYER_V01_REPORT.md`。
