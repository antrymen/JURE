# Molecular Chain v1 提示词入口

2026-10-05 起，当前 Codex 原生三 Agent 调查使用 `COMMON.md` + 对应角色文件：

- `EXPLORER.md`：数量不固定的具体机制链，逐基因桥接。
- `INVESTIGATOR.md`：逐边数据/GRN/文献取证，追查关键断点。
- `CRITIC.md`：逐边审核，定向返回 Explorer 或 Investigator。

可运行 `python -m jure.agents.molecular_chain_prompts explorer`（或 investigator、critic）导出完整角色提示词。在派发子 Agent 时，将导出的完整提示词与真实输入路径、可用能力及预算一起提供；不再使用历史运行脚本中固定 H1/H2/H3 的生成模板。

本次为提示词与原生子 Agent 交接格式更新，没有重跑十五个案例，也没有把历史调查重新判为新协议结果。

## 旧 API runtime 兼容边界

旧 GLM/API runtime 使用冻结 prompt hash、至少两个假说和 pairwise 验证器。此版本不直接覆盖那些历史协议或其 schema；新提示词的单假说/空列表、edge/gene-bridge 输出不能不经适配就传入旧验证器。上述导出入口用于当前用户指定的 Codex 原生子 Agent 流程。若以后启用旧 API runtime，需另行迁移相应 schema、验证器、路由和冻结配置，不能只更换 system string 后宣称兼容。

## 验收标准

允许一条有具体内容的候选链，不凑三个；无合理候选可返回空。不以细胞组成/检测机制凑备择。泛化过程不能作为终点。每个 clue gene 有独立桥接，未知边显式保留。Investigator 的每项证据对应明确边；Critic 的退回必须对应明确断点。可查缺口继续查，不可查缺口诚实停止。
