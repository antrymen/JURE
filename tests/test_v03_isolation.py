"""Pipeline-owned isolation, immutable locks, and per-gene-set work accounting.

Small synthetic execution fixtures test software contracts only; they do not
modify the frozen scientific benchmark or claim statistical power.
"""
from collections import Counter
import hashlib
import json

import numpy as np
import pytest

from clue_discovery.v02.populations import Population
from clue_discovery.v03.artifacts import ArtifactStore, digest
from clue_discovery.v03.catalogue import FrozenReferenceCatalogue
from clue_discovery.v03.config import ScalableConfig
from clue_discovery.v03.estimator import state_space
from clue_discovery.v03.mfi import contrast_signs
from clue_discovery.v03.multiple_testing import MultipleTestingAudit
from clue_discovery.v03 import bottom_up, pipeline, validation


def _config(**overrides):
    # Deliberately tiny deterministic software smoke fixture, not a scientific preset.
    values = dict(hvg_pool_size=3, max_order=3, candidate_mode="hybrid",
                  n_null_simulations=39, n_bootstrap=40,
                  max_pair_candidates=20, max_triplet_candidates=20,
                  max_quad_candidates=10, max_bootstrap_gene_sets=20,
                  max_exploration_candidates_per_order=20, max_exploration_candidates=40)
    values.update(overrides)
    return ScalableConfig(**values)


def _population(label, *, altered=False, sparse=False):
    states = state_space(4)
    if sparse:
        cells = np.vstack([np.zeros((800, 4), dtype=np.int64), np.ones((800, 4), dtype=np.int64)])
    else:
        # Pure ABC signal and an independent D; raw count amplitudes force an
        # unambiguous discovery-owned Fano pool without altering binary states.
        counts = np.repeat(np.rint(100 * (1 + .6 * contrast_signs(3))).astype(int), 2)
        cells = np.repeat(states, counts, axis=0).astype(np.int64)
    if altered:
        cells = np.random.default_rng(483).integers(0, 2, size=cells.shape)
        cells *= np.array([1, 8, 6, 10])
    else:
        cells *= np.array([10, 8, 6, 1])
    return Population(cells, ("A", "B", "C", "D"), tuple(f"{label}_{i}" for i in range(len(cells))))


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_a_discovery_unchanged_when_only_b_changes_and_both_locks_precede_validation(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "code_hashes", lambda: {"isolation_test": "frozen"})
    original_validate = pipeline.validate_locked
    barriers = []

    def checked_validation(population, locked, config, store, testing, **kwargs):
        barrier_path = store.root / "both_discoveries_frozen_before_validation.json"
        barrier = json.loads(barrier_path.read_text())
        assert barrier["validation_started"] is False
        for relative, checksum in barrier["frozen_file_hashes"].items():
            assert _sha(store.root / relative) == checksum
        assert barrier["locked_hashes"][kwargs["source_fold"]] == digest(locked)
        for fold in ("A", "B"):
            assert (store.root / f"discovery_{fold}_frozen.json").exists()
        barriers.append((store.root.name, kwargs["source_fold"]))
        return original_validate(population, locked, config, store, testing, **kwargs)

    monkeypatch.setattr(pipeline, "validate_locked", checked_validation)
    config = _config()
    a = _population("A")
    initial = pipeline.fit_twofold(a, _population("B"), config, tmp_path / "initial")
    changed = pipeline.fit_twofold(a, _population("B", altered=True), config, tmp_path / "changed")
    assert initial.discoveries["A"].locked  # The hash check must cover real frozen discoveries, not empties.
    for relative in ("hvg_selection_A.csv", "selected_hvgs_A.csv", "dependency_graph_A.csv",
                     "dependency_graph_summary_A.json", "candidate_proposals_A.csv",
                     "candidate_search_log_A.csv", "frozen_candidates_A.csv", "discovery_A_frozen.json"):
        assert _sha(tmp_path / "initial" / relative) == _sha(tmp_path / "changed" / relative), relative
    assert initial.discoveries["A"].locked == changed.discoveries["A"].locked
    assert initial.discoveries["B"].hvg_genes != changed.discoveries["B"].hvg_genes
    assert _sha(tmp_path / "initial" / "hvg_selection_B.csv") != _sha(tmp_path / "changed" / "hvg_selection_B.csv")
    assert len(barriers) == 4
    assert all(row["cross_fold_replicated"] for row in initial.validations["A"])
    assert any(not row["cross_fold_replicated"] for row in changed.validations["A"])


def test_discovery_and_locked_validation_compute_counts_and_bootstrap_once_per_gene_set(tmp_path, monkeypatch):
    config = _config()
    store = ArtifactStore(tmp_path / "work")
    testing = MultipleTestingAudit()
    discovery_counts, discovery_boot, validation_counts, validation_boot = [], [], [], []
    original_counts, original_boot = bottom_up.joint_counts, bottom_up.bootstrap_gene_set
    original_vcounts, original_vboot = validation.joint_counts, validation.bootstrap_gene_set

    def count_discovery(binary, columns, genes):
        discovery_counts.append(tuple(genes))
        return original_counts(binary, columns, genes)

    def bootstrap_discovery(counts, **kwargs):
        discovery_boot.append(kwargs["seed"])
        return original_boot(counts, **kwargs)

    def count_validation(binary, columns, genes):
        validation_counts.append(tuple(genes))
        return original_vcounts(binary, columns, genes)

    def bootstrap_validation(counts, **kwargs):
        validation_boot.append(kwargs["seed"])
        return original_vboot(counts, **kwargs)

    monkeypatch.setattr(bottom_up, "joint_counts", count_discovery)
    monkeypatch.setattr(bottom_up, "bootstrap_gene_set", bootstrap_discovery)
    monkeypatch.setattr(validation, "joint_counts", count_validation)
    monkeypatch.setattr(validation, "bootstrap_gene_set", bootstrap_validation)
    discovery = bottom_up.discover(_population("A"), config, store, testing, fold="A")
    assert all(count == 1 for count in Counter(discovery_counts).values())
    evaluated = [row for row in discovery.records if row.get("state_table_computed")]
    assert len(discovery_counts) == len(evaluated)
    assert len(discovery_boot) == len(set(discovery_boot)) == 1
    # The pure triplet has four positive residual states; one bootstrap must
    # supply all of them, rather than being called once per concrete pattern.
    assert len(discovery.locked) == 4
    assert len({row["candidate_id"] for row in discovery.locked}) == 1

    def forbidden(*args, **kwargs):
        raise AssertionError("locked validation must not perform discovery or HVG selection")

    monkeypatch.setattr(bottom_up, "select_hvgs", forbidden)
    monkeypatch.setattr(bottom_up, "discover", forbidden)
    rows, sets = validation.validate_locked(_population("B"), discovery.locked, config, store, testing,
                                            source_fold="A", validation_fold="B")
    assert len(validation_counts) == len(validation_boot) == len(sets) == 1
    assert len(rows) == len(discovery.locked) == 4
    assert {r["reference_id"] for r in rows} == {r["reference_id"] for r in discovery.locked}
    assert all(row["cross_fold_replicated"] for row in rows)
    paths = {row["bootstrap_path"] for row in rows}
    assert len(paths) == 1
    arrays = np.load(store.root / next(iter(paths)))
    assert arrays["mfi"].shape == (config.n_bootstrap,)
    assert arrays["pattern_absolute_gain"].shape == (config.n_bootstrap, 8)


def test_poor_full_table_estimability_prunes_before_bootstrap_in_both_roles(tmp_path, monkeypatch):
    config = _config()
    store = ArtifactStore(tmp_path / "poor")
    testing = MultipleTestingAudit()
    good = bottom_up.discover(_population("A"), config, store, testing, fold="A")
    assert good.locked

    def forbidden(*args, **kwargs):
        raise AssertionError("poor full-table estimability must block expensive resampling")

    monkeypatch.setattr(bottom_up, "bootstrap_gene_set", forbidden)
    monkeypatch.setattr(validation, "bootstrap_gene_set", forbidden)
    monkeypatch.setattr(validation, "conditional_gain_test", forbidden)
    monkeypatch.setattr(bottom_up.GainNullCalibration, "calibrate", forbidden)
    bad = bottom_up.discover(_population("C", sparse=True), config, store, testing, fold="C")
    evaluated = [row for row in bad.records if row.get("state_table_computed")]
    assert evaluated
    assert all(row["estimability_status"] == "poor" for row in evaluated)
    assert all(row["prune_reason"] == "poor_estimability" for row in evaluated)
    assert not bad.locked
    rows, sets = validation.validate_locked(_population("B", sparse=True), good.locked, config, store, testing,
                                            source_fold="A", validation_fold="B")
    assert len(sets) == 1
    assert sets[0]["estimability_status"] == "poor"
    assert sets[0]["bootstrap_status"] == "not_evaluated"
    assert all(not row["cross_fold_replicated"] for row in rows)


def test_frozen_catalogue_returns_copies_and_rejects_on_disk_tampering(tmp_path):
    record = {"reference_id": "Rtest", "genes": ["A", "B", "C"], "order": 3,
              "pattern": "101", "quality_flags": ["stable"], "catalogue_tier": "exploratory",
              "reference_frequency": .2}
    catalogue = FrozenReferenceCatalogue.freeze([record], config_hash="frozen_config", run_version="software_test")
    catalogue.write(tmp_path)
    path = tmp_path / "frozen_reference_catalogue.json"
    loaded = FrozenReferenceCatalogue.load(path)
    assert loaded.sha256 == catalogue.sha256
    copy = loaded.records
    copy[0]["genes"][0] = "OTHER"
    assert loaded.records[0]["genes"] == ["A", "B", "C"]
    payload = json.loads(path.read_text())
    payload["payload"]["records"][0]["reference_frequency"] = .99
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="checksum mismatch"):
        FrozenReferenceCatalogue.load(path)
