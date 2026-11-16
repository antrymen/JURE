"""Restyle frozen validation results; no statistical estimation or refiltering."""
from pathlib import Path
import hashlib
import json
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
INTERNAL = ROOT / "manuscript/figures/Figure3A/Figure3A_source_data.csv"
SUMMARY = ROOT / "outputs/result2_preliminary_20261012/n100"
CROSS = ROOT / "outputs/result2_cross_dataset"
INPUTS = [
    INTERNAL, SUMMARY / "summary_A_to_B.json", SUMMARY / "summary_B_to_A.json",
    CROSS / "bidirectional_summary.csv", CROSS / "day6_to_day8_validation.csv",
    CROSS / "day8_discovery/day8_to_day6_validation.csv",
]

def hashes():
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in INPUTS}

before = hashes()
plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 10,
    "axes.titlesize": 12, "axes.labelsize": 10, "xtick.labelsize": 9,
    "ytick.labelsize": 9, "axes.spines.top": False,
    "axes.spines.right": False, "axes.linewidth": .8,
    "figure.facecolor": "white", "axes.facecolor": "white",
    "pdf.fonttype": 42, "ps.fonttype": 42,
})

def draw(name, panels, xlabel, ylabel, internal=False):
    # Identical page size and square panel dimensions for both figures.
    fig = plt.figure(figsize=(12, 6.3))
    axes = [fig.add_axes([x, .14, .39, .39 * 12 / 6.3])
            for x in (.075, .585)]
    for letter, ax, panel in zip("AB", axes, panels):
        title, frame, xc, yc, stats = panel
        x, y = frame[xc].to_numpy(), frame[yc].to_numpy()
        assert len(x) == int(stats["evaluable"])
        assert np.isfinite(x).all() and np.isfinite(y).all()
        if internal:
            lim = (-70, 70)
            ax.axhline(0, color="#dddddd", lw=.8, zorder=0)
            ax.axvline(0, color="#dddddd", lw=.8, zorder=0)
        else:
            # Preserve the original cross-dataset plot's limits exactly.
            values = np.r_[x, y]
            pad = np.ptp(values) * .06
            lim = (values.min() - pad, values.max() + pad)
        ax.scatter(x, y, s=9 if internal else 8,
                   alpha=.35 if internal else .25, color="#8065A6",
                   edgecolors="none", rasterized=False)
        ax.plot(lim, lim, "--", color="#999999", lw=1, zorder=0)
        ax.set(xlim=lim, ylim=lim, xlabel=xlabel, ylabel=ylabel)
        ax.set_aspect("equal")
        ax.set_title(title, pad=10)
        ax.text(-.105, 1.045, letter, transform=ax.transAxes,
                fontweight="bold", fontsize=14, va="bottom")
        rate = (f"Same direction + Holm significant = {stats['replication_rate']:.2%}"
                if internal else f"Same direction = {stats['direction_agreement']:.2%}")
        label = (f"n = {int(stats['evaluable']):,}\n"
                 f"Pearson r = {stats['pearson']:.3f}\n{rate}")
        ax.text(.035, .965, label, transform=ax.transAxes, va="top",
                fontsize=9, linespacing=1.5)
    fig.savefig(OUT / f"{name}.png", dpi=300)
    fig.savefig(OUT / f"{name}.pdf")
    plt.close(fig)

internal = pd.read_csv(INTERNAL)
panels = []
for key, title in [("A_to_B", "A → B"), ("B_to_A", "B → A")]:
    stats = json.loads((SUMMARY / f"summary_{key}.json").read_text())
    panels.append((title, internal.loc[internal.direction == key],
                   "discovery_delta_pp", "validation_delta_pp", stats))
draw("Supplementary_Figure_S1", panels,
     "Discovery joint-state change, ΔP (pp)",
     "Validation joint-state change, ΔP (pp)", internal=True)

summary = pd.read_csv(CROSS / "bidirectional_summary.csv").set_index("direction")
forward = pd.read_csv(CROSS / "day6_to_day8_validation.csv")
reverse = pd.read_csv(CROSS / "day8_discovery/day8_to_day6_validation.csv")
# These are the exact evaluability masks and mappings in plot_bidirectional.py.
panels = [
    ("Day6 → Day8", forward.loc[forward.day8_status == "OK"],
     "delta_percentage_points", "day8_delta_pp", summary.loc["Day6 → Day8"]),
    ("Day8 → Day6", reverse.loc[reverse.status == "OK"],
     "day8_delta_pp", "day6_delta_pp", summary.loc["Day8 → Day6"]),
]
draw("Supplementary_Figure_S2", panels, "Discovery ΔP (pp)", "Validation ΔP (pp)")
assert hashes() == before, "An original input changed during rendering."
(OUT / "input_sha256.json").write_text(json.dumps(before, indent=2) + "\n")
print("Created Supplementary_Figure_S1/S2: PNG (300 dpi) and vector PDF.")
