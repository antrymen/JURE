"""Offline migration checks on a read-only historical checkpoint."""
from copy import deepcopy
import json
from pathlib import Path
import pytest
from jure.casefile import CaseStore, load_case
from jure.casefile.history import verify_history
from jure.protocol.admission import investigation_first, latest_admission, investigation_completed_after_proposal
from jure.runtime.admission_migration import migrate_initial_handoff, validate_migration_source
from jure.runtime.pilot import validate_investigation_first_resume

CONFIG = Path('configs/agent_pilot_glm47_admission_v2_a.json')


def test_migration_preserves_science_history_and_next_real_actor():
    config=json.loads(CONFIG.read_text())
    spec=config['resume_sources']['A']
    path=Path(spec['directory'])/'case_file/case_file.json'
    raw=path.read_bytes(); source=load_case(path)
    with CaseStore() as store:
        store.import_case(source)
        migrated=migrate_initial_handoff(store,source.metadata.case_id,predecessor=spec)
        assert migrated.investigation_history[:len(source.investigation_history)]==source.investigation_history
        assert migrated.hypotheses==source.hypotheses
        assert migrated.evidence_questions==source.evidence_questions
        assert migrated.critic_audits==source.critic_audits
        assert migrated.action_state.next_actor=='investigator'
        assert investigation_first(migrated) and not investigation_completed_after_proposal(migrated)
        assert latest_admission(migrated).actor=='controller'
        assert 'explorer_event' not in latest_admission(migrated).metadata
        verify_history(migrated)
        with pytest.raises(ValueError,match='v1 initial'):
            migrate_initial_handoff(store,source.metadata.case_id,predecessor=spec)
    assert path.read_bytes()==raw


def test_continuation_validates_source_scope_and_budget():
    config=json.loads(CONFIG.read_text())
    assert validate_investigation_first_resume(config,'A')
    with pytest.raises(ValueError,match='Case A'):
        validate_investigation_first_resume(config,'AB')
    for role, field in [(None,'provider_max_calls_per_case'),('critic','max_explorer_reframes'),('investigator','max_tool_calls_per_run')]:
        changed=deepcopy(config)
        target=changed[role] if role else changed
        target[field]+=1
        with pytest.raises(ValueError,match='budgets'):
            validate_investigation_first_resume(changed,'A')
    config['handoff_migration']['inherited_model_calls']=0
    with pytest.raises(ValueError,match='inherited calls'):
        validate_investigation_first_resume(config,'A')
