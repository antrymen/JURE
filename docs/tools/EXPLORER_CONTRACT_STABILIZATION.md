# Explorer Contract Stabilization v1

Scope: stabilize **initial** Explorer proposals, then measure engineering validity without Investigator, Critic or evidence acquisition. Existing protocol v3 capability boundaries, revision acceptance, discrimination semantics and STOP rules remain in place. Scientific text and choices are authored only by the JURE Explorer model.

## Content and object ownership

`ContentExplorerBackend` accepts a smaller content schema: mechanistic question, hypotheses, their nested predictions, each prediction's nested evidence question, comparison expectations/outcomes, and pairwise contrasts. The model uses short one-based hypothesis positions solely to express scientific comparisons. It does not generate database IDs, clue/case lineage, statuses, initial/revise operations or parallel prediction/question reference lists.

`compile_initial` assigns deterministic local IDs, attaches the authoritative parent clue, resolves hypothesis positions, connects each question to its containing prediction, constructs comparison targets from the owner and named alternatives, and maps readable observable names to registered capability IDs. It copies the immutable observation directly from the Case File context. Directed edges use source/target fields rather than model-authored serialized tuples.

The model still chooses what the observable and outcomes mean. The adapter does not select a tool, invent an alternative, fill in a missing prediction, infer a missing contrast, repair malformed JSON, reinterpret a result or supply a mechanism. It rejects unknown/self references and unavailable capabilities. Unknown biological aliases are not guessed; normalization is restricted to an exact case-insensitive match of a supplied gene symbol in structured edges and is logged. Scientific prose is copied from parsed content.

## Scientific-content retention

For every compiled proposal, a separate reverse projection reconstructs the content schema from the legacy objects. Its canonical hash must equal the parsed input content hash. Explicit gene-symbol case normalization is reversible and logged; other scientific content changes cause failure. This measures preservation within the adapter, **not equivalence between independently generated hypotheses in the two benchmark arms**. Raw provider responses are retained separately from typed content and compiled objects.

The existing Explorer semantic validator and atomic CaseStore commit still run after compilation. A contract-valid proposal can fail scientific-content guards and remain uncommitted. Automated entity/overclaim/redundancy checks are heuristics; their flags are not Critic judgments or established biological errors.

This version intentionally implements initial-mode compilation only. It rejects implicit reframe conversion; the existing reframe/Revision Acceptance protocol is unchanged. A later content-only reframe interface needs explicit revision lineage semantics and separate validation before adoption.

## Frozen evaluation

Protocol: `configs/explorer_contract_benchmark_v1.json`.

There were only four previously initialized pilot Case Files. The evaluation therefore initializes 20 separate inputs from the verified 6,129-candidate pool: 10 enrichment and 10 depletion, hash order within each stratum, unique perturbation conditions, excluding all four pilot conditions. Selection rules are frozen before ranking. No effect or biological attractiveness ranking is used. These are contract-test inputs, not additional completed scientific investigations.

Both arms use the same 20 immutable initial inputs, GLM-5.3 provider settings, factual capability snapshot and unchanged scientific guard. The arms are `legacy_identifiers` and `deterministic_adapter`. Each input-arm receives exactly one model request, no retry; at most 40 calls total. Two independent worker processes run requests, each with its own wall deadline and one-call budget. Case/arm ordering is fixed, with alternating arm order. All failures remain in the denominator; no replacement inputs or result-driven prompt tuning.

The adapter arm changes the output contract and its interface instructions; this is a paired comparison of interfaces, not an isolated causal ablation of identifier generation. The frozen provider configuration and code hashes are retained. The source-derived scientific context is shared, while technical output instructions differ.

Report separately:

- **Contract pass rate:** schema and reference validation passes / all 20 planned attempts per arm, including transport failures in the denominator.
- **Full proposal submission rate:** commits passing the unchanged scientific guard / all 20 attempts.
- Failure categories: JSON/schema, lineage, hypothesis reference, prediction/question mismatch, capability, provider, entity-guard flags and other scientific-content-guard flags. The last two are automated diagnostics, not expert biological adjudication.
- Calls/retries, reported tokens and missing usage; adapter content-retention checks with their actual denominator.

The declared contract target is 95% (19/20). Report full-submission readiness separately; passing an engineering metric does not authorize bypassing scientific validation. Twenty inputs yield a descriptive estimate, not proof of production reliability. No automatic full Case A launch is attached to this evaluation.

## Pilot budget isolation

The failed v3 A attempt remains immutable: 8 model calls consumed, 72 of its 80-call global allowance remaining. This separate Explorer-only engineering experiment neither resets nor consumes that pilot ledger. B/C/D remain paused. New A execution must explicitly retain its prior call history and remaining stage/scientific limits, or be clearly declared a new protocol evaluation; it is not silently started by this benchmark.

Implementation: `jure/agents/explorer/content_adapter.py`, `contract_checks.py`, and `jure/runtime/contract_benchmark.py`. Offline synthetic fixtures never enter the real benchmark.
