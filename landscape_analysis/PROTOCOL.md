# Broad Screening v0.1 / Landscape Analysis

2026-09-27：只分析已完成的 Day 6 聚合输出，不调用 LLM/Jev/三 Agent，不读取 Day 8，不检索 pathway 或给模块作生物学命名。本协议在计算分布与聚类结果前写入。

## 输入与矩阵

以已通过 FINAL_AUDIT 的 Day 6 scan 为输入，读取 statistics.npz、counts/identities.json、冻结 manifest、candidates.jsonl。验证 count identity hashes、Catalogue digest、维度、candidate 数量及每条 candidate 与矩阵的一致性；记录全部使用文件的 SHA256。不会重新扫描表达或重新选 candidates。

主矩阵为有至少一条 candidate 的 419 targets × 全部 341 reference patterns，数值为 batch-matched delta（频率差）。所有可估计的非候选 delta 仍保留。另导出 candidate-only 矩阵（非候选 NA）、selection-encoded 矩阵（有足够总体样本但未入选为编码 0，缺失/样本不足为 NA）、candidate mask 和逐格状态/原因。编码 0 不代表观察效应为 0，NA 的含义由对应矩阵定义。正负方向是联合检出状态 enrichment/depletion，不是 DE。

主图显示全部 419×341 连续 delta；第二张同排序候选图显示筛选结果。419 是以本次筛选为条件的 target 子集，不代表全体 perturbations。对全体样本量充足且有 matched control 的 targets，另做 pattern clustering 敏感性分析。

## 预先规定的描述分析

- enrichment/depletion、target/pattern 的 candidate degree 分布，按全部 341 patterns 与有 candidate 的 patterns 分别报告。
- top 1/3/5/10/20/50/100 patterns/triplets/targets 的 candidate 集中度，以及覆盖 50/70/80/90% candidate 所需的数量。重复 triplet/states 不解释为独立机制。
- targets：对全部 continuous delta 做 cosine distance + average linkage，关注 signed response shape；热图保留原始效应幅度，不做按行 z-score。
- patterns：对跨 target 的 continuous delta 做 Pearson correlation distance + average linkage，正相关归组，反相关另报；共享 genes、同 triplet 的构成性关系单列。
- 两个树都以 distance=0.30 切分为主描述分组，0.20/0.40/0.50 为敏感性；不是检验得到的“真实模块数”。patterns 至少 3 个且涉及至少 2 个 triplets 才标记 provisional response module，其他为 small/single-triplet groups。目标分组完整保留，小组也不删除。
- 单一图形难展示所有标签，主图提供树、分组色条与完整顺序 CSV；另做模块代表 pattern 的可读小图。图的 raw delta 色标不裁剪观察值。
- PCA/SVD 报告中心化矩阵的解释方差比例与未中心化的平方效应能量；数学低秩不等于同样数量的独立生物程序。

## 稳健性与边界

目标聚类比较连续 delta、selection-encoded delta 和 triplet 等权特征（每 state 乘 1/sqrt(该 triplet 的已收录 states 数)）。报告同一 distance cut 下分组数与 adjusted Rand index，不凭结果挑最漂亮参数。

固定随机种子 20260927、50 次重采样。目标分组按 triplet 整块重采样特征；pattern 分组按 target 重采样行；报告原始组内部成对 co-assignment 的比例。它只度量特征/样本扰动下的描述稳定性，不是细胞 bootstrap、独立生物重复或显著性。零范数或零方差 profile 若存在，从相应距离计算隔离并明确单列，不以填 0 修复距离。

另报 candidate degree 与 target cell count 的 Spearman 相关，以揭示筛选功效/样本量可能影响 landscape 的程度，不把相关性解释为原因。

不把未检索命名为 novel，不把常见模式命名为 stress/cell-cycle，不把明显模块解释为已验证机制。只输出结构 triage features，不冻结最终 20–30 个 Day 8 待验证案例。下一阶段才接 biological interpretation；之后冻结 Day 8 验证集合与标准，再从验证结果选 5–10 个 Deep cases。

## 产物与验收

独立、可重跑脚本与源 hash；矩阵及状态、target/pattern/triplet 汇总、成员及近邻、相关 pattern pairs、分组敏感性/稳定性、PCA、结构 triage features、PNG/PDF 科学图、中文结果报告和运行 manifest。原有 scan 文件保持不变。

验收重点：行列身份、6129 mask 与 JSONL 一致、enrichment+depletion 守恒、degree 与分组计数守恒、非候选实际效应保留、0/NA 状态可区分、signed distance 与重采样正确。可导出图需目视检查。
