"""Factual observable catalog; no case genes, suggested queries or tool order."""

CATALOG={
 'data_experiment':[
  ('state.marginal','Single-gene detected/undetected frequency; one state gene.'),
  ('state.pairwise','Two-gene contingency table, marginals and p11 minus product of marginals; exactly two state genes; association only.'),
  ('state.joint','Multi-gene joint detected/undetected frequency.'),
  ('state.conditional','State frequency within a specified detected/undetected conditioning subset.'),
  ('state.condition_comparison','Condition-level signed-state comparison with matched NT support.'),
  ('state.signed_contrast','Descriptive comparison of two signed states; no automatic test of their delta difference.')],
 'knowledge_graph':[('knowledge.relations','Curated relations/shared neighbors/paths; connectivity is not causal regulation.')],
 'gene_knowledge':[('knowledge.gene_context','Gene identities, annotations and available gene-set context; no new experimental observation.')],
 'literature':[('literature.search','Find publication candidates; search hits are not evidence.'),
               ('literature.retrieve','Retrieve PubMed abstract passages and provenance; experimental design and claim support require Agent audit, not automatic verification.')],
 'clue_query':[('clue.context','Read frozen clue associations and context; no independent replication.')],
}


def capability_summary(cards):
    lookup={c['tool_id']:c for c in cards}
    observables=[]
    for tool,items in CATALOG.items():
        card=lookup.get(tool,{})
        for identifier,description in items:
            observables.append({'capability_id':identifier,'observable':description,
                'availability':card.get('availability','unavailable')})
    return {'observables':observables,'unavailable':[
        'Single-cell count-depth/library-size diagnostics and multivariable covariate adjustment.',
        'Continuous-expression correlations or abundance distributions through this binary-state interface.',
        'Direct RNA-stability, protein-level, time-course or wet-lab measurements.',
        'Day8 replication and automatic literature experimental-design verification.'],
        'contract':'Describe predictions using these observable boundaries. External-only predictions may be limitations; each hypothesis needs a currently reachable discriminating question. Choose mechanisms freely. This catalog chooses no tool, query, biological target or result.'}


ROLE_CONTRACTS={
 'explorer':'''Protocol v3: Form a competing hypothesis space that covers the alternatives in your own mechanistic question. Read capability_summary before formulating predictions. Each hypothesis needs a reachable discrimination specification: target hypotheses, distinct conditional expectations, observable/capability IDs, possible outcomes including a non-discriminating result, and scope limits. These are hypothetical comparisons, not acquired evidence or verdicts. Do not select tools or prescribe their order. EvidenceQuestion.discrimination is required for every new question. A revision batch can contain fewer changes than the complete hypothesis set; unchanged hypotheses persist. Address each revision_defect explicitly through the revised objects; only the Critic may accept the revision. Preserve the immutable observation string exactly; never translate it. Use English for generated technical fields so the registered lexical validation contract is applied consistently.''',
 'investigator':'''Protocol v3: Prioritize reduction of unresolved differences between competing hypotheses, not evidence count. Each operational plan must include a discrimination specification grounded in the selected question and current predictions, with an observable, outcome branches and non-discriminating branch. Prerequisite measurements may be partial progress; do not call marginals alone a test of conditional dependence, or descriptive association causal direction. Every interpretation requires information_update linked to the predeclared outcome IDs, or null when no outcome can be assessed. This is advisory acquisition progress, never a hypothesis/claim verdict. You choose queries and tools. Use available schemas and preserve the intended scientific question; if not executable, return an empty plan and record the limitation.''',
 'critic':'''Protocol v3: Distinguish hypothesis design, evidence limitations, and capability limits. Check whether each hypothesis has a reachable discriminating observable; acknowledge external-only components rather than pretending a binary-state proxy establishes temporal or causal mechanism. Check coverage of the alternatives named in the mechanistic question. Revision acceptance assesses each named defect against the submitted objects, using RESOLVED/PARTIAL/UNRESOLVED; saving a revision is not acceptance. Acceptance does not authorize bypassing C1 before C2. For C2, audit claims against actual acquired evidence, allowing insufficient/challenged results. Entering C2 is an evaluation metric, never a reason to pass an inadequate C1. Stop reasons distinguish evidence, capability, revision budget, tool budget, and stalling. You decide scientific judgments; deterministic code enforces the declared limits.'''
}
