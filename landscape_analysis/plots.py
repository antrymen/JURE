"""Publication-style static figures, with continuous and filtered views separate."""
from __future__ import annotations

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap, ListedColormap
from scipy.cluster.hierarchy import dendrogram

INK = '#193441'
MUTED = '#637682'
RED = '#bb4939'
BLUE = '#286c8e'
GRAY = '#e4e8ea'
PALETTE = ['#2a7182', '#d57a44', '#748e4e', '#8d6aa4', '#437bad', '#c05872',
           '#7d795b', '#54a296', '#ba9b40', '#737cc0', '#976345', '#4c6978']
DELTA = LinearSegmentedColormap.from_list('matched_delta', [BLUE, '#fcfcf9', RED], N=256)
DELTA.set_bad('#d9dfe2')


def style():
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 10,
        'axes.titlesize': 12, 'axes.titleweight': 'bold', 'axes.labelcolor': INK,
        'text.color': INK, 'xtick.color': MUTED, 'ytick.color': MUTED,
        'axes.edgecolor': '#cbd3d7', 'axes.spines.top': False, 'axes.spines.right': False,
        'figure.facecolor': 'white', 'axes.facecolor': 'white', 'savefig.facecolor': 'white',
        'pdf.fonttype': 42, 'svg.fonttype': 'none'})


def save(fig, output, name):
    fig.savefig(output / 'figures' / f'{name}.png', dpi=210, bbox_inches='tight')
    fig.savefig(output / 'figures' / f'{name}.pdf', bbox_inches='tight')
    plt.close(fig)


def main_heatmap(output, delta, mask, row_tree, col_tree, rgroup, cgroup, filtered):
    ro, co = row_tree['order'], col_tree['order']
    values = 100 * delta[np.ix_(ro, co)]
    if filtered:
        values = np.where(mask[np.ix_(ro, co)], values, np.nan)
    limit = max(10, float(np.ceil(np.max(np.abs(delta)) * 10) * 10))
    fig = plt.figure(figsize=(16, 11))
    fig.text(.055, .967, 'DAY 6  /  PERTURBATION LANDSCAPE', fontsize=11, color=MUTED, weight='bold')
    fig.text(.055, .927, 'Selected candidates in the same landscape' if filtered else
             'Shared response structure across perturbations', fontsize=23, weight='bold')
    fig.text(.055, .893, f'{len(delta):,} candidate-bearing targets × {delta.shape[1]} reference patterns  ·  '
             f'{int(mask.sum()):,} exploratory associations', fontsize=12, color=MUTED)
    top = fig.add_axes([.16, .77, .69, .095])
    dendrogram(col_tree['linkage'], ax=top, no_labels=True, color_threshold=0, above_threshold_color='#9aaab2')
    top.set_axis_off()
    left = fig.add_axes([.055, .17, .083, .58])
    dendrogram(row_tree['linkage'], ax=left, orientation='left', no_labels=True,
               color_threshold=0, above_threshold_color='#9aaab2')
    left.invert_yaxis(); left.set_axis_off()
    c_codes = {g: i for i, g in enumerate(sorted(set(cgroup)))}
    r_codes = {g: i for i, g in enumerate(sorted(set(rgroup)))}
    cmap = ListedColormap(PALETTE)
    stripe = fig.add_axes([.16, .758, .69, .007])
    stripe.imshow([[c_codes[g] % len(PALETTE) for g in cgroup[co]]], aspect='auto', cmap=cmap,
                  vmin=0, vmax=len(PALETTE)-1); stripe.set_axis_off()
    stripe = fig.add_axes([.145, .17, .006, .58])
    stripe.imshow([[r_codes[g] % len(PALETTE)] for g in rgroup[ro]], aspect='auto', cmap=cmap,
                  vmin=0, vmax=len(PALETTE)-1); stripe.set_axis_off()
    ax = fig.add_axes([.16, .17, .69, .58])
    im = ax.imshow(values, cmap=DELTA, vmin=-limit, vmax=limit, aspect='auto', interpolation='nearest', rasterized=True)
    ax.set_xticks([]); ax.set_yticks([])
    ax.set_xlabel('Reference patterns · hierarchical order', labelpad=10)
    fig.text(.025, .46, 'Perturbation targets · hierarchical order', rotation=90,
             ha='center', va='center', fontsize=10)
    for spine in ax.spines.values(): spine.set_visible(False)
    counts = fig.add_axes([.87, .17, .075, .58], sharey=ax)
    counts.barh(np.arange(len(ro)), mask[ro].sum(1), height=1, color='#456d7b', linewidth=0)
    counts.set_ylim(len(ro)-.5, -.5); counts.set_yticks([])
    counts.set_xlabel('Candidate\npatterns', fontsize=9)
    counts.tick_params(axis='x', labelsize=8)
    counts.spines['left'].set_visible(False)
    cbax = fig.add_axes([.60, .075, .25, .016])
    cb = fig.colorbar(im, cax=cbax, orientation='horizontal')
    cb.set_label('Matched Δ (percentage points)', fontsize=10)
    fig.text(.055, .092, 'Gray = not selected; observed Δ remains available.' if filtered else
             'All observed effects retained, including non-candidates.', fontsize=10)
    fig.text(.055, .069, 'Trees use continuous Δ: target cosine / pattern correlation; average linkage.', fontsize=9, color=MUTED)
    fig.text(.055, .048, 'Color strips: distance 0.30 groups (palette reused). Full identities and leaf order are in CSV.',
             fontsize=9, color=MUTED)
    fig.text(.055, .027, 'Exploratory structure only · no biological annotation · no Day 8 validation', fontsize=9, color=MUTED)
    save(fig, output, '02_candidate_heatmap' if filtered else '01_continuous_landscape')


def make_figures(output, delta, mask, targets, refs, names, row_tree, col_tree, rgroup,
                 cgroup, target_table, pattern_table, modules, module_scores, summary,
                 pca_xy, explained, raw_energy, sensitivity):
    style()
    main_heatmap(output, delta, mask, row_tree, col_tree, rgroup, cgroup, False)
    main_heatmap(output, delta, mask, row_tree, col_tree, rgroup, cgroup, True)
    fig, axes = plt.subplots(2, 3, figsize=(16, 10))
    fig.subplots_adjust(left=.075, right=.96, top=.84, bottom=.10, hspace=.48, wspace=.32)
    fig.text(.075, .956, 'DAY 6  /  LANDSCAPE DIAGNOSTICS', fontsize=11, color=MUTED, weight='bold')
    fig.text(.075, .914, 'How concentrated is the candidate landscape?', fontsize=23, weight='bold')
    fig.text(.075, .877, f"{summary['enrichment']:,} enrichment + {summary['depletion']:,} depletion  ·  "
        f"{summary['candidate_patterns']} of {summary['reference_patterns']} patterns have candidates", color=MUTED, fontsize=12)
    ax = axes[0, 0]
    ax.hist(target_table.candidates, bins=25, color='#447b8b', edgecolor='white', linewidth=.6)
    ax.axvline(summary['target_candidate_distribution']['median'], color=RED, linestyle='--', linewidth=1.3)
    ax.set(title='A   Candidate burden per target', xlabel='Selected patterns', ylabel='Targets')
    ax.text(.97, .93, f"Median {summary['target_candidate_distribution']['median']:g}\n"
        f"Mean {summary['target_candidate_distribution']['mean']:.1f}", transform=ax.transAxes, ha='right', va='top')
    ax = axes[0, 1]
    ax.hist(pattern_table.candidate_targets, bins=25, color='#d58b65', edgecolor='white', linewidth=.6)
    ax.set(title='B   Recurrence of each pattern', xlabel='Targets with a selected association', ylabel='Reference patterns')
    ax.text(.97, .93, f"{int((pattern_table.candidate_targets == 0).sum())} patterns\nhave no candidates",
            transform=ax.transAxes, ha='right', va='top')
    ax = axes[0, 2]
    for values, label, color in [(pattern_table.candidate_targets.values, 'Patterns', RED),
                                 (target_table.candidates.values, 'Targets', BLUE)]:
        y = np.cumsum(np.sort(values)[::-1]) / np.sum(values)
        ax.plot(np.arange(1, len(y)+1), y * 100, label=label, color=color, linewidth=2)
    ax.axhline(70, color='#a1abb1', linestyle=':', linewidth=1)
    ax.set(title='C   Candidate concentration', xlabel='Top-ranked patterns / targets', ylabel='Cumulative candidate share (%)', ylim=(0, 103))
    ax.legend(frameon=False, loc='lower right')
    ax = axes[1, 0]
    for values, label, color in [(explained, 'Centered variance', BLUE), (raw_energy, 'Uncentered effect energy', RED)]:
        ax.plot(np.arange(1, 16), np.cumsum(values)[:15] * 100, 'o-', markersize=3, color=color, label=label)
    ax.axhline(80, color='#a1abb1', linestyle=':', linewidth=1)
    ax.set(title='D   Low-dimensional structure', xlabel='Number of components', ylabel='Cumulative fraction (%)', ylim=(0, 103))
    ax.legend(frameon=False, fontsize=9, loc='lower right')
    ax = axes[1, 1]
    ax.scatter(target_table.n_cells, target_table.candidates, s=15, alpha=.6, color=BLUE, edgecolors='none')
    ax.set_xscale('log')
    ax.set(title='E   Sample size and candidate burden', xlabel='Target cells (log scale)', ylabel='Selected patterns')
    ax.text(.03, .94, f"Spearman ρ = {summary['candidate_degree_vs_target_cells_spearman']:.2f}", transform=ax.transAxes, va='top')
    ax = axes[1, 2]
    largest = target_table.groupby('target_group').size().sort_values(ascending=False).head(6).index.tolist()
    ax.scatter(pca_xy[:, 0], pca_xy[:, 1], s=15, color='#b7c1c6', alpha=.6, label='Other groups', edgecolors='none')
    for i, group in enumerate(largest):
        ix = rgroup == group
        ax.scatter(pca_xy[ix, 0], pca_xy[ix, 1], s=19, alpha=.8, color=PALETTE[i], label=f'{group} (n={ix.sum()})', edgecolors='none')
    ax.set(title='F   Targets in the first two PCs', xlabel=f'PC1 ({explained[0]:.1%})', ylabel=f'PC2 ({explained[1]:.1%})')
    ax.legend(frameon=False, fontsize=7.5, loc='best', handlelength=.8, borderpad=.1)
    fig.text(.075, .034, 'All diagnostics condition on the candidate-bearing target set. PCs and clusters are descriptive, not biological program counts.',
             fontsize=10, color=MUTED)
    save(fig, output, '03_landscape_diagnostics')

    # Readable fingerprints: selected signature columns, with all raw data retained elsewhere.
    chosen_modules = modules.loc[modules.group_kind == 'provisional_response_module'].sort_values(
        'candidates', ascending=False).head(8)
    chosen_cols = []
    col_labels = []
    for module in chosen_modules.pattern_group:
        rows = pattern_table.loc[pattern_table.pattern_group == module].sort_values('candidate_targets', ascending=False)
        rows = rows.drop_duplicates('triplet').head(3)
        for row in rows.itertuples():
            j = int(np.flatnonzero(refs == row.reference_id)[0])
            chosen_cols.append(j)
            col_labels.append(f'{module}   {names[j]}')
    chosen_targets = target_table.groupby('target_group').size().sort_values(ascending=False).head(12)
    selected_groups = chosen_targets.index.tolist()
    cells = np.array([np.median(delta[rgroup == group][:, chosen_cols], axis=0) for group in selected_groups]).T * 100
    if len(chosen_cols):
        fig = plt.figure(figsize=(16, max(8, len(chosen_cols) * .33 + 3.4)))
        fig.text(.045, .963, 'DAY 6  /  DESCRIPTIVE RESPONSE SIGNATURES', fontsize=11, color=MUTED, weight='bold')
        fig.text(.045, .922, 'Representative patterns distinguish target groups', fontsize=23, weight='bold')
        fig.text(.045, .886, 'Three recurrent patterns from distinct triplets per major module; colors show group-median observed Δ.',
                 fontsize=11, color=MUTED)
        ax = fig.add_axes([.34, .21, .56, .60])
        limit = max(10, np.ceil(np.max(np.abs(cells))/10)*10)
        im = ax.imshow(cells, aspect='auto', cmap=DELTA, vmin=-limit, vmax=limit, interpolation='nearest')
        ax.set_yticks(np.arange(len(col_labels)), col_labels, fontsize=9)
        ax.set_xticks(np.arange(len(selected_groups)), [f'{g}\nn={chosen_targets[g]}' for g in selected_groups], fontsize=9)
        ax.tick_params(axis='both', length=0, pad=8)
        for spine in ax.spines.values(): spine.set_visible(False)
        for i in range(1, len(col_labels)):
            if col_labels[i].split()[0] != col_labels[i-1].split()[0]:
                ax.axhline(i-.5, color='white', linewidth=2)
        cbax = fig.add_axes([.68, .105, .22, .019])
        cb = fig.colorbar(im, cax=cbax, orientation='horizontal')
        cb.set_label('Median matched Δ (percentage points)', fontsize=10)
        fig.text(.045, .11, f'Displayed target groups cover {int(chosen_targets.sum())} / {len(targets)} targets.', fontsize=10)
        fig.text(.045, .075, 'M IDs are correlation groups; + / − mean detected / undetected, not differential-expression direction.', fontsize=10, color=MUTED)
        fig.text(.045, .045, 'Gene names identify patterns only. No pathway, stress, or cell-cycle annotation has been assigned.', fontsize=10, color=MUTED)
        save(fig, output, '04_module_fingerprints')

    # Signed module relationships show anticorrelation without merging opposing patterns.
    active = modules.loc[modules.candidates > 0].sort_values('candidates', ascending=False).head(16).pattern_group.tolist()
    corr = module_scores[active].corr().values
    fig, ax = plt.subplots(figsize=(10, 9))
    fig.subplots_adjust(left=.10, right=.87, top=.82, bottom=.12)
    im = ax.imshow(corr, cmap=DELTA, vmin=-1, vmax=1)
    ax.set_xticks(range(len(active)), active, fontsize=10)
    ax.set_yticks(range(len(active)), active, fontsize=10)
    ax.tick_params(length=0)
    fig.colorbar(im, ax=ax, fraction=.045, pad=.05, label='Pearson correlation of module z-mean profiles')
    fig.suptitle('Module relationships include opposing responses', y=.95, fontsize=19, weight='bold')
    fig.text(.10, .875, 'Largest candidate-bearing groups · averages of standardized continuous pattern effects', fontsize=10, color=MUTED)
    fig.text(.10, .046, 'Anticorrelation can reflect alternative states of overlapping gene sets. It does not establish regulation.', fontsize=9, color=MUTED)
    save(fig, output, '05_module_relationships')
