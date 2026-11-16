# gene_knowledge — tool card

Purpose: Resolve human gene identity and retrieve source annotations/gene sets.

Backend: HGNC + Harmonizome API 1.0

Version: `api1.0;snapshot:real-tools-v01-smoke;hgnc:3e5da5b757afce6cae333d3e6c97a59ff3aadfb13da1c70f89d9a8f252b9e7ec`

Source class: `CURATED_GENESET_DATABASE`

Allowed agents: investigator, critic

Readiness: **READY**（固定 smoke 验收；不是 Agent 运行结果）

When to use: Inspect gene identity, annotations or membership in source gene sets.

When not to use: Not a perturbation-specific effect or an independent confirmation.

Limitations: HGNC symbol/Ensembl/alias 映射；真实 gene sets/pathway/context 响应。

Failure behavior: Structured status; no mock fallback; no failure upgraded to evidence.

Provenance: Source identifiers, original retrieval time, hashes and query retained; no inference added.

## Example query

```json
{
  "operation": "get_gene_info",
  "gene": "DDIT4"
}
```

Example result: [gene_knowledge_result.json](/Users/mac/Documents/ChatGPT/JURE/outputs/tool_validation/smoke_case/gene_knowledge_result.json) — `OK`.

## Input schema

```json
{
  "additionalProperties": false,
  "properties": {
    "operation": {
      "enum": [
        "get_gene_info",
        "query_gene_sets",
        "query_pathways",
        "query_functional_context"
      ],
      "title": "Operation",
      "type": "string"
    },
    "gene": {
      "maxLength": 80,
      "minLength": 1,
      "title": "Gene",
      "type": "string"
    },
    "species": {
      "const": "Homo sapiens",
      "default": "Homo sapiens",
      "title": "Species",
      "type": "string"
    },
    "limit": {
      "default": 20,
      "maximum": 50,
      "minimum": 1,
      "title": "Limit",
      "type": "integer"
    }
  },
  "required": [
    "operation",
    "gene"
  ],
  "title": "GeneQuery",
  "type": "object"
}
```

Output schema: `EvidenceEnvelope`，完整 JSON Schema 见 [registry_snapshot.json](/Users/mac/Documents/ChatGPT/JURE/outputs/tool_validation/smoke_case/registry_snapshot.json)。
