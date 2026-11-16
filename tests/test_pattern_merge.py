import pytest
from clue_discovery import JointPattern, merge_patterns
from clue_discovery.candidate_search import merge_candidates


def test_canonical_hash_subsets_and_merge():
    target = JointPattern(("C", "B", "A"), (1, 0, 1))
    assert target.to_string() == "A+B-C+"
    assert target.canonicalize() == target
    assert len(set([target, JointPattern(("A", "B", "C"), (1, 0, 1))])) == 1
    subsets = target.subpatterns()
    assert {s.to_string() for s in subsets} == {"A+B-", "A+C+", "B-C+"}
    assert merge_patterns(subsets[0], subsets[1]) == target
    merged = merge_candidates([*subsets, *subsets])
    assert list(merged) == [target]
    assert len(merged[target]) == 3


def test_conflicts_disjoint_and_duplicates():
    p = JointPattern(("A", "B"), (1, 0))
    assert merge_patterns(p, JointPattern(("A", "C"), (0, 1))) is None
    assert merge_patterns(p, JointPattern(("C", "D"), (0, 1))) is None
    assert merge_patterns(p, p) is None
    with pytest.raises(ValueError):
        JointPattern(("A", "A"), (0, 1))
