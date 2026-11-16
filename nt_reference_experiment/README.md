# NT two-fold reference experiment

新增入口为 `clue_discovery.nt_reference` 和本目录，原 v0.2 不变。代码已完成本地合成验证，另提供面向 2 GB 无卡实例的低内存运行方式；实际运行是否完成及其结果以对应输出目录的 `execution_status.json` 和报告为准。

实验规则见 [PROTOCOL.md](PROTOCOL.md)。真实实验固定使用 NT-only、GEM 分层 two-fold、各 fold 自己的 Fano top12、2–4 阶、marginal MFI、α=0.5、1,000 次 bootstrap 及原筛选门槛。首次成功运行后再讨论实验结果；禁止自动修改阈值寻找阳性。

## 本地验证

在项目根目录运行：

```bash
.venv/bin/python -m pytest -q
OPENBLAS_NUM_THREADS=1 .venv/bin/python -m nt_reference_experiment.demo \
  --kind parity --run-dir outputs/nt_twofold_synthetic_parity
.venv/bin/python -m nt_reference_experiment.report \
  --run-dir outputs/nt_twofold_synthetic_parity
OPENBLAS_NUM_THREADS=1 .venv/bin/python -m nt_reference_experiment.demo \
  --kind sparse --run-dir outputs/nt_twofold_synthetic_sparse
.venv/bin/python -m nt_reference_experiment.report \
  --run-dir outputs/nt_twofold_synthetic_sparse
```

输出目录必须为空，防止覆盖结果。Parity 演示含预先设定的三阶和四阶结构；sparse 演示验证不可估计表/空目录的完整输出。两者都用 1,000 次 bootstrap，报告明确标记 SYNTHETIC。模块为四个人工变量，不能与真实 12 基因模块的预期成功率类比。

## 之后的真实运行

在能访问原始 h5ad 的 CPU 环境、项目根目录执行：

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
python -m nt_reference_experiment.run \
  --source /root/autodl-tmp/data/public_crispri/ReplogleWeissman2022_K562_essential.h5ad \
  --run-dir outputs/nt_twofold_replogle_run01 --project-root .
MPLBACKEND=Agg python -m nt_reference_experiment.report \
  --run-dir outputs/nt_twofold_replogle_run01
```

不需要 GPU。读取原数据需要 anndata/h5py，报告需要 matplotlib；实际软件版本自动保存。HDF5 使用 64 MiB chunk cache，仅读取明确的 NT 行。第一遍分块累积各 fold 的 raw-count Fano 统计，第二遍只保留两个冻结模块的基因并集（最多 24 列）。每块最多 128 行，不同时保留完整 NT × 全基因矩阵和两个副本；不读取 `uns/obsm/raw/layers`。保存 NT 逐细胞 metadata 供后续深度/批次审计，不分析 perturbation。

Linux 低内存试跑可通过 `python -m nt_reference_experiment.measure --output resources.json --rss-limit-mib 1400 -- <运行命令>` 包装。它记录子进程 RSS、容器 2 GB 限制、匿名内存与文件缓存；子进程 RSS 超过 1,400 MiB 时主动停止。不会因为可回收文件缓存占用高而误判，也不更改机器配置、其他服务或实验门槛。0.5 核 CPU 可能使运行更慢；是否能跑完以实测为准。

## 结果定位

- `nt_fold_manifest.json`：数据、A/B IDs、实际模块、参数、环境和代码 hash。
- `discoveries_frozen.json`：双方向 discovery 完成且验证开始前的 checkpoint。
- `fold_A_discovery.csv` 与 `fold_B_validation.csv`：A→B。
- `fold_B_discovery.csv` 与 `fold_A_validation.csv`：B→A。
- `cross_fold_summary.csv`：精确状态的单向验证及双向重发现。
- `state_table_estimability.csv`：完整表稀疏指标、MFI 摘要及 bootstrap 数组索引。
- `mfi_bootstrap_distributions.npz`：原始 MFI bootstrap 分布。
- `order_reproducibility_summary.csv`：每阶、每方向的状态和 gene-set 数量。
- `nt_reference_metadata.json`：各统计家庭、锁定 hash、seed/namespace、停止原因。
- `REPORT.md`、`summary.json`、`overview.png/pdf`：报告和图。

`mfi_only_stable` 是基因组合的估计稳定性；`within_fold_stable` 还要求具体状态满足支持数与富集门槛。`cross_fold_replicated` 不强制双向重发现，`bidirectionally_rediscovered` 则要求相同 genes+states+order 被两边各自发现并双向通过。

q 值仅属于所标注方向和阶段的 enrichment family，不能叫作 MFI FDR。两个方向共享 A/B，并非两项独立实验；先前使用过的 NT 仍是开发数据。
