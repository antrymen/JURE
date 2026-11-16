# Proposed public tree

```text
JURE/
├── README.md
├── REPRODUCTION.md
├── PAPER_RESULTS_INDEX.md
├── RELEASE_VALIDATION.md
├── RELEASE_READINESS.md
├── LICENSE_RECOMMENDATIONS.md       # LICENSE remains an author decision
├── PUBLICATION_EXCLUSIONS.json
├── PUBLICATION_EXCLUSIONS.md
├── pyproject.toml / Makefile / .gitignore
├── clue_discovery/ / perturbation_scan/
├── broad_screening/ / landscape_analysis/ / broad_annotation/
├── triage/ / jure/
├── real_data_test/ / real_data_v02/ / real_nt_v04_holm/
├── nt_reference_experiment/ / stage2_validation/
├── configs/ / examples/ / tests/
├── scripts/ / experiments/reference_scripts/
├── docs/                           # retained technical documentation
├── data/README.md                  # no raw dataset
└── evidence/                       # immutable candidate scientific archive
```

`.release_review/`, unpublished manuscript text, local research audits and old preparation reports are not exported. Historical helper packages remain to preserve dependencies. Source/config paths needing environment review remain explicitly listed as a blocker rather than silently rewritten.
