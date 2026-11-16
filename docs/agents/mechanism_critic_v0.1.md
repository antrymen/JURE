# Mechanism Critic v0.1

## Role

Mechanism Critic is the scientific reasoning auditor and dynamic router in JURE. It asks what the current hypothesis space and acquired evidence justify, and whether the next useful action is hypothesis revision, evidence acquisition, or stopping. It uses the existing Shared Case File rather than a second investigation database.

This is a dynamic multi-agent mechanism investigation protocol that combines hypothesis-level auditing, claim-level evidence verification, and evidence-aware routing. Sequential evidence accumulation and claim-level verification are design inspirations; this implementation does not reproduce POPPER or VCR-Agent.

## Agent boundaries

Explorer owns mechanistic questions, hypotheses, predictions, and initial evidence questions. Investigator owns tool selection, acquisition, evidence normalization, and the dynamic evidence queue. Critic owns audits, verification claims, hypothesis status changes, gaps, contradictions, requests, routing, and stopping.

Critic receives no evidence-tool registry or executable tools. It cannot retrieve publications, query a network, compute dataset statistics, create hypotheses, rewrite observations, or edit evidence bodies/provenance. The backend proposes structured reasoning; deterministic validation and the CaseStore transaction enforce mutations. A revision request asks Explorer to fix hypothesis formulation. An investigation request states needed evidence characteristics and leaves tool selection to Investigator.

## Two-stage audit

Every run performs C1 hypothesis audit first. A failed C1 records a revision request and routes to Explorer without entering C2. C1 can run again after new evidence or an Explorer revision. Once C1 passes, C2 decomposes current hypotheses into claims, audits relevant evidence, synthesizes hypothesis states, attributes failures, and decides the next action. This internal ordering is fixed; the sequence of agents is not.

## Hypothesis audit

C1 checks groundedness, distinctness, testability, falsifiability, discriminability, scope, and coverage of important alternatives. Scientific hypotheses must distinguish observation from causal interpretation, have observable predictions and weakening conditions, and differ in mechanism rather than wording. Coverage findings describe the missing kind of alternative; they do not invent H4. Requests preserve the original clue and useful elements of the hypothesis space while identifying specific required changes.

## Mechanistic claims

A `MechanisticClaim` is a verification unit linked to an existing hypothesis revision and its predictions. It must preserve the hypothesis meaning. An unidentified upstream process remains unidentified; Critic cannot introduce a named regulator. Every critical claim has a `criticality_reason` explaining why the mechanism needs it. Difficulty finding evidence cannot make a critical claim noncritical. Claims associated with historical hypothesis revisions remain in the audit trail but do not govern the current revision.

## Claim-level evidence audit

The claim–evidence matrix separates dataset, network, and literature findings. Evidence is checked for relevance, directness, context match, source quality, support quality, provenance completeness, overclaim, and conflict. Links alone do not establish semantic relevance. An original `EvidenceRecord` remains intact; a separate `EvidenceAuditRecord` stores the Critic interpretation.

A network edge is useful indirect evidence of a candidate architecture, not causal proof. Dataset associations do not establish regulation. Generic co-mention does not verify an experiment. Missing search results are insufficient information, not a negative experiment. A powered, matched direct null result can challenge a required prediction. Context-dependent differences are retained with context explanations rather than silently treated as interchangeable experiments.

Evidence is not counted as votes. Ten contextual sources cannot mechanically outweigh one relevant, matched, sufficiently supported direct perturbation experiment. Descriptive claim coverage counts have no support-percentage threshold and no aggregate confidence score.

## Four statuses

| Status | Meaning |
| --- | --- |
| `supported` | Relevant evidence supports the required claim, without an unresolved critical conflict. |
| `partially_supported` | Some support exists, but an important component or contextual/directness requirement remains unresolved. |
| `challenged` | Substantive evidence conflicts with a required prediction. |
| `insufficient` | Available information does not justify a supported or challenged conclusion. |

These states are revisable. New evidence may move a hypothesis from insufficient to supported, or from supported to challenged. `PROVEN`, absolute truth labels, overall confidence percentages, and products of heterogeneous evidence scores are not used. A hypothesis with an unresolved critical claim cannot be supported; a strong challenge to a critical claim challenges the hypothesis.

## Failure attribution and routing

| Attribution | Normal next action |
| --- | --- |
| `hypothesis_problem`, `prediction_problem`, `hypothesis_space_inadequate` | Explorer receives a structured revision request. |
| `evidence_question_problem`, `evidence_quality_problem`, `evidence_missing` | Investigator receives a structured investigation request. |
| `evidence_conflict` | Investigator investigates discriminating evidence, or Explorer revises an inadequate space. |
| `tool_limit` | Evaluate whether the remaining uncertainty requires an evidence-limited stop. |
| `no_problem` | Evaluate evidence sufficiency. |

Every decision records related hypotheses, claims, evidence, gaps, and a reason that explains why that actor can address the current problem. Newly acquired evidence incompatible with all active hypotheses routes back to Explorer. Routing never assumes that evidence problems always need more retrieval.

## Evidence-sufficient stop

A sufficient stop requires an adequate hypothesis space, enough support for a remaining explanation and its critical claims, substantive discrimination of alternatives, no unresolved critical contradiction, and no obviously addressable critical gap. A partially supported explanation is eligible when only noncritical uncertainty remains. Compatible mechanisms need not be forced into a single winner. Remaining uncertainty is always stated, including an explicit “none identified within current evidence scope” when appropriate.

Sufficiency describes the current evidence scope; it does not establish an absolute causal proof.

## Evidence-limited stop

A limited stop is a valid investigation outcome when remaining explanations cannot be sufficiently distinguished with the available tools and evidence. Reasons include unavailable critical evidence, saturation, exhausted budget, unresolved hypothesis space at the reframe limit, or unavailable capabilities.

The stop preserves remaining hypotheses, unresolved critical gaps, evidence already checked, why current tools cannot resolve the uncertainty, and recommended future experiments. It does not force a winner or equate missing evidence with a false mechanism.

## Stall detection

Each round records an `InvestigationProgressSnapshot` derived from the Case File: useful new evidence, resolved/new gaps, hypothesis and claim status changes, discriminating questions, contradiction changes, and route. Repeated generic co-mentions are not scientific progress merely because the evidence record count grows. Consecutive rounds without meaningful progress trigger a final audit rather than unbounded retrieval.

## Budget

`CriticConfig` exposes `max_critic_rounds=6`, `max_investigator_rounds=8`, `max_explorer_reframes=2`, `max_total_tool_calls=30`, and `max_consecutive_stalled_rounds=2`, plus stop and audit policy switches. These defaults are operational limits, not scientifically optimized parameters.

A reached budget initiates a final Critic audit. The resulting case may already be evidence sufficient; otherwise the stop records the unresolved claims and whether a potentially useful query remains beyond the allowed budget. Budget exhaustion does not directly label the evidence insufficient.

Actual tool attempts still consume budget when later interpretation or artifact persistence fails and the scientific transaction rolls back. The counter reconciles committed tool events with failed-run artifacts by run ID; the next Investigator run is capped by the remaining global allowance.

## Recommended experiments

A recommended experiment specifies an objective, target uncertainty, intervention, measurement, discriminating outcomes under the remaining hypotheses, related claims/hypotheses, rationale, and feasibility notes. It is a future validation suggestion only. No experiment is executed, and no outcome is represented as guaranteed.

## Audit trail and artifacts

Shared Case File stores claims and separate hypothesis audits, evidence audits, claim audits, syntheses, failure attributions, status changes, progress snapshots, routing decisions, stop records, and final reports. Every successful mutation is append-only in `InvestigationHistory`; staged invalid backend output cannot partially commit scientific state. Run IDs support idempotent retries and reference validation checks all cross-record links.

Stage-specific contexts bound backend input: C1 receives observations, hypotheses, predictions, weakening conditions, and basic questions; C2 receives current claims and relevant evidence/provenance; final audit adds unresolved conflicts, gaps, progress, capabilities, and budget state. The entire history and raw tool output are not indiscriminately supplied.

Artifacts include `hypothesis_evidence_matrix.json`, `hypothesis_evidence_matrix.csv`, `investigation_trajectory.json`, and the final report when stopped. The trajectory is derived from authoritative Case File history. Final reports separate observation, interpretation, and uncertainty and retain challenging evidence, contradictions, and unresolved gaps.

## Synthetic tests

The acceptance suite covers the fourteen specified scenarios: C1 pass, redundant hypotheses, missing alternative, network-only evidence, overclaim, direct contradictory findings, evidence breaking the hypothesis space, sufficient stop, limited stop, stall, reached budget, critical-claim protection, agent boundaries, and dynamic round-trip routing.

Additional regression checks cover transaction rollback, idempotent runs, context filtering, provenance, unknown references, quality and directness caps, negative-search semantics, context mismatch, evidence-count voting, history integrity, and exported artifacts. The integration case calls the real Explorer, Investigator, and Critic classes with mock data/tools and dispatches from `ActionState.next_actor`; routing is an observed result rather than a prescribed controller sequence.

## Acceptance criteria

`python -m jure.agents.critic.demo` demonstrates Explorer routing, Investigator routing, and both sufficient and limited stopping. Tests must prove C1 gates C2; linked claims preserve mechanism meaning; evidence audits preserve raw records; statuses remain reversible and traceable; routing follows attributed failures; budgets and stalls enter final audit; and STOP reports preserve uncertainty and counterevidence. The three-agent loop must finish within its hard budget with valid references and a complete immutable history.

Only mock/synthetic cases are included. No real GRN, literature backend, biological case, Clue Discovery change, Tensor Network, reinforcement learning, or wet-lab execution is part of v0.1.

## Future statistical interface

A future `SequentialStatisticalEvidence` could attach a formally specified local null hypothesis and sequential statistic to one prediction. v0.1 implements neither e-values nor sequential testing, and it does not combine heterogeneous dataset/network/literature findings into a mechanism probability.

## Provider integration and capability availability

`JSONCriticBackend` accepts an injected `transport(request)` that returns a mapping or JSON text. The request includes the method, system instructions, bounded stage context, strict response schema, and `strict_json=True`. A deployment supplies its own provider adapter; no model vendor, credentials, network connection, or evidence acquisition is built into the Critic.

```python
from jure.agents.critic import JSONCriticBackend, MechanismCritic

critic = MechanismCritic(backend=JSONCriticBackend(transport=my_structured_json_transport))
result = critic.run(store, case_id, available_capabilities=["dataset", "literature"])
```

`available_capabilities=None` means that availability has not been specified. An explicit empty collection means that no current acquisition capability is available. The latter can justify an evidence-limited stop with concrete unresolved gaps and future validation suggestions; unspecified availability cannot by itself justify that conclusion.

The default `MockCriticBackend` provides deterministic lexical and structural heuristics for synthetic tests, not general scientific understanding of biological prose. Provider output remains advisory: a proposed high-support status cannot bypass directness, context, provenance, critical-claim, or reference guards. General semantic claim decomposition, subtle alternative mechanisms, and source interpretation need a validated reasoning backend. No benchmark of real biological accuracy is claimed by these synthetic acceptance tests.
