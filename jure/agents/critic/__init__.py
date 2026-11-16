"""JURE Mechanism Critic v0.1: scientific audit and dynamic routing."""
from .agent import MechanismCritic
from .backend import CriticBackend, JSONCriticBackend, MockCriticBackend
from .context import build_critic_context
from .result import CriticConfig, CriticRunResult
from .artifacts import ClaimEvidenceMatrix, build_claim_evidence_matrix, investigation_trajectory

__all__ = ['MechanismCritic', 'CriticBackend', 'JSONCriticBackend', 'MockCriticBackend',
           'CriticConfig', 'CriticRunResult', 'build_critic_context', 'ClaimEvidenceMatrix',
           'build_claim_evidence_matrix', 'investigation_trajectory']
