from copy import deepcopy
from dataclasses import replace
import json

import numpy as np
import pytest
from scipy.stats import false_discovery_control

from clue_discovery.v02.populations import Population
from clue_discovery.v03.candidate import candidate_id
from clue_discovery.v04.config import ScalableConfig
from clue_discovery.v04.pipeline import fit_twofold
from clue_discovery.v04_validation.policy import freeze_family, evaluate_family, adjust_pvalues
from clue_discovery.v04_validation.experiment import run_experiment
from clue_discovery.v04_validation.benchmark import cases, pregenerate, load_case, binomial_interval, pooled_error_upper


def locked(genes=('A', 'B', 'C'), state=(0, 0, 0), fold='A'):
    cid = candidate_id(genes)
    return dict(candidate_id=cid, reference_id=cid+''.join(map(str, state)),
                genes=genes, states=state, order=3, discovery_fold=fold)


def validation(record, p, *, raw_pass=True, quality='good'):
    source = record['discovery_fold']; dest = 'B' if source == 'A' else 'A'
    gene_set = dict(candidate_id=record['candidate_id'], genes=record['genes'], order=3,
        p_gain=p, estimability_status=quality, gain_method='exact_conditional_complete_lower_order_fiber',
        evaluation_role=f'{dest}_validation_from_{source}')
    state = dict(record, validation_fold=dest, pattern=''.join(map(str, record['states'])),
                 cross_fold_replicated=raw_pass)
    return gene_set, state


@pytest.mark.parametrize('p', [[], [.02], [0, .01, .04, .06], [.5, .5, .01, .01, 1],
                              np.random.default_rng(893).uniform(size=97)])
def test_bh_matches_scipy_and_is_order_invariant(p):
    p = np.asarray(p)
    result = adjust_pvalues(p, 'bh')
    if len(p):
        assert np.allclose(result, false_discovery_control(p, method='bh'))
        assert np.allclose(adjust_pvalues(p[::-1], 'bh')[::-1], result)
    else:
        assert not len(result)


def test_holm_reference_values_ties_and_empty():
    assert np.allclose(adjust_pvalues([0, .01, .04, .06], 'holm'), [0, .03, .08, .08])
    assert np.allclose(adjust_pvalues([.02, .02, .8], 'holm'), [.06, .06, .8])
    assert np.allclose(adjust_pvalues([.8, .02, .02], 'holm'), [.8, .06, .06])
    assert not len(adjust_pvalues([], 'holm'))


@pytest.mark.parametrize('p', [[-1], [1.01], [np.nan], [np.inf], [[.1]]])
def test_invalid_p_values_fail_closed(p):
    with pytest.raises(ValueError):
        adjust_pvalues(p, 'bh')


def test_multiple_states_share_one_member_and_raw_filter_is_retained():
    d = [locked(), locked(state=(1, 1, 0))]
    family = freeze_family(d, source_fold='A', validation_fold='B')
    assert len(family.members) == 1
    gene_set, first = validation(d[0], .02)
    _, second = validation(d[1], .02, raw_pass=False)
    sets, states, manifests = evaluate_family(family, d, [gene_set], [first, second])
    assert len(sets) == 4 and len(states) == 8
    assert all(r['family_size'] == 1 and r['adjusted_p'] == .02 for r in sets)
    assert sum(r['qualified'] for r in states) == 4
    assert all(m['member_count'] == 1 for m in manifests)


def test_missing_and_poor_members_are_not_removed_from_family():
    d = [locked(), locked(('D','E','F')), locked(('G','H','I'))]
    family = freeze_family(d, source_fold='A', validation_fold='B')
    good, state = validation(d[0], .02)
    poor, _ = validation(d[1], .00001, quality='poor')
    rows, states, manifests = evaluate_family(family, d, [good, poor], [state])
    bh = next(r for r in rows if r['candidate_id'] == good['candidate_id'] and r['arm'] == 'bh_05')
    assert bh['family_size'] == 3 and bh['adjusted_p'] == pytest.approx(.06)
    assert not bh['family_gain_rejected']
    assert all(not r['family_gain_rejected'] for r in rows if r['candidate_id'] != good['candidate_id'])
    assert all(r['n_unevaluable'] == 2 for r in manifests)
    assert next(r for r in states if r['arm'] == 'raw_05')['qualified']
    assert not next(r for r in states if r['arm'] == 'bh_05')['qualified']


def test_two_directions_are_separate_with_prespecified_split_budget():
    for source, dest in [('A','B'), ('B','A')]:
        d = [locked(fold=source)]
        family = freeze_family(d, source_fold=source, validation_fold=dest)
        gs, state = validation(d[0], .04)
        rows, _, _ = evaluate_family(family, d, [gs], [state])
        flags = {r['arm']: r['family_gain_rejected'] for r in rows}
        assert flags == dict(raw_05=True, bh_05=True, bh_025=False, holm_025=False)


def test_mutation_extra_tests_wrong_direction_and_new_state_are_rejected():
    d = [locked()]
    family = freeze_family(d, source_fold='A', validation_fold='B')
    gs, state = validation(d[0], .01)
    with pytest.raises(ValueError, match='lock changed'):
        evaluate_family(family, d+[locked(('D','E','F'))], [gs], [state])
    with pytest.raises(ValueError, match='duplicate'):
        evaluate_family(family, d, [gs, gs], [state])
    changed = dict(gs, evaluation_role='A_validation_from_B')
    with pytest.raises(ValueError, match='direction'):
        evaluate_family(family, d, [changed], [state])
    changed = dict(state, states=(1, 0, 0))
    with pytest.raises(ValueError, match='state changed'):
        evaluate_family(family, d, [gs], [changed])
    changed = dict(state, genes=('C', 'B', 'A'))
    with pytest.raises(ValueError, match='state changed'):
        evaluate_family(family, d, [gs], [changed])
    with pytest.raises(ValueError, match='duplicate'):
        freeze_family([d[0], d[0]], source_fold='A', validation_fold='B')


def test_empty_family_and_two_or_four_way_are_not_claimed():
    family = freeze_family([], source_fold='A', validation_fold='B')
    rows, states, info = evaluate_family(family, [], [], [])
    assert rows == states == [] and len(info) == 4
    assert all(r['rejection_count'] == 0 for r in info)


def population(prefix):
    states = np.array([[int(x) for x in f'{i:03b}'] for i in range(8)], dtype=np.uint8)
    matrix = np.repeat(states, np.where(states.sum(1)%2, 70, 330), axis=0)
    return Population(matrix, ('A','B','C'), tuple(f'{prefix}{i}' for i in range(len(matrix))))


def test_lock_barrier_and_compact_storage_preserve_frozen_v04_numerical_results(tmp_path, monkeypatch):
    from clue_discovery.v04_validation import experiment
    cfg = replace(ScalableConfig(), hvg_pool_size=3, max_order=3,
                  fingerprint_bands=4, n_null_simulations=99, n_bootstrap=40)
    a, b = population('a'), population('b')
    baseline = fit_twofold(a, b, cfg, tmp_path/'baseline')
    observed = []
    original = experiment.validate_locked
    def wrapper(*args, **kwargs):
        path = tmp_path/'corrected'
        assert (path/'validation_families_frozen.json').exists()
        assert (path/'both_discoveries_and_families_frozen_before_validation.json').exists()
        observed.append(kwargs['source_fold'])
        return original(*args, **kwargs)
    monkeypatch.setattr(experiment, 'validate_locked', wrapper)
    result = run_experiment(a,b,cfg,tmp_path/'corrected', compact=True)
    assert observed == ['A','B']
    for fold in ('A','B'):
        assert baseline.discoveries[fold].proposals == result.discoveries[fold].proposals
        fields = ('reference_id','mfi','p_gain','q_gain','cross_fold_replicated','mfi_sign_stability')
        expected = [{k:r[k] for k in fields} for r in baseline.validations[fold]]
        actual = [{k:r[k] for k in fields} for r in result.raw_validations[fold]]
        assert expected == actual
    assert all(r['qualified'] for r in result.corrected_states)
    arrays = list((tmp_path/'corrected').rglob('*_array_audit.json'))
    assert arrays and all(not json.loads(p.read_text())['arrays_persisted'] for p in arrays)
    with pytest.raises(FileExistsError):
        run_experiment(a,b,cfg,tmp_path/'corrected')


def test_fresh_benchmark_seed_namespace_and_locked_case_count():
    specifications = cases()
    assert len(specifications) == 232
    assert len({c['seed'] for c in specifications}) == 232
    assert all(c['seed'] not in {11,29,47,20260927} for c in specifications)
    for kind in ('independent','biased_independent','pairwise_only'):
        assert sum(c['kind'] == kind for c in specifications) == 60


def test_pregeneration_identity_checks_and_corruption_guard(tmp_path):
    # Development fixture: deliberately not a prespecified benchmark case/seed.
    specs = [dict(case_id='unit_only', kind='parity', size=8, seed=887, strength=.5)]
    index = pregenerate(tmp_path, specs)
    populations, metadata = load_case(tmp_path/'datasets/unit_only', index[0])
    assert all(p.matrix.shape == (6000,8) for p in populations.values())
    assert 'target_genes_posthoc_only' not in metadata
    path = tmp_path/'datasets/unit_only/data.json'
    path.write_text('{}')
    with pytest.raises(ValueError, match='changed'):
        load_case(path.parent,index[0])


def test_null_interval_is_not_claimed_to_be_zero():
    lo, hi = binomial_interval(0,60,one_sided=True)
    assert lo == 0 and .048 < hi < .05
    assert binomial_interval(0,0) == [None,None]


def test_pooled_heterogeneous_bernoulli_bound_and_limits():
    assert pooled_error_upper(0,180) == pytest.approx(1-.05**(1/180))
    assert pooled_error_upper(1,180) > binomial_interval(1,180,one_sided=True)[1]
    assert pooled_error_upper(2,180) > pooled_error_upper(1,180)
    assert pooled_error_upper(180,180) == 1
    assert pooled_error_upper(0,0) is None
