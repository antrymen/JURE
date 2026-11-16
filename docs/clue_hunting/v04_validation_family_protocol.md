# v0.4 Validation Family 实验协议

目标是隔离 validation multiple-testing correction 的作用，不改变搜索、MFI、Gain、bootstrap、弱信号阈值或 discovery 配额。原始 v0.4 代码的 71 个冻结文件逐一核对哈希。新代码只在 `clue_discovery/v04_validation/` 增加实验与校正层。

## 冻结顺序与 family

先记录代码哈希、全部 case/seed、配置和判定规则；再一次性生成并哈希冻结全部新 synthetic 数据；之后才开始逐个 case 的计算。每个 case 先独立完成 A/B discovery，再冻结两套 locked genes + states 及 testing families，最后进行 A→B、B→A validation。数据真值仅在校正结果写出以后读入，用于评估，不送入搜索器。

每个方向一个三阶 family：**该方向全部 discovery-locked canonical gene sets**。多个具体 states 共用一个 gene-set Gain 检验。不能先看验证侧 support、bootstrap、p 或方向是否通过再选择 family 成员。不可估计、未执行或缺失的成员保留名额，校正计算使用 accounting p=1，输出保留“未检验”，不会把 1 冒充实际测得的 p。

二阶和四阶原始结果可以审计，但不在本次三阶正式比较范围。对锁定状态的最终判定取原 v0.4 raw qualification 与 family-level gate 的交集；原始结果保存，不被覆盖。

## 预定四个比较方案

| Arm | 每方向规则 | 用途 |
|---|---|---|
| raw_05 | 每候选 p_gain≤0.05 | 原始基线 |
| bh_05 | 全 family BH q≤0.05 | 用户要求的主要比较 |
| bh_025 | 全 family BH q≤0.025 | 两方向分配预算的经验比较 |
| holm_025 | 全 family Holm adjusted p≤0.025 | 预先指定的保守参照 |

不将 A/B 两侧看过结果后筛出的候选合并成一个缩小的 family。每方向最多 0.025 的 gene-set FWER，依据 union bound 可给两方向并集最多 0.05 的上界，前提是每个方向的 held-out p-values 有效；不要求两个方向独立。进一步筛选 Holm 拒绝集合不会增加“至少一个假拒绝”的事件概率。

BH 的独立性/PRDS 条件没有在共享基因的所有候选中证明；再经过 bootstrap 或 pattern 过滤后的子集也不自动继承原 BH 的 FDR。因此 BH 是本次经验比较，不写成已经证明的全局 FDR。此实验控制/评估的单位是 gene set，不把它说成 d-tuple-level FDR 或机制正确性。

依据：[SciPy false_discovery_control](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.false_discovery_control.html)、[R p.adjust](https://stat.ethz.ch/R-manual/R-devel/library/stats/html/p.adjust.html)。

## 新数据

每 fold 6000 cells。样本生成沿用已有生成器，使用新的域分离 seed：`SHA256(JURE_validation_family_v1_new_holdout_20260927 : case_id)` 的前 64 bits。算法自己的 seed 保持冻结值。所有 case seeds 唯一，且不使用旧的 11、29、47、20260927。

- 100-gene null：balanced independent、heterogeneous independent（检测率 0.05–0.95）、pairwise-only（含非零 main effects），各 60 个独立数据集，共 180 个。
- 100-gene positives：medium θ=0.50、strong θ=0.65，各 20 个数据集。
- 1000-gene positives：medium θ=0.50、strong θ=0.65，各 6 个数据集。

共 232 个完整 case，不是将同一个数据集重抽候选 seed 232 次。匿名基因中的目标位置随机决定。positive 通过正常搜索，不能 oracle 注入，也不能为恢复目标追加预算。未增加 weak θ=0.35 的调参任务。

## 预先指定的评估

分别报告 family-level Gain 拒绝集合和叠加原有 pattern/稳定性门槛后的 qualified 集合。指标包括：每个 null 数据集是否至少产生一个假 clue、去重后的假阳性 gene sets 数、平均 FDP、family 大小、是否为空；阳性包括 proposal recall、discovery 锁定、end-to-end power、双向恢复、相对同批 raw 已确认目标的保留率。

各同分布 regime 的比例提供 Clopper–Pearson 95% 区间。三类 null 的 pooled 事件概率允许不相同，使用独立 Bernoulli 的保守 KL-Chernoff 单侧 95% 上界：求解 `n KL(observed_rate || upper) = log(20)`。这是三类平均事件率的上界，不冒充各类型都具有相同错误率；各类型仍单列报告。

工程检查在生成数据前固定：

1. 每类 null 的“至少一个假 clue”观察比例≤0.05，全部 180 个 null 的 pooled 单侧 95% 上界≤0.05。
2. 每个 strong 分组 end-to-end power≥0.80；相对 raw 的保留率≥0.90。
3. 每个 medium 分组相对 raw 的保留率≥0.80；其绝对 end-to-end power单独报告，不为达标修改搜索器。
4. 每个阳性分组至少有 3 个 raw 已确认目标，否则保留率证据不足，不能算通过。

这些是预定的工程检查，不是数学保证的替代物。`holm_025` 是预先指定的保守 arm，不根据结果挑赢家。所有 arm 均给出完整结果；若不通过，不重抽 seed、不放宽规则、不删失败 case。

## 运行与保存

保持 1999 次 null 模拟、1000 次 bootstrap。新实验的 storage adapter 仅将可从 counts/seed 重建的模拟数组替换为 shape/dtype/hash 审计记录，仍执行全部模拟；数值等价性有回归测试。CSV 无损 gzip 压缩后记录压缩前后哈希，counts、锁定对象、families、原始/调整 p 和判定均保存。

本机最多两个独立 CPU workers，不用 GPU、不连接 AutoDL。记录 worker 累计 RSS，不将它说成 AutoDL 2 GiB cgroup 验收。实验通过也不自动运行真实 NT、不自动向 Agent 提供候选；真实数据和生物学重复仍需单独验证。
