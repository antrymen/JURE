"""Network edges are candidate connectivity, not demonstrated causal mechanisms."""
from abc import abstractmethod

from pydantic import Field

from jure.casefile.models import FrozenJSON, FrozenModel, Text

from .base import EvidenceTool


NETWORK_LIMITATION = (
    "Network connectivity alone does not establish causal regulation in the current perturbation context."
)


class NetworkEdge(FrozenModel):
    source_gene: Text
    target_gene: Text
    network_name: Text
    network_version: Text
    edge_type: Text
    direction: Text = "source_to_target"
    context: Text | None = None
    source_reference: Text
    query_parameters: FrozenJSON = Field(default_factory=FrozenJSON)


class NetworkEvidenceTool(EvidenceTool):
    @abstractmethod
    def query_edge(self, source_gene, target_gene, context=None): ...

    @abstractmethod
    def query_shared_regulators(self, target_genes, context=None): ...

    @abstractmethod
    def query_paths(self, source_gene, target_gene, max_hops=2, context=None): ...

    def validate_payload(self, operation, payload):
        super().validate_payload(operation, payload)
        for field in ("network_name", "network_version", "context", "query_parameters",
                      "edges", "paths", "shared_regulators", "warnings", "limitations", "has_results"):
            if field not in payload:
                raise ValueError(f"network response missing {field}")
        if any(not isinstance(payload[field], list) for field in ("edges", "paths", "shared_regulators")):
            raise ValueError("network result collections must be lists")
        if bool(payload["edges"] or payload["paths"] or payload["shared_regulators"]) != payload["has_results"]:
            raise ValueError("has_results conflicts with network results")
        for edge in payload["edges"]:
            NetworkEdge.model_validate(edge)
        for regulator in payload["shared_regulators"]:
            if not regulator.get("regulator") or not regulator.get("edges"):
                raise ValueError("shared regulator needs a name and supporting edges")
            for edge in regulator["edges"]:
                validated = NetworkEdge.model_validate(edge)
                if validated.source_gene != regulator["regulator"]:
                    raise ValueError("shared-regulator edge has the wrong source")
        for path in payload["paths"]:
            if not path.get("nodes") or len(path["edges"]) != len(path["nodes"]) - 1:
                raise ValueError("path nodes must match its edges")
            for index, edge in enumerate(path["edges"]):
                validated = NetworkEdge.model_validate(edge)
                if (validated.source_gene, validated.target_gene) != tuple(path["nodes"][index:index + 2]):
                    raise ValueError("path edges do not connect the declared nodes")
        if NETWORK_LIMITATION not in payload["limitations"]:
            raise ValueError("network response must preserve its causal limitation")
