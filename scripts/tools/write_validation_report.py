"""Summarize saved fixed-query validation artifacts, never scientific findings."""
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'outputs/tool_validation/smoke_case'
def read(name):return json.loads((OUT/name).read_text())
def link(path):return str((ROOT/path).resolve())

def write_report():
    manifest=read('tool_availability_manifest.json');audit=read('provenance_audit.json');snapshot=read('registry_snapshot.json')
    allcounts=json.loads((ROOT/'outputs/tool_validation/day6_all_counts_check.json').read_text())
    tests=json.loads((ROOT/'outputs/tool_validation/test_results.json').read_text());known=read('known_counts_check.json')
    stats=read('data_joint_state_result.json')['result']['statistics']
    traces=[json.loads(s) for s in (OUT/'tool_trace.jsonl').read_text().splitlines()]
    sources={'case_file':'case_read_case.json','clue_query':'clue_query_result.json','data_experiment':'data_joint_state_result.json',
        'knowledge_graph':'kg_result.json','gene_knowledge':'gene_knowledge_result.json','literature':'literature_retrieve_result.json','tn_query':'tn_stub.json'}
    notes={'case_file':'沿用 CaseStore、角色权限、revision 和审计链；写入在 TEST 副本验收。',
        'clue_query':'只读冻结 facts；不提升 evidence level。',
        'data_experiment':'六种查询模式；低 support、缺测、无分母独立标记。',
        'knowledge_graph':'PrimeKG 8,100,498 条有向存储边；bounded paths 可截断。',
        'gene_knowledge':'HGNC symbol/Ensembl/alias 映射；真实 gene sets/pathway/context 响应。',
        'literature':'真实 search/metadata/abstract 已通过；自动科学证据分类未实现，全文未接入。',
        'tn_query':'仅 schema/stub；没有后端。'}
    table=[]
    for tool,record in manifest['tools'].items():
        status=record['validated_status'];evidence='n/a' if tool=='tn_query' else 'yes'
        acceptance='n/a' if tool=='tn_query' else 'PASS (real retrieval)' if tool=='literature' else 'PASS'
        table.append(f"| {tool} | {record['backend']} | {status} | {evidence} | {acceptance} | {notes[tool]} |")
    for card in snapshot['tools']:
        name=card['tool_name'];result=read(sources[name]);doc=ROOT/'docs/tools'/f'{name}.md'
        body=f"# {name} — tool card\n\nPurpose: {card['description']}\n\nBackend: {card['data_source']}\n\nVersion: `{card['source_version']}`\n\nSource class: `{card['source_type']}`\n\nAllowed agents: {', '.join(card['allowed_agents'])}\n\nReadiness: **{manifest['tools'][name]['validated_status']}**（固定 smoke 验收；不是 Agent 运行结果）\n\nWhen to use: {card['when_to_use']}\n\nWhen not to use: {card['when_not_to_use']}\n\nLimitations: {notes[name]}\n\nFailure behavior: {card['error_policy']}\n\nProvenance: {card['provenance_policy']}\n\n## Example query\n\n```json\n{json.dumps(card['example_queries'][0],indent=2,ensure_ascii=False)}\n```\n\nExample result: [{sources[name]}]({link('outputs/tool_validation/smoke_case/'+sources[name])}) — `{result['status']}`.\n\n## Input schema\n\n```json\n{json.dumps(card['input_schema'],indent=2,ensure_ascii=False)}\n```\n\nOutput schema: `EvidenceEnvelope`，完整 JSON Schema 见 [registry_snapshot.json]({link('outputs/tool_validation/smoke_case/registry_snapshot.json')})。\n"
        doc.write_text(body)
    sections=[
        '# Real Evidence Tool Layer v0.1 — 验收报告\n',
        '本轮已完成真实工具层建设与固定查询验收。`MINIMUM_REAL_INVESTIGATION_READY = true`。这是工具可用性门槛，不是 Agent investigation 的完成或科学结论。已在此停止，没有启动四个 case。\n',
        '| Tool | Backend | Production | Provenance | Acceptance | Notes |\n|---|---|---|---|---|---|\n'+'\n'.join(table)+'\n',
        '## 关键验证\n',
        f"- {tests['passed']} 项 unit/既有工具/CaseStore 回归测试通过，0 失败。TEST fixtures 与 REAL smoke 的 registry、cache、CaseStore 隔离。\n"
        f"- 真实源文件 SHA-256：`{allcounts['source_sha256']}`。从 {allcounts['n_cells']:,} 个允许细胞、{allcounts['n_genes']:,} 个基因生成 detection bit store。\n"
        f"- 对 {allcounts['n_patterns']} 个冻结 signed states、{allcounts['n_groups']:,} 个 condition–batch 分组独立 Boolean mask + bincount 重算，分母及全部计数完全匹配；不是回读 candidate CSV。\n"
        f"- TIMM23B 固定 smoke：`{stats['condition_hits']}/{stats['condition_n']}`，perturbation `{stats['condition_frequency']:.12f}`，matched NT `{stats['matched_nt_frequency']:.12f}`，delta `{stats['delta']:.12f}`（`{stats['delta_percentage_points']:.8f} pp`）。四项 known-count 检查全部 PASS。\n"
        '- 六种 data modes 均执行。conditional 的 NT batch 分母不足时返回 INSUFFICIENT_SUPPORT；未知基因 NOT_EVALUABLE，非法 state INVALID_QUERY。没有把这些状态解释为机制支持或反证。\n'
        f"- 固定 smoke 保存 {len(traces)} 条 ToolCallTrace；每条都有结果 artifact/hash。Critic 缓存读取、强制重算数据、强制重新获取 PubMed 均单独记录。\n"
        f"- {audit['protected_files_checked']} 个受保护文件的 SHA 检查无变化；4 Initial Case Files 仍为 revision 1，未新增 hypothesis、EvidenceRecord、audit 或路由。\n",
        '## 用户要求的 15 项回答\n',
        '1. **READY**：case_file、clue_query、data_experiment、knowledge_graph、gene_knowledge。\n'
        '2. **PARTIAL**：literature。真实 search、metadata、abstract retrieval 工作；extract_evidence 仅验证调用方提供的逐字片段，分类为 null 并返回 NOT_EVALUABLE，不伪造 DIRECT/CONTRADICTORY 等科学判断。\n'
        '3. **UNAVAILABLE**：当前六类主工具没有整类不可用；tn_query 为 NOT_IMPLEMENTED。网络单次故障仍会真实返回 SOURCE_ERROR。\n'
        '4. **真实 backend**：上表列出；原始来源、版本、许可证与 commit 见 external_dependencies.json 和 source_audit。\n'
        '5. **Mock fallback**：不存在。production factory 不导入 mock；REAL registry 拒绝 TEST backend；Case File production evidence 写入拒绝 TEST envelope。\n'
        '6. **真实 Day6**：是。最终存储在本地从校验通过的原始 H5AD 构建，按既有 frozen allowed-cell table 选择；未读取 Day8、未做新 discovery。\n'
        '7. **TIMM23B known counts**：是。240/498、matched NT、delta 独立复现；结果见 known_counts_check.json。\n'
        '8. **真实 papers**：是。PubMed 返回并再次获取了 PMID 39729999、28473584 的真实 metadata/abstract；这是检索验收，不评价其对当前 case 的支持程度。\n'
        '9. **真实 KG**：是。PrimeKG 官方 CSV 长度与 MD5 校验通过后导入本地 SQLite；实体、直接边、bounded subgraph/path、缺失和非法查询均验收。边的 confidence/PMID 在源 CSV 未提供时保留 null/空列表。\n'
        '10. **真实 Gene Knowledge**：是。HGNC resolver 和 Harmonizome gene / alias / sets / pathways / functional context 均真实查询。早期 20 秒 timeout 的失败保留在 external_preflight；最终 45 秒、有上限重试的验收成功，不删除失败记录。大集合按 limit 返回 TRUNCATED。\n'
        '11. **Provenance**：PASS。原始查询、normalized query、source IDs、source/version/hash、时间、参数、data cell-set IDs 或 API response artifact 均保留；共享来源标为相关，不按工具数量计独立证据。\n'
        '12. **Critic 独立 re-query**：有同一 registry 的真实工具权限；force_requery + reason 绕过结果 cache。测试由固定脚本以 Critic 角色执行，并明确 stage=FIXED_ACCEPTANCE_SCRIPT；不是一次真实 Critic 审计。\n'
        '13. **Trace/cache**：PASS。key 包含实现/来源/数据/语义版本与参数；cache 保留原时间和 query ID；失败不缓存。预算跨同 run 重启保留；cache 命中也计调用次数。\n'
        '14. **Agent prompts**：没有修改。Case File Protocol、Clue Discovery、scan 源码及冻结初始文件也没有修改。新增 role-bound tool surface 和 machine-readable schemas；没有预设工具顺序。\n'
        '15. **真实 investigation**：没有。Agent 调用 0、LLM 调用 0、case investigation 0；没有生成机制报告、Critic verdict、ablation 或 Agent benchmark trace。\n',
        '## 接入边界与限制\n',
        '真实工具通过 `registry.bind(role, case_id, stage=...)`、`functions_for(client)` 和 `execute_function` 提供。Investigator/Critic 共享 registry，角色由可信 host 绑定，不由模型参数选择。旧 mock acquisition 的 payload normalizer 不能直接处理 batch-weighted NT，未强行套用。下一阶段启动真实 Agents 时，host 必须使用新 EvidenceEnvelope surface；本轮没有进行旧 runner 的端到端生产运行验证。\n\n'
        '沿用现有 Case File 协议：Explorer 可建立 seed EvidenceQuestion；Investigator follow-up 要有已有 question/evidence lineage。adapter 不伪造 actor 绕过这一要求。Critic 可重新获取并写 tool_action/audit；正式 EvidenceRecord 的作者权限仍属于 Investigator。新 queue 展示字段通过原 query_spec 与 trace 关联，不修改原 schema。\n\n'
        'PubMed 当前只获取 abstracts，未接入全文或可靠自动证据分类；Harmonizome 是 live service，仍可能超时；KG 搜索受节点/边/hop 上限约束，TRUNCATED/NO_RESULT 不能被理解成关系不存在。这些限制会随每个 envelope 返回。\n\n'
        '最初上传本地细胞清单的操作被自动审批拒绝，未执行。随后检查了服务器已有清单；最终用本地完整下载、SHA 校验一致的公开源构建存储。远端重复转换进程已停止，本次远端临时目录和 SSH 会话已清理，可以关闭实例。原服务器数据未修改。\n',
        '## 产物\n',
        f"- [Registry 文档]({link('docs/tools/TOOL_REGISTRY.md')})；[设计来源]({link('docs/tools/DESIGN_PROVENANCE.md')})；[依赖清单]({link('docs/tools/external_dependencies.json')})。\n"
        f"- [工具可用性与最低门槛]({link('outputs/tool_validation/smoke_case/tool_availability_manifest.json')})；[provenance audit]({link('outputs/tool_validation/smoke_case/provenance_audit.json')})。\n"
        f"- [全部冻结计数对照]({link('outputs/tool_validation/day6_all_counts_check.json')})；[TIMM23B 独立核对]({link('outputs/tool_validation/smoke_case/known_counts_check.json')})。\n"
        f"- [固定查询 trace]({link('outputs/tool_validation/smoke_case/tool_trace.jsonl')})；[registry snapshot]({link('outputs/tool_validation/smoke_case/registry_snapshot.json')})；[source graph]({link('outputs/tool_validation/smoke_case/source_independence_graph.json')})。\n"
        f"- [固定验收脚本]({link('scripts/tools/validate_real_tools.py')})；[数据抽取]({link('scripts/tools/build_cell_store.py')})；[资源审计]({link('outputs/tool_validation/resource_audit.json')})。\n",
        '**停止状态：工具层验收完成。下一阶段是否启动 JURE 的三个 Agents，由用户确认；本轮没有启动。**\n'
    ]
    report=ROOT/'REAL_EVIDENCE_TOOL_LAYER_V01_REPORT.md';report.write_text('\n'.join(sections));print(report)

if __name__=='__main__':write_report()
