# clue_query — tool card

Purpose: Inspect frozen reference, shift and landscape facts.

Backend: Frozen Day6 reference and landscape

Version: `9e807bcb127e06d04d11971b3ab2f1e641a140cec2f21a6dad08c4b7e08a5138`

Source class: `PRIMARY_EXPERIMENTAL_DATA`

Allowed agents: explorer, investigator, critic

Readiness: **READY**（固定 smoke 验收；不是 Agent 运行结果）

When to use: Inspect existing clue facts, support and related frozen states.

When not to use: Not a new experiment or a mechanism search.

Limitations: 只读冻结 facts；不提升 evidence level。

Failure behavior: Structured status; no mock fallback; no failure upgraded to evidence.

Provenance: Source identifiers, original retrieval time, hashes and query retained; no inference added.

## Example query

```json
{
  "operation": "get_condition_association",
  "condition": "TIMM23B",
  "genes": [
    "DDIT4",
    "PHGDH",
    "RGS16"
  ],
  "states": [
    1,
    1,
    1
  ]
}
```

Example result: [clue_query_result.json](/Users/mac/Documents/ChatGPT/JURE/outputs/tool_validation/smoke_case/clue_query_result.json) — `OK`.

## Input schema

```json
{
  "additionalProperties": false,
  "properties": {
    "operation": {
      "enum": [
        "get_case_clue",
        "get_reference_state",
        "get_condition_association",
        "get_landscape_context",
        "get_related_states",
        "get_signed_state_contrasts",
        "get_co_response_context"
      ],
      "title": "Operation",
      "type": "string"
    },
    "case_id": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Case Id"
    },
    "condition": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Condition"
    },
    "reference_id": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Reference Id"
    },
    "genes": {
      "items": {
        "type": "string"
      },
      "maxItems": 10,
      "title": "Genes",
      "type": "array"
    },
    "states": {
      "items": {
        "type": "integer"
      },
      "maxItems": 10,
      "title": "States",
      "type": "array"
    },
    "limit": {
      "default": 20,
      "maximum": 100,
      "minimum": 1,
      "title": "Limit",
      "type": "integer"
    }
  },
  "required": [
    "operation"
  ],
  "title": "ClueQuery",
  "type": "object"
}
```

Output schema: `EvidenceEnvelope`，完整 JSON Schema 见 [registry_snapshot.json](/Users/mac/Documents/ChatGPT/JURE/outputs/tool_validation/smoke_case/registry_snapshot.json)。
