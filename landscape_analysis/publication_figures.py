"""Redraw three frozen landscape figures; no re-clustering or model calls.

The publication preview uses an explicitly labelled, symmetric asinh colour
normalization. Source values, candidate masks and dendrograms are unchanged.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import AsinhNorm, LinearSegmentedColormap, ListedColormap
from matplotlib.patches import Rectangle
import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import dendrogram, leaves_list

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'outputs/broad_screening_v01_landscape_20260927'
OUTPUT = ROOT / 'outputs/broad_screening_v01_paper_preview_20260927'
INK = '#182127'
GRAY = '#647078'
TREE = '#647079'
BLUE = '#2166ac'
RED = '#b2182b'
MASK_GRAY = '#e8ebed'
OTHER = '#d1d6d9'
WIDTH_MM = 180
HEIGHT_MM = 168
MODULE_COLORS = dict(zip([f'M{i:02d}' for i in range(1, 9)],
    ['#332288', '#66aacc', '#44aa99', '#117733', '#999933', '#ddcc77', '#cc6677', '#882255']))
TARGET_COLORS = dict(zip([f'T{i:02d}' for i in range(1, 5)],
    ['#6a3d9a', '#1b9e77', '#377eb8', '#c99413']))
EFFECT_CMAP = LinearSegmentedColormap.from_list('effect',
    [(0, '#174c83'), (.22, '#4d91bd'), (.40, '#b4d5e6'), (.5, '#ffffff'),
     (.60, '#efc0b4'), (.78, '#ce6856'), (1, '#8e172c')], N=512)
EFFECT_CMAP.set_bad(MASK_GRAY)
CORR_CMAP = LinearSegmentedColormap.from_list('correlation',
    [BLUE, '#ffffff', RED], N=512)
CORR_CMAP.set_bad('#ffffff')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def mm_axes(fig, x, y, w, h):
    width, height = fig.get_size_inches() * 25.4
    return fig.add_axes([x / width, y / height, w / width, h / height])


def mm_text(fig, x, y, text, **kwargs):
    width, height = fig.get_size_inches() * 25.4
    return fig.text(x / width, y / height, text, **kwargs)


def setup():
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 7,
        'axes.labelsize': 7, 'axes.titlesize': 9, 'xtick.labelsize': 6,
        'ytick.labelsize': 6, 'text.color': INK, 'axes.labelcolor': INK,
        'xtick.color': GRAY, 'ytick.color': GRAY, 'axes.edgecolor': '#949da2',
        'axes.linewidth': .4, 'xtick.major.width': .4, 'ytick.major.width': .4,
        'xtick.major.size': 2, 'ytick.major.size': 2, 'axes.spines.top': False,
        'axes.spines.right': False, 'figure.facecolor': 'white', 'axes.facecolor': 'white',
        'savefig.facecolor': 'white', 'mathtext.default': 'regular'})


def load(source):
    manifest = json.loads((source / 'RUN_MANIFEST.json').read_text())
    used = ['matrices/observed.csv.gz', 'matrices/candidate_mask.csv.gz',
            'matrices/linkage_and_order.npz', 'tables/target_summary.csv',
            'tables/pattern_summary.csv', 'tables/pattern_modules.csv',
            'tables/module_activity_descriptive_zmean.csv', 'SUMMARY.json']
    hashes = {}
    for rel in used:
        hashes[rel] = sha(source / rel)
        if hashes[rel] != manifest['artifacts_sha256'][rel]:
            raise ValueError(f'Frozen input hash mismatch: {rel}')
    observed = pd.read_csv(source / used[0], index_col=0)
    mask = pd.read_csv(source / used[1], index_col=0).astype(bool)
    if not observed.index.equals(mask.index) or not observed.columns.equals(mask.columns):
        raise ValueError('Mask and matrix axes differ')
    if observed.shape != (419, 341) or mask.values.sum() != 6129:
        raise ValueError('Unexpected landscape dimensions')
    with np.load(source / used[2], allow_pickle=False) as z:
        trees = {k: z[k].copy() for k in z.files}
    for prefix in ('target', 'pattern'):
        if not np.array_equal(leaves_list(trees[f'{prefix}_linkage']), trees[f'{prefix}_order']):
            raise ValueError('Saved tree and leaf order differ')
    target = pd.read_csv(source / used[3]).set_index('target').loc[observed.index]
    pattern = pd.read_csv(source / used[4]).set_index('reference_id').loc[observed.columns]
    modules = pd.read_csv(source / used[5])
    scores = pd.read_csv(source / used[6], index_col=0).loc[observed.index]
    summary = json.loads((source / 'SUMMARY.json').read_text())
    return observed, mask, trees, target, pattern, modules, scores, summary, hashes


def tree_axes(fig, rect, linkage, orientation):
    ax = mm_axes(fig, *rect)
    dendrogram(linkage, ax=ax, orientation=orientation, no_labels=True,
               color_threshold=0, above_threshold_color=TREE)
    for coll in ax.collections:
        coll.set_linewidth(.28)
        coll.set_alpha(.85)
    if orientation == 'left':
        ax.invert_yaxis()
    ax.set_axis_off()
    return ax


def band(fig, rect, groups, colors, orientation):
    values = ['other'] + list(colors)
    cmap = ListedColormap([OTHER] + list(colors.values()))
    numbers = np.array([values.index(g) if g in colors else 0 for g in groups])
    matrix = numbers[None, :] if orientation == 'horizontal' else numbers[:, None]
    ax = mm_axes(fig, *rect)
    ax.imshow(matrix, cmap=cmap, vmin=0, vmax=len(values)-1, aspect='auto',
              interpolation='nearest')
    ax.set_axis_off()


def landscape(fig, observed, mask, trees, target, pattern, filtered):
    ro, co = trees['target_order'], trees['pattern_order']
    raw_pp = observed.values * 100
    values = raw_pp[np.ix_(ro, co)]
    selected = mask.values[np.ix_(ro, co)]
    if filtered:
        values = np.ma.masked_where(~selected, values)
    norm = AsinhNorm(linear_width=5, vmin=-65, vmax=65, clip=False)
    assert raw_pp.min() >= norm.vmin and raw_pp.max() <= norm.vmax
    r_groups = target.target_group.values[ro]
    c_groups = pattern.pattern_group.values[co]
    n, m = values.shape
    letter = 'B' if filtered else 'A'
    title = 'Exploratory perturbation-associated candidates' if filtered else 'Perturbation response landscape'
    mm_text(fig, 5, 162, letter, fontsize=12, weight='bold', va='baseline')
    mm_text(fig, 12, 162, title, fontsize=10, weight='bold', va='baseline')
    subtitle = ('6,129 selected associations | 4,202 enrichment; 1,927 depletion' if filtered else
                '419 perturbation targets × 341 reference patterns | Day 6, K562')
    mm_text(fig, 12, 157, subtitle, fontsize=7, color=GRAY)

    x, y, w, h = 31, 35, 125, 101
    tree_axes(fig, (x, 142, w, 10.5), trees['pattern_linkage'], 'top')
    tree_axes(fig, (8, y, 12.5, h), trees['target_linkage'], 'left')
    band(fig, (x, 138, w, 1.7), c_groups, MODULE_COLORS, 'horizontal')
    band(fig, (27, y, 1.7, h), r_groups, TARGET_COLORS, 'vertical')
    ax = mm_axes(fig, x, y, w, h)
    ax.imshow(values, cmap=EFFECT_CMAP, norm=norm, aspect='auto', interpolation='nearest')
    ax.set_autoscale_on(False)
    ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values(): s.set_visible(False)

    # Highlight only eight leading pattern groups and four major target groups;
    # all remaining cells remain in the original matrix and order.
    for group, color in MODULE_COLORS.items():
        ix = np.flatnonzero(c_groups == group)
        if not len(ix): continue
        start, end = ix.min() - .5, ix.max() + .5
        if len(ix) != int(end - start): raise ValueError('Pattern group is not contiguous')
        ax.plot([start, end], [n + .8, n + .8], color=color, linewidth=1.4, clip_on=False)
        xpos = x + (ix.mean() + .5) / m * w
        mm_text(fig, xpos, 31.8, group, ha='center', va='top', fontsize=6.2, color=color, weight='bold')
    for group, color in TARGET_COLORS.items():
        ix = np.flatnonzero(r_groups == group)
        if not len(ix): continue
        ypos = y + h * (1 - (ix.mean() + .5) / n)
        mm_text(fig, 24, ypos, group, ha='center', va='center', rotation=90,
                fontsize=6.5, color=color, weight='bold')
    mm_text(fig, 3.2, y + h/2, 'Perturbation targets', rotation=90, fontsize=7, ha='center', va='center')
    mm_text(fig, x + w/2, 25, 'Reference patterns', fontsize=7, ha='center')

    # Candidate burden on an explicit integer scale; the two plots use the same
    # bars so masking cannot change the meaning of the side summary.
    counts = mm_axes(fig, 160, y, 13, h)
    plus = ((raw_pp > 0) & mask.values).sum(1)[ro]
    minus = ((raw_pp < 0) & mask.values).sum(1)[ro]
    counts.barh(np.arange(n), plus, height=1, color=RED, linewidth=0)
    counts.barh(np.arange(n), minus, left=plus, height=1, color=BLUE, linewidth=0)
    counts.set_ylim(n-.5, -.5); counts.set_xlim(0, 110)
    counts.set_xticks([0, 50, 100]); counts.set_yticks([])
    counts.tick_params(axis='x', labelsize=5.5, pad=1.5)
    counts.spines[['left', 'right', 'top']].set_visible(False)
    mm_text(fig, 166.5, 138, 'Candidates\nper target', ha='center', va='bottom', fontsize=5.7, linespacing=1.15)

    cax = mm_axes(fig, 31, 13.2, 78, 2.4)
    cb = fig.colorbar(matplotlib.cm.ScalarMappable(norm=norm, cmap=EFFECT_CMAP), cax=cax, orientation='horizontal')
    cb.set_ticks([-60, -20, -5, 0, 5, 20, 60])
    cb.set_ticklabels(['−60', '−20', '−5', '0', '5', '20', '60'])
    cb.minorticks_off(); cb.outline.set_linewidth(.35)
    cb.ax.tick_params(labelsize=6, pad=1.5, length=2)
    mm_text(fig, 70, 18, 'Matched Δ frequency (percentage points)', fontsize=7, ha='center')
    mm_text(fig, 70, 5, 'asinh color scale; complete effect range retained', fontsize=6.2, ha='center', color=GRAY)
    for yy, color, text in [(19, RED, 'Enrichment'), (13.5, BLUE, 'Depletion')]:
        fig.add_artist(Rectangle((123/WIDTH_MM, yy/HEIGHT_MM), 2/WIDTH_MM, 2/HEIGHT_MM,
                                 transform=fig.transFigure, facecolor=color, edgecolor='none'))
        mm_text(fig, 127, yy + .05, text, va='bottom', fontsize=6.5)
    if filtered:
        fig.add_artist(Rectangle((123/WIDTH_MM, 8/HEIGHT_MM), 2/WIDTH_MM, 2/HEIGHT_MM,
                                 transform=fig.transFigure, facecolor=MASK_GRAY, edgecolor='#b3babf', linewidth=.3))
        mm_text(fig, 127, 8.05, 'Not selected', fontsize=6.5)
    else:
        mm_text(fig, 123, 8, 'All observed effects', fontsize=6.4, color=GRAY)


def correlations(fig, modules, scores):
    # Replicate the group subset from the original figure, including the tie rule.
    selected = modules.loc[modules.candidates > 0].sort_values('candidates', ascending=False).head(16)
    groups = selected.pattern_group.tolist()
    records = selected.set_index('pattern_group')
    corr = scores[groups].corr().values
    k = len(groups)
    masked = np.ma.masked_where(np.triu(np.ones((k, k), bool), 1), corr)
    mm_text(fig, 5, 162, 'C', fontsize=12, weight='bold')
    mm_text(fig, 12, 162, 'Response-group correlations', fontsize=10, weight='bold')
    mm_text(fig, 12, 157, '16 leading candidate-bearing groups | Pearson r across 419 perturbation targets', fontsize=7, color=GRAY)

    x, y, size = 16, 46, 103
    ax = mm_axes(fig, x, y, size, size)
    ax.imshow(masked, cmap=CORR_CMAP, vmin=-1, vmax=1, interpolation='nearest')
    ax.set_xticks(range(k), groups, rotation=90, fontsize=6)
    ax.set_yticks(range(k), groups, fontsize=6.5)
    ax.tick_params(axis='both', length=0, pad=2.5)
    for s in ax.spines.values(): s.set_visible(False)
    for i in range(k):
        for j in range(i + 1):
            value = corr[i, j]
            # Diagonal is visually quiet; its known self-correlation is retained.
            if i == j:
                ax.add_patch(Rectangle((j-.5, i-.5), 1, 1, facecolor='#edf0f2', edgecolor='white', linewidth=.35))
                text, color = '1', GRAY
            else:
                ax.add_patch(Rectangle((j-.5, i-.5), 1, 1, fill=False, edgecolor='white', linewidth=.35))
                text = f'{0.0 if abs(value) < .005 else value:.2f}'.replace('-', '−')
                color = 'white' if abs(value) >= .62 else INK
            ax.text(j, i, text, ha='center', va='center', fontsize=5.1, color=color)

    # Matched row metadata supplies composition without assigning pathway names.
    meta = mm_axes(fig, 124, y, 52, size)
    meta.set_xlim(0, 52); meta.set_ylim(k-.5, -.5); meta.set_axis_off()
    meta.text(1.5, -1.0, 'Patterns', fontsize=6.3, ha='center', va='bottom', weight='bold')
    meta.text(15, -1.0, 'Candidates', fontsize=6.3, ha='center', va='bottom', weight='bold')
    meta.text(28, -1.0, 'Frequent genes', fontsize=6.3, ha='left', va='bottom', weight='bold')
    for i, group in enumerate(groups):
        r = records.loc[group]
        if i % 2 == 0:
            meta.add_patch(Rectangle((-2, i-.5), 56, 1, facecolor='#f5f7f8', edgecolor='none'))
        meta.text(1.5, i, str(int(r.patterns)), va='center', ha='center', fontsize=6.1)
        meta.text(15, i, f'{int(r.candidates):,}', va='center', ha='center', fontsize=6.1)
        genes = r.top_genes.split('; ')[:3]
        meta.text(28, i, ', '.join(genes[:2]) + '\n' + genes[2], va='center', ha='left',
                  fontsize=5.65, linespacing=1.12)
    cax = mm_axes(fig, 16, 27, 62, 2.5)
    cb = fig.colorbar(matplotlib.cm.ScalarMappable(norm=matplotlib.colors.Normalize(-1, 1), cmap=CORR_CMAP),
                     cax=cax, orientation='horizontal')
    cb.set_ticks([-1, -.5, 0, .5, 1]); cb.ax.tick_params(labelsize=6, pad=2)
    cb.outline.set_linewidth(.35)
    mm_text(fig, 47, 32, 'Pearson correlation', ha='center', fontsize=7)
    mm_text(fig, 93, 29, 'Group activity: mean standardized pattern Δ', fontsize=6.4)
    mm_text(fig, 93, 23, 'Gene lists describe composition, not pathway annotations.', fontsize=6.1, color=GRAY)
    mm_text(fig, 16, 12, 'Groups are defined from continuous effects; opposing profiles may include alternative states of shared genes.',
            fontsize=6.2, color=GRAY)
    return groups, corr


def save_png(fig, path, dpi):
    fig.savefig(path, dpi=dpi, facecolor='white', edgecolor='none')
    plt.close(fig)


def main(source, output, dpi=450):
    if output.exists():
        raise FileExistsError('Choose a new preview output directory; frozen figures are not overwritten.')
    output.mkdir(parents=True)
    setup()
    data = load(source)
    observed, mask, trees, target, pattern, modules, scores, summary, hashes = data
    for filtered in (False, True):
        fig = plt.figure(figsize=(WIDTH_MM/25.4, HEIGHT_MM/25.4))
        landscape(fig, observed, mask, trees, target, pattern, filtered)
        name = 'B_selected_candidates.png' if filtered else 'A_continuous_landscape.png'
        save_png(fig, output / name, dpi)
    fig = plt.figure(figsize=(WIDTH_MM/25.4, HEIGHT_MM/25.4))
    groups, corr = correlations(fig, modules, scores)
    save_png(fig, output / 'C_group_correlations.png', dpi)
    pd.DataFrame(corr, index=pd.Index(groups, name='group'), columns=groups).to_csv(output / 'C_source_correlations.csv')
    key = modules.loc[modules.pattern_group.isin(groups)].set_index('pattern_group').loc[groups]
    key.to_csv(output / 'group_key.csv')
    captions = '''# Figure captions — paper previews

**A. Perturbation response landscape.** Batch-matched changes in joint detection-state frequency across 419 perturbation targets with at least one selected association and 341 frozen reference patterns in Day 6 K562 data. Rows and columns retain the original average-linkage ordering, using cosine distance for targets and Pearson correlation distance for patterns. All observed effects, including non-selected comparisons, are shown. Colors represent frequency differences in percentage points with a symmetric asinh normalization (linear width 5 percentage points; limits −65 to +65); colorbar ticks are in the original units. No values are clipped. Strips identify the eight leading pattern groups (M01–M08) and four leading target groups (T01–T04), ranked by candidate count; other groups are gray. Bars give enrichment and depletion candidate counts per target.

**B. Selected exploratory associations.** The same matrix, ordering and color normalization as A, retaining only the 6,129 exploratory candidates (4,202 enrichment and 1,927 depletion). Gray cells indicate non-selected comparisons, not zero effects or missing measurements. Candidates retain the original effect/support gates and selected-family Holm screening; they do not acquire confirmatory error control or external validation through this visualization.

**C. Response-group correlations.** Lower-triangular Pearson correlations between the activity profiles of the same 16 leading candidate-bearing groups shown in the original analysis figure. For each group, activity is the mean of its constituent patterns' delta values standardized across the 419 targets. Numeric labels show Pearson r; self-correlations are muted. Right-hand annotations give the number of reference patterns, selected associations and three frequent constituent genes. Groups may include small groups or a singleton; group identities are descriptive rather than independently established biological programs. Anticorrelation may partly reflect alternative states of overlapping gene sets.

## 展示说明

- 仅重绘，不重新聚类、筛选或命名生物学功能；原始矩阵、candidate mask 与 row/column order 不变。
- A/B 使用相同的 **asinh 非线性色阶**，刻度仍为原始百分点；完整保留 −39.23 至 +61.06 个百分点的观察范围。色阶是视觉映射，不是按行/列重新标准化数据。
- 主要分组使用唯一颜色和 M/T 标签，其他组统一灰色；B 中矩阵灰色表示未入选，与组色条中的灰色语义不同。
- C 保留原图的 16 个 groups 及顺序，只有上三角重复信息被隐藏。数字、矩阵 CSV 与颜色互相对应。
- 当前按用户要求仅导出 PNG 预览，未生成 SVG 或 PDF。

## 复现

```bash
MPLCONFIGDIR="$PWD/tmp/publication_mpl" .venv/bin/python -m landscape_analysis.publication_figures \\
  --output outputs/paper_preview_reproduction
```
'''
    (output / 'FIGURE_CAPTIONS.md').write_text(captions)
    if any(sha(source / p) != digest for p, digest in hashes.items()):
        raise RuntimeError('Analysis inputs changed during redraw')
    manifest = dict(created_utc=datetime.now(timezone.utc).isoformat(), source=str(source),
        source_inputs_sha256=hashes, rendering_script_sha256=sha(__file__),
        format='PNG only', dpi=dpi, figure_size_mm=[WIDTH_MM, HEIGHT_MM],
        data_and_clustering_unchanged=True, candidate_count=int(mask.values.sum()),
        row_order_unchanged=True, column_order_unchanged=True,
        color_normalization=dict(type='asinh', linear_width_pp=5, vmin_pp=-65, vmax_pp=65,
                                 observed_min_pp=float(observed.values.min()*100),
                                 observed_max_pp=float(observed.values.max()*100), clipped_values=0),
        correlation_groups=groups, model_calls=0, day8_accessed=False,
        matplotlib=matplotlib.__version__, numpy=np.__version__, pandas=pd.__version__,
        artifacts_sha256={p.name: sha(p) for p in sorted(output.iterdir()) if p.is_file()})
    (output / 'RENDER_MANIFEST.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(dict(output=str(output), figures=3, candidate_count=int(mask.values.sum()),
                          unchanged_inputs=True, clipped_values=0, dpi=dpi)))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=SOURCE)
    parser.add_argument('--output', type=Path, default=OUTPUT)
    parser.add_argument('--dpi', type=int, default=450)
    args = parser.parse_args()
    main(args.source.resolve(), args.output.resolve(), args.dpi)
