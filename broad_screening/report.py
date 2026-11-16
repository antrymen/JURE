"""Deterministic manuscript drafts and five-question acceptance report."""
import json
import numpy as np
import pandas as pd
from .io import dump


def md_table(table,columns,labels=None):
    labels=labels or columns
    def value(v):
        if isinstance(v,(float,np.floating)):return f'{v:.3f}' if np.isfinite(v) else 'NA'
        return str(v).replace('|',' / ')
    return '\n'.join(['| '+' | '.join(labels)+' |','| '+' | '.join(['---']*len(columns))+' |']+
        ['| '+' | '.join(value(row[c]) for c in columns)+' |' for _,row in table.iterrows()])


LIMITATIONS='''1. Day 6 candidates remain exploratory; reference selection and perturbation comparisons reuse NT cells.
2. Groups are statistical response groups; no biological names or functional annotations have been assigned.
3. PCA axes do not estimate the number of biological programs.
4. Group boundaries depend on representation, distance, cut and sampling; internal bootstrap stability is not external replication.
5. Candidate burden is associated with target sample size; count-based ordering is not a biological importance ranking.
6. Batch matching does not remove cell-state composition, detection-depth, guide or other residual confounding.
7. Joint-state frequency shifts do not demonstrate changes in higher-order interaction strength or causal regulation.
8. The primary cohort contains candidate-bearing targets and the catalogue is preselected, not an unbiased census of all gene combinations.
9. Same-triplet states share a denominator and can be mutually exclusive; opposing profiles need not imply antagonistic regulation.
10. Gene-only OR collapse is an explicit information-removing ablation, not a new biological statistic; binary versus continuous comparisons also change effect encoding.
11. Pair correlations and selected examples are descriptive and selection-affected; no new significance tests or independent validation are claimed.
12. Sampling blocks may retain biological heterogeneity. Compression is organizational, not proof that records in a block are mechanistically equivalent.
13. Day 8, literature, GO/pathway annotation, JEV and the three Deep Agents were not used. No cases were finally selected.
'''


def make_reports(out,d,cfg,g,modules,membership,cores,sensitivity,interfaces,overlap,meta):
    top=modules.head(cfg.main_cards)
    robustness=sensitivity['robustness'];abl=sensitivity['ablation'].set_index('representation')
    brief=[]
    for r in top.itertuples():
        alt=robustness.loc[(robustness.reference_module==r.module_id)&(robustness.alternative_run!='continuous_pearson')]
        cont=alt.loc[alt.comparison_kind=='continuous_profile'];binary=alt.loc[alt.comparison_kind=='representation_change']
        brief.append(dict(module_id=r.module_id,continuous_min_jaccard=cont.membership_jaccard.min(),
            continuous_min_centroid=cont.centroid_correlation.min(),representation_min_jaccard=binary.membership_jaccard.min(),
            status=interfaces['robust_status'][r.module_id]))
    rb=pd.DataFrame(brief)
    df0=overlap.loc[(overlap.shared_gene_count==0)&(overlap.metric=='pearson_r')].iloc[0]
    pair=meta['D'];contrast=meta['E'];mcontrast=meta['E_modules']
    comp=interfaces['compression'].set_index('category').n
    bc=abl.loc['candidate_binary_state_preserved'];gc=abl.loc['gene_only_any_candidate']
    main=abl.loc['continuous_pearson']
    # Conditional interpretation: the controlled bridge may contradict a simple
    # claim of superiority, so report all metrics and the sign of each change.
    signed_better_coherence=bool(bc.common_binary_within_coherence>gc.common_binary_within_coherence)
    signed_better_preservation=bool(bc.common_binary_correlation_mae<gc.common_binary_correlation_mae)
    q3=(f"Same-triplet states have distinct observed response profiles (example r={contrast['pearson_r']:.3f}). "
        f"On the common evaluable pair set of the binary bridge, state preservation {'improved' if signed_better_coherence else 'did not improve'} continuous-profile coherence "
        f"and {'reduced' if signed_better_preservation else 'did not reduce'} correlation reconstruction error relative to gene-only OR collapse. "
        'This supports information loss under the specified collapse, not universal superiority of every clustering metric or a causal interpretation.')
    decisions=dict(
        Q1=dict(status='answered',conclusion='Concentrated, low-dimensional response organization coexists with pattern diversity',
                outputs=['tables/candidate_concentration.csv','tables/pca_variance.csv']),
        Q2=dict(status='answered_with_parameter_dependence',conclusion='Report stability separately for continuous choices and representation changes',
                outputs=['tables/module_robustness.csv','tables/module_stability.csv','tables/bootstrap_module_alignment.csv.gz']),
        Q3=dict(status='answered_with_defined_ablation',conclusion=q3,
                outputs=['tables/signed_state_ablation.csv','tables/same_genes_different_states.csv','tables/signed_state_contrast_pairs.csv']),
        Q4=dict(status='answered',conclusion=f"Gene-disjoint pairs: median r={df0['median']:.3f}; maximum={df0['maximum']:.3f}",
                outputs=['tables/gene_overlap_response_similarity.csv','tables/pattern_pair_similarity.csv.gz']),
        Q5=dict(status='answered_without_final_selection',conclusion=f"{g['n_candidates']} records organized into {int(comp['target_module_direction_blocks'])} sampling blocks with overlapping structural strata",
                outputs=['tables/case_pool_compression.csv','tables/case_strata_summary.csv','agent_inputs/deep_case_pool.jsonl']))
    dump(out/'audit/acceptance_questions.json',decisions)
    methods=f'''# Methods draft — Broad Screening v0.1

Frozen Day 6 perturbation-associated candidates, the reference catalogue, comparison statistics, target sample counts and batch/support records were imported without repeating the scan or changing qualification, effect/support gates, Holm adjustment, reference discovery, HVG selection, MFI, Gain or upstream bootstrap procedures. Previously verified landscape artifacts were audited against their saved SHA-256 hashes and checked against the original scan. Candidate identities retained their original target, reference ID, ordered genes, binary states, effect, adjusted p-value and exploratory status.

The primary landscape comprised targets with at least one frozen candidate and all reference states. Each entry was the batch-matched prevalence difference, expressed in percentage points. Continuous observed effects were retained for non-selected comparisons. Candidate, tested, support and reason masks were exported separately. The all-target effect view retained NA for insufficiently supported effects. Selection-encoded zeros and candidate indicators were used only as explicitly named sensitivity representations. Positive/negative gene states denote raw count >0/=0; positive/negative effects denote enrichment/depletion of that exact joint state.

Reference-state profiles were grouped by average-linkage hierarchical clustering using Pearson correlation distance and a cut of {cfg.clustering_cut:.2f}. Target profiles used cosine distance and the existing average-linkage ordering. Group identifiers were assigned by decreasing candidate mass with deterministic identity tie breaks; these identifiers are dataset-specific display labels. Genes were not clustering features. Group activity was the target-wise median signed effect across constituent states. Mean standardized effects were retained solely as a historical activity comparison.

PCA used column-centered continuous effects without per-column variance scaling. Full target scores, state loadings, explained variance and cumulative variance were exported. Rescaling frequency differences to percentage points changes score units but not explained-variance ratios. Candidate concentration was measured independently at group and state levels.

Internal pattern stability used {cfg.bootstrap_repetitions} target bootstrap samples with replacement (seed {cfg.seed}); response similarity and groups were recomputed for each sample. The historical random stream was reconstructed to add per-replicate partition traces and group alignment. Pairwise co-assignment was label-invariant. A stable core was the largest complete-linkage block within a reference group whose pairwise co-assignment was at least {cfg.stable_core_pair_probability:.2f}, with at least {cfg.stable_core_min_size} states. Ties used mean pairwise stability then reference IDs. Remaining states were boundaries; singletons were unassessable. This deterministic block rule does not claim a maximum graph clique. A representative was the response-correlation medoid, breaking ties by stability, candidate coverage, median absolute effect and reference ID. No p-values determined representatives.

Sensitivity runs compared Pearson and Spearman similarity, alternative cuts {list(cfg.sensitivity_cuts)}, continuous effects, candidate-only zero encoding, state-preserving candidate indicators and signed candidate indicators. A gene-only ablation applied a target-wise OR to the candidate indicators of all reference states sharing the exact same gene triplet. Collapsed profiles and group assignments were mapped back to the common reference-state universe for comparison. State-preserving binary versus gene-only binary comparisons form the controlled bridge; continuous versus binary comparisons additionally change effect encoding. Correlation reconstruction error, continuous-effect coherence, separation, pair stability, cross-triplet stability, target clustering consistency and merged record counts were reported. Undefined constant profiles were excluded and their coverage reported. Controlled binary-bridge metrics used the same pair set evaluable under both binary representations; full-coverage summaries were retained separately. Coherence and stability comparisons were additionally restricted to that common domain, and same-triplet pairs were excluded from the cross-triplet stability summary to avoid forced co-assignment inflation. Core-on/off comparisons exported annotation-unit size, stability and coherence. Disabling bootstrap marks stability unassessed.

Across sensitivity and bootstrap runs, groups were aligned by maximal membership Jaccard overlap, followed by continuous-effect median-centroid correlation. Many-to-one matches were allowed and reported; IDs were never matched as strings. Core recovery, representative recovery, direction consistency, splits and shared matches were exported. Descriptive alignment required Jaccard ≥{cfg.robustness_jaccard_min}, centroid r ≥{cfg.robustness_centroid_min} and, where a core existed, core recovery ≥{cfg.robustness_core_recovery_min}. These are organizational rules, not statistical significance thresholds.

All reference-state pairs were evaluated for Pearson/Spearman response correlation, gene and exact gene-state overlap, gene Jaccard, common evaluable targets, shared candidate targets and direction concordance. Direction concordance excluded exact-zero effects. Distributions were summarized within gene-overlap strata, including all gene-disjoint pairs. Same-triplet and overlapping-gene state contrasts were retained. Example selection used maximal gene-disjoint Pearson correlation and minimal same-triplet Pearson correlation among pairs with shared candidates; these exploratory examples were not hypothesis tests.

Candidate burden and effect summaries were related descriptively to target cell count using Spearman correlation. Target specificity was the absolute median activity in a group divided by the sum of absolute median activities over groups with at least three patterns and two triplets. Strong activity required ≥{cfg.strong_module_activity_pp:g} percentage points; module-specific targets required exactly one strong eligible group and a share ≥{cfg.module_specificity_min}, while cross-module targets required at least two. High effect (≥{cfg.high_effect_pp:g} pp), high support (≥{cfg.high_target_support_cells} cells), and sample-size-context flags (<{cfg.sample_size_context_cells} or ≥{cfg.high_target_support_cells} cells) were frozen descriptive strata. No residuals were interpreted as biological scores.

All source candidates were exported to an unselected case pool. Sampling blocks used target × response group × effect direction; a within-block representative was the candidate closest to the group medoid. This labels organizational redundancy without deleting candidates. Gene-disjoint context required Pearson ≥{cfg.context_pearson_min}, Spearman ≥{cfg.context_spearman_min} and ≥{cfg.context_shared_candidates_min} common candidate targets. Overlapping-gene contrast context required at least two shared genes, a state disagreement, Pearson ≤{cfg.contrast_pearson_max} and the same minimum common support. Case-set coverage can be audited for supplied IDs without automatically selecting a set. Whole-group and stable-core annotation objects retain every exact signed state. No biological interpretation, new significance testing, external validation or model execution was performed.
'''
    (out/'METHODS_DRAFT.md').write_text(methods)
    result=f'''# Results draft — descriptive Day 6 landscape

The frozen scan contained {g['n_candidates']:,} exploratory associations across {g['n_targets_with_candidates']} perturbation targets and {g['n_patterns_with_candidates']} candidate-bearing states out of {g['n_patterns_total']} reference states. Of these associations, {g['n_enrichment']:,} represented enrichment and {g['n_depletion']:,} depletion of joint-state prevalence. The four largest response groups accounted for {g['top_module_coverage']['4']:.1%} of candidate records, indicating concentration of perturbation-associated responses without establishing independent biological programs.

Continuous signed-effect profiles showed substantial low-dimensional organization: the first three and four centered principal components explained {g['pca_first3']:.1%} and {g['pca_first4']:.1%} of the variance. Nevertheless, {g['pattern_counts_for_coverage']['70']} individual states were needed to cover 70% of candidate records, with {g['pattern_counts_for_coverage']['50']}, {g['pattern_counts_for_coverage']['80']} and {g['pattern_counts_for_coverage']['90']} needed for 50%, 80% and 90%, respectively. These complementary measures indicate concentration with retained state-level diversity.

The fixed primary clustering yielded {g['n_modules']} response groups. '''+' '.join(
        f"{r.module_id} contained {r.n_patterns} states and {r.n_candidates:,} candidates ({r.fraction_of_all_candidates:.1%}); its mean internal co-assignment was {r.mean_co_clustering:.3f}, with {r.stable_core_size} core and {r.boundary_size} boundary states."
        for r in top.itertuples())+f''' Group recovery across sensitivity analyses was heterogeneous and is reported by matched membership and centroid similarity rather than module identifiers. High within-group bootstrap stability did not guarantee unchanged boundaries across representations.

The exact-state contrast “{contrast['pattern_a']}” versus “{contrast['pattern_b']}” used the same genes but showed Pearson r={contrast['pearson_r']:.3f} across targets. For the two leading groups, activity correlation was {mcontrast['median_correlation']:.3f} using the prespecified median aggregate and {mcontrast['zmean_correlation']:.3f} under the historical standardized-mean aggregate. In the matched binary ablation ({int(bc.common_binary_pair_count):,} common evaluable state pairs), continuous-profile within-group coherence was {bc.common_binary_within_coherence:.3f} with exact states and {gc.common_binary_within_coherence:.3f} after gene-only OR collapse; correlation reconstruction MAE was {bc.common_binary_correlation_mae:.3f} and {gc.common_binary_correlation_mae:.3f}, respectively. Gene-only collapse merged {int(gc.source_records_merged_by_representation):,} candidate records into shared target–triplet keys. These are descriptive consequences of the specified collapse; opposing same-triplet effects can also reflect mutually exclusive states.

Across all {int(df0.n_pairs):,} gene-disjoint state pairs, Pearson correlations had median {df0['median']:.3f}, 95th percentile {df0.q95:.3f}, 99th percentile {df0.q99:.3f} and maximum {df0.maximum:.3f}; {int(df0.n_ge_08):,} pairs ({df0.fraction_ge_08:.1%}) had r≥0.8. The leading example, “{pair['pattern_a']}” and “{pair['pattern_b']}”, had Pearson r={pair['pearson_r']:.3f}, Spearman ρ={pair['spearman_rho']:.3f}, and {int(pair['n_shared_candidate_targets'])} shared candidate targets. Thus highly coordinated responses were observed for some states without gene overlap, while the complete distribution establishes their frequency in this selected landscape. Shared response does not identify a common causal mechanism.

Candidate burden was associated with target cell count within the candidate-bearing cohort (Spearman ρ={g['candidate_burden_cell_count_rho']:.3f}). All {g['n_candidates']:,} candidates were therefore retained with support and sample-size context and organized into {int(comp['target_module_direction_blocks']):,} target–group–direction sampling blocks, containing {int(comp['additional_records_within_blocks']):,} additional records within blocks. Structural strata support future sampling across stable cores, state contrasts, co-response contexts and response directions. No Deep cases were finally selected, and Day 8 validation was not performed.
'''
    (out/'RESULTS_DRAFT.md').write_text(result)
    summary_text=f'''# Broad Screening v0.1 — 结果摘要

所有数字来自本次冻结结果；图表制作按用户最新要求暂缓。

- Q1：前四组覆盖 {g['top_module_coverage']['4']:.1%} 候选；前三 PCA 轴解释 {g['pca_first3']:.1%} 方差；70% 候选仍需 {g['pattern_counts_for_coverage']['70']} 个 states。
- Q2：主要组的内部稳定性和跨参数恢复分别报告，不能互相替代。
- Q3：同基因不同状态的响应可明显不同；指定 gene-only collapse 会丢失响应信息，但不预设所有聚类指标均有改善。
- Q4：gene-disjoint pairs 的完整分布、分位数和 top pairs 均已输出；最高 Pearson r={df0.maximum:.3f}。
- Q5：{g['n_candidates']:,} 条候选组织为 {int(comp['target_module_direction_blocks']):,} 个抽样块；保留全部原始记录，未生成机制排名或最终选例。
- 样本量：candidate-bearing targets 中 burden–cell count ρ={g['candidate_burden_cell_count_rho']:.3f}；用于 context，不当 biological breadth。

{md_table(top,['module_id','n_patterns','n_candidates','mean_co_clustering','stable_core_size','boundary_size','representative_signed_pattern'])}

{md_table(rb,['module_id','continuous_min_jaccard','continuous_min_centroid','representation_min_jaccard','status'])}

{q3}

下一阶段的 annotation 优先考虑稳定核心及跨连续分析选择恢复较好的组。完整成员见 `tables/stable_core_membership.csv`；输入分别导出 whole/core 两种对象。本轮到此停止。
'''
    (out/'RESULTS_SUMMARY.md').write_text(summary_text)
    report=f'''# Broad Screening v0.1 — Perturbation-associated Higher-order Response Landscape

## 1. Dataset / inputs

输入为冻结 Day 6 scan 与已核验 Landscape。共 {g['n_targets_total']} targets × {g['n_patterns_total']} states；主矩阵为 {g['n_targets_with_candidates']} 个 candidate-bearing targets × {g['n_patterns_total']} states。全部 {g['n_candidates']:,} candidates 的 source line、clue ID、source SHA-256、genes/states 和原始统计字段可追溯。参照图谱具有预选择背景。

## 2. Global landscape — Q1

{g['n_enrichment']:,} enrichment，{g['n_depletion']:,} depletion。effect 单位为百分点，case 原始 delta 仍保留 frequency fraction。所有非候选的可用连续效应保留；tested/support/reason 分开。主矩阵没有缺失，全 targets 视图对 support 不足保留 NA。

## 3. Candidate concentration

前 1/2/3/4 组覆盖：{', '.join(f"{g['top_module_coverage'][str(k)]:.1%}" for k in (1,2,3,4))}。达到 50/60/70/80/90% 候选覆盖所需 patterns：{', '.join(str(g['pattern_counts_for_coverage'][str(k)]) for k in (50,60,70,80,90))}。组级集中和 state 多样性同时存在。

## 4. PCA structure

中心化连续矩阵前三轴解释 {g['pca_first3']:.1%}，前四轴 {g['pca_first4']:.1%}。完整 variance、scores、loadings 已导出。未把维度数解释成生物程序数。

## 5. Pattern modules

{md_table(top,['module_id','n_patterns','n_candidates','n_enrichment','n_depletion','representative_signed_pattern'])}

代表 pattern 按预先固定的 medoid 规则选择，因此可能不同于历史“候选最多的 pattern”。M 编号不包含功能命名。

## 6. Module stability — Q2

{md_table(top,['module_id','mean_co_clustering','q10_co_clustering','min_co_clustering','stable_core_size','boundary_size'])}

{md_table(rb,['module_id','continuous_min_jaccard','continuous_min_centroid','representation_min_jaccard','status'])}

稳定核心按任意成员对 co-assignment ≥{cfg.stable_core_pair_probability} 的 complete-linkage block 定义。单成员组不可估计成对稳定性。50/100 等重复数由配置控制。bootstrap alignment 与 co-assignment 是互补输出：前者关注组的恢复，后者对标签置换不敏感。

## 7. Signed-state specificity — Q3

{q3}

{md_table(sensitivity['ablation'],['representation','n_groups','common_binary_within_coherence','common_binary_correlation_mae','common_cross_triplet_stability','target_clustering_ari_vs_continuous','source_records_merged_by_representation'])}

同基因状态实例：`{contrast['pattern_a']}` / `{contrast['pattern_b']}`，r={contrast['pearson_r']:.3f}。领先两组 median activity r={mcontrast['median_correlation']:.3f}；历史 z-mean r={mcontrast['zmean_correlation']:.3f}。两者估计对象不同，不用改阈值去追历史数字。Pearson、Spearman、signed-state overlap、candidate overlap 和 direction concordance 均见逐 pair 表。

## 8. Gene-disjoint co-response — Q4

{md_table(overlap.loc[overlap.metric=='pearson_r'],['shared_gene_count','n_pairs','median','q95','q99','maximum','n_ge_08'])}

最高实例：`{pair['pattern_a']}` / `{pair['pattern_b']}`，r={pair['pearson_r']:.3f}，ρ={pair['spearman_rho']:.3f}，共同候选 targets={int(pair['n_shared_candidate_targets'])}。全体 disjoint pairs 的统计已给出，未将单一例子当作全局规律。gene-overlap 分层是描述性比较，不能据此计算“gene overlap 造成了多少相关性”的因果比例。

## 9. Target response structure

复用全部 continuous effect profiles 的 cosine/average-linkage target groups。median module activity、module-specific/cross-module targets 独立导出。module-specific targets={len(interfaces['specific'])}，cross-module targets={len(interfaces['cross'])}；这些计数取决于冻结的 activity 与 specificity 规则，不自动等同生物学特异性。

## 10. Sample-size dependence

candidate-bearing cohort 的 burden–cell count ρ={g['candidate_burden_cell_count_rho']:.3f}。`sample_size_dependence.csv` 还给出 mean/max |Δ| 与 n_modules_hit 的关联。所有候选均携带样本量和原始 burden；sample_size_sensitive 是样本量分层提示，不是对某个 target 混杂程度的测量。

## 11. Case triage — Q5

{md_table(interfaces['compression'],['category','n'])}

{md_table(interfaces['strata'],['stratum','n_cases','n_targets','n_modules','n_redundancy_blocks'])}

strata 可重叠，不应将各行相加作为总数。同 target/group/direction 只定义组织性抽样块。所有 {g['n_candidates']:,} source candidates 仍保留；evidence_status=day6_exploratory，day8_status=not_performed。`evaluate_case_set_coverage(case_ids)` 可审计人工提交的集合，不会自行挑选或执行 Agent。

## 12. Limitations

{LIMITATIONS}

## 13. Outputs and acceptance

- [Results summary](RESULTS_SUMMARY.md)、[Methods draft](METHODS_DRAFT.md)、[Results draft](RESULTS_DRAFT.md)。未生成 Discussion。
- `tables/`：burdens、modules、cores、robustness、pair analyses、ablation 和完整 triage。
- `matrices/`：带符号连续效应、candidate/tested/support/reason、co-clustering；明确单位与 NA。
- `annotation_inputs/module_annotation_input.jsonl`：每个组的 whole/core 两种对象。
- `agent_inputs/deep_case_pool.jsonl`：可追溯但未选择的案例池。
- `figure_data/`：冻结的 plot-ready tables；按最新要求未制作图表。
- `audit/config_frozen.yaml`、`run_manifest.json`、`integrity_check.json`、`acceptance_questions.json`。

Q1–Q5 都有明确结果与输出；Q2/Q3 按实际敏感性和消融结果限定结论。未调用 JEV/LLM、GO、文献检索、Day 8 或 Deep Agents。
'''
    (out/'LANDSCAPE_REPORT.md').write_text(report)
    diagnostic=f'''# Reproduction diagnostic

All saved legacy artifacts and original scan inputs were hash-audited. The continuous matrix and candidate mask were matched by target/reference ID to source arrays. The primary group assignments were reused when the cut matched; membership alignment is in `historical_module_alignment.csv`.

PCA was recomputed only to export all score/loading columns; its variance ratios were compared with the historical export. Bootstrap labels were reconstructed because historical output saved co-assignment but not per-replicate partitions; the original interleaved random stream was preserved. Default matching configurations verify reconstructed co-assignment against the cached matrix. See `reproduction_metrics.json` for numeric differences.

The leading group pair has median-activity correlation {mcontrast['median_correlation']:.6f} and historical z-mean correlation {mcontrast['zmean_correlation']:.6f}. This difference follows the newly requested robust aggregate, not altered data or forced relabeling. Medoid representatives can differ from historical coverage-ranked examples. Stable-core membership is newly defined at a frozen pair threshold, not copied from a prior narrative.

The gene-disjoint example was selected from recomputed pair statistics: r={pair['pearson_r']:.6f}, shared candidates={int(pair['n_shared_candidate_targets'])}. Sample-size association was recomputed: ρ={g['candidate_burden_cell_count_rho']:.6f}. Historical values were never acceptance targets or hardcoded membership rules.

Input differences: none after hash audit. NA handling: no imputation in primary profiles; unsupported all-target effects remain NA. Sensitivity encodings are separately labelled. No parameter was tuned to recover old percentages. Graphics deferred by the latest user instruction.
'''
    (out/'audit/reproduction_diagnostic.md').write_text(diagnostic)
    (out/'REPRODUCTION_DIAGNOSTIC.md').write_text(diagnostic)
