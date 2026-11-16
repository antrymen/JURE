# Broad Biological Interpretation — reserved interface

This directory reserves a downstream optional Triage/annotation interface. Broad Screening itself is now Clue Discovery Stage III; see [the method contract](../docs/clue_discovery/JURE_Clue_Discovery_Method.md). This directory reserves the next-stage interface only. No model, JEV, GO, pathway or literature implementation is included.

Future input: `outputs/broad_screening_v01/annotation_inputs/module_annotation_input.jsonl`, with separate `whole_module` and `stable_core` objects. Preserve ordered genes, states, reference IDs, target support, exact signed states and evidence scope. An empty core is unavailable, not a successful annotation unit.

Any future JEV adapter requires confirmation of the intended model and its actual interface. The existing conditional [TypeSafe Jev audit](../docs/agents/jev_capability_audit_20260927.md) does not establish a biological embedding API.

Day 8 status and annotation are not populated in v0.1. Day 6 memberships cannot be changed retrospectively using Day 8 outcomes without a new version.
