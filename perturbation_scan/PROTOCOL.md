# Day 6 Perturbation Scan v0.1：探索性关联扫描

用户于 2026-09-27 确定路线：保留 Day 6 的 341 个 NT patterns，扫描同一 Day 6 的 perturbation cells，输出 exploratory perturbation-associated candidates；Day 8 后续用自己的 NT 与 perturbation 作外部验证。本协议在本轮 perturbation 表达读取之前确定，不修改 NT discovery 或其 Catalogue。

## 输入与隔离

主 Catalogue payload SHA256：`23f7840ad7e9b14347b0101e2f8fddbc93f31f524033fb1f64368609cef6bf68`，341 states、86 triplets、57 genes。+ 为 raw count>0，− 为 raw count=0，不表示 DE 上下调。

源数据 `ReplogleWeissman2022_K562_essential.h5ad`，310385×8563，MD5 `d8cba17576d1a8afc0f7d71b79cad0f7`。全部 10691 个 NT 都参与过 Catalogue，未用 NT 为 0。剩余 299694 个细胞不等于全部准入：保留既有 CPA/external-benchmark target 隔离，排除 `dataset_audit/combined_audit.json` 的 canonical targets 与 aliases，仅纳入 nperts=1 的允许 targets。

v0.4 Catalogue 未使用 perturbation 表达，但早期 v0.1/v0.2 曾分析过部分扰动数据。不得宣称整个 Day 6 为首次盲测。48 个 batch 不视作独立生物学重复。

表达读取前冻结源文件与代码 hashes、Catalogue hash、target 清单、batch/guide metadata、允许细胞行号和全部配置。禁止按观察到的 shift 重新选 genes、states 或 targets。不读取被隔离 target 的表达行，也不读取 Day 8/CPA。

## 对照、效应和 support

每个 target 在其出现的 batch 内与配套 NT 比较。`w_b=n_target,b/n_target`；`p_NT,matched=sum(w_b*p_NT,b)`；主效应 `delta=p_target-p_NT,matched`。另报 pooled NT frequency、pooled delta，保留各 batch 整数命中数和总数。

预定门槛：target≥100 cells；每个占用 batch 的 NT≥20；matched NT effective n=`1/sum(w_b²/n_NT,b)`≥100；abs(delta)≥0.10。

增加方向：target hits≥10，且 target 样本量下 NT 预期未命中数≥10；减少方向：target misses≥10，NT 预期命中数≥10。允许足够样本下的 0 命中 depletion。不满足条件的比较保留全局分母，标注 not_tested 和原因，以 accounting p=1 计入校正。

## 检验、区间和 family

每 batch 固定 2×2 表边际，超几何分布直接非负卷积，统计量为各 batch target hits 之和；双侧 p 为两倍较小的含端点尾概率，截断为 1。需要零假设下 batch 内可交换细胞及跨 batch 抽样独立，不消除 guide/细胞组成/检测深度混杂。

所有预定 targets×341 states 组成一个 family，Holm alpha=0.05。support/effect gate 不缩小分母。**这里只是探索性筛查：NT 参与选择尚未校正，nominal p 或 adjusted p 不具备本项目确认性错误率保证。** 不启用潜在全集校正，不将通过者自动标成 confirmed clue。

提供 nominal pointwise 95% Hoeffding 区间：`delta ± sqrt((1/n_target+sum(w_b²/n_NT,b))*log(2/0.05)/2)`，截断到 [-1,1]。它不是条件检验的反演，也未校正 NT 选择或多重性，不能作确认性区间；不用于额外筛选。

Candidate = support/effect gates 通过且全局 selected-family Holm adjusted p≤0.05。排序固定为 adjusted p、abs(delta) 降序、target、reference ID。所有通过者保留；first_case 只是展示，不改标准。

## 输出与后续

输出全比较表、聚合 batch 命中数、candidate JSON、首例、manifest 和资源证据。字段明确 `exploratory_perturbation_candidate`、`nt_selection_adjusted=false`、`eligible_as_confirmed_clue=false`、`external_validation_status=not_performed`；可以用于 Explorer 开发，本轮不实际调用 Agent。

频率 shift 不等于三阶 interaction rewiring，不证明超越 DE 的解释量，也不证明因果机制。Day 8 下一阶段须先冻结 Day 6 候选的 target、genes、state、direction、testing family、配套 control 和验收规则；同方向只是必要条件之一，不足以单独叫 validated clue。无对应 target、缺基因或样本不足标注不可验证；时间不同导致未复现也不能直接推翻 Day 6。

## 验证和资源

先测试单 batch/跨 batch 精确概率、batch 构成混杂、Holm 全 family、0 命中 depletion、小样本和缺失对照、Catalogue 篡改及允许行隔离。新 synthetic fixture 预生成并记录 hashes 后再扫描：balanced null、batch-heterogeneous null、pairwise-only null、强/中等正负 shift。它是实现检查，不用来宣称已解决 NT 选择偏差或建立普适 power。

单进程、BLAS 单线程、HDF5 cache 64 MiB、允许行分块，仅保留 57 genes；聚合 target×batch×pattern hits。运行目录不覆盖，失败保留；源数据、冻结 NT 算法和 Catalogue 不变。
