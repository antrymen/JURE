# Result 2 preliminary experiments — execution protocol, 2026-10-12

Scope: local CPU, fixed 341-state NT catalogue, internal reproducibility only.
No CPA/Day8 access, no new reference discovery, no full-data candidate list used
for discovery. Original source code and results remain unchanged.

Cohorts use the frozen metadata split only: both folds n>=100 (386 targets)
and both folds n>=50 (1242 targets). Both use all 341 patterns. Each cohort
is a separate analysis, not an additional independent replication.

Discovery in each fold: original batch-weighted NT baseline, NT>=20 per
occupied batch, effective NT>=100, |delta|>=0.10, directional support>=10,
exact two-sided stratified hypergeometric test, Holm across all cohort targets
x341 at 0.05; skipped comparisons count as p=1. Freeze all four discovery
lists and directions before running either validation direction.

Validation: all discovery-locked comparisons remain in each directional family.
Require total support at the cohort threshold and matched NT support as above.
No validation effect-size or state-hit prefilter. Recompute exact two-sided p;
Holm across locked list at 0.025 per direction. Report same-sign fraction,
Pearson/Spearman without inferential correlation p, same-sign+Holm pass,
and same-sign+Holm+|validation delta|>=0.10. Report denominators and unassessable
rows explicitly. No claim that NT selection has been repaired or that these
are biological replicates. Report common 386-target results separately within
the 1242-target run and the added 856-target stratum, including changes in
discovery family size. No claim that all sensitivity differences are caused
by cell count alone.

Descriptive lower-order experiment: evaluated universe is all 1242 metadata
eligible targets x341 states in each fold, not just replicated candidates.
First pilot: 12 targets selected from evenly spaced ranks of minimum fold n
(ties target name), all86 triplets, both folds. Scale only if finite fits,
max marginal error <=1e-8, |three-way log contrast|<=1e-7 for >=99% fits and
observed-matched effect reconstruction error <=1e-10. Failures are reported,
not hidden by retuning.

Fit pooled target 8-cell distribution and target-batch-weighted NT 8-cell
mixture separately. This is projection AFTER mixing, not a within-batch
causal/higher-order test. Primary symmetric pseudocount is 0.5 per state:
(p*n_eff+0.5)/(n_eff+4), n_eff=target n or matched NT effective n.
Independent projection preserves first moments; pairwise maximum entropy
preserves first and second moments of the smoothed distribution. Report raw
observed delta, smoothed delta, model predicted shifts, raw-minus-model
residuals, smoothed-minus-model residuals, and smoothing shift. Sensitivity
pseudocounts 0.1 and1.0 are fixed before results. No p-values or significance
claims from residuals. Fit once per target x triplet and reuse across states.

Pilot batch-mixture diagnostic: also compare projection of matched NT mixture
with weighted projections of individual NT batches (adequate NT support),
using the same alpha and recording smoothing contribution. Synthetic pilot
includes independent distribution, pairwise-only model, odd parity, and
mixture of independent distributions. Validate marginal preservation and
show mixture-induced residual is possible. Do not fit each sparse target
batch with 1–2cells. Scaling eligibility concerns numerical adequacy only,
not evidence that residuals have a biological interpretation.

Summaries: absolute-error MAE/RMSE/correlation across all fixed states and
for |observed delta|>=0.10 separately. Relative absolute error only on this
large-effect set; never call 1-error a fraction of causal mechanism explained.
Pairwise fitting uses same observations, so its advantage is descriptive
in-sample fit, not out-of-sample prediction. No bootstrap required here.

Outputs: immutable configuration/source/input hashes, groupwise 8-state counts,
discovery and validation tables, plots PNG/PDF, pilot diagnostics, full
lower-order tables, sensitivity comparisons, run resources, final report.
