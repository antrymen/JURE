# case_file — tool card

Purpose: Read Case File sections and append revisioned role-owned records.

Backend: JURE CaseStore

Version: `casefile-0.1.1`

Source class: `BACKGROUND_SOURCE`

Allowed agents: explorer, investigator, critic

Readiness: **READY**（固定 smoke 验收；不是 Agent 运行结果）

When to use: Read shared state or persist your role-owned output.

When not to use: Do not rewrite snapshots or impersonate another role.

Limitations: 沿用 CaseStore、角色权限、revision 和审计链；写入在 TEST 副本验收。

Failure behavior: Structured status; no mock fallback; no failure upgraded to evidence.

Provenance: Source identifiers, original retrieval time, hashes and query retained; no inference added.

## Example query

```json
{
  "operation": "read_case",
  "case_id": "<bound case id>"
}
```

Example result: [case_read_case.json](/Users/mac/Documents/ChatGPT/JURE/outputs/tool_validation/smoke_case/case_read_case.json) — `OK`.

## Input schema

```json
{
  "additionalProperties": false,
  "properties": {
    "operation": {
      "enum": [
        "read_case",
        "read_section",
        "append_record",
        "history",
        "get_evidence",
        "get_hypotheses",
        "get_audits"
      ],
      "title": "Operation",
      "type": "string"
    },
    "case_id": {
      "title": "Case Id",
      "type": "string"
    },
    "section": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Section"
    },
    "record_type": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Record Type"
    },
    "record": {
      "anyOf": [
        {
          "additionalProperties": true,
          "type": "object"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Record"
    },
    "expected_revision": {
      "anyOf": [
        {
          "minimum": 1,
          "type": "integer"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Expected Revision"
    },
    "envelope_query_id": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Envelope Query Id"
    }
  },
  "required": [
    "operation",
    "case_id"
  ],
  "title": "CaseQuery",
  "type": "object"
}
```

Output schema: `EvidenceEnvelope`，完整 JSON Schema 见 [registry_snapshot.json](/Users/mac/Documents/ChatGPT/JURE/outputs/tool_validation/smoke_case/registry_snapshot.json)。
