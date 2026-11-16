"""Deterministic Chinese report rendering from measured summaries."""
from __future__ import annotations


def markdown_table(headers, rows):
    return '\n'.join(['| ' + ' | '.join(headers) + ' |',
                      '| ' + ' | '.join(['---'] * len(headers)) + ' |'] +
                     ['| ' + ' | '.join(str(v).replace('|', '/') for v in row) + ' |' for row in rows])


def write_report(output, s, targets, patterns, modules, target_groups, sensitivity):
    active = modules.loc[modules.group_kind == 'provisional_response_module'].sort_values('candidates', ascending=False)
    top = patterns.sort_values(['candidate_targets', 'reference_id'], ascending=[False, True]).head(12)
    tg = target_groups.sort_values('targets', ascending=False).head(10)
    fmt = lambda v: f'{v:.1%}'
    lines = ['# Day 6 Broad Screening v0.1：Landscape Analysis', '',
        '**本轮只有数值分析：未调用 LLM、Jev、三个调查 Agent 或外部知识库；未读取 Day 8。所有分组为描述性结构，尚无生物学功能命名。**', '',
        f"已验证输入包含 {s['source_candidates']:,} 个探索性 candidates，来自 {s['source_targets']:,} 个允许 targets 中的 {s['main_targets']} 个；主矩阵为 **{s['main_targets']}×{s['reference_patterns']}**。{s['candidate_patterns']} 个 patterns 至少有一条 candidate，涉及 {s['candidate_triplets']} 个 triplets；原 Catalogue 为 {s['reference_triplets']} 个 triplets。", '',
        '## 主要结果', '',
        f"- **{s['enrichment']:,} enrichment（{s['enrichment']/s['source_candidates']:.1%}），{s['depletion']:,} depletion（{s['depletion']/s['source_candidates']:.1%}）。** 正负表示联合检出状态频率增加/减少，不是基因上调/下调。",
        f"- 每个 candidate-bearing target 平均关联 **{s['target_candidate_distribution']['mean']:.2f}** 个 patterns，中位数 **{s['target_candidate_distribution']['median']:g}**，IQR {s['target_candidate_distribution']['q25']:g}–{s['target_candidate_distribution']['q75']:g}，范围 {s['target_candidate_distribution']['min']}–{s['target_candidate_distribution']['max']}。",
        f"- 按全部 {s['reference_patterns']} patterns 计算，每个平均关联 **{s['pattern_candidate_distribution_all']['mean']:.2f}** 个 targets；只按 {s['candidate_patterns']} 个活跃 patterns 计算为 **{s['pattern_candidate_distribution_active']['mean']:.2f}**。",
        f"- 最常见的前 10 / 20 个 patterns 分别占 **{fmt(s['concentration']['patterns']['top_10'])} / {fmt(s['concentration']['patterns']['top_20'])}** candidates；达到 70% 需要 **{s['concentration']['patterns']['number_for_70pct']} 个 patterns**。按 triplet 合并计数后，前 10 triplets 占 {fmt(s['concentration']['triplets']['top_10'])}。",
        f"- 前 3 个中心化 PCA 轴解释 **{fmt(s['top3_centered_pca_variance'])}** 方差，前 4 个为 **{fmt(s['top4_centered_pca_variance'])}**；80% / 90% 方差分别需要 {s['components_for_80pct_variance']} / {s['components_for_90pct_variance']} 个轴。未中心化前 3 个轴解释 {fmt(s['top3_raw_effect_energy'])} 平方效应能量。",
        f"- 固定 distance=0.30 得到 **{s['target_groups']} 个 target groups、{s['pattern_groups']} 个 pattern groups**；其中 {s['provisional_modules']} 组满足至少 3 patterns 且至少 2 triplets 的临时模块标准。前 3 / 4 个 pattern groups 占 **{fmt(s['top3_pattern_groups_candidate_fraction'])} / {fmt(s['top4_pattern_groups_candidate_fraction'])}** candidates。分组切点是预定描述参数，不是显著性或真实程序数估计。", '',
        '观察到较强的共享响应结构，同时仍有局部差异：候选不是彼此独立的故事，但当前数值结果不足以把全景压缩成几个已知生物程序。candidate 集中度、矩阵低秩和聚类分组是三个不同问题，不能直接改写成“若干 stress/cell-cycle programs 解释了同样比例的机制”。', '',
        '## 完整连续效应与候选视图', '',
        '![完整连续效应](figures/01_continuous_landscape.png)', '',
        '主图包含所有可估计的 Δ，包括未通过筛选的格子。行以 cosine distance、列以 Pearson correlation distance 作 average linkage；显示原始效应而非按行标准化数值。完整树和行列顺序均导出，色条仅辅助辨认分组。', '',
        '![筛选后候选](figures/02_candidate_heatmap.png)', '',
        '第二张图使用相同顺序，非候选为灰色。灰色是“未入选”，不能解释为缺失效应或真实零效应。', '',
        f"主矩阵中原始 Δ 缺失 {s['main_raw_effects_missing']} 个；有 **{s['main_non_candidates_with_nonzero_effect']:,} 个非候选格子仍有非零观察效应**。selection-encoded 矩阵保留原连续矩阵 {fmt(s['selection_retained_effect_energy'])} 的平方效应能量。", '',
        markdown_table(['主矩阵状态', '格数'], [(k, f'{v:,}') for k, v in s['main_matrix_status'].items()]), '',
        '## 跨 target 反复出现的 patterns', '',
        markdown_table(['Pattern', 'Targets', 'Enrichment', 'Depletion', '候选占比', '组'],
            [(r.pattern, r.candidate_targets, r.enrichment_targets, r.depletion_targets,
              f'{r.candidate_share:.1%}', r.pattern_group) for r in top.itertuples()]), '',
        '同一 triplet 的不同 states、共享一个/两个 genes 的 patterns 并不独立。相关 pair 表显式保存 same_triplet 与 shared_gene_count；另导出基因完全不重叠的高相关 patterns 作为后续调查入口。', '',
        '## 临时 response modules', '',
        'M 编号来自固定切点的相关分组，按候选条数排序编号；该排序只影响展示，不参与聚类。表内 genes 是组成摘要，不是 pathway 注释。稳定性是 50 次 target 重采样下原组内成对 co-assignment 平均值。', '',
        markdown_table(['组', 'Patterns / triplets', 'Candidates', '占比', '正 / 负', '组内稳定性', '常见 genes'],
            [(r.pattern_group, f'{r.patterns} / {r.triplets}', r.candidates, f'{r.candidate_fraction:.1%}',
              f'{r.enrichment} / {r.depletion}', f'{r.mean_coassignment:.2f}', r.top_genes)
             for r in active.head(12).itertuples()]), '',
        '![模块指纹](figures/04_module_fingerprints.png)', '',
        '该图每组取不同 triplets 中 candidate 最多的至多 3 个 patterns，按主要 target groups 显示 Δ 中位数；是可读摘要，不能据此覆盖完整矩阵。', '',
        '![模块间相关](figures/05_module_relationships.png)', '',
        '正相关模块可能仍存在共同背景；反相关模块可能只是同一 triplet 的互斥状态。模块 z-mean 只表示跨 targets 标准化后的描述性活动，不能当机制置信度。', '',
        '模块边界应结合稳定性解读。高平均 co-assignment 不代表每个成员同样稳定；完整表同时保存 10% 分位数与最低成对稳定性，可优先区分稳定核心和边界成员。主切点给出细分组，不应将全部分组数量等同于独立 response programs。', '',
        '## 相似 perturbation profiles', '',
        markdown_table(['组', 'Targets', 'Candidates', 'Medoid', '重采样稳定性', '候选较多的示例 targets'],
            [(r.target_group, r.targets, r.candidates, r.medoid,
              f'{r.mean_coassignment:.2f}' if r.pairs else 'NA：单成员', r.example_targets) for r in tg.itertuples()]), '',
        '每个 target 的前 5 个近邻见 `tables/target_nearest_neighbours.csv`。距离基于全部 continuous delta；同时给出同方向 candidate 的 Jaccard 与样本量，避免只凭最大 effect 看相似性。target 稳定性按 triplet 整块重采样，保留同一 triplet 内各 state 的依赖。', '',
        '## 参数与选择敏感性', '',
        markdown_table(['轴', '输入', 'cut', '组数', '最大组', 'ARI vs 主分析'],
            [(r['axis'], r['input'], r['cutoff'], r['groups'], r['largest_group'], f"{r['adjusted_rand_vs_primary']:.3f}")
             for r in sensitivity]), '',
        f"triplet 等权后的前三 PCA 轴解释 {fmt(s['top3_equal_triplet_pca_variance'])} 方差。另以全体 **{s['adequate_targets']} 个总体样本/对照充足 targets** 重做 pattern clustering，检视只分析 419 个入选 targets 带来的选择影响。ARI 仅比较分组，不是外部验证。", '',
        f"candidate 数量与 target cell count 的 Spearman ρ 为 **{s['candidate_degree_vs_target_cells_spearman']:.3f}**。本图仍可能受样本量/功效、共同 NT、检测水平、guide 和细胞组成影响；本轮没有做细胞层面的机制区分。", '',
        '![分布与低维结构](figures/03_landscape_diagnostics.png)', '',
        '## 文件与复现', '',
        markdown_table(['文件', '用途'], [
            ('matrices/observed.csv.gz', '419×341 原始 matched Δ；不把非候选填零'),
            ('matrices/candidate_only.csv.gz', '只有候选保留 Δ，其他 NA；NA 指未入选'),
            ('matrices/selection_encoded.csv.gz', '通过总体 support 的非候选编码 0；不充分/缺失为 NA；编码 0 非真实效应 0'),
            ('matrices/candidate_mask.csv.gz + status.csv.gz', '候选身份与逐格筛选状态；与数值矩阵联用'),
            ('matrices/all_targets_observed_and_masks.npz', '2034 个 targets 的原始 Δ、mask、reason、n 与 adequate 标志'),
            ('tables/target_summary.csv / pattern_summary.csv / triplet_summary.csv', 'degree、方向、集中度和统计背景'),
            ('tables/pattern_modules.csv / target_groups.csv', '成员数、稳定性与示例；具体成员在 pattern/target summary'),
            ('tables/structural_triage_features.csv', '全部 6129 条的结构特征；无生物学/novelty 判断，尚未选 Day 8 或 Deep cases'),
            ('figures/*.png / *.pdf', '可预览和导出的科学图'),
            ('ANALYSIS_FROZEN.json / RUN_MANIFEST.json / SUMMARY.json', '方法参数、输入/代码/产物 hashes、核验与数字摘要')]), '',
        '```bash', 'MPLCONFIGDIR="$PWD/tmp/landscape_mpl" .venv/bin/python -m landscape_analysis.run \\',
        '  --output outputs/broad_screening_v01_landscape_reproduction', '```', '',
        '输出目录必须不存在，脚本拒绝覆盖。输入扫描、算法、Catalogue、candidate mask 与 Day 8 均不修改。', '',
        '## 下一阶段边界', '',
        '先根据稳定的结构分组做 module-level biological interpretation，比较数据库检索或轻量模型是否有增益；当前不决定 Jev 接入。随后按效应、特异性、模块覆盖、方向、已知/稀少证据和 Day 8 可评估性冻结 20–30 例及验证规则，再从验证结果选 5–10 个 Deep cases。当前结构表不是最终选例，也不是机制发现清单。', '']
    (output / 'LANDSCAPE_REPORT.md').write_text('\n'.join(lines))
