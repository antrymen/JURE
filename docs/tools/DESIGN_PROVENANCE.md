# Real Evidence Tool Layer v0.1 — 设计来源

本轮只建设和验收工具，所有 live queries 都来自固定脚本。没有运行 Explorer、Investigator、Critic 或 GLM，也没有生成 case hypotheses、机制解释或终局审计。

| 来源 | 使用方式 | 边界 |
|---|---|---|
| [POPPER](https://github.com/snap-stanford/POPPER) | DESIGN_INSPIRATION：把明确的数据问题交给可执行统计工具 | 没有复制代码、Agent 框架或统计决策流程；官方仓库 API 未识别许可证 |
| [VCR-Agent](https://github.com/valence-labs/VCR-Agent) | DESIGN_INSPIRATION：分别接入 KG、gene knowledge 和 PubMed，保留可定位来源 | 没有复制框架、prompt 或本地 RAG；官方仓库 API 未识别许可证 |
| [PrimeKG](https://github.com/mims-harvard/PrimeKG) / [Dataverse](https://doi.org/10.7910/DVN/IXA7BM) | WRAPPED_BACKEND：官方 kg.csv 导入本地 SQLite | 使用数据，不复制其 Python 框架；代码 MIT，下载数据集元数据为 CC0 1.0；底层聚合来源仍需保留 |
| [Harmonizome API](https://maayanlab.cloud/Harmonizome/documentation) | WRAPPED_BACKEND：原始基因与 association 响应 | API 1.0；实时内容以日期、响应哈希固定；不是独立于上游数据库的确认 |
| [PubMed E-utilities](https://www.nlm.nih.gov/dataguide/eutilities/utilities.html) | WRAPPED_BACKEND：ESearch + EFetch | 真实 PMID、metadata、abstract；没有本地 RAG、自动科学证据分类或全文抓取 |
| [HGNC](https://www.genenames.org/download/statistics-and-files/) | WRAPPED_BACKEND：人类 approved complete set | 符号、Ensembl、别名映射；多义别名拒绝自动选取 |
| JURE CaseStore / VerifiedPilotSource | DIRECT_CODE_REUSE：直接调用现有实现 | Case File Protocol 和冻结发现流程没有修改 |
| JURE `perturbation_scan.statistics.simultaneous_delta_radius` | DIRECT_CODE_REUSE：直接 import 原区间函数 | 保留 nominal pointwise、不作 selection-adjusted 或 confirmatory 宣称 |

Day6 的 matched-control 估计在原 `perturbation_scan.scan.scan` 内联实现，没有可直接 import 的独立 kernel。新工具按同一公式实现 `w=n/N; matched=w@(nt_x/nt_n); effective_n=1/sum(w²/nt_n)`，不修改原 scan；验收用独立 cell-level 重算与冻结 counts 的全部 341 个状态对照。条件查询对 conditioning subset 重定义分母并明示；不冒充原始全细胞估计。

VCR 的本地 PubMedFastRAG 需要额外大型数据库、索引和服务。本轮没有安装它；实际接入的是兼容其 grounded-retrieval 思路的 PubMed API wrapper。因此不能称为“已经集成 POPPER/VCR 原生 Tool”。

Harmonizome [条款](https://maayanlab.cloud/Harmonizome/terms) 原文标示 academic/non-profit 使用，并写作 “CC BY NA SA 4.0”；本仓库不擅自把这一字符串改写成另一许可证。NCBI [免责声明和版权说明](https://www.ncbi.nlm.nih.gov/About/disclaimer.html) 适用于 PubMed 内容；PubMed 收录不等于第三方摘要/全文自动获得再分发许可。

外部仓库的 commit、许可证元数据、依赖、引用和实际接入方式见 `external_dependencies.json`；实际网络检查保存在 `outputs/tool_validation/source_audit/`。
