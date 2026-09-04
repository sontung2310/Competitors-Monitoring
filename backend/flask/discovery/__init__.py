"""Layer 1 website discovery package."""

from .classification import (
    CandidateClassifier,
    CandidateForClassification,
    ClassificationResult,
    DeterministicStubClassifier,
    OpenAIClassifier,
    OpenAIClassifierConfigurationError,
    classify_candidates,
    classify_by_rules,
)
from .service import DiscoveryError, DiscoveryService

__all__ = [
    "CandidateClassifier",
    "CandidateForClassification",
    "ClassificationResult",
    "DeterministicStubClassifier",
    "DiscoveryError",
    "DiscoveryService",
    "OpenAIClassifier",
    "OpenAIClassifierConfigurationError",
    "classify_by_rules",
    "classify_candidates",
]
