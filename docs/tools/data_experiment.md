# data_experiment — tool card

Purpose: Query real Day6 measured signed states with matched controls.

Backend: Replogle K562 essential Day6

Version: `80cecabc8bb6454fc94d6c58b1b3ea3607ea5b264ab73659234fd203210f18fe`

Source class: `PRIMARY_EXPERIMENTAL_DATA`

Allowed agents: investigator, critic

Readiness: **READY**（固定 smoke 验收；不是 Agent 运行结果）

When to use: Measure a specified signed-state probability/association in the canonical experiment.

When not to use: Not a discovery scan, biological replication or causal proof.

Limitations: 六种查询模式；低 support、缺测、无分母独立标记。

Failure behavior: Structured status; no mock fallback; no failure upgraded to evidence.

Provenance: Source identifiers, original retrieval time, hashes and query retained; no inference added.

## Example query

```json
{
  "mode": "JOINT_STATE",
  "condition": "TIMM23B",
  "state": {
    "DDIT4": 1,
    "PHGDH": 1,
    "RGS16": 1
  }
}
```

Example result: [data_joint_state_result.json](/Users/mac/Documents/ChatGPT/JURE/outputs/tool_validation/smoke_case/data_joint_state_result.json) — `OK`.

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
    "mode": {
      "enum": [
        "MARGINAL",
        "PAIRWISE",
        "JOINT_STATE",
        "CONDITIONAL",
        "CONDITION_COMPARISON",
        "STATE_CONTRAST"
      ],
      "title": "Mode",
      "type": "string"
    },
    "condition": {
      "title": "Condition",
      "type": "string"
    },
    "state": {
      "additionalProperties": {
        "type": "integer"
      },
      "maxProperties": 12,
      "minProperties": 1,
      "title": "State",
      "type": "object"
    },
    "conditioning_states": {
      "additionalProperties": {
        "type": "integer"
      },
      "maxProperties": 12,
      "title": "Conditioning States",
      "type": "object"
    },
    "contrast_state": {
      "anyOf": [
        {
          "additionalProperties": {
            "type": "integer"
          },
          "type": "object"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Contrast State"
    },
    "condition_b": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Condition B"
    },
    "dataset_id": {
      "default": "replogle_k562_essential_day6",
      "title": "Dataset Id",
      "type": "string"
    },
    "min_condition_cells": {
      "default": 100,
      "minimum": 1,
      "title": "Min Condition Cells",
      "type": "integer"
    },
    "min_nt_per_batch": {
      "default": 20,
      "minimum": 1,
      "title": "Min Nt Per Batch",
      "type": "integer"
    },
    "min_effective_nt": {
      "default": 100,
      "minimum": 1,
      "title": "Min Effective Nt",
      "type": "integer"
    },
    "min_events": {
      "default": 10,
      "minimum": 1,
      "title": "Min Events",
      "type": "integer"
    }
  },
  "required": [
    "mode",
    "condition",
    "state"
  ],
  "title": "ExperimentQuery",
  "type": "object"
}
```

Output schema: `EvidenceEnvelope`，完整 JSON Schema 见 [registry_snapshot.json](/Users/mac/Documents/ChatGPT/JURE/outputs/tool_validation/smoke_case/registry_snapshot.json)。
