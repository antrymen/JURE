# knowledge_graph — tool card

Purpose: Look up typed entities, edges and bounded directed paths.

Backend: PrimeKG

Version: `e2749d6f85c2d80da3e43cd2c1284fc857c29eda437ae045af05698cbba5c653`

Source class: `CURATED_KNOWLEDGE_GRAPH`

Allowed agents: investigator, critic

Readiness: **READY**（固定 smoke 验收；不是 Agent 运行结果）

When to use: Check whether curated relations or bounded paths exist.

When not to use: Do not infer unrecorded edges or treat a path as case-specific mechanism.

Limitations: PrimeKG 8,100,498 条有向存储边；bounded paths 可截断。

Failure behavior: Structured status; no mock fallback; no failure upgraded to evidence.

Provenance: Source identifiers, original retrieval time, hashes and query retained; no inference added.

## Example query

```json
{
  "operation": "query_entity",
  "entity": "DDIT4"
}
```

Example result: [kg_result.json](/Users/mac/Documents/ChatGPT/JURE/outputs/tool_validation/smoke_case/kg_result.json) — `OK`.

## Input schema

```json
{
  "additionalProperties": false,
  "properties": {
    "operation": {
      "enum": [
        "query_entity",
        "query_edge",
        "find_paths",
        "local_subgraph"
      ],
      "title": "Operation",
      "type": "string"
    },
    "entity": {
      "title": "Entity",
      "type": "string"
    },
    "target": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Target"
    },
    "max_hops": {
      "default": 2,
      "maximum": 3,
      "minimum": 1,
      "title": "Max Hops",
      "type": "integer"
    },
    "max_nodes": {
      "default": 30,
      "maximum": 100,
      "minimum": 1,
      "title": "Max Nodes",
      "type": "integer"
    },
    "max_edges": {
      "default": 60,
      "maximum": 200,
      "minimum": 1,
      "title": "Max Edges",
      "type": "integer"
    },
    "max_paths": {
      "default": 10,
      "maximum": 30,
      "minimum": 1,
      "title": "Max Paths",
      "type": "integer"
    },
    "relation_types": {
      "items": {
        "type": "string"
      },
      "maxItems": 30,
      "title": "Relation Types",
      "type": "array"
    },
    "entity_types": {
      "items": {
        "type": "string"
      },
      "maxItems": 20,
      "title": "Entity Types",
      "type": "array"
    }
  },
  "required": [
    "operation",
    "entity"
  ],
  "title": "GraphQuery",
  "type": "object"
}
```

Output schema: `EvidenceEnvelope`，完整 JSON Schema 见 [registry_snapshot.json](/Users/mac/Documents/ChatGPT/JURE/outputs/tool_validation/smoke_case/registry_snapshot.json)。
