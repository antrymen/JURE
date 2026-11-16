# tn_query — tool card

Purpose: Reserved TN interface; no backend.

Backend: not configured

Version: `NOT_IMPLEMENTED`

Source class: `COMPUTATIONAL_PREDICTION`

Allowed agents: investigator, critic

Readiness: **NOT_IMPLEMENTED**（固定 smoke 验收；不是 Agent 运行结果）

When to use: Future integration only.

When not to use: Unavailable in v0.1.

Limitations: 仅 schema/stub；没有后端。

Failure behavior: Structured status; no mock fallback; no failure upgraded to evidence.

Provenance: Source identifiers, original retrieval time, hashes and query retained; no inference added.

## Example query

```json
{
  "operation": "query",
  "query": {}
}
```

Example result: [tn_stub.json](/Users/mac/Documents/ChatGPT/JURE/outputs/tool_validation/smoke_case/tn_stub.json) — `NOT_IMPLEMENTED`.

## Input schema

```json
{
  "additionalProperties": false,
  "properties": {
    "operation": {
      "const": "query",
      "default": "query",
      "title": "Operation",
      "type": "string"
    },
    "query": {
      "additionalProperties": true,
      "title": "Query",
      "type": "object"
    }
  },
  "required": [
    "query"
  ],
  "title": "TNQuery",
  "type": "object"
}
```

Output schema: `EvidenceEnvelope`，完整 JSON Schema 见 [registry_snapshot.json](/Users/mac/Documents/ChatGPT/JURE/outputs/tool_validation/smoke_case/registry_snapshot.json)。
