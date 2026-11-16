"""Bounded, explicitly human-guided continuation of the committed Case C pilot."""
import json
from pathlib import Path
from jure.casefile import load_case
from jure.casefile.history import agent_round_counts
from jure.tools.real.registry import file_sha


def validate_case_c_second_cycle(config, letters):
    from .pilot import initial_case_path, resume_checkpoint
    if letters!='C' or config['case_order']!=['C'] or not config.get('user_authorization'):
        raise ValueError('Explicit Case C continuation authorization required')
    if set(config.get('initial_case_sources',{}))!={'C'} or set(config.get('resume_sources',{}))!={'C'}:
        raise ValueError('One hash-bound Case C checkpoint required')
    if config['max_transitions']!=5 or config['provider_max_calls_per_case']>56 or config['registry_budgets']['total']>12:
        raise ValueError('Second-cycle budget exceeded')
    anchor=config['continuation_anchor']
    initial=load_case(initial_case_path('C',config))
    first,stages,traces,calls=resume_checkpoint(initial,anchor)
    if first.action_state.next_actor!='investigator' or first.action_state.current_phase!='evidence_needed':
        raise ValueError('Continuation must follow a committed Investigator route')
    if any(agent_round_counts(first,r)['completed']!=1 for r in ('explorer','investigator','critic')):
        raise ValueError('Anchor must be the completed first cycle')
    if calls!=26 or len(traces)!=6 or max(s['transition'] for s in stages)!=3:
        raise ValueError('Unexpected first-cycle ledger')
    current,_,_,current_calls=resume_checkpoint(initial,config['resume_sources']['C'])
    if current_calls<calls or current.investigation_history[:len(first.investigation_history)]!=first.investigation_history:
        raise ValueError('Continuation must preserve the first-cycle history and usage')
    spec=config['continuation_context']
    if file_sha(spec['path'])!=spec['sha256']:raise ValueError('Human guidance hash changed')
    context=json.loads(Path(spec['path']).read_text())
    if context.get('author')!='human' or not context.get('directions'):
        raise ValueError('Explicitly attributed human directions required')
