# Clue Hunting v0.4：候选覆盖与验证配额

v0.4 修改候选生成和 discovery 内的计算优先级。MFI、lower-order KL Gain、estimability、bootstrap 与固定状态跨 fold 验证继续使用 v0.3 的统计实现。v0.3 代码、冻结参数、原实验产物全部保留；本次结果写入新的目录。

## 候选生成

保留 dependency 与均匀随机探索，另为三阶预留一个 `higher_order_fingerprint` 通道，不要求二阶边或父集合。默认从总三阶预算 4000 中划出 1000 个名额，剩余 3000 由旧通道分配；三者交集按 canonical gene set 合并、保留实际来源。重复或名额未用满时不根据结果追加抽样。

指纹算法只接收当前 discovery 的 binary cell × gene 矩阵：

1. 使用冻结 seed 生成 64 组 cell 子集，每组 12 cells；组内不放回，组间允许重叠。
2. 每个基因在这一组 cells 的 0/1 向量编码成整数。对所有基因对 A/B 查询 `fingerprint(A) XOR fingerprint(B)`，寻找具有相同或互补指纹的 C。这样的匹配直接涉及三变量，不要求 A/B 具有二阶相关。
3. 每个 band 内仅保留 `i<j<k`，因此同一 triple 最多贡献一次碰撞。每个指纹 bucket 最多 16 genes；超出时按冻结随机优先级取子集。每 band 最多 100,000 碰撞，超出时按 seeded bottom-hash 采样，避免字母靠前者占满预算。所有截断都有计数。
4. 按跨 band 碰撞次数优先，seeded hash 打破平局，最多选 4096 个组合。在当前 discovery 的全部 cells 上计算绝对标准化三阶中心矩，仅用于候选排序；选前 1000 个进入正式统计，记录每个被精筛组合的分数、rank 与来源。

对理想平衡 parity 分布、奇偶优势强度 θ，在独立细胞的总体模型下，单组 b cells 全部同奇偶的概率为 `((1+θ)/2)^b + ((1-θ)/2)^b`。这是算法为何能看到 pure-three-way 的直觉，不是实际有限样本、多 band、bucket 截断和排序之后的总体召回保证。真实 recall 必须实测；不得将此公式当作检验 p 值。

该通道是偏好强 parity 模式的工程启发式，不是完整高阶搜索，不宣称复现某篇论文的新算法。偏置 marginals、低检测率、弱信号都可能使碰撞被噪声淹没；中心矩也可能由低阶结构产生。指纹或中心矩高分只是“值得检测”，必须经过完整状态表、MFI/Gain 和锁定验证才能成为 reference pattern。

## 内存和工作量

不枚举完整三元组或构建 G×G×G tensor。每 band 扫描 G(G−1)/2 个 pair，并在有界 bucket 内查找第三变量；工作量取决于 band 数、pair 数和 bucket cap。默认最多缓存 640 万个 uint64 碰撞编码，编码本体上限约 48.8 MiB；排序、去重和计数还需要额外工作内存，不能将这个数冒充整进程峰值。

完整 cell 精筛只处理至多 4096 个组合，以 64 个组合 × 1024 cells 的块计算。候选元数据、统计模拟及原二阶图审计也占资源；内置进程 RSS guard 保留，但它不等于 2 GiB 容器的硬限制。当前 benchmark 在本机运行，不代表 AutoDL 2 GiB/0.5 CPU 环境验收。

## Calibration 与 bootstrap 优先级

原代码的字母排序截断同时可能影响 Gain calibration 和 bootstrap。v0.4 先完成候选的 discovery 点估计，再按预先规定的排序分配 calibration；calibration 完成后才排序 bootstrap shortlist。

Calibration 排序：estimability（good 优先）、KL Gain 降序、最小状态支持降序、seeded candidate hash。Bootstrap 排序：estimability、校准 p_gain 升序、KL Gain 降序、最小状态支持降序、seeded candidate hash。没有 Gain 的阶数使用绝对 MFI 作效应摘要。所有 p 值相同时由效应量继续排序，不假装分辨 Monte Carlo 分辨率以下的差异。

排序只使用本方向的 discovery 信息；验证结果不能改变 rank、名额或已锁定状态。每个候选保存 priority key/rank/scope，单独导出 bootstrap 分配表。保留原预算：每 fold 128 个 bootstrap gene sets，默认 2/3/4 阶为 25/76/27，每次 1000 draws；Gain calibration 上限 512，null draws 为 1999。排序不会增大预算，也不是新的 FDR 证明。

## 资格与版本边界

v0.4 默认 `primary_requires_dependency_source=False`：有无二阶图来源只作 provenance，不能据此禁止统计合格的 pure-higher-order 候选进入严格目录。但任何 discovery 预算未完成则不授予 primary 的保守规则仍保留。统计合格、双向重发现、搜索预算完整和来源在产物中分别记录，不能用 primary=0 代替全部统计失败。

双 discovery 均冻结后才开始对侧验证；具体 genes + states 原样检验。随机 cell fold 仍不是独立生物学重复；四阶搜索未升级；探索性 selected-universe 推断不等于全局 FDR。新算法先在 synthetic 上测量，未自动重跑真实 NT，也未接入 perturbation、Agent 或 TN。

## 预定验收

- 代码测试检查：没有图/父集合仍可提出 parity 目标；500/1000 基因有界；输入列重排可复现；密集碰撞有明确截断；强初筛组合不因名字靠后失去配额；validation 不能进入排序；旧版本回归与源码 hash 保留。
- 固定 synthetic 覆盖：100/500/1000 genes，θ=0.35/0.65，seed=11/29/47，每个 seed 两个独立 6000-cell folds。逐项报告成功和失败，不按结果改 seed。
- 完整统计：原 100-gene recovery 数据（核对原哈希）、一个 1000-gene 强信号案例；independent、biased independent、pairwise-only 各 3 个 seed 的 100-gene 阴性案例。均保留正式 1999/1000 重采样次数。
- 覆盖实验不代表 full pipeline；单次千基因 full synthetic 不代表真实 NT；少量 null 运行不证明 FDR。验收以报告为准，不预写成功结论。
