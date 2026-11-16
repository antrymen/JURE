"""Public acquisition contracts and deterministic offline evidence tools."""
from .base import EvidenceTool, EvidenceType, ExecutionStatus, ToolExecutionResult, ToolMetadata
from .dataset import DatasetEvidenceTool
from .literature import LiteratureEvidenceTool, RetrievedItem, VerifiedEvidenceCandidate
from .network import NetworkEdge, NetworkEvidenceTool
from .registry import EvidenceToolRegistry

__all__ = [
    "EvidenceTool", "EvidenceType", "ExecutionStatus", "ToolMetadata", "ToolExecutionResult",
    "EvidenceToolRegistry", "DatasetEvidenceTool", "NetworkEvidenceTool", "LiteratureEvidenceTool",
    "NetworkEdge", "RetrievedItem", "VerifiedEvidenceCandidate", "MockDatasetTool", "MockNetworkTool",
    "MockLiteratureTool",
]


def __getattr__(name):
    """Legacy test imports stay available; production imports do not load mocks."""
    if name in {"MockDatasetTool", "MockLiteratureTool", "MockNetworkTool"}:
        from . import mock
        return getattr(mock, name)
    raise AttributeError(name)
