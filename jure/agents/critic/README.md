# Mechanism Critic v0.1

Audits existing hypotheses and their claim-level evidence, then routes the Shared Case File to Explorer, Investigator, or an evidence-sufficient/evidence-limited stop. No evidence tools are called by Critic.

```python
from jure.agents.critic import MechanismCritic, CriticConfig

result = MechanismCritic(config=CriticConfig()).run(
    store, case_id, run_id="critic_round_1", artifact_dir="outputs/critic",
    available_capabilities=("dataset", "network", "literature"),
)
assert result.success, result.validation_errors
case = store.load_case(case_id)
print(case.action_state.next_actor)
```

Run the offline examples:

```sh
python -m jure.agents.critic.demo --output outputs/mechanism_critic_demo
```

`MockCriticBackend` supports deterministic defaults and per-method injected responses for tests. A provider-neutral backend boundary separates reasoning from validation, provenance checks, legal statuses, budgets, transactions, and history. The default backend is a conservative synthetic policy, not a general biological reasoning model.

See [the design document](../../../docs/agents/mechanism_critic_v0.1.md) for scientific boundaries, routing/stopping policy, and acceptance scenarios.

For a structured reasoning provider, inject a transport; JURE does not bind a
provider SDK or make a network call on behalf of Critic:

```python
from jure.agents.critic import JSONCriticBackend, MechanismCritic

# transport receives method, system instructions, a bounded stage context,
# strict response schema, and returns a JSON object or JSON text.
backend = JSONCriticBackend(transport=my_structured_json_transport)
result = MechanismCritic(backend=backend).run(store, case_id)
```

`available_capabilities=None` leaves capability availability unspecified; it
must not imply that all acquisition is impossible. An explicit empty collection
(`[]` or `()`) states that no acquisition capability is currently available and
allows an evidence-limited stop with the unresolved gaps and future validation
recommendations preserved. Capability names describe evidence families; no tool
handle is supplied to Critic.

The default mock uses inspectable lexical/structural heuristics for synthetic
acceptance cases. It is not validated for scientific judgment on arbitrary
biological prose. A production transport still passes through the same closed
schemas, reference checks, conservative evidence guards, and transactional store.
