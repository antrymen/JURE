"""Program checks object consistency; scientific flags are not verdicts."""
from types import SimpleNamespace
import pytest
from jure.agents.critic.validation import validate_evidence_audit, scientific_review_flags, normalize_claims
from jure.agents.critic.evidence_audit import EvidenceAuditResult


def audit_fixture(status='supported'):
    evidence=SimpleNamespace(evidence_id='E1',source_type='grn',negative_evidence_type='not_found',
        provenance=SimpleNamespace(source_id='unit',tool='unit',source_uri='unit://fixture'),raw_result_reference='unit.json')
    case=SimpleNamespace(evidence_records=[evidence])
    claim=SimpleNamespace(claim_id='C1')
    result=EvidenceAuditResult.model_validate({'evidence_audits':[{'evidence_id':'E1','claim_ids':['C1'],
        'directness_assessment':'direct','context_assessment':'unknown','support_quality_assessment':'unknown',
        'source_quality_assessment':'unknown','provenance_check':'complete','contradiction_detected':True,
        'critic_interpretation':'Synthetic output used only to test validator ownership.'}],
        'claim_audits':[{'claim_id':'C1','status':status,'evidence_ids':['E1'],
            'supporting_evidence_ids':['E1'] if status=='supported' else [],
            'challenging_evidence_ids':['E1'] if status=='challenged' else [],'summary':'Synthetic test verdict.'}]})
    return case,(claim,),result,{'evidence_records':[{'evidence_id':'E1'}]}


@pytest.mark.parametrize('status',['supported','challenged'])
def test_quality_thresholds_and_source_interpretation_are_flags(status):
    case,claims,result,context=audit_fixture(status)
    validate_evidence_audit(case,result,claims,context)
    flags=scientific_review_flags(case,result=result)
    assert {'NETWORK_DIRECTNESS_REVIEW','RETRIEVAL_ABSENCE_REVIEW','CLAIM_SUPPORT_JUSTIFICATION_REVIEW'}<={f['code'] for f in flags}
    assert result.claim_audits[0].status==status


def test_provenance_and_reference_consistency_still_reject():
    case,claims,result,context=audit_fixture()
    case.evidence_records[0].provenance.source_id=''
    with pytest.raises(ValueError,match='provenance'):validate_evidence_audit(case,result,claims,context)
    case.evidence_records[0].provenance.source_id='unit'
    with pytest.raises(ValueError,match='every relevant evidence'):validate_evidence_audit(case,result,claims,{'evidence_records':[]})


def test_named_claim_entity_is_flagged_without_program_scientific_rejection():
    from jure.casefile import CaseStore
    from jure.agents.critic.demo import create_case
    from jure.agents.critic.backend import MockCriticBackend,ClaimDecompositionResult
    from jure.agents.critic.context import build_critic_context
    with CaseStore() as store:
        case=create_case(store)
        result=ClaimDecompositionResult.model_validate(MockCriticBackend().decompose_claims(build_critic_context(case,'hypothesis')))
        claims=list(result.claims)
        claims[0]=claims[0].model_copy(update={'statement':claims[0].statement+' Unverified mediator XYZ123.'})
        normalized=normalize_claims(case,claims)
        assert normalized[0].statement==claims[0].statement
        assert scientific_review_flags(case,normalized)[0]['code']=='CLAIM_ENTITY_PROVENANCE_UNCLEAR'
