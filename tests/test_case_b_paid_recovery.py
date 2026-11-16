"""Replay the real B answers through transport, admission and persistence offline."""
import json
from pathlib import Path

from jure.casefile import CaseStore, load_case
from jure.casefile.history import verify_history
from jure.agents.explorer.agent import MechanismExplorer
from jure.agents.explorer.models import ExplorerConfig
from jure.agents.explorer.scientific_content import ScientificContentBackend
from jure.runtime.backends import CheckedTransport


def test_complete_paid_b_revision_commits_without_any_model_regeneration():
    base=Path('outputs/agent_pilot_v1_20260928')
    initial=base/'run_035_case_b_continuation/B/model_calls'
    detail=base/'run_036_case_b_mapping_recovery/B/model_calls/call_0001_explorer'
    paths=[initial/'call_0001_explorer',initial/'call_0002_explorer',detail]
    rows=iter(paths);methods=[]
    request=json.loads(json.loads((paths[0]/'request.json').read_text())['messages'][1]['content'])
    source=load_case(base/'run_036_case_b_mapping_recovery/B/case_file/case_file.json')
    def replay(req, *, role):
        assert role=='explorer'
        methods.append(req['mode'])
        path=next(rows)  # Any unplanned paid request fails this offline test.
        return json.loads((path/'response.json').read_text())['content']
    config=json.loads(Path('configs/agent_pilot_case_b_mapping_recovery.json').read_text())
    backend=ScientificContentBackend(CheckedTransport(replay,'explorer',schema_retries=0,protocol_v3=True))
    agent=MechanismExplorer(backend,ExplorerConfig(**config['explorer']))
    with CaseStore() as store:
        store.import_case(source)
        result=agent.run(store,source.metadata.case_id,mode='reframe',
            reframe_reason=source.critic_audits.revision_requests[-1].reason,
            capability_summary=request['context']['capability_summary'])
        assert result.success, result.validation_errors
        final=store.load_case(source.metadata.case_id)
        verify_history(final)
        assert final.clue==source.clue
        assert final.hypotheses[:4]==source.hypotheses
        assert final.evidence_records==source.evidence_records
        assert final.critic_audits==source.critic_audits
        assert len(final.hypotheses)==5
        assert len(result.created_prediction_ids)==2
        assert len(result.created_evidence_question_ids)==10
        assert final.action_state.next_actor=='investigator'
        assert methods==['hypothesis_changes','pair_selection','pair_details']
        assert not backend.audit['patches']
        authored=json.loads((paths[0]/'response.json').read_text())['content']
        fields=json.loads(authored)['changes'][0]['fields']
        assert final.hypotheses[-1].current_revision.mechanism_statement==fields['mechanism_statement']
