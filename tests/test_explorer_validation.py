"""Semantic adversarial tests for untrusted Explorer proposals."""

import copy

import pytest

from jure.agents.explorer.demo import initial_output, synthetic_clue
from jure.agents.explorer.models import ExplorerConfig, ExplorerOutput
from jure.agents.explorer.validation import interpret_observation, validate_explorer_output
from jure.casefile.models import (
    CaseFile, CaseMetadata, EvidenceGap, HistoryEvent, HypothesisRecord,
    HypothesisRevision, MechanisticQuestion,
)


@pytest.fixture
def case():
    return CaseFile(metadata=CaseMetadata(case_id="CASE_TEST", cell_context="K562"),
                    clue=synthetic_clue())


def errors(case, payload=None, **kwargs):
    return validate_explorer_output(ExplorerOutput.model_validate(payload or initial_output(case)), case, **kwargs)


def test_observation_copy_error_reports_precise_characters_without_repair(case):
    payload=initial_output(case)
    original=payload['observation_interpretation']
    payload['observation_interpretation']=original+'"'
    failure=errors(case,payload)
    assert any('Character differences (zero-based)' in e and 'expected[' in e and 'received[' in e for e in failure)
    assert payload['observation_interpretation']==original+'"'


def existing_case(case):
    output = ExplorerOutput.model_validate(initial_output(case))
    hypotheses = []
    events = []
    for index, proposal in enumerate(output.hypotheses, 1):
        revision = HypothesisRevision(
            revision_id=f"HR{index}", title=proposal.title,
            mechanism_statement=proposal.mechanism_statement,
            mechanism_type=proposal.mechanism_type,
            assumptions=proposal.assumptions, unresolved_points=proposal.unresolved_points,
            weakening_conditions=proposal.weakening_conditions,
        )
        hypotheses.append(HypothesisRecord(hypothesis_id=proposal.hypothesis_id,
                                            current_revision_id=revision.revision_id,
                                            revisions=(revision,)))
        events.append(HistoryEvent(
            event_id=f"EV{index}", sequence=index, case_revision=index,
            actor="explorer", action="HYPOTHESIS_CREATED", object_type="hypothesis",
            object_id=proposal.hypothesis_id, summary="Initial proposal",
            metadata={"hypothesis_revision_id": revision.revision_id,
                      "structure": proposal.structure.model_dump(mode="json")},
        ))
    return case.model_copy(update={
        "hypotheses": tuple(hypotheses), "investigation_history": tuple(events),
        "mechanistic_question": MechanisticQuestion(question_id="MQ1", question_text=output.mechanistic_question,
                                                     derived_from_clue_id=case.clue.clue_id),
        "evidence_gaps": (EvidenceGap(gap_id="GAP1", description="Neither mechanism explains conditional response."),),
    })


def reframe_output(case):
    initial = initial_output(case)
    proposal = copy.deepcopy(initial["hypotheses"][0])
    proposal.update(
        hypothesis_id="H4", title="Conditional joint-state possibility",
        mechanism_statement="The response of C to perturbation X may depend jointly on A and B states in K562 cells.",
        mechanism_type="conditional_dependence",
        derived_from=[{"object_type": "evidence_gap", "object_id": "GAP1"}],
        structure={"causal_structure": "joint conditional dependence", "directness": "unspecified",
                   "cell_state_explanation": False, "conditional_dependence": True, "directed_edges": []},
    )
    prediction = copy.deepcopy(initial["predictions"][0])
    prediction.update(prediction_id="P4", hypothesis_id="H4",
                      statement="The C response should depend on the joint A and B states.",
                      discriminates_from_hypotheses=["H1", "H2", "H3"])
    question = copy.deepcopy(initial["evidence_questions"][0])
    question.update(question_id="Q4", question_text="Does the C response depend on the joint A and B states?",
                    derived_from_prediction_ids=["P4"], relevant_hypothesis_ids=["H4", "H1"],
                    discriminates_between=["H4", "H1"])
    return dict(initial, hypotheses=[proposal], predictions=[prediction], evidence_questions=[question],
                contrasts=[{"hypothesis_a": "H4", "hypothesis_b": identifier,
                            "difference": "Conditional dependence on the joint state instead of the alternative topology."}
                           for identifier in ("H1", "H2", "H3")])


def test_initial_proposal_is_valid_and_validator_is_read_only(case):
    before = case.model_dump_json()
    assert errors(case) == ()
    assert case.model_dump_json() == before


def test_negative_statistical_subject_is_not_a_proof_assertion():
    from jure.agents.explorer.validation import _has_overclaim
    assert not _has_overclaim('The shift is an exploratory association and no statistic establishes causation.')
    assert not _has_overclaim('No statistical association can prove regulation.')
    assert _has_overclaim('Statistical association establishes causation.')
    assert _has_overclaim('No statistic establishes causation; MFI proves regulation.')


def test_preserving_untouched_hypothesis_is_not_an_evidence_verdict(case):
    current=existing_case(case);payload=reframe_output(current)
    payload['warnings']=['H3 is retained unchanged; the original predictions remain stored.']
    assert not any('final verdicts' in e for e in errors(current,payload,mode='reframe',reframe_reason='Unit request'))
    payload['warnings']=['H3 is retained as supported.']
    assert any('final verdicts' in e for e in errors(current,payload,mode='reframe',reframe_reason='Unit request'))
    payload['warnings']=['H4 is retained unchanged.']
    assert any('final verdicts' in e for e in errors(current,payload,mode='reframe',reframe_reason='Unit request'))
    payload['warnings']=['H3 is retained unchanged; H3 is confirmed.']
    assert any('final verdicts' in e for e in errors(current,payload,mode='reframe',reframe_reason='Unit request'))


def test_observation_reports_populations_and_raw_evidence_without_thresholds(case):
    text = interpret_observation(case)
    assert "0.08" in text and "0.31" in text and "0.23" in text
    assert "detected expression" in text and "undetected expression" in text
    assert "Reference discovery statistics" in text and "Reference validation statistics" in text
    assert "Perturbation-associated shift statistics" in text
    assert '"sign_stability": 0.99' in text and '"sign_stability": 1.0' in text
    assert "K562" in text
    assert "do not by themselves establish a causal" in text


def test_observation_preserves_custom_encoding_without_relabeling(case):
    encoding = "1 = above the supplied threshold; 0 = below the supplied threshold"
    pattern = case.clue.pattern.model_copy(update={"encoding": encoding})
    changed = case.model_copy(update={"clue": case.clue.model_copy(update={"pattern": pattern})})
    text = interpret_observation(changed)
    assert encoding in text
    assert "detected" not in text


@pytest.mark.parametrize("observation", [
    "Perturbation X activates A, represses B and activates C.",
    "MFI proves A and B regulate C.",
    "Perturbation X is associated with an increase from 0.08 to 0.99.",
])
def test_causal_or_fabricated_observation_is_rejected(case, observation):
    payload = initial_output(case)
    payload["observation_interpretation"] = observation
    assert any("observation_interpretation" in error for error in errors(case, payload))


@pytest.mark.parametrize("question", [
    "What is the function of X in K562 cells?",
    "How does the A→B→C cascade explain the X-induced A+B-C+ prevalence shift in K562?",
    "Why does perturbation X activate A, repress B and regulate C in the K562 joint pattern?",
])
def test_question_must_be_clue_grounded_and_open_to_competing_mechanisms(case, question):
    payload = initial_output(case)
    payload["mechanistic_question"] = question
    assert any("mechanistic_question" in error for error in errors(case, payload))


def test_paraphrases_rejected_even_with_three_different_structure_labels(case):
    payload = initial_output(case)
    for hypothesis, statement in zip(payload["hypotheses"],
                                     ("A regulates C", "A may control C", "C is affected by A")):
        hypothesis["mechanism_statement"] = statement
    matches = [error for error in errors(case, payload) if "redundant hypotheses" in error]
    assert len(matches) == 3


def test_identical_structure_rejected_despite_different_mechanism_prose(case):
    payload = initial_output(case)
    payload["hypotheses"][1]["structure"] = copy.deepcopy(payload["hypotheses"][0]["structure"])
    assert any("redundant hypotheses H1 and H2" in error for error in errors(case, payload))


@pytest.mark.parametrize("statement", [
    "These genes should be biologically related.",
    "This mechanism should be important.",
    "There should be supporting literature.",
    "This pathway probably plays a role.",
    "Gene A may affect gene B.",
    "This pathway is biologically important.",
])
def test_untestable_predictions_are_rejected(case, statement):
    payload = initial_output(case)
    payload["predictions"][0]["statement"] = statement
    assert any("not a testable" in error for error in errors(case, payload))


def test_missing_prediction_weakening_and_question_coverage(case):
    payload = initial_output(case)
    payload["hypotheses"][0]["weakening_conditions"] = []
    payload["predictions"].pop(1)
    payload["evidence_questions"].pop(2)
    result = errors(case, payload)
    assert any("weakening condition" in error for error in result)
    assert any("H2 requires at least one prediction" in error for error in result)
    assert any("P3 requires a derived evidence question" in error for error in result)


@pytest.mark.parametrize("field,value,match", [
    ("derived_from_prediction_ids", [], "prediction lineage"),
    ("derived_from_prediction_ids", ["P_missing"], "prediction lineage"),
    ("relevant_hypothesis_ids", ["H2"], "owner"),
    ("discriminates_between", ["H1"], "at least two"),
    ("discriminates_between", ["H2", "H3"], "source prediction owner"),
])
def test_evidence_question_lineage_and_comparison_coherence(case, field, value, match):
    payload = initial_output(case)
    payload["evidence_questions"][0][field] = value
    assert any(match in error for error in errors(case, payload))


def test_question_cannot_expand_source_prediction_alternatives(case):
    payload = initial_output(case)
    payload["predictions"][0]["discriminates_from_hypotheses"] = ["H2"]
    payload["evidence_questions"][0].update(relevant_hypothesis_ids=["H1", "H3"],
                                           discriminates_between=["H1", "H3"])
    assert any("does not follow" in error for error in errors(case, payload))


@pytest.mark.parametrize("identifier", ["CASE_TEST", "CLUE_SYNTHETIC_EXPLORER", "H2", "P2", "Q2"])
def test_global_ids_cannot_collide_across_existing_or_proposed_types(case, identifier):
    payload = initial_output(case)
    payload["predictions"][0]["prediction_id"] = identifier
    assert any("collides" in error for error in errors(case, payload))


def test_contrasts_are_required_for_every_pair(case):
    payload = initial_output(case)
    payload["contrasts"].pop()
    assert any("every pair" in error for error in errors(case, payload))


@pytest.mark.parametrize("location", ["statement", "edge", "contrast"])
def test_unbacked_named_regulator_is_rejected_in_all_output_locations(case, location):
    payload = initial_output(case)
    if location == "statement":
        payload["hypotheses"][0]["mechanism_statement"] = "STAT1 may be the shared upstream regulator of A, B and C."
    elif location == "edge":
        payload["hypotheses"][0]["structure"]["directed_edges"] = [["STAT1", "A"]]
    else:
        payload["contrasts"][0]["difference"] = "A STAT1 mechanism has a different upstream topology than the cascade."
    assert any("unsupported named" in error and "STAT1" in error for error in errors(case, payload))


def test_overclaim_and_relabeling_rejected_outside_observation(case):
    payload = initial_output(case)
    payload["hypotheses"][0]["mechanism_statement"] = "MFI proves A and B regulate C."
    payload["hypotheses"][1]["assumptions"] = ["+ means upregulated; - means downregulated"]
    result = errors(case, payload)
    assert any("proof of a causal" in error for error in result)
    assert any("cannot be relabeled" in error for error in result)


@pytest.mark.parametrize("statement", [
    "H1 is retained; H2 is rejected.",
    "The shared upstream mechanism has confidence=90%.",
    "H1 wins over H2.",
    "The hypothesis has probability: 0.8.",
])
def test_free_text_cannot_smuggle_verdicts_rankings_or_scores(case, statement):
    payload = initial_output(case)
    payload["hypotheses"][0]["mechanism_statement"] = statement
    assert any("scores, rankings or final verdicts" in error for error in errors(case, payload))


def test_future_conditional_weakening_is_not_a_current_verdict(case):
    payload = initial_output(case)
    payload["hypotheses"][0]["weakening_conditions"] = [
        "If adequate context-matched experiments exclude shared upstream connectivity, H1 is rejected by a future critic."
    ]
    assert errors(case, payload) == ()


def test_reframe_add_preserves_old_space_and_compares_only_changed_pairs(case):
    case = existing_case(case)
    before = case.model_dump_json()
    assert errors(case, reframe_output(case), mode="reframe", reframe_reason="New conditional observation") == ()
    assert case.model_dump_json() == before


def test_reframe_requires_reason_prior_lineage_and_all_changed_comparisons(case):
    case = existing_case(case)
    payload = reframe_output(case)
    payload["hypotheses"][0]["derived_from"] = []
    payload["contrasts"].pop()
    result = errors(case, payload, mode="reframe")
    assert any("reframe reason" in error for error in result)
    assert any("lineage to a prior" in error for error in result)
    assert any("every pair" in error for error in result)


def test_reframe_redundancy_uses_persisted_current_structure(case):
    case = existing_case(case)
    payload = reframe_output(case)
    payload["hypotheses"][0]["structure"] = initial_output(case)["hypotheses"][0]["structure"]
    result = errors(case, payload, mode="reframe", reframe_reason="Review gap")
    assert any("redundant hypotheses H1 and H4" in error for error in result)


def test_reframe_revision_needs_real_content_change_and_reason(case):
    case = existing_case(case)
    initial = initial_output(case)
    payload = reframe_output(case)
    proposal = copy.deepcopy(initial["hypotheses"][0])
    proposal.update(operation="revise", derived_from=[{"object_type": "hypothesis", "object_id": "H1"}])
    payload["hypotheses"] = [proposal]
    payload["predictions"][0]["hypothesis_id"] = "H1"
    payload["predictions"][0]["discriminates_from_hypotheses"] = ["H2"]
    payload["evidence_questions"][0].update(relevant_hypothesis_ids=["H1", "H2"],
                                           discriminates_between=["H1", "H2"])
    payload["contrasts"] = initial["contrasts"][:2]
    result = errors(case, payload, mode="reframe", reframe_reason="Review gap")
    assert any("requires a reason" in error for error in result)
    assert any("substantive change" in error for error in result)
    proposal["reason"] = "Account for the new context constraint"
    proposal["assumptions"] += ["The unidentified upstream process must vary across the relevant contexts."]
    assert errors(case, payload, mode="reframe", reframe_reason="Review gap") == ()


def test_new_revision_can_follow_prior_verdict_without_overwriting_it(case):
    case = existing_case(case)
    old = case.hypotheses[0]
    retained = old.current_revision.model_copy(update={"status": "retained"})
    old = old.model_copy(update={"revisions": (retained,)})
    case = case.model_copy(update={"hypotheses": (old, *case.hypotheses[1:])})
    initial = initial_output(case)
    payload = reframe_output(case)
    payload["hypotheses"][0].update(hypothesis_id="H1", operation="revise", reason="New gap requires revised conditions",
                                     derived_from=[{"object_type": "hypothesis", "object_id": "H1"}])
    payload["predictions"][0].update(hypothesis_id="H1", discriminates_from_hypotheses=["H2", "H3"])
    payload["evidence_questions"][0].update(relevant_hypothesis_ids=["H1", "H2"], discriminates_between=["H1", "H2"])
    payload["contrasts"] = initial["contrasts"][:2]
    assert errors(case, payload, mode="reframe", reframe_reason="Review gap") == ()
    assert case.hypotheses[0].current_revision.status == "retained"


def test_config_applies_to_initial_and_changed_batch_not_total_history(case):
    payload = initial_output(case)
    assert any("count" in error for error in errors(case, payload, config=ExplorerConfig(max_hypotheses=2)))
    case = existing_case(case)
    assert errors(case, reframe_output(case), mode="reframe", reframe_reason="New observation",
                  config=ExplorerConfig(max_hypotheses=2)) == ()

@pytest.mark.parametrize('sentence',[
    'An association does not prove a causal mechanism.',
    'Bootstrap results cannot establish regulation.',
    'A frequency shift does not by itself establish causal regulation.',
    '关联不能证明因果调控。',
    'This is a descriptive association, not established regulatory relationships.',
])
def test_negated_proof_is_not_an_overclaim(case,sentence):
    from jure.agents.explorer.validation import _has_overclaim
    assert not _has_overclaim(sentence)

@pytest.mark.parametrize('sentence',[
    'An association proves a causal mechanism.',
    'The bootstrap establishes causal regulation.',
    'Association does not prove causality, but this association proves regulation.',
    '关联证明因果调控。',
])
def test_positive_proof_remains_rejected(sentence):
    from jure.agents.explorer.validation import _has_overclaim
    assert _has_overclaim(sentence)

def test_names_from_supplied_clue_are_grounded_without_becoming_causal_evidence(case):
    from jure.agents.explorer.validation import _unbacked_names
    # These symbols are in the synthetic clue; unknown molecular names still fail.
    assert not _unbacked_names('A-B state and C-negative cells',case,set())
    assert _unbacked_names('UNKNOWN-GENE mediates A-B',case,set())=={'UNKNOWN-GENE'}

def test_hypothesized_is_an_explicit_possibility_label(case):
    payload=initial_output(case)
    h=payload['hypotheses'][0]
    h['mechanism_statement']='It is hypothesized that A regulates C through an unspecified mediator.'
    h['assumptions']=[];h['unresolved_points']=[]
    assert not any('unverified possibility' in e for e in errors(case,payload))

def test_typed_upstream_names_are_available_but_raw_payload_is_not(case):
    from jure.agents.explorer.validation import _unbacked_names
    from jure.casefile.models import FrozenJSON
    clue=case.clue.model_copy(update={
        'upstream_context':FrozenJSON({'shared_candidate_conditions':['TESTGENE'],'group_id':'M17'}),
        'source_payload':FrozenJSON({'untrusted_unused_text':'HIDDENNAME'})})
    changed=case.model_copy(update={'clue':clue})
    assert not _unbacked_names('TESTGENE in M17',changed,set())
    assert _unbacked_names('HIDDENNAME',changed,set())=={'HIDDENNAME'}

def test_statistics_and_logic_abbreviations_are_not_molecular_names(case):
    from jure.agents.explorer.validation import _unbacked_names
    assert not _unbacked_names('FDR FWER BH BY QC AND OR',case,set())
    assert _unbacked_names('STAT1 remains unsupplied',case,set())=={'STAT1'}

def test_entity_in_raw_evidence_provenance_is_case_grounded(case):
    from jure.casefile.models import EvidenceRecord,Provenance
    from jure.agents.explorer.validation import _unbacked_names
    record=EvidenceRecord(question_id='Q_TEST',claim_tested='Generic fixture question',result_summary='Measured result retained.',
        source_type='dataset',provenance=Provenance(source_id='UNIT_ONLY',parameters={'tool_result':{'state':{'MEASUREDGENE':1}}}))
    updated=case.model_copy(update={'evidence_records':(record,)})
    assert not _unbacked_names('MEASUREDGENE',updated,set())
    assert _unbacked_names('UNMEASUREDGENE',updated,set())=={'UNMEASUREDGENE'}
