from types import SimpleNamespace

from jure.agents.investigator.agent import latest_investigation_budget


def event(budget, *, actor='critic', extension=False, authorization=True):
    metadata = {'budget_state': budget}
    if extension:
        metadata['controller_event'] = 'USER_AUTHORIZED_BUDGET_EXTENSION'
        if authorization:
            metadata['authorization'] = {'user_instruction': '放宽给case b的预算'}
    return SimpleNamespace(actor=actor, metadata=metadata,
                           action='annotation.added' if extension else 'FINAL_CRITIC_AUDIT_STARTED')


def test_explicit_extension_overrides_old_exhausted_audit():
    old = {'investigator_rounds': 3, 'investigator_rounds_remaining': 0}
    new = {'investigator_rounds': 3, 'investigator_rounds_remaining': 2}
    case = SimpleNamespace(investigation_history=[event(old), event(new, actor='controller', extension=True)])
    assert latest_investigation_budget(case) is new


def test_new_critic_audit_overrides_prior_extension():
    extension = {'investigator_rounds_remaining': 2}
    exhausted = {'investigator_rounds_remaining': 0}
    case = SimpleNamespace(investigation_history=[event(extension, actor='controller', extension=True), event(exhausted)])
    assert latest_investigation_budget(case) is exhausted


def test_model_annotation_or_missing_authorization_cannot_extend_budget():
    old = {'investigator_rounds_remaining': 0}
    for actor, authorization in [('critic', True), ('controller', False)]:
        case = SimpleNamespace(investigation_history=[event(old), event({'investigator_rounds_remaining': 20},
            actor=actor, extension=True, authorization=authorization)])
        assert latest_investigation_budget(case) is old
