"""Layer 1 website discovery package."""

from .classification import (
    CandidateClassifier,
    CandidateForClassification,
    ClassifierConfigurationError,
    ClassificationResult,
    DeterministicStubClassifier,
    OpenJevClassifier,
    OpenJevClassifierConfigurationError,
    OpenAIClassifier,
    OpenAIClassifierConfigurationError,
    build_classifier_from_env,
    classify_candidates,
    classify_by_rules,
)
from .audit import (
    CORE_PAGE_TYPES,
    DiscoveryAuditResult,
    OpenAIDiscoveryAudit,
    SuggestedCandidateForAudit,
)
from .service import (
    DiscoveryConflictError,
    DiscoveryError,
    DiscoveryNotFoundError,
    DiscoveryService,
)

__all__ = [
    "CandidateClassifier",
    "CandidateForClassification",
    "ClassifierConfigurationError",
    "ClassificationResult",
    "DeterministicStubClassifier",
    "DiscoveryError",
    "DiscoveryConflictError",
    "DiscoveryNotFoundError",
    "DiscoveryService",
    "OpenAIClassifier",
    "OpenAIClassifierConfigurationError",
    "OpenJevClassifier",
    "OpenJevClassifierConfigurationError",
    "build_classifier_from_env",
    "classify_by_rules",
    "classify_candidates",
    "CORE_PAGE_TYPES",
    "DiscoveryAuditResult",
    "OpenAIDiscoveryAudit",
    "SuggestedCandidateForAudit",
]
