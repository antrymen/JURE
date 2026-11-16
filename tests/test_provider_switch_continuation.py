"""Provider changes must not silently restart Case A or replenish budgets."""
from copy import deepcopy
import json
from pathlib import Path
import pytest
from jure.runtime.pilot import validate_provider_switch_continuation


def config():
    return json.loads(Path('configs/agent_pilot_glm5_case_a_continuation.json').read_text())


def test_saved_investigator_handoff_can_change_provider_only():
    value = config(); before = deepcopy(value)
    assert validate_provider_switch_continuation(value, 'A')
    assert value == before


@pytest.mark.parametrize('field', ['provider_max_calls_per_case', 'max_transitions', 'schema_retries'])
def test_model_switch_does_not_replenish_limits(field):
    value = config(); value[field] += 1
    with pytest.raises(ValueError, match='cannot change'):
        validate_provider_switch_continuation(value, 'A')


def test_model_switch_requires_actual_predecessor_usage():
    value = config(); value['provider_switch']['inherited_model_calls'] = 0
    with pytest.raises(ValueError, match='inherited usage'):
        validate_provider_switch_continuation(value, 'A')


def test_model_switch_cannot_unfreeze_other_cases():
    with pytest.raises(ValueError, match='existing Case A'):
        validate_provider_switch_continuation(config(), 'AB')


def extension():
    return json.loads(Path('configs/agent_pilot_glm53_flash_case_a_extension.json').read_text())


def test_explicit_three_transition_extension_preserves_current_explorer_handoff():
    value = extension(); before = deepcopy(value)
    assert validate_provider_switch_continuation(value, 'A')
    assert value == before


@pytest.mark.parametrize('field', ['max_transitions', 'provider_max_calls_per_case'])
def test_extension_cannot_increase_any_further_budget(field):
    value = extension(); value[field] += 1
    with pytest.raises(ValueError):
        validate_provider_switch_continuation(value, 'A')


def test_extension_requires_recorded_authorization_and_preserves_scientific_limits():
    value = extension(); del value['transition_amendment']['user_authorization']
    with pytest.raises(ValueError, match='Explicit amendment'):
        validate_provider_switch_continuation(value, 'A')
    value = extension(); value['critic']['max_explorer_reframes'] += 1
    with pytest.raises(ValueError, match='cannot change'):
        validate_provider_switch_continuation(value, 'A')
