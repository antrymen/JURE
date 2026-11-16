# Replogle K562 Essential：v0.2 首次真实数据运行

在读取本轮响应结果前固定本方案；这是开发性真实数据审计，不是独立 benchmark，也不是外部平台预注册。v0.1 历史结果保留，不根据其 TRRAP 候选手动选择本轮模块。

## 数据和隔离

源文件沿用 scPerturb `ReplogleWeissman2022_K562_essential.h5ad`，MD5 `d8cba17576d1a8afc0f7d71b79cad0f7`。核对 310385 cells、10691 NT 和全部2057 target计数。按已有 aliases canonicalize；CPA 42个保留targets在本源数据中重叠者全部排除，CPA/RPE1/day8表达不读取。

使用 `ReferenceConfig(random_seed=20260927)`，其余阈值均取现有v0.2默认值：max_order=7，bootstrap=200，max_candidates=100000，occupancy>=0.9，min_observed_state_count>=3，max_tests=1000000，shift BH 为本轮全targets×catalogue。超过计算预算则明确记录失败，不截取候选、不看结果后换模块或放宽阈值。

NT 按源数据 GEM batch 分层，以50%/25%/25%拆成 discovery/validation/test。GEM只是平衡技术批次，不是生物学重复。拆分仅使用cell ID和batch；所有NT只出现于其中一份。旧v0.1的calibration和test划分不自动继承；本轮是另一次开发性细胞划分，不宣称此前从未看过这些数据。

只读取discovery NT全基因counts以选模块：默认detection interval [0.01,0.99]过滤后按raw-count Fano (sample variance/mean)从高到低选12genes，tie按基因名。validation/test/perturbation均不参与选基因。选定后冻结split IDs、module及代码/协议hash。

## 主分析

在discovery建立候选、validation原样检验，只有通过者进入frozen catalogue。自动停止仅使用discovery；候选稀疏度、原始计数和失败原因均保留。

之后才从所有非保留target cells提取固定module；每个target使用其全部细胞，不按响应或support预筛targets。一次调用 `test_perturbations`，使用完整reserved NT test pool，BH覆盖全部targets×全部catalogue模式。低细胞容量也保留，但单列n_cells及两组support；低容量阳性不自动算强证据。

pooled reference_test并非target-specific batch matching。逐target报告batch total variation、总UMI/检测基因中位数；同时报告所选模式每组count和occupancy。不得把pool匹配不足、测序深度或单细胞抽样误差解释为机制。此次不修改原算法加入批次模型。

## 预先固定的辅助检查

所有辅助检查只使用已冻结patterns，不影响catalogue或主分析的q值。

1. 在reserved NT test内部做3次无重叠两半比较(seed101/202/303)，以及6次容量检查：按旧6target各自细胞数抽取pseudo-perturbation，其余test NT作为pseudo-control。每次两组互斥，不同诊断之间可复用细胞；不属于独立生物学重复。
2. 原API要求test cell IDs恰好匹配catalogue，诊断使用独立函数，读取原frozen patterns并对test NT的两份互斥子集计算相同Fisher/bootstrap/BH；不改catalogue、不改barcode、不绕过主API身份检查。每次诊断的BH family是全catalogue模式，不能当作主分析2034targets的精确全局FDR估计。
3. 对旧6target各做50%和25%下采样(seed101/202/303)，reference_test及catalogue不变，只减少perturbation cells。每个fraction/seed形成一个敏感性场景：更新这6个target的p值，其余target保留主分析p值，再在同一完整主family上重做BH；使用同一效应/support/bootstrap门槛。报告exact-pattern recall、方向一致性和CI，基线无候选时为NA。这不是新独立验证，不以其结果改门槛。

catalogue为空时完整输出零结果，不启动追加“救信号”实验；发现最高阶数只是本模块/阈值下的观测，不称普遍生物学上限。

## 交付

六张v0.2要求主表、frozen catalogue JSON、module/split/代码hash、完整target shift矩阵、每阶通过数量、negative-control及downsampling汇总、报告和图。重点区分具体pattern数与独立gene-set数、二阶与>=3阶、reference holdout与生物学重复。原始表达保持远端，取回结果与可复现元数据。
