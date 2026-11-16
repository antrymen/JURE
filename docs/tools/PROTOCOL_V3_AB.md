# Protocol v3.0 — A/B evaluation

Codex implements and verifies interfaces. JURE Explorer, Investigator and Critic author all scientific questions, hypotheses, acquisition decisions and verdicts. C/D remain paused. Baseline A/B snapshots and initial Case Files remain immutable.

## Changes

1. Explorer receives a factual, registry-derived observable catalog, including unavailable measurements. New evidence questions declare competing hypotheses, distinct conditional expectations, observable/capability IDs, possible outcomes (including a non-discriminating branch), and interpretation limits. No biological targets, hypotheses or tool order are supplied by the host.
2. An Explorer revision is a submission, routed to Critic for targeted acceptance against individually labelled, verbatim defects in the original revision request. Each defect is RESOLVED, PARTIAL or UNRESOLVED and links to actual submitted objects. Only an all-RESOLVED request consumes the successful-revision allowance. Unaccepted submissions cannot enter Investigator. Acceptance does not bypass the next full C1 audit.
3. Investigator declares a hypothesis comparison before querying, selects tools independently, and records an advisory information update against those predeclared outcomes. This update is acquisition progress, not a claim verdict. Tool-input schemas are checked before execution. Superseded questions remain in history but are excluded from the current queue.

The Critic still controls C1 and C2. No rule passes C1 merely to satisfy the evaluation metric. Acceptance uses real Critic model calls, commits separate append-only history events, and does not masquerade as a full C1/C2 audit round. Invalid submissions/checks preserve diagnostics without promoting scientific writes.

## Stops and budgets

Persisted stop codes include `evidence_sufficient`, `evidence_limited`, `capability_limited`, `revision_budget_exhausted`, `tool_budget_exhausted`, `stalled`, and `agent_budget_exhausted` for other declared agent-round limits. Technical/controller/provider failures remain failures and do not fabricate a scientific STOP.

`configs/agent_pilot_glm53_v30_ab.json` retains GLM-5.3, temperature/context/provider settings, 80 model calls, 18 real tool calls and 12 controller transitions per case. Other unchanged limits: 3 full Critic rounds, 3 Investigator rounds, 1 successful Explorer revision, 2 questions / 4 tool calls per Investigator run, 2 Critic source rechecks per full round, one failed-stage retry and one schema retry. Targeted acceptance has at most 2 attempts per request, within the existing global bounds. Rejected acceptance does not consume the successful-revision allowance, but its model calls and controller transitions are counted.

## Evaluation

Run A and B independently from the same untouched initial Case Files. Do not seed baseline hypotheses, evidence, reports or Codex posthoc analysis. Both outcomes are retained even if A fails. Freeze source hashes, base prompt hashes, role protocol contracts, capability catalog, provider configuration and all budgets before execution; do not edit them during execution.

Primary success: at least one case **commits a nonempty claim-level evidence audit after C1 passes**. A function attempt, rolled-back C2 output, final report, hypothesis status or winning mechanism alone does not meet this criterion. Report C2 attempts separately from committed audits.

Secondary observations: executable comparison mappings; per-defect acceptance results; real tool provenance; acquisition progress; routing; distinct stop reasons; model/tool use. A/B baseline and v3 are a small combined protocol-evolution pilot, not evidence for the causal effect of each component or a powered single-factor ablation.

Offline tests use isolated synthetic fixtures, never pilot scientific inputs. Historical snapshots are checked for hash/history compatibility. Agent reports remain authored by the three JURE agents; engineering comparisons are labelled separately.

## Executed scope and technical continuation

The user narrowed the active evaluation to **A only**. B/C/D remain paused. Run 016 was interrupted after a diagnostic namespace defect; run 017 preserved all 5 prior A requests and committed history, with no budget replenishment. Its A-specific retry caps allow only two remaining Explorer generation attempts and no extra stage retry; global bounds remain unchanged. A ended after 8 cumulative requests without a committed initial proposal. B had no Agent/model calls.

At completion, artifact auditing verified the frozen code and source history. Subsequent offline fixes distinguish Day6/Day8 metadata labels from molecules and supply exact initial typed lineage IDs. They did not change the failed run or trigger more model calls. See [Case A engineering review](/Users/mac/Documents/ChatGPT/JURE/outputs/agent_pilot_v1_20260928/CASE_A_PROTOCOL_V3_REVIEW.md) for the measured result and limitations.
