# Clue Hunting v0.3

Scalable Incremental Higher-Order Discovery：先在较大的 NT 基因池中提出有限、可追溯的组合，再评价完整状态表、marginal MFI、低阶模型之外的 Gain、bootstrap 和对侧锁定复现。当前层输出 **Reference Higher-order Pattern**；没有分析 perturbation 时不称 Perturbation-associated Clue。

详细设计与验收要求见 [设计文档](../../docs/clue_hunting/clue_hunting_v0.3.md) 和 [验收清单](../../docs/clue_hunting/v03_acceptance_checklist.md)。旧 v0.2 与 Top12 baseline 保留。运行结果、实际命令和资源数据以对应 benchmark report 为准；此 README 不表示已完成真实 1,000 基因全流程。

## 运行入口

在项目根目录、已安装本项目依赖的 Python 环境中运行。每条命令使用新的空输出目录；程序拒绝覆盖已有冻结 run。以下路径是复现示例，已有同名结果时应改用新版本目录，不能删除旧结果后冒充同一次运行。

```bash
python -m clue_discovery.v03.synthetic \
  --output-dir outputs/clue_hunting_v03_benchmark/statistical

python -m clue_discovery.v03.recovery \
  --output-dir outputs/clue_hunting_v03_benchmark/search_recovery

python -m clue_discovery.v03.benchmark --mode synthetic \
  --output-dir outputs/clue_hunting_v03_benchmark/scale_synthetic
```

- `synthetic`：预定 pairwise-only、pure-three-way、redundant-extension、pure-four-way 统计检验，以及 24 次固定 pairwise-only null 的假阳性审计。默认 1,999 次 null draws、1,000 次 bootstrap；不是 search recall 或真实 NT 结果。
- `recovery`：默认 100 genes、合计 12,000 个独立合成 cells（每 fold 6,000），依次比较 `dependency_only / exploration_only / hybrid`；另有独立的 3-gene positive-path control。支持 `--n-cells`、`--universe-size`、`--without-four-way`，参数应在运行前固定，不能根据恢复结果选择。3-gene control 不能替代 100-gene coverage。
- `benchmark --mode synthetic`：默认 10,691 行、1,200 列的固定合成资源压力数据，从 QC 后基因中依次选取 50/100/250/500/1000 HVG，执行前三档完整流程和后两档 proposal dry-run。原 1000 列试跑有一个基因被既定 QC 排除，故保留该失败记录并改用有 QC 余量的输入；未改变筛选阈值。它检验资源与流程，不代替真实 NT 资格。

已核对的真实 Replogle 源文件使用独立入口；将 `--source` 替换为实际绝对路径：

```bash
python -m clue_discovery.v03.benchmark --mode real \
  --source /absolute/path/ReplogleWeissman2022_K562_essential.h5ad \
  --output-dir outputs/clue_hunting_v03_benchmark/scale_real
```

真实入口核验既有源 MD5 `d8cba17576d1a8afc0f7d71b79cad0f7`、310,385 × 8,563 形状和全部 10,691 个精确 NT cells。准备阶段按冻结 cell IDs/GEM 分层，仅从各 discovery fold 的 raw counts 计算 Fano 排名，保留各自 top1000 的并集投影；50/100/250/500/1000 使用自身排名的相应前缀。**准备 top1000 投影不执行 1000-gene search，也不让 validation 参与本方向的选择。** 该入口不接受任意未审计 h5ad 作为等价源。

完整 50/100/250 流程默认使用 1,000 次 bootstrap、1,999 次 null calibration。500/1000 只做 HVG/图/有限提案计数，不做高阶统计、bootstrap 或正式 locked validation；四阶 dry-run 使用未经统计资格筛选的三阶父组合，作为搜索负载上界，不能当作预计发现数量。每个规模运行于独立子进程。Linux 调用 `nt_reference_experiment.measure` 监测 RSS 并在超过默认 1,400 MiB 时终止；worker 另有阶段性 RSS 检查。此限额是采样监控，不是 cgroup 硬隔离，仍应阅读资源审计中的实测值。

`benchmark` 支持 `--config` 读取预先准备的 YAML；它在读数据前冻结五个规模的配置和 hash。`--worker/--prepared/--dry-run` 用于该 runner 的内部子进程，不应绕过规模执行顺序自行启动全量 500/1000 bootstrap。

关键入口结果为 `STATISTICAL_REPORT.md`、`SEARCH_RECOVERY_REPORT.md`、各规模的 `run_manifest.json`、`scale_benchmark.csv`、`execution_status.json`。本轮综合交付报告约定在 `outputs/clue_hunting_v03_benchmark/BENCHMARK_REPORT.md`；是否完成及实际资源/恢复数字只能由报告与对应产物确认。

## 一个具体状态意味着什么

`A+ B- C+` 表示 A/C 检测到表达、B 未检测到表达，不是 A/C 上调、B 下调。

假设某状态 observed frequency 为 20%，一个 lower-order model 的 expected frequency 为 6%，则其 absolute gain 为：

```text
20% - 6% = 14 percentage points
```

“After accounting for lower-order structure, the A+ B- C+ state occurs substantially more often than expected.”

这仅用于解释差值的单位，不是从本仓库某张联合状态表拟合得到的 synthetic result；任意给定的 observed/expected 数字未必同时满足最大熵拟合约束。实际计算必须从完整 `2^k` 表拟合并保留概率定义。它表示 statistical higher-order structure，不推出 “A and B regulate C”。

## 为什么要逐阶扩展

```text
AB + C → ABC
           │
           └─ 是否存在 AB / AC / BC 无法解释的增量？
                ├─ No  → 不优先沿该路径扩展
                └─ Yes → 完成可估计性/支持/bootstrap资格 → KEEP ABC
                                                               │
                                              预算和支持允许时 consider +D
                                                               ↓
                                                              ABCD
                                                               │
                                               是否超出所有低阶解释？
                                                   ├─ No  → stop
                                                   └─ Yes → KEEP ABCD
```

`KEEP=True` 不一定 `EXPAND=True`。保留 ABC 与是否继续加 D 是两项决策；达到最高阶、预算边界或状态表稀疏边界，都可终止扩展。L3 提案不要求所有 pair parents 显著，另有独立 exploration 入口。

## 为什么不能只依赖二阶图

令三个 0/1 变量的分布与 `1 + θ (-1)^(A+B+C)` 成比例，且 `0<|θ|<1`。全部状态有正概率，任意两变量可相互独立，但三变量仍有非零高阶 log contrast。单纯沿 pairwise edges 搜索可能完全不提出 `(A,B,C)`。

Dependency channel 负责效率，固定预算、seed 和 sampling rule 的 exploration channel 补充搜索覆盖。有限随机探索**不保证**找到任意纯高阶组合；必须把“没提出”与“提出但统计没通过”分开报告。不会没找到就继续加抽直到出现阳性，也不把 planted tuples 或旧 sentinel 作为隐藏强制候选。

## MFI、Gain、d-tuple 分别保存

- MFI：gene set 的最高阶 log contrast，含方向和 bootstrap 稳定性。
- Set-level Gain：完整联合分布相对于 lower-order model 的 KL 等差异。
- Pattern-level Gain：具体 d-tuple 的 observed probability 与 lower-order expectation 的差值、ratio 和 log ratio。

对于完整二元表且 lower-order model 只去掉唯一最高阶项，`MFI=0` 与相应 `KL=0` 的零假设相关联，不能当作两项独立佐证。多个状态共享同一个 gene-set-level MFI 和 bootstrap。非负 KL 本身没有有意义的正负方向稳定性；有方向的是各状态的 signed Gain。当前目录只筛选具有足够 support 且相对低阶预期正向富集的具体状态；完整表仍保留负向 Gain。

默认四阶 Gain 关闭，保留 MFI bootstrap、support 和具体状态点富集，没有独立的 d-tuple enrichment bootstrap CI；这类结果只能作为 exploratory。`gain_mode=off` ablation 也不获得完整 Gain qualification。关闭 bootstrap 时，可记录 ablation 的数值条件通过，但不能标成正式 cross-fold reproducible。

## 冻结与结果解释

每个 discovery fold 独立选 HVG、构图、提案及校准。两边发现均冻结后，才在对侧评价原样的 genes + states；validation 不重新挑 pattern，不调 threshold。

Discovery 的 Gain 用拟合低阶模型后的参数 bootstrap 校准。Validation 的效应量是其自身经验表相对于最佳低阶解释的 Gain；显著性用预先规定的 exact conditional test：固定 validation 的全部低阶 marginals，在可行整数状态表中计算概率，低阶模型的未知参数被条件化消去。没有使用 validation 拟合校准模型或反向调参。两种显著性程序在输出中分别标记；不能用对固定 discovery 分布的偏离，把普通低阶 marginals 漂移误当成最高阶结构。

分别输出 `within_discovery_stable`、`cross_fold_replicated`、`bidirectionally_rediscovered`。双向重发现要求同一 concrete state 在两侧独立出现，并且两方向锁定验证均通过；基因不在对侧池或组合没被提案时，单列 searchable 状态。

NT cell split 不是独立生物学重复；已经反复用于开发的 NT 不称 untouched benchmark。数据驱动搜索、筛选和分阶段检验的 family 全部审计，默认 exploratory；当前资格使用 calibrated candidate p，q 单列审计，不宣称已控制全局 FDR。`primary` 只是满足较严格预定条件的目录层级，并不改变这一推断边界。不能将每个 neighborhood 的 BH 合并称全局 FDR。

## 规模与验收边界

按 50 → 100 → 250 完整集成检查，再做 500/1000 dry-run。分阶预算、图覆盖、Gain calibration、bootstrap workload 和磁盘/RSS 都要报告；dry-run 不代表千基因 × 1000-bootstrap 已完成。是否更好用搜索覆盖、null 行为、恢复、复现和成本判断，不能只比较候选数量。

默认 128 个 bootstrap gene sets 是每个 discovery fold 的预算，按 2/3/4 阶固定分配 25/76/27；含两方向 discovery 和两个对侧 validation 的全 run 上限为 512 次 gene-set bootstrap。一次 gene-set bootstrap 的 1,000 draws 是另一维度，不能与 gene-set 数混淆。资源限制是否实际生效、峰值是进程还是容器，均以资源审计为准。

本轮仅升级 NT reference discovery，不接入 perturbation、Agent investigation 或 TN training。正式真实数据运行后的参数修改必须另建版本，经人工审阅；不根据阳性数自动调参。
