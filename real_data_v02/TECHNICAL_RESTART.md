# 首轮读取缓存修复

第一次启动在 discovery NT 读取阶段停止，尚未输出 feature selection、manifest 或任何统计检验结果。原日志、split IDs 和退出记录保存在远端 `attempt01_io/`。

源文件 X 是 float32 稠密 gzip 数据集，chunk=(1213,67)。逐次取得 AnnData.X 会反复打开 HDF5 Dataset，并重复解压相同块。修复后保持一个 Dataset 对象和 128 MiB raw chunk cache；原 extract 的允许行、行序、原始计数校验、列选择均不改变。缓存只影响底层读取，不将其他行用于分析。

重跑沿用 PROTOCOL.md 的所有规则、seed、划分和统计阈值。新增测试覆盖压缩矩阵中的非连续行、跨块、列重排、排除行和文件关闭。算法模块未修改。

第二次启动后实际探针显示 HDF5 复用了 AnnData 已打开文件的默认 8 MiB 缓存，未使用申请的 128 MiB；在仍未输出模块或统计结果时停止，并存为 `attempt02_io/`。进一步修复为先关闭仅用于读取 metadata 的文件，再打开缓存读取器；新增实际缓存大小断言。第三次启动为正式完成的统计运行。
