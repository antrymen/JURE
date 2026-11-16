# 框架与代码阅读路线

## 数据如何流动

```text
表达计数 + 细胞/基因标识 + 扰动标签 + 批次 + NT
    ↓ Dataset Adapter
参考联合状态 → 扰动效应及统计证据 → 共响应模块
    ↓ Triage / SelectedCase
Shared Case File
    ↔ Explorer：竞争假说、预测与修订
    ↔ Investigator：取证与结果解释
    ↔ Critic：审查、补查路由与停止判断
    ↓ 案例报告、证据状态、未解决问题
```

## 推荐阅读顺序

1. `clue_discovery/run.py`：统一入口和运行清单。
2. `clue_discovery/adapters/base.py`、`schemas/`：输入约束和输出契约。
3. `clue_discovery/reference/`、`perturbation_scan/`、`landscape/`：三阶段接口。
4. `perturbation_scan/statistics.py`、`scan.py`：条件检验、Holm和候选筛选。
5. `broad_screening/`：响应模块和稳定核心。
6. `triage/`、`jure/casefile/selected_adapter.py`：案例衔接。
7. `jure/casefile/models.py`、`store.py`：共享状态、版本与持久化。
8. `jure/agents/{explorer,investigator,critic}/`：三个角色；Critic的路由与停止逻辑。
9. `jure/runtime/`、`jure/tools/`：调度、恢复和工具契约。

`v02/v03/v04` 是真实依赖，不按目录名新旧删除。`nt_reference_experiment`还导入`real_data_test.prepare`，因此一并保留。

## 旧文档怎样看

`architecture/PROJECT_ARCHITECTURE.md` 是2026-10-25的研究目录地图，保留作背景。它引用的论文、outputs和数据路径通常仍在原研究目录，不属于本交付目录的独立示例。

源码目录里的README也可能记录当时状态，例如某时点只接通Mock工具或某个模型。它们不是2026-11-13统一运行状态；本目录README与DELIVERY_CHECKS明确的是此次验证范围。

## 为什么没有把所有东西放进src

当前入口存在以`__file__`定位项目根目录、读取邻近配置和生成源码哈希的代码。保留平铺包布局可以保持这类关系。平铺布局同样可安装；迁移src属于后续重构，不是本次文件交付的必要条件。
