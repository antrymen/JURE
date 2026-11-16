# Explorer initial-pairwise-v1

只改变 Explorer 初始提案的内部接口。科学主流程仍是 `Explorer → Investigator → Critic(C1 → C2)`；C1 不前置。新接口目前供独立 Explorer smoke 使用，没有切换历史 pilot 或重置 A 的调查状态、假说与预算。Reframe 继续保留现有接口，本版本不声称解决 revision contract。

## 两轮内部任务

1. `initial_hypotheses`：Explorer 生成 mechanistic question、假说及其 rationale、结构、限制和自身 predictions。输出不含 ID、lineage、alternative 或 comparison matrix。
2. 程序按数组位置枚举所有无序 pair。`initial_pair_design` 一次接收完整固定表单，逐项填写各 pair 的科学差异、observable、两方 expectations、prediction 关联和三个 outcome。三个假说对应三个必填 pair，四个假说对应六个；不增加模型请求次数。

每个 pair 的两方由程序固定，因此另一方就是合法 alternative，模型不能选择自身或换成另一个 pair。模型仍须选择该 question 实际对应哪些已有 predictions；程序不会自动宣称所有 predictions 都被测试。未被任何 question 覆盖的 prediction 阻止提交，留给 Explorer 修订。

每个 pair 有三个必填 outcome 槽，分别绑定唯一类别：`FAVORS_FIRST`、`FAVORS_SECOND`、`NON_DISCRIMINATING`。每个槽都需要 Explorer 提供 observation、reason 和 interpretation limit。缺少任何内容都不补写。类别互斥不证明文字中的科学判断合理；文字与类别在科学含义上是否一致，仍由调查后的 Critic 审核。

## 确定性编译与内容保留

程序分配 H/P/Q ID、clue lineage、pair/alternative 引用和 capability ID。科学文本逐字段复制，独立从编译结果反向提取，与两轮输入比较及计算哈希。假说 rationale 保存在现有 hypothesis `reason` 及其历史事件；outcome reason 通过向 `PossibleOutcome` 添加可选字段保留到 question discrimination，兼容没有该字段的旧记录。

为兼容现有 Investigator/Critic 数据模型，互斥类别确定性编译成旧的 favors/non_discriminating 字段。`FAVORS_FIRST` 只生成 favors first，不附加 weakens second；偏向一方不自动等于反驳另一方。没有补写科学差异、expected results、理由或限制。

全部 pair 完成并通过原有 machine/completeness gate 后，才由现有 `MechanismExplorer` 原子提交。第二轮失败不会把第一轮写成已提交 proposal。程序只返回下一执行者 Investigator；smoke 不执行 Investigator。

## 离线审计边界

历史 S3/S4/S5 保留原始输出和来源哈希。可以依据 hypothesis/prediction 数量生成新表单，但不能把没有填写的科学内容补齐。旧输出没有独立 stage B/outcome reason，因此不能宣称它们已通过新接口。合成测试证明新 schema 可表达完整设计、会拒绝指定结构错误；不代表 GLM 的真实通过率或机制比较质量。

## 下一轮 smoke

配置：`configs/explorer_pairwise_smoke_v1.json`。固定沿用旧 S1–S5，分别覆盖 enrichment、depletion、stable-core、signed-state contrast、gene-disjoint context。仍然只有 **5 个输入**；每个最多两次内部请求，总上限 **10 次模型请求**。第一轮失败则不调用第二轮。模型为 `glm-4.7-flash`，不重试、不替换输入、不增加样本、不回退昂贵模型。

只报告 machine contract、pair coverage、no self-alternative、outcome consistency、content retention；同时保留 provider availability、完整返回和阶段通过的各自分母。Provider 失败不算科学失败，也不据此发布真实通过率。没有真实 evidence tools、Investigator 或 Critic 调用，历史 pilot 不写入。

准备命令不访问网络：

```bash
.venv/bin/python -m jure.runtime.pairwise_smoke prepare --output <new-smoke-directory>
```

本轮只准备，尚未运行。Provider 可用后，在冻结目录执行 `run`，通过隐藏输入提供 key。运行后不自动追求更多样本，也不自动启动 Case A；先按上述五项检查结果。若要继续 A，沿用其现有 Investigator checkpoint 和剩余预算，不能用 smoke 或新 initial 接口偷偷替换 A 的已提交假说。
