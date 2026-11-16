from itertools import product

import numpy as np
import pandas as pd
import pytest

from clue_discovery.v02 import Population, ReferenceConfig, fit_reference, test_perturbations
from real_data_v02.diagnostics import DIAGNOSTIC_COLUMNS, locked_nt_diagnostic


def population(prefix, uniform=False):
    states = np.array(list(product((0, 1), repeat=3)), dtype=np.uint8)
    counts = np.full(8, 250) if uniform else np.where(states.sum(axis=1) % 2 == 0, 400, 100)
    matrix = np.repeat(states, counts, axis=0)
    return Population(matrix, tuple('ABC'), tuple(f'{prefix}:{i}' for i in range(len(matrix))))


@pytest.fixture(scope='module')
def fixture():
    discovery, validation = population('d'), population('v')
    control, pseudo = population('c'), population('p', uniform=True)
    reserved = Population(np.vstack([control.matrix, pseudo.matrix]), control.gene_names,
                          control.cell_ids + pseudo.cell_ids)
    cfg = ReferenceConfig(max_order=3, n_bootstrap=80)
    diagnostic_ref = fit_reference(discovery, validation, reserved, candidate_genes=tuple('ABC'), config=cfg)
    return discovery, validation, control, pseudo, diagnostic_ref, cfg


def test_diagnostic_matches_main_statistics_without_modifying_catalogue(fixture):
    discovery, validation, control, pseudo, ref, cfg = fixture
    # Independently fit a legal main-test design with the same discovery evidence.
    # The main API then compares identical assay values but has different legal cohorts.
    main_ref = fit_reference(discovery, validation, control, candidate_genes=tuple('ABC'), config=cfg)
    label = 'synthetic_diagnostic'
    before = (ref.catalogue.payload_json, ref.catalogue.sha256)
    result = locked_nt_diagnostic(ref.catalogue, control, pseudo, label)
    expected = test_perturbations(main_ref.catalogue, control, {label: pseudo}).shifts
    columns = [
        'reference_id', 'order', 'control_count', 'perturb_count', 'control_frequency',
        'perturb_frequency', 'delta_frequency', 'p_value_shift', 'q_value_shift',
        'bootstrap_delta_median', 'bootstrap_delta_ci_low', 'bootstrap_delta_ci_high',
        'delta_sign_stability', 'support', 'status',
    ]
    assert len(result) == 4
    pd.testing.assert_frame_equal(result[columns], expected[columns])
    assert result.fdr_family_size.eq(4).all()
    assert result.fdr_family.str.contains('not_main_family').all()
    assert (ref.catalogue.payload_json, ref.catalogue.sha256) == before


def test_diagnostic_rejects_overlap_and_non_test_ids_before_encoding(fixture):
    discovery, validation, control, pseudo, ref, _ = fixture
    with pytest.raises(ValueError, match='overlap'):
        locked_nt_diagnostic(ref.catalogue, control, control, 'overlap')
    for leaked in (discovery, validation):
        poisoned = Population(np.full(leaked.matrix.shape, -1), leaked.gene_names, leaked.cell_ids)
        with pytest.raises(ValueError, match='discovery/validation'):
            locked_nt_diagnostic(ref.catalogue, poisoned, pseudo, 'leak')
    outsider = population('outside')
    with pytest.raises(ValueError, match='reserved'):
        locked_nt_diagnostic(ref.catalogue, outsider, pseudo, 'outside')


def test_empty_catalogue_retains_schema_and_audit(fixture):
    discovery, _, control, pseudo, _, cfg = fixture
    reserved = Population(np.vstack([control.matrix, pseudo.matrix]), control.gene_names,
                          control.cell_ids + pseudo.cell_ids)
    empty = fit_reference(discovery, population('v2', uniform=True), reserved,
                          candidate_genes=tuple('ABC'), config=cfg).catalogue
    result = locked_nt_diagnostic(empty, control, pseudo, 'empty')
    assert result.empty
    assert set(DIAGNOSTIC_COLUMNS) <= set(result.columns)
    assert result.attrs['fdr_family_size'] == 0
    assert result.attrs['catalogue_sha256'] == empty.sha256
