# literature — tool card

Purpose: Search PubMed and retrieve verifiable abstracts; passage validation is partial.

Backend: NCBI PubMed E-utilities

Version: `esearch0.3/efetch-xml;snapshot:real-tools-v01-smoke`

Source class: `BACKGROUND_SOURCE`

Allowed agents: investigator, critic

Readiness: **PARTIAL**（固定 smoke 验收；不是 Agent 运行结果）

When to use: Find and inspect original paper records relevant to an Agent-authored question.

When not to use: A search hit or abstract alone does not establish experimental design or claim support.

Limitations: 真实 search/metadata/abstract 已通过；自动科学证据分类未实现，全文未接入。

Failure behavior: Structured status; no mock fallback; no failure upgraded to evidence.

Provenance: Source identifiers, original retrieval time, hashes and query retained; no inference added.

## Example query

```json
{
  "operation": "search",
  "entities": [
    "DDIT4"
  ],
  "limit": 3
}
```

Example result: [literature_retrieve_result.json](/Users/mac/Documents/ChatGPT/JURE/outputs/tool_validation/smoke_case/literature_retrieve_result.json) — `OK`.

## Input schema

```json
{
  "additionalProperties": false,
  "properties": {
    "operation": {
      "enum": [
        "search",
        "retrieve",
        "extract_evidence"
      ],
      "title": "Operation",
      "type": "string"
    },
    "entities": {
      "items": {
        "type": "string"
      },
      "maxItems": 10,
      "title": "Entities",
      "type": "array"
    },
    "relation": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Relation"
    },
    "process": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Process"
    },
    "cell_type": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Cell Type"
    },
    "perturbation": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Perturbation"
    },
    "keywords": {
      "items": {
        "type": "string"
      },
      "maxItems": 10,
      "title": "Keywords",
      "type": "array"
    },
    "pmids": {
      "items": {
        "type": "string"
      },
      "maxItems": 10,
      "title": "Pmids",
      "type": "array"
    },
    "limit": {
      "default": 5,
      "maximum": 20,
      "minimum": 1,
      "title": "Limit",
      "type": "integer"
    },
    "claim": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Claim"
    },
    "passages": {
      "items": {
        "additionalProperties": true,
        "type": "object"
      },
      "maxItems": 10,
      "title": "Passages",
      "type": "array"
    }
  },
  "required": [
    "operation"
  ],
  "title": "LiteratureQuery",
  "type": "object"
}
```

Output schema: `EvidenceEnvelope`，完整 JSON Schema 见 [registry_snapshot.json](/Users/mac/Documents/ChatGPT/JURE/outputs/tool_validation/smoke_case/registry_snapshot.json)。
