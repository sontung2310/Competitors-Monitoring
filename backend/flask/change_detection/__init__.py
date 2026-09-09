"""Deterministic change creation from confirmed snapshot differences."""

from .repository import ChangeRepository
from .service import (
    CHANGE_TYPE_BY_PAGE_TYPE,
    DEFAULT_CHANGE_STATUS,
    DEFAULT_CHANGE_TYPE,
    PROCESSOR_CHANGE_TYPES,
    NarrativeSummaryResult,
    ChangeError,
    ChangeService,
    create_change,
    derive_change_type,
    generate_narrative_summary_with_url,
    resolve_blog_detected_url,
    resolve_product_detected_url,
)

__all__ = [
    "CHANGE_TYPE_BY_PAGE_TYPE",
    "ChangeError",
    "ChangeRepository",
    "ChangeService",
    "DEFAULT_CHANGE_STATUS",
    "DEFAULT_CHANGE_TYPE",
    "PROCESSOR_CHANGE_TYPES",
    "NarrativeSummaryResult",
    "create_change",
    "derive_change_type",
    "generate_narrative_summary_with_url",
    "resolve_blog_detected_url",
    "resolve_product_detected_url",
]
