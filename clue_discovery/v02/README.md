# Clue Discovery v0.2：reference-guided

v0.2 将 reference 高阶结构发现与 perturbation prevalence-shift testing 分开。它采用 Stator 的 MFI / d-tuple 思路，在本实现中使用 marginal MFI，借鉴 mTRIM 的逐层兼容组合搜索，并实现 discovery → locked validation → reserved-control testing 的隔离流程。MFI 和 bottom-up search 不作为新统计量或新搜索范式宣称。

v0.1 的所有原算法文件保持原样，根命名空间 `clue_discovery` 仍是 v0.1 API（其中 `__version__` 标识该 baseline）；新增入口位于 `clue_discovery.v02`，发行包版本为 0.2.0。

## 调用

```python
from clue_discovery.v02 import Population, ReferenceConfig, run_discovery

nt = Population(X_nt, tuple(gene_names), tuple(nt_cell_ids))
perturbations = {
    'TRRAP': Population(X_trrap, tuple(gene_names), tuple(trrap_cell_ids)),
}
result = run_discovery(
    mode='reference_guided', nt=nt, perturbations=perturbations,
    candidate_genes=module_genes,  # 必须预先指定或仅用 discovery 数据选择
    config=ReferenceConfig(max_order=7),
)
result.write('outputs/reference_guided_run')
```

输入沿用 detected binary 语义：默认 raw count > 0 为 1；不是相对对照的 up/down。矩阵支持 NumPy、pandas、SciPy sparse；仅所选 module 转稠密。显式 cell IDs 必须全局唯一（必要时加数据集/样本前缀），模块列按 gene names 对齐。跨来源误用同一细胞、验证细胞混入 test 或 perturbation 会报错。调用方不能通过重命名细胞来绕开隔离；程序只能检查提供的身份信息。

`split_reference()` 在查看表达值之前，按固定 seed 将 NT 分成 50%/25%/25%。对 10,691 NT，无分层时分别为 5,345 / 2,672 / 2,674；可传 `strata` 做批次分层，取整后总数可能略有不同。每个 stratum 必须足够分成三份。

如需仅用 discovery 选择基因，可先调用 `split_reference()`，再将该三份 Population 与选定模块传入 `fit_reference()`。已有约束或 calibration cohort 需由调用方事先纳入 split 设计；不会自动复用 v0.1 的 1,000 calibration cells 或历史特征表。不要以本轮结果反复更换 seed/模块/阈值。

## Stage A：discovery-only 逐阶搜索

只在 discovery 中做基因 detection-rate 过滤。只枚举所有二阶 0/1 patterns；三阶及以上调用共享 k−2 子模式的兼容 k−1 模式合并，去重并保留生成父模式。不会逐阶重新枚举所有基因 combinations。

每个 gene set 构建完整 2^k 状态表，计算

`MFI_k = Σ_s (-1)^(k-|s|) log P(s)`。

该公式扩展到 2–7 阶，是 marginal log contrast，不包含 Markov blanket conditioning。默认每格 pseudocount=0.5。具体 d-tuple 计算 observed support、independence expected support、enrichment 及 plug-in binomial upper tail；因此 reference catalogue 保留正富集模式，不收录仅 depletion 的模式。

记录 pattern support、全部 raw state counts、occupancy、zero_state_count/fraction、min_state_count（含零）和 min_observed_state_count（仅非零格）。默认 occupancy ≥0.9、最小非零格计数 ≥3；不满足时不 bootstrap、不保留、不继续扩展。阈值是可配置筛选条件，不代表已证明统计校准或不存在平滑偏差。

质量合格的 gene set 做联合状态表 multinomial bootstrap，与对 cell rows 重采样等价；一次计算同时服务其全部具体 patterns，避免同一 gene set 的 MFI 区间因 pattern 不同而变化。seed 由全局 seed、阶段及基因集合确定。

参考候选保留要求：support≥20、|MFI|≥0.5、null q≤0.05、MFI bootstrap sign stability≥0.95 且 CI 不跨0、enrichment bootstrap sign stability≥0.95 且 CI 下界>0。默认200次 bootstrap。

三种行动独立记录：`KEEP_AS_REFERENCE` 是 discovery 暂存，最终还需 validation；`EXPAND` 只看 discovery 中的 table quality、pattern support、expected support 和配置的扩展规则；`PRUNE` 表示既不暂存也不扩展。KEEP 与 EXPAND 可以同时为 True。

默认 `allow_support_only=True`，不因低阶 MFI 不显著或不稳定就停止。纯四阶/七阶 parity 可以具有完全独立的低阶边际；以“没有 stable lower-order candidates”作为停止条件会漏检它们。预算超限明确报错，不能静默返回偏向早期候选的 catalogue。默认最多100,000个候选，最坏仍有组合爆炸，不能将逐阶实现本身等同于已解决复杂度问题。

无可扩展或兼容可合并候选时自动停止；`max_order=7` 只是上限。validation 的复现率不会反馈到 Stage A 的扩展或停止策略。观察到的最高通过阶数只适用于当前模块、样本量和阈值，不解释为 K562 的普遍生物学阶数上限。

## Stage B：locked reference validation

只评价 Stage A 锁定的 genes/states，既不重搜也不改变编码、模块或阈值。重复检查 support、occupancy、null enrichment、bootstrap，并要求与 discovery 的 MFI 同号。只有通过者进入 frozen catalogue。

discovery 的 BH family 包括所有实际评价过的阶数和 patterns；validation 的 BH family 包括所有锁定候选，不按验证成功者重算。自适应发现后的 plug-in null 仍属于探索性统计，不能宣称严格的全局 FDR 保证。

随机 NT cell split 是 held-out reference-cell validation，不能称为 independent biological replication。相关细胞、批次和同一培养条件仍可能共享误差。没有假设 NT cell split 等同于真实实验重复。

Catalogue 同时保存精确 split cell IDs、配置、发现/验证证据及二值输入指纹。`FrozenCatalogue` 使用不可变 JSON 和 SHA-256；CSV 用于查看，后续测试应加载 `frozen_reference_catalogue.json`，避免手动改 CSV 后仍冒充锁定候选。

## Stage C：只测试冻结 patterns 的 prevalence shift

```python
from clue_discovery.v02 import FrozenCatalogue, test_perturbations
catalogue = FrozenCatalogue.load('outputs/reference_guided_run/frozen_reference_catalogue.json')
shifts = test_perturbations(catalogue, reserved_nt_population, perturbations)
```

reserved NT 必须是 catalogue 中登记的完整 test cohort，不能使用 discovery/validation NT 替换。计算 pattern frequency、Delta、ratio、双侧 Fisher、BH、两组支持数和 binomial bootstrap shift CI/方向稳定性。只重采样已定义模式的 0/1 携带状态，不重新估计 perturbation MFI，也不要求 perturbation 具有完整的2^k状态表。两组 occupancy 仍报告，但不作为该阶段的 MFI 门槛。

默认 BH family 为**本次调用提供的全部 perturbations × catalogue patterns**，包括不显著和低支持结果；也可在冻结配置中明确选择 per-perturbation。分多个调用运行不能再声称所有调用共享一次全局校正。默认 testing budget=1,000,000，超限报错。

`candidate_shift` 要求 max(两组支持数)≥20、|Delta|≥0.02、q≤0.05、bootstrap sign stability≥0.95 且 CI不跨0。允许 perturbation 中 pattern 消失，因此不要求两组各≥20；两组具体计数必须分别检查。Bootstrap 稳定不等于实验重复，当前所有 shift 都标记 `replication_status=not_available`，没有提前使用 `reproducible_clue` 标签。

这里检验的是 reference 定义的 state prevalence，不是 MFI 改变，也不是超越 DE/pairwise 的增量信息。默认使用用户提供的完整 reference_test pool，不自动做 batch matching、测序深度调整或 pseudobulk；在真实数据运行前需预先指定相应比较设计。

## 兼容探索通道

```python
baseline = run_discovery(mode='perturbation_emergent',
                        X_control=X_control, X_perturb=X_perturb,
                        gene_names=gene_names, config=legacy_config)
```

该入口调用未修改的 v0.1 `discover_clues`，仍只支持二/三阶。名称代表 de novo 探索通道，不意味着已经证明 NT interaction=0 或 perturbation 新产生了 interaction；v0.1 本身没有这一严格差异检验。建议仅在足够细胞量下使用，不根据 reference-guided 阴性结果无约束追加筛选。

## 输出与验证

主流程生成：`reference_candidates.csv`、`reference_search_log.csv`、`reference_validation.csv`、`frozen_reference_catalogue.csv`、`perturbation_state_shifts.csv`、`order_summary.csv`。另有机器可加载 catalogue JSON、gene QC、运行元数据及 perturbation × state 的 Delta/call 矩阵。未通过的 discovery/validation/shift 都保留；空 catalogue 也生成有列名的空输出。

```bash
python -m pytest -q
python -m clue_discovery.v02.demo --output outputs/clue_discovery_v02_demo
```

新增测试覆盖 reference 三阶复现、固定模式 shift、验证失败排除、reference blind spot 与旧通道、稀疏表停止、validation/test 无泄漏、四阶与七阶纯 parity 逐层发现、KEEP+EXPAND、重叠细胞拒绝、全 family BH、预算失败及 catalogue 序列化。未引入 TN、条件 MFI、pairwise maximum entropy，也未执行真实数据 v0.2 扫描。
