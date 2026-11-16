# Release candidate validation

Local review date: 2026-11-15. Validation used an independent copy inside the ignored `.release_review/candidate/` directory, after applying PUBLICATION_EXCLUSIONS.json. No original research datasets or model credentials were supplied.

## Exact command forms and results

Run from the candidate root; `python` below denotes the existing Python 3.13 scientific environment. Fully resolved commands and logs remain in the private `.release_review/commands.json`.

| Command | Outcome |
|---|---|
| `python scripts/verify_paper_results.py` | PASS: evidence hashes, four validation summaries, core reconstruction and 18/11 record completeness |
| `python -m examples.run_synthetic --output <review>/synthetic` | exit 0 |
| `python -m examples.run_casefile --output <review>/casefile` | exit 0 |
| `make test-offline PYTHON=<scientific-python>` | 108 passed, 3 explicitly deselected |
| `python -m clue_discovery.run --help` | exit 0 |
| `<build-python> -m pip wheel --no-deps --no-build-isolation --wheel-dir <review>/wheels <candidate>` | exit 0 |
| `<build-python> -m pip install --no-index --no-deps --target <review>/installed <wheel>` | exit 0 |
| Directory-outside-source imports with PYTHONPATH set to installed target | exit 0; package location asserted inside installed target |

Installed dependencies verified: numpy 2.5.3, scipy 1.18.1, pandas 3.0.6, pydantic 2.13.5, PyYAML 6.0.3, pytest 9.1.1, h5py 3.16.0, anndata 0.13.4. These are observed versions, not a newly invented historical environment lock. They satisfy the declared lower bounds and existing upper bounds.

The build used already-available setuptools/wheel. Scientific imports/tests reused installed dependencies; this is not proof of fresh-machine network installation. Live GLM execution, raw-data recomputation and historical Codex sessions were not tested.

## Integrity and links

All original Python sources, scientific configurations and archived evidence are compared to the pre-cleanup inventory. Documentary hyperlink repairs are recorded separately with private backups. Evidence inventory hashes and original source manifests are not rewritten. No cache or generated wheel/build directory is included in the final candidate. Final link and integrity outcomes are summarized in RELEASE_READINESS.md; detailed checks are private local audit records.
