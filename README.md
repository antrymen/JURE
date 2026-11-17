# JURE

**Joint-state Understanding through Reasoning and Evidence** connects statistical discovery in single-cell genetic perturbation data to evidence-driven mechanistic investigation.

## Components

**Clue Discovery** identifies reference joint gene-detection states, measures perturbation-associated prevalence shifts, and groups shared response patterns. **Case Investigator** uses Mechanism Explorer, Evidence Investigator and Mechanism Critic with a Shared Case File to formulate explanations, acquire evidence and request revisions or follow-up. Candidate explanations are not experimentally validated mechanisms.

## Install

Use Python 3.11–3.13 on macOS/Linux as the intended environment. Current local validation uses Python 3.13 on macOS; other versions/platforms have not all been tested. Package metadata retains its original Python >=3.10 requirement.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[test,real]'
```

The `real` extra supplies data-reading dependencies, not the research datasets. A fresh-machine online dependency resolution is not claimed; see [validation](RELEASE_VALIDATION.md).

## Quick start

Run from the repository root with new output directories:

```bash
python -m examples.run_synthetic --output runs/synthetic
python -m examples.run_casefile --output runs/casefile
python scripts/verify_paper_results.py
make test-offline
```

The synthetic example reruns a small three-stage analysis. The Case File example exercises storage, not LLM reasoning. The verification script checks bundled result hashes, recomputes Holm-adjusted summaries and reconstructs stable cores from archived co-clustering data. The available offline test suite was executed successfully. Tests requiring unavailable research artifacts were excluded.

## Paper results and cases

- [Paper-result index](PAPER_RESULTS_INDEX.md): claims, implementation, frozen inputs and archived results.
- [Historical case index](evidence/CASE_INDEX.md): 18 cases and 11 complete evidence-feedback chains.
- [Archive provenance](evidence/README.md): original and exported hashes and declared path transformations.
- [Reproduction guide](REPRODUCTION.md): exact executable scope and missing inputs.

## Reproducibility boundaries

| Capability | Status |
|---|---|
| Verify archived aggregate results | Available offline |
| Re-execute synthetic and Case File examples | Available offline |
| Recompute the entire paper from raw single-cell data | Not independently verified; required data and historical layout absent |
| Re-execute historical multi-agent investigations | Not provided by the current Python runtime |

Historical paper cases used Codex native subagent protocols, with batch-dependent review order. The current Python pilot uses GLM transport. It must not be presented as the executor of those historical cases. Archived roles, initial inputs and follow-up records are evidence to inspect, not simulated runtime calls.

## Repository structure

```text
clue_discovery/                 Discovery entry and components
perturbation_scan/              Statistical perturbation analysis
broad_screening/, landscape_analysis/  Shared response analysis
triage/, jure/                 Case selection, agents, tools and Case File
configs/                       Original historical configurations
examples/, tests/              Offline examples and tests
experiments/reference_scripts/ Historical experiment source archive
scripts/                       Utilities and result verification
evidence/                      Aggregate results and historical cases
docs/                          Technical documentation
```

Older `real_*`, `nt_reference_experiment/` and `stage2_validation/` packages remain because scientific workflows depend on them. Core paths were preserved.

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.

Copyright (c) 2026 JURE Contributors.
