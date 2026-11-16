# Jev 能力核查与 JURE 接入决定

检索日期：2026-09-27。对象：**TypeSafe Jev**。项目原先没有 JEV 全称/论文链接，已向用户询问是否为该模型；在确认前，本文件为条件性核查，不代表已识别另一个同名生物模型。本轮没有调用 Jev API 或测量其生物任务质量。

## 结论

若 JEV 指 TypeSafe Jev，它适合作为 Broad Screening 的**可选结构化判断 backend**。现有一手资料不支持把它写成 biological foundation representation、gene embedding 模型或表达矩阵 encoder。

合理接口是：`冻结 candidate + 外部检索的功能/关系材料 → Jev 原子分类/判断 → 透明分层选例`。短解释由模板或另一个生成模型完成；Deep 的机制提出与审计继续由 Explorer、Investigator、Critic 负责。这是基于公开接口作出的设计判断，尚非 JURE 实验结论。

## 已核实能力

| 问题 | 一手资料与结论 | 对 JURE 的影响 |
|---|---|---|
| 它是什么？ | 官方称 System One decision model；当前稳定 ID 为 `jev-1.13.0`，`jev-latest` 为可变别名。[介绍](https://docs.typesafe.ai/introduction)、[Models](https://docs.typesafe.ai/models) | 固定版本并记录返回 model；不把它当已验证的生物专用模型 |
| 能接收什么？ | `state` 为文本、JSON object 或 array；自然语言与文本化结构，不是专用单细胞矩阵接口。[State](https://docs.typesafe.ai/concepts/state) | 可传 target、带符号状态、已算出的 shift、实验背景与证据片段；表达计算留在扫描代码 |
| 能返回什么？ | Choice 为预定义选项；Score 为有序量表；Noul 为 yes/no 命题的概率。同一 state 下多问题独立求值；不生成自由文本。[Primitives](https://docs.typesafe.ai/introduction)、[API](https://docs.typesafe.ai/api) | 适合 process/context/evidence 分类；不能直接产出新的 pathway 名、引用正文或机制报告 |
| 是否有 embedding？ | 已审阅官方 API、模型页及文档索引，未找到公开 embedding 输出接口。[API](https://docs.typesafe.ai/api)、[文档索引](https://docs.typesafe.ai/llms.txt) | 暂不定义 `JevEmbeddingBackend`；若做 retrieval reranking，应报告 reranking 效果 |
| 是否有生物示例？ | 官方 hierarchical-classification cookbook 包含 MeSH 生物医学文档分类示例。[Cookbook](https://docs.typesafe.ai/cookbooks/hierarchical_classification) | 说明可以组织该类分类任务；不证明 gene-set annotation、perturbation–gene retrieval 或机制推理准确率 |
| confidence 是什么？ | Choice/Score 的 confidence 由概率分布计算；Noul 没有单独 confidence。[Confidence](https://docs.typesafe.ai/confidence) | 保留原概率；不能将 confidence 写成该生物学结论的正确率，更不能写成机制为真概率 |

官网 2026-09-15 的[发布说明](https://typesafe.ai/blog/introducing-system-one-models-and-jev)包含架构/训练方法 RLCD 的介绍与 workflow 评测。它不是 JURE 生物任务验证；供应商对 schema 合法性的保证不等于科学判断不会出错。官方[能力局限](https://docs.typesafe.ai/model-jaggedness/jev-1.13)也指出数值计算、多跳推理和长而无关的上下文等不足。JURE 的 delta、检验、Day 8 判定与选例配额应由代码处理。

## “最新论文”核查的范围

在本次官网、官方文档及论文检索范围内，未找到 TypeSafe 官方公开的完整 Jev 模型技术论文，也未找到针对 JURE 所需 perturbation / signed gene-set 任务的验证。不能据此断言所有未公开或未索引资料都不存在。

检索到 2026-09-24 的原始研究包括 [Jev in the Wild](https://arxiv.org/abs/2609.30216)（公共项目生态分析）与 [Just Ask Jev](https://arxiv.org/abs/2609.29429)（alignment failure 检测评测）。它们是应用研究，并非生物学表征或扰动响应论文，不能替代我们的领域 benchmark。

## 拟议的原子问题

| 输出 | 问题必须明确限制在提供材料内 | 实现建议 |
|---|---|---|
| `process_labels` | 材料是否支持某个指定的 biological process？ | 每个过程单独判断，允许多个过程；先处理 insufficient_context，不能强制选唯一 pathway |
| `relation_status` | 哪一类已提供的关系材料适用：known、partial、not_found_in_scope、insufficient_context？ | Choice；具体 rubric 写入 instructions，不能只依赖 question key |
| `relation_scope` | 材料支持单基因功能、target→单基因、target→gene set，还是带方向的联合状态？ | Choice；不把 pathway co-membership 升级为 signed-state explanation |
| `context_match` | 材料的物种、细胞背景和扰动方式与当前 case 的匹配情况如何？ | 明确的等级/选项；未知单列 |
| `supporting_source` | 预先检索的哪条来源支持上述待判关系？ | 从提供的 source IDs 中选，含 none；代码检查引用存在，Deep 再审原文 |

所有问题都看到同一份 state、彼此独立；同一调用内不能假设后一个问题会读取前一个答案。需要依赖时由代码分阶段组合。原始材料覆盖不足、model abstention 和请求失败分别计数，不把失败填成“关系不存在”。

Jev 不能承担知识库本身：gene function、pathway annotation 与文献上下文先经独立检索取得；不能仅凭 target 加三个符号就把模型记忆写成有来源的证据。提供材料的可信程度、适用背景和版本仍需保留。

## 是否采用的最小实验

先做同证据包、同病例划分、同 annotation rubric 的三组：确定性规则、轻量 LLM、Jev。模型调用前固定开发集与评价集、来源版本、弃权规则、rubric 和成本核算口径。

报告 process 多标签准确性、关系范围与方向判断准确性、带来源 coverage、弃权后的 coverage–error 曲线、概率校准、端到端延迟与成本。检索、缓存、重试及可选短文本生成都计入总成本。不要用 Jev 自己的概率作为 ground truth，也不要只统计有输出的成功行。

若测试 embedding 的价值，另设真实提供 embedding 的模型与固定 retrieval baseline；Jev 作为分类或 reranking 组件单独消融。若它在相同材料下没有可复现的质量/成本收益，Broad 仍可用规则或轻量 LLM 完成，不为保留模型名字增加依赖。

整体输入合同、分层选例、Day 8 隔离与 Deep 适配见 [Broad Screening 设计](broad_screening_v0.1.md)。
