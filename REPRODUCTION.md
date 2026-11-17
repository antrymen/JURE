> **Current public-export status (2026-11-15):** Targeted technical filtering is complete. Nine excerpt fields are excluded with an explicit parent/public hash map, and the MED30 historical error is prominently documented. Earlier dated audit findings describe prior snapshots. MIT rights-holder authorization and the copyright notice remain pending; no publication approval is asserted. See [public-export notes](evidence/PUBLIC_EXPORT_NOTES.md).

# Reproduction guide

## 1. Verify archived scientific results

```bash
python scripts/verify_paper_results.py
# Optional fresh output path:
python scripts/verify_paper_results.py --output runs/paper_verification.json
```

All inputs are in `evidence/`; no external model or raw matrix is needed. Checks cover 341 reference states/86 gene combinations, four validation directions, five selected stable cores, PHB2 prevalence and 18 case records/11 complete feedback chains. Hash verification detects accidental archive changes; it does not independently establish the truth of biological evidence.

Holm and summary statistics are recalculated from saved P values and effects. Stable cores are reconstructed from the saved co-clustering matrix. Raw-cell exact tests and 50 real-data bootstrap iterations are not rerun.

## 2. Re-execute examples and offline tests

```bash
python -m examples.run_synthetic --output runs/synthetic
python -m examples.run_casefile --output runs/casefile
make test-offline
```

Use a new output directory each time. Synthetic seed is 20260927. The test target runs the complete established 108-test offline suite: integration, Case File store/models and perturbation scan tests, with the three explicit research-artifact-dependent deselections in Makefile. Remaining historical tests were not collectively certified offline.

## 3. Full raw-data recomputation: not yet portable

`real_nt_v04_holm/run.py` requires prepared NT data and frozen engine manifests. `perturbation_scan/run.py` validates the exact Day6 data hash and reads dataset isolation rules. `stage2_validation/result2.py` requires the frozen split, cell assignment and Day6 tool-store counts. `broad_screening/io.py` consumes complete legacy and scan directories. Cross-dataset reference scripts retain historical path assumptions and require the original Day8 data.

These inputs are not reconstructed from manuscript numbers. Merely passing --help or installing the package does not establish that these experiments run. See [the experiment index](experiments/README.md) and [paper-result mapping](PAPER_RESULTS_INDEX.md).

## 4. Historical Agent re-execution: not available as one command

The historical Case Investigator experiments reported in the paper were conducted using **GPT-5.6 Luna** within the OpenAI Codex environment.

All three agents—Mechanism Explorer, Evidence Investigator, and Mechanism Critic—used GPT-5.6 Luna through Codex native subagent execution.

The model configuration is confirmed by the researcher. The public archive does not independently verify the model identity from complete native execution logs.

Read [the case index](evidence/CASE_INDEX.md). Records preserve three batch protocols and actual archived scientific role outputs.

The historical execution order differed across batches:

- **Batches 1 and 2:** Mechanism Explorer → Evidence Investigator → Mechanism Critic.
- **Batch 3:** Pre-investigation C1 assessment was performed before evidence investigation.

The current Python implementation uses **GLM as an alternative language-model backend** for implementation and testing. It was not used to generate the historical Case Investigator results reported in the paper.

The GLM-based Python runtime is a separate implementation and does not provide an equivalent replay of the historical Codex native subagent sessions.

Archived role outputs, evidence records, Critic assessments and revision histories are preserved as historical research artifacts. They should not be interpreted as newly generated outputs from the current Python runtime.

No keys or provider services are needed to inspect the archive.

## Environment and validation

See [RELEASE_VALIDATION.md](RELEASE_VALIDATION.md) for exact commands, dependency versions and outcomes in an independent candidate directory.

Empty-machine dependency resolution and live model calls remain unverified. No scientific settings were changed to make tests pass.
