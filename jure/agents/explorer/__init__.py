"""Mechanism Explorer v0.1: proposal generation, never evidence acquisition."""
from .agent import MechanismExplorer
from .backend import ExplorerBackend, JSONExplorerBackend, MockExplorerBackend
from .context import ContextLimitError, build_explorer_context
from .models import (
    EvidenceQuestionProposal, ExplorerConfig, ExplorerOutput, ExplorerRunResult,
    HypothesisContrast, HypothesisProposal, MechanismStructure, PredictionProposal,
)
from .validation import interpret_observation, validate_explorer_output

__all__ = [
    "ContextLimitError", "EvidenceQuestionProposal", "ExplorerBackend", "ExplorerConfig",
    "ExplorerOutput", "ExplorerRunResult", "HypothesisContrast", "HypothesisProposal",
    "JSONExplorerBackend", "MechanismExplorer", "MechanismStructure", "MockExplorerBackend",
    "PredictionProposal", "build_explorer_context", "interpret_observation", "validate_explorer_output",
]
