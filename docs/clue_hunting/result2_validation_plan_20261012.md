# Result 2：A/B 内部复现与低阶响应解释检验

2026-10-12。设计建议与可行性审计，尚非冻结运行协议；本次没有执行新的响应检验、没有训练或改变 discovery、没有连接服务器。

## 结论

两个实验都可开展。A/B 内部复现的工程难度较低；低阶检验已有三变量二阶最大熵求解器，但稀疏 batch、估计对象与零假设必须先处理。先完成 A/B 协议及共同的数据计数层，再用受控 synthetic 检查低阶估计器，最后冻结两项验证的 family 后执行。不要先看 B 的通过结果再决定残差检验集合或规则。

当前路线是固定 341-state Catalogue 下的内部重分析，不是全流程无泄漏验证。两折 NT 都参与过原 Catalogue；Day 6 perturbation 及后续 case 也已被分析。重新划分不产生全新的盲测数据。严格折内流程需要重建 Catalogue/HVG/候选选择；真正外部证据仍需 CPA/Day 8 等合适实验。

## 已核实输入

- A/B 分配已于 2026-10-07 保存，当前 SHA256 核对通过：`7ad1014aba84822ae14ad5b81a3f8bc57b8181e838daa86625e323ace737319b`。按 target×batch×guide 分层，仅用 metadata。
- NT：A=5383，B=5308；perturbation：A=148207，B=147904。两折互斥，2034 个 targets 都出现于两折。
- 每折 target 细胞数中位数均为 61。

| 每折最低 target cells | A 达标 | B 达标 | 两折同时达标 |
|---|---:|---:|---:|
| 50 | 1284 | 1290 | 1242 |
| 75 | 761 | 755 | 719 |
| 100 | 411 | 409 | 386 |
| 150 | 149 | 151 | 146 |
| 200 | 63 | 62 | 61 |

- 非空 target×batch×fold 小格中位数为 2 cells，99.34% 少于 8 cells。不能据此逐小格自由拟合 8 状态分布及二阶最大熵模型。
- 本地已有原始 h5ad（约1.55 GB）和 `data/day6_tool_store/states.npy`（328585070 bytes）。缓存以 packbits 保存306802 cells×8563 genes；数组形状306802×1071，uint8，不是1071个基因。只逐块解码 Catalogue 的57genes，无需展开全基因矩阵。
- `clue_discovery/v03/lower_order_null.py` 已实现完整低一阶最大熵投影；对于三基因就是 pairwise 模型，支持批量拟合。输入必须严格正，零格处理仍需固定与校准。
- 现有 residual screen 只描述 NT 参考状态偏离二阶模型，不是 perturbation-induced residual change 的检验。

## 实验一：固定 Catalogue 的 A/B 内部复现

### 推荐主分析

1. 仅用已冻结 metadata 定义两折各≥100 cells 的386-target主分析集。此定义须在查看新分折效应前锁定；结论限定在这些较高样本量 targets。全部2034targets另有覆盖表，不把未达标算成生物学不复现。
2. 保留全部341states，不使用全数据6129候选、419candidate-bearing targets、M01–M04或已展示案例来筛主分析对象。
3. A/B各自在本折重新扫描：batch-matched NT、原10pp效应门槛、方向相关support、原检验与Holm筛查。主 discovery family 是预定386×341比较；任何后续 support/effect 未通过的比较不从 family 删除。保留全局693594作为另行声明的敏感性分析是可选项，不根据结果选择更漂亮版本。
4. 两边 discovery 都先完成并锁定列表、方向和配置，再开始相互 validation。A→B 的验证 family 是全部 A-locked candidates，反向同理。不可先看 B 的显著性再缩小 family。
5. 建议分两层报告：方向一致且验证侧通过预定校正；以及在此前提下验证侧也达到10pp。单纯同号另报。双侧检验加方向门槛易复用；若采用单侧，方向只能由 discovery 折锁定。两个验证方向若合并作一类错误率声明，须分配方向间预算，例如每方向0.025。
6. ≥50 cells/折的1242-target扩展分析可作为预先定义的敏感性分析，另设 family、独立报告；不可先看主分析结果后为救回候选再启用。

### 产出

- 双方向 A-locked/B-locked 清单与所有验证结果。
- 方向一致率、验证规则通过比例、强效应保留比例；分母分别注明发现候选数、可评估数、未评估数。
- ΔA–ΔB 图与效应相关：用发现侧锁定集合计算，不能只保留两侧显著者。另给 metadata 主分析全比较描述视图。
- 按样本量、NT频率、原效应大小分层，展示功效下降和 winner's curse 引起的效应收缩。
- 共享target、genes和NT使关联不独立；不能把每个state×target当独立重复来给相关性或复现率过窄的置信区间。描述结果与估计不确定性方法分开。
- 标注 fixed-catalogue internal reproducibility；Holm没有消除NT Catalogue选择效应，不升级为确认性整体FWER或生物学重复证据。

## 实验二：超出低阶模型的响应信息

### 先定义估计对象

对同一冻结state，在相同target-batch权重下，分别算 observed、independent、pairwise 三个响应差：

`Δobs = sum_b w_b [p_P,b(s) - p_N,b(s)]`

`Δpair = sum_b w_b [q_P,b^(2)(s) - q_N,b^(2)(s)]`

`R2 = Δobs - Δpair = sum_b w_b [(p_P,b-q_P,b^(2)) - (p_N,b-q_N,b^(2))]`

独立模型R1同理。独立模型比较针对二值检测状态的一阶边际，不等价于击败所有基于连续表达的DE方法。

R2是“相对指定二阶模型的响应残差”。R2≠0与log-linear三阶参数变化不是同一个命题；不能直接称调控重连。残差很小也可能是有意义的负结果：强频率shift可以主要由低阶变化解释。不要用 R2/Δobs 在Δobs接近零时作解释比例；可报告有符号残差、绝对百分点误差和足够效应范围内的描述性指标。

### 稀疏 batch 是首要障碍

逐target×batch×fold通常只有1–2cells，直接加伪计数再拟合可能由平滑强度主导；逐小格非参数bootstrap也不能凭空生成未观察到的状态。

建议先并列评估两个估计层级：

- **描述性基准**：本折内target聚合分布，对NT按target的batch构成配重，分别作独立/二阶投影。易实现，但“混合后拟合”不等于“逐batch拟合后混合”，不能把所有残差归因于细胞内高阶变化。
- **候选主模型**：利用跨batch信息的分层/部分汇聚log-linear模型，明确哪些batch参数共享、哪些target的一阶/二阶变化可变。这是新增建模假设，不能宣称与原stratified检验完全等价。先在包含batch异质性、稀疏格和guide差异的synthetic中校准；不稳就将本轮残差结果限定为描述性，不硬报显著性。

实现上先聚合完整8格表，按唯一target×triplet复用拟合。原6129条候选包含5501个不同target×triplet；正式验证仍用A/B新锁定集合。在精确保留边际的三变量二阶投影下，同一triplet八个残差仅差parity符号，不能计作八份独立高阶证据。采用收缩模型后须重新审查这一性质及解释。

### 不确定性与零假设

- 重采样必须重新估计观测频率、边际、模型及R；保留batch结构和共享NT的相关性。不能把重叠三元组的bootstrap彼此完全独立后再宣称全局保证。
- 1000次bootstrap可用于初步区间和数值稳定性，但普通百分位区间不自动产生有效的校正p。若用超越次数构造Monte Carlo p，1000次的分辨率约0.001，面对数千检验可能根本达不到校正门槛。正式p的计算、模拟预算或解析近似必须先定并校准。
- 要检验 R2=0，模拟零假设必须对应“残差变化为零”。不能简单把NT和perturbation都生成为无三阶项：真实NT已有高阶结构，这检验的是另一个更强命题。
- 若另测三阶log-linear参数差异，应允许NT具有非零三阶项，并明确这和R2不是同一个endpoint。
- 不默认BH在共享NT/重叠states下自动适用；选定Holm或其他方法，并记录依赖条件、原始p有效性和family。多重校正不能修复错误零假设、模型失配或NT预选择。

## 两个实验怎样连接

A中确定候选、state、方向、残差endpoint和检验family；在B中对整份锁定清单同时计算响应复现与残差检验。反向同理。不先用B筛400个“成功复现者”，再把这400个作为无选择的残差检验family。

报告交叉表：响应复现且有残差支持；响应复现但残差证据不足；未达响应复现门槛；不可评估。两个endpoint的校正范围分别明确；如果要宣称交集集合整体受控，需额外定义联合决策/错误预算，不能从两个单独校正自动继承。

## 实施顺序、资源与停止条件

1. 冻结分析协议；核对split与缓存的hash、cell-ID一对一映射及原benchmark排除。只使用预定metadata决定主/扩展cohort。
2. 建共同计数层：按fold×target×batch×triplet保存8格表，并对原全部NT/pooled scan做守恒核验。bit-packed缓存只解码57genes。
3. 开发与测试A/B适配器；同时用synthetic审查低阶估计/零假设。冻结两边discovery，再打开相互validation计算。若残差方案尚未冻结，则不能先看B复现结果再选择其统计规则。
4. 实施冻结的双方向分析与低阶评估，按triplet和bootstrap小块处理，导出所有未评估原因，不为增加发现调整规则。
5. 出图：流程与样本覆盖、A/B效应、方向/统计复现、观测与低阶预测、残差与不确定性、预定展示规则案例。

本地数据齐全，A/B适配与小规模低阶测试可本地完成。GPU不是必需品；有界内存设计应能接近现有无卡配置，但新增bootstrap/分层拟合的耗时与峰值尚未实测，不能沿用“4分25秒”承诺。先以metadata预选的规模做运行时测试再外推。若采用全流程折内重建，则另开协议，不覆盖现有341目录与Result 1。

## 依据

- [A/B split manifest](/Users/mac/Documents/ChatGPT/JURE/outputs/stage2_day6_ab_split_v1_20261007/SPLIT_MANIFEST.json)
- [当前扫描协议](/Users/mac/Documents/ChatGPT/JURE/perturbation_scan/PROTOCOL.md)
- [现有 NT residual screen 的边界](/Users/mac/Documents/ChatGPT/JURE/outputs/candidate_reference_residual_screen_20260930/REVIEW.md)
- [二阶投影实现](/Users/mac/Documents/ChatGPT/JURE/clue_discovery/v03/lower_order_null.py)
- [R p.adjust：Holm、BH、BY及其依赖条件](https://stat.ethz.ch/R-manual/R-devel/library/stats/html/p.adjust.html)
- [SciPy bootstrap：区间、重采样与分块计算](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.bootstrap.html)
