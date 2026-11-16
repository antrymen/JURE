"""Protocol-only synthetic fixtures; none are used in real A/B runs."""
from copy import deepcopy
from types import SimpleNamespace
import pytest
from pydantic import ValidationError
from jure.protocol.contracts import DiscriminationSpec,RevisionAcceptance,accepted_revision_count,pending_submission
from jure.protocol.capabilities import capability_summary
from jure.agents.explorer import MechanismExplorer,MockExplorerBackend
from jure.agents.explorer.models import ExplorerConfig
from jure.agents.explorer.demo import initial_output,synthetic_clue
from jure.agents.critic import MechanismCritic
from jure.agents.critic.backend import MockCriticBackend,StopEvaluation
from jure.agents.critic.result import CriticConfig
from jure.agents.critic.stopping import stop_choice
from jure.agents.critic.stall_detection import budget_state
from jure.agents.investigator import EvidenceInvestigator,InvestigatorConfig
from jure.casefile import CaseStore,ActionState,HypothesisAuditResult,RevisionRequest
from jure.casefile.history import verify_history,agent_round_counts
from jure.runtime.backends import validate_investigator_interface,InterfaceContractError


CAPS=capability_summary([{'tool_id':'data_experiment','availability':'available'}])

def comparison(targets=('H1','H2')):
    return {'targets':list(targets),'expectations':[{'hypothesis_id':h,'prediction':f'Observable response pattern {i} under the unit hypothesis.'} for i,h in enumerate(targets)],
        'observable':'Binary conditional state frequency','capability_ids':['state.conditional'],
        'possible_outcomes':[{'outcome_id':'O1','observation':'First predeclared pattern','favors':[targets[0]],'weakens':[targets[1]],'non_discriminating':False,'interpretation_limit':'Synthetic association only.'},
        {'outcome_id':'O0','observation':'No usable difference','favors':[],'weakens':[],'non_discriminating':True,'interpretation_limit':'No hypothesis verdict.'}],
        'scope_limit':'Synthetic observable; not a causal experiment.'}


def proposal(case,suffix=None):
    result=initial_output(case)
    for q in result['evidence_questions']:
        q['discrimination']=comparison(tuple(q['discriminates_between']))
    if suffix:
        for h in result['hypotheses']:
            h.update(operation='revise',reason='Synthetic defect repair',derived_from=[{'object_type':'hypothesis','object_id':h['hypothesis_id']}])
            h['assumptions']=list(h.get('assumptions',[]))+[f'Unit revision {suffix.lower()} is an unverified possibility.']
        for p in result['predictions']:p['prediction_id']+=suffix
        for q in result['evidence_questions']:
            q['question_id']+=suffix;q['derived_from_prediction_ids']=[p+suffix for p in q['derived_from_prediction_ids']]
    return result


@pytest.fixture
def investigation(tmp_path):
    with CaseStore(tmp_path/'unit.sqlite') as store:
        case=store.create_case_from_clue(synthetic_clue(),cell_context='K562')
        result=MechanismExplorer(MockExplorerBackend([proposal(case)]),ExplorerConfig(protocol_v3=True,max_retries=0)).run(store,case.metadata.case_id,capability_summary=CAPS)
        assert result.success,result.validation_errors
        case=store.load_case(case.metadata.case_id)
        request=RevisionRequest(required_changes=('Make the unit discriminating prediction executable.',),reason='Synthetic defect',affected_hypothesis_ids=('H1',),critic_round=1)
        audit=HypothesisAuditResult(case_id=case.metadata.case_id,overall_status='revision_required',audit_summary='Synthetic defect',critic_round=1)
        case=store.append_critic_records(case.metadata.case_id,revision_requests=(request,),hypothesis_audits=(audit,),actor='critic',expected_revision=case.metadata.case_revision)
        case=store.set_action_state(case.metadata.case_id,ActionState(current_phase='exploration_needed',next_actor='explorer'),actor='critic',expected_revision=case.metadata.case_revision)
        yield store,case.metadata.case_id,request


def submit(store,cid,suffix):
    case=store.load_case(cid)
    result=MechanismExplorer(MockExplorerBackend([proposal(case,suffix)]),ExplorerConfig(protocol_v3=True,max_retries=0)).run(store,cid,mode='reframe',reframe_reason='Synthetic defect',capability_summary=CAPS)
    assert result.success,result.validation_errors
    return store.load_case(cid)


class AcceptanceBackend(MockCriticBackend):
    def __init__(self,status='RESOLVED',bad_reference=False):super().__init__();self.status=status;self.bad_reference=bad_reference
    def accept_revision(self,context):
        return {'request_id':context['revision_request']['request_id'],'submission_run_id':context['submission']['run_id'],'status':self.status,
                'checks':[{'defect_id':d['defect_id'],'status':self.status,'reason':'Synthetic targeted assessment.',
                           'resolution_object_ids':['MISSING'] if self.bad_reference else ['H1'] if self.status=='RESOLVED' else []}
                          for d in context['revision_defects']], 'summary':'Synthetic acceptance outcome.'}


def test_saved_revision_requires_critic_acceptance_and_does_not_spend_success_budget(investigation,tmp_path):
    store,cid,request=investigation;before=submit(store,cid,'R1')
    assert before.action_state.next_actor=='critic' and pending_submission(before)
    assert accepted_revision_count(before)==0
    blocked=EvidenceInvestigator(config=InvestigatorConfig(protocol_v3=True)).run(store,cid,artifact_dir=tmp_path/'blocked')
    assert not blocked.success and 'acceptance' in blocked.validation_errors[0]
    result=MechanismCritic(AcceptanceBackend(),CriticConfig(protocol_v3=True,max_explorer_reframes=1)).run(store,cid,artifact_dir=tmp_path/'accept')
    assert result.success,result.validation_errors
    after=store.load_case(cid);assert after.action_state.next_actor=='investigator'
    assert accepted_revision_count(after)==1 and pending_submission(after) is None
    assert after.hypotheses==before.hypotheses and after.evidence_records==before.evidence_records
    assert agent_round_counts(after,'critic')['completed']==0  # separate targeted audit, still costs a provider call
    assert budget_state(after,CriticConfig(protocol_v3=True,max_explorer_reframes=1),1)['explorer_reframes_remaining']==0
    verify_history(after)


def test_unresolved_revision_retries_then_stops_with_exact_reason(investigation,tmp_path):
    store,cid,_=investigation;critic=MechanismCritic(AcceptanceBackend('UNRESOLVED'),CriticConfig(protocol_v3=True,max_explorer_reframes=1,max_revision_acceptance_attempts=2))
    submit(store,cid,'R1');r=critic.run(store,cid,artifact_dir=tmp_path/'first');assert r.success,r.validation_errors
    case=store.load_case(cid);assert case.action_state.next_actor=='explorer' and accepted_revision_count(case)==0
    submit(store,cid,'R2');r=critic.run(store,cid,artifact_dir=tmp_path/'second');assert r.success,r.validation_errors
    case=store.load_case(cid);assert case.action_state.stop_reason=='revision_budget_exhausted'
    assert accepted_revision_count(case)==0 and not case.evidence_records and not case.critic_audits.claim_audits
    assert case.critic_audits.final_reports[-1].stop_type=='revision_budget_exhausted'
    verify_history(case)


def test_invalid_acceptance_cannot_route_or_spend_success(investigation,tmp_path):
    store,cid,_=investigation;case=submit(store,cid,'R1')
    result=MechanismCritic(AcceptanceBackend(bad_reference=True),CriticConfig(protocol_v3=True)).run(store,cid,artifact_dir=tmp_path/'bad')
    assert not result.success and 'unknown Case File' in result.validation_errors[0]
    after=store.load_case(cid)
    assert after.hypotheses==case.hypotheses and after.action_state==case.action_state
    assert accepted_revision_count(after)==0 and pending_submission(after)


def test_acceptance_cannot_hide_unresolved_check():
    with pytest.raises(ValidationError,match='Overall acceptance'):
        RevisionAcceptance(request_id='RR',submission_run_id='E',status='RESOLVED',summary='Unit',checks=[{'defect_id':'D1','status':'UNRESOLVED','reason':'Unit'}])


def test_comparison_requires_other_outcome_and_linked_hypotheses():
    d=comparison();DiscriminationSpec.model_validate(d)
    for mutation in ('unlinked','no_non_discriminating'):
        bad=deepcopy(d)
        if mutation=='unlinked':bad['possible_outcomes'][0]['favors']=['H9']
        else:bad['possible_outcomes'][1]['non_discriminating']=False
        with pytest.raises(ValidationError):DiscriminationSpec.model_validate(bad)


def test_unavailable_observable_rejected_without_scientific_rewrite(tmp_path):
    with CaseStore(tmp_path/'unit.sqlite') as store:
        c=store.create_case_from_clue(synthetic_clue(),cell_context='K562');p=proposal(c)
        p['evidence_questions'][0]['discrimination']['capability_ids']=['rna.stability']
        result=MechanismExplorer(MockExplorerBackend([p]),ExplorerConfig(protocol_v3=True,max_retries=0)).run(store,c.metadata.case_id,capability_summary=CAPS)
        assert not result.success and any('unavailable capability' in e for e in result.validation_errors)
        assert not store.load_case(c.metadata.case_id).hypotheses
        assert p['evidence_questions'][0]['discrimination']['capability_ids']==['rna.stability']


def test_invalid_initial_revision_ids_are_not_misreported_as_genes(tmp_path):
    from jure.agents.explorer.models import ExplorerOutput
    from jure.agents.explorer.validation import validate_explorer_output
    with CaseStore(tmp_path/'unit.sqlite') as store:
        case=store.create_case_from_clue(synthetic_clue(),cell_context='K562')
        output=proposal(case)
        for hypothesis in output['hypotheses']:
            hypothesis['operation']='revise'
            hypothesis['reason']='Uncommitted correction mistaken for a revision.'
        output['evidence_questions'][0]['discrimination']['scope_limit']='Comparison of H1 and H2 is hypothetical.'
        errors=validate_explorer_output(ExplorerOutput.model_validate(output),case,config=ExplorerConfig(protocol_v3=True),capability_summary=CAPS)
        assert any('existing hypothesis in reframe mode' in e for e in errors)
        assert not any('unsupported named molecular specifics' in e and ('H1' in e or 'H2' in e) for e in errors)


def test_initial_retry_schema_keeps_add_operation():
    from jure.agents.explorer.backend import JSONExplorerBackend
    captured=[]
    JSONExplorerBackend(lambda request:captured.append(request)).generate_initial({},feedback=('Previous output invalid',))
    assert captured[0]['response_schema']['$defs']['HypothesisProposal']['properties']['operation']['const']=='add'


def test_stage_labels_are_not_molecules_and_initial_lineage_is_typed(tmp_path):
    from jure.agents.explorer.validation import _unbacked_names
    from jure.agents.explorer.context import build_explorer_context
    with CaseStore(tmp_path/'unit.sqlite') as store:
        case=store.create_case_from_clue(synthetic_clue(),cell_context='K562')
        assert _unbacked_names('Day6 versus Day8; ZXCV99',case,set())=={'ZXCV99'}
        context=build_explorer_context(case,'initial')
        assert context['lineage_catalog']==[
            {'object_id':case.metadata.case_id,'object_type':'case'},
            {'object_id':case.clue.clue_id,'object_type':'clue'}]


@pytest.mark.parametrize('mode,genes',[('MARGINAL',{'A':1,'B':1}),('PAIRWISE',{'A':1,'B':1,'C':1})])
def test_invalid_cardinality_fails_before_acquisition(mode,genes):
    request={'method':'operationalize_question','protocol_v3':True,'context':{'active_hypotheses':[{'hypothesis_id':'H1'},{'hypothesis_id':'H2'}],'pending_questions':[{'question_id':'Q1','relevant_hypothesis_ids':['H1','H2']}],
        'tool_capabilities':[{'tool_id':'data_experiment','tool_type':'dataset','capabilities':['query'],'availability':'available'}]}}
    response={'question_id':'Q1','evidence_type':'dataset','discrimination':comparison(),'planned_operations':[{'operation':'query','inputs':{'condition':'X','mode':mode,'state':genes}}]}
    with pytest.raises(InterfaceContractError,match='input contract failed'):validate_investigator_interface(request,response)


@pytest.mark.parametrize('kind,limits,reframe,stalled,expected',[
 ('none',[],True,False,'revision_budget_exhausted'),('none',['revision_acceptance_attempts'],False,False,'revision_budget_exhausted'),
 ('none',['total_tool_calls'],False,False,'tool_budget_exhausted'),('none',['critic_rounds'],False,False,'agent_budget_exhausted'),
 ('capability',[],False,False,'capability_limited'),('evidence',[],False,False,'evidence_limited'),('none',[],False,True,'stalled')])
def test_stop_classification(kind,limits,reframe,stalled,expected):
    case=SimpleNamespace(hypotheses=(),mechanistic_claims=(),evidence_gaps=(),contradictions=())
    result=stop_choice(case,SimpleNamespace(overall_status='revision_required'),[],StopEvaluation(reason='Unit',no_further_queries=True,limitation_kind=kind),
        {'hard_limit_reached':bool(limits),'reached_limits':limits,'explorer_reframe_limit_reached':reframe},
        {'investigation_stalled':stalled},CriticConfig(protocol_v3=True),'explorer' if reframe else 'stop')
    assert result[0]==expected


def test_protocol_v3_can_reach_c2_without_forcing_a_winner(tmp_path):
    from jure.agents.critic.demo import create_case,add_synthetic_evidence
    with CaseStore(tmp_path/'c2.sqlite') as store:
        case=create_case(store)
        case=add_synthetic_evidence(store,case,source_type='grn',directness='indirect',source_quality='curated_database',support_quality='limited')
        result=MechanismCritic(config=CriticConfig(protocol_v3=True)).run(store,case.metadata.case_id,
            available_capabilities=[],artifact_dir=tmp_path/'c2')
        assert result.success,result.validation_errors
        final=store.load_case(case.metadata.case_id)
        assert final.critic_audits.claim_audits and final.critic_audits.evidence_audits
        assert final.action_state.stop_reason!='evidence_sufficient'
        verify_history(final)


def test_superseded_questions_are_preserved_but_not_reinvestigated(investigation):
    from jure.agents.investigator.context import build_investigator_context
    store,cid,_=investigation;before=store.load_case(cid);after=submit(store,cid,'R1')
    registry=SimpleNamespace(protocol_v3=True,metadata_snapshot=lambda:[])
    context=build_investigator_context(after,registry=registry)
    assert {q.question_id for q in before.evidence_questions}<=set(context['excluded_superseded_question_ids'])
    assert not set(context['excluded_superseded_question_ids'])&{q['question_id'] for q in context['pending_questions']}
    assert after.evidence_questions[:len(before.evidence_questions)]==before.evidence_questions
