PYTHON ?= python
.PHONY: help test-offline demo-casefile demo-synthetic
help:
	@echo "make test-offline | demo-casefile | demo-synthetic (fresh runs/ outputs required)"
test-offline:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m pytest -q -p no:cacheprovider tests/test_clue_discovery_integration.py tests/test_casefile_store.py tests/test_casefile_models.py tests/test_perturbation_scan.py --deselect=tests/test_clue_discovery_integration.py::test_frozen_day6_regression_read_only --deselect=tests/test_clue_discovery_integration.py::test_day8_metadata_smoke_does_not_claim_full_adapter --deselect=tests/test_perturbation_scan.py::test_catalogue_tamper
demo-casefile:
	$(PYTHON) -m examples.run_casefile --output runs/casefile
demo-synthetic:
	$(PYTHON) -m examples.run_synthetic --output runs/synthetic
