# Real-data Test v0.1：Replogle K562 Essential day 6

本轮是 smoke test 与 algorithm audit，暂不修改 `clue_discovery/` 的算法、阈值或判定。CPA 的表达矩阵、响应和重复均不打开；Replogle day 8 / RPE1 不参与。沿用已有目标隔离表，排除 CPA 42 个 canonical targets 及其别名对应的扰动细胞。它们作为表达特征不另外排除。

## 数据验收与冻结

优先复用服务器已有 `ReplogleWeissman2022_K562_essential.h5ad`，核对 scPerturb Zenodo record 13350497 的 MD5 `d8cba17576d1a8afc0f7d71b79cad0f7`。官方处理脚本从作者 `K562_essential_raw_singlecell_01.h5ad` 读取 counts，仅重整元数据；本轮仍实测矩阵中数值非负、有限、整数。检查细胞/基因数量、唯一 barcodes、gene/guide/batch 字段、NT 标签与项目 Table S2 计数。不能把 gene 名称中含 `nt` 的细胞当 control；仅接受精确的 `non-targeting` / `control` 标签，并核对其他字段。任何身份或 count 校验不符都先停止。

只在原作者处理后的单细胞集合上运行，不依据扰动响应、knockdown 效率或 clue 显著性选细胞。GEM group / lane 仅用于批次诊断和对照匹配，不传入 independent replicate 参数。

从 NT 中用固定 seed=20260927 随机留出 1,000 个 calibration cells，用于特征选择；这些细胞不进入任何检验。仅在 calibration controls 上应用默认 detection interval `[0.01, 0.99]`，记录全部基因 detection rate。候选 module 固定为剩余基因中 raw-count Fano factor (`variance/mean`, ddof=1) 最高的 12 个，tie 按基因名排序。特征选择不读取任何扰动表达，也不读取检验用 NT。Fano 仅用于确定本轮小 module，不是 ClueScore。

在移除保留目标后，仅按细胞数量选择 6 个扰动：`100–149`、`150–299`、`>=300` 三个容量区间各随机取 2 个；seed 固定，先锁定目标再读取响应。每个目标使用全部可用目标细胞；从 NT test pool 按 GEM group 抽取每组目标细胞数 3 倍的 control cells（无放回），不足时显式终止，禁止悄悄补不匹配批次。目标间可重用 controls，同一比较内不重复采样。这里“100%”指该目标全部细胞及固定匹配 control pool。

## 固定运行设计

- 基线：6 个扰动 × 100% cells；默认 `DiscoveryConfig()`，包括 200 bootstrap、support_only=True。
- 下采样：每目标分别在固定 control/perturb pool 内无放回随机排列，按 50%、25% 取前缀；3 个 seed（101、202、303），同 seed 的 25% 是 50% 子集。module、阈值、bootstrap seed 不改变。
- 容量匹配负对照：每个真实目标对应 1 次 NT-vs-NT 比较，按真实目标的各 batch cell count 分配 pseudo-perturbation，另取 3 倍 pseudo-control，同次比较两组互斥。
- 大样本负对照：剩余 test NT pool 按 3 个固定 seed 随机分成互斥两半，保留真实 dropout 与相关结构。不同随机拆分可以重复使用细胞；它们不是独立生物学重复。

合计 51 次比较：6 baseline、36 downsample、6 matched null、3 half-split null。候选模块仅 12 genes，完整搜索上界是 264 二阶 + 1,760 三阶 = 2,024 patterns/比较。本轮不会把全转录组投入组合搜索；记录 observed/theoretical candidate ratio，不能把人为 module 限制算成 bottom-up 剪枝的效果。

## 固定输出与判断口径

每次比较保留完整 `clues.csv`、`candidate_search_log.csv`、`gene_qc.csv`、`run_metadata.json`，包含失败模式。额外记录源文件校验和、所有脚本/算法哈希、config、module、targets、每个比较的 cell IDs 与采样 seed，确保可重算。

汇总搜索规模、耗时、bootstrap shortlist 数量、各 status 数量、三阶 clue 的两组 support/频率、Delta、MFI、CI、稳定性、零状态个数和最小联合状态计数，并报告细胞总 UMI/检测基因数及 batch 构成的条件差异。所有 clue 是统计候选，本轮不解释为生物机制或真实假阳性已排除。

下采样对照完整 100% 的三阶 `candidate_clue` 集合，报告 exact-pattern recall、Jaccard、Delta 同向率以及是否仍被搜索。额外将基线候选按 `abs(Delta)` 降序、pattern string 打破并列取 top 20，报告相同 pattern 的找回率；它只是单一 effect size 排序，不是综合分。基线没有候选时 recall 为 NA，不能写为 100%。下采样不是 independent replication。

负对照报告每次候选数、比例、是否有任何三阶候选以及其效应/支持分布。9 次 control split 足以发现明显失控，但不能据此声称已经校准精确 FDR。任何问题先记录到审计结论，完成本轮后再决定算法修订，不根据结果更换目标或反复调整 threshold。

## 来源

- [Replogle 作者数据](https://doi.org/10.25452/figshare.plus.20029387)
- [scPerturb 固定版本与 checksum](https://zenodo.org/records/13350497)
- [scPerturb 官方处理脚本](https://github.com/sanderlab/scPerturb/blob/master/dataset_processing/scripts/ReplogleWeissman2022.py)，本地副本及 Git blob ID 保存在 sources。
- 项目已有 `dataset_audit/replogle_counts.json` 与 `combined_audit.json` 仅用于 cell-count 对账与保留目标隔离；不读取 CPA 表达数据。
