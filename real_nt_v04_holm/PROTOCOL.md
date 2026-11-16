# Real NT v0.4 + Holm

本次仅运行已准备并校验的 Replogle K562 Essential day 6 的 10,691 个 NT cells，沿用原 GEM-stratified A/B cell split 与各自 fold 的 Fano 排名。该拆分不是 biological replicate。

顺序运行 500 与 1000 genes 的完整 discovery、1000 次 bootstrap、locked validation 与 Holm 校正；不使用 dry-run，不调整搜索或统计阈值。500 genes 为预定规模检查；1000 genes 为预定主 Catalogue。两者复用 cells，不将两套 Catalogue 合并后声称原 family 错误率，也不看结果选择规模。

全部原 v0.4 及 validation-family 源文件与上一轮 synthetic 验收哈希一致。新增适配器使用旧的 own-fold feature moments 选择，并在两侧 discovery 和 testing families 全部冻结后才开始 validation。每方向的所有 locked 三元基因组纳入 Holm，阈值 0.025；missing/poor 保留名额。具体 state 仍须通过原 bootstrap、方向和 pattern 条件。二阶和四阶只保留原始审计。

单进程、单线程，各规模在独立进程中顺序执行；保持 1400 MiB RSS 保护，记录实际 cgroup CPU/内存与 OOM 事件。模拟仍实际执行，仅压缩可复现数组的存储并保留哈希与摘要。失败保留，不扩大预算或改参数后覆盖结果。

导出 `holm_reference_catalogue_frozen.json` 和 `holm_reference_patterns.csv`，包括具体基因及 +/- 状态、分 fold 和 pooled NT support/频率、方向性证据、Holm family 与 adjusted p。Holm-qualified 是新增证据字段，不覆盖原 v0.4 的 primary veto 或掩盖 budget-limited search。未通过 Holm 的原结果仍保留。

pooled NT 频率用于描述。Catalogue 选择已使用这些 NT，因此后续 perturbation significance 必须另行冻结使用独立 control 或处理选择效应的设计，不能把同一 NT pool 自动视作独立留出基线。当前 Catalogue 不是 perturbation-associated clue，不交给 Agent，不声称 state-level FDR 或生物学重复验证。
