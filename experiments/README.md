# Paper experiments

| Experiment | Original workspace entry | Required artifacts | Status |
|---|---|---|---|
| Day6 reference discovery | `real_nt_v04_holm/run.py` | Day6 counts, frozen configuration | Research workflow; data not bundled |
| Perturbation shifts | `perturbation_scan/run.py` | Frozen reference catalogue, matched metadata/counts | Research workflow |
| Day6 internal validation | `stage2_validation/result2.py` | Frozen Day6 reference and split counts | Historical protocol, per-direction alpha 0.025 |
| Day6 → Day8 | `outputs/result2_cross_dataset/validate_day6_to_day8.py` | Locked Day6 candidates, Day8 H5AD | Reference script, external inputs required |
| Day8 → Day6 | `outputs/result2_cross_dataset/run_day8_scan_and_validate.py` | Day8 discovery and Day6 validation counts | Reference script, external inputs required |
| Shared response | `broad_screening/run.py` | Perturbation scan outputs | Research workflow |
| Case investigation | Historical Codex role artifacts | Frozen clues, tools, model access, dispatch protocol | Not a run of current GLM pilot |

`reference_scripts/` preserves selected original scripts with source-relative paths. Do not execute these from their archive directory assuming the data root was rewritten. The source mapping is in `docs/PROVENANCE.json`; detailed artifacts and missing inputs are in `RESULTS_PROVENANCE.md`.

No full reproduction command is claimed without its data, source snapshot and execution protocol. No historical results were regenerated during this preparation.

## Bundled result verification (2026-11-15)

Aggregate results and historical role records are now in `evidence/`. Run `python scripts/verify_paper_results.py` from the repository root. See `PAPER_RESULTS_INDEX.md` and `REPRODUCTION_STATUS.md` for exact reproduction boundaries. This addition does not make the historical scripts above portable.
