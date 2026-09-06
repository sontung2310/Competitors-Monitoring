"""Pluggable content processors for Layer 2 monitoring.

This module defines the processor boundary introduced in roadmap item 1.12.
The current implementation is deliberately limited to ``TextBlobProcessor``;
structured product-listing processing belongs to a later roadmap item.

The low-level monitoring functions live in ``website_monitoring.service``. They
are imported inside ``TextBlobProcessor.process`` rather than at module import
time so this boundary can be used by that service without creating an import
cycle.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol


@dataclass(frozen=True)
class ProcessResult:
    """Canonical output returned by every content processor."""

    changed: bool
    snapshot_content: str
    change_events: list[dict[str, str]]


class ContentProcessor(Protocol):
    """Process fetched content against the previous compatible snapshot."""

    def process(
        self,
        raw_content: str,
        previous_snapshot: Mapping[str, Any] | None,
    ) -> ProcessResult:
        """Return canonical snapshot content and zero or more change events."""


class ContentProcessingError(RuntimeError):
    """Raised when a processor cannot compare its input safely."""


class TextBlobProcessor:
    """Preserve the existing whole-page normalize/hash/diff behavior."""

    def __init__(self, *, page_type: str = "OTHER") -> None:
        if not isinstance(page_type, str) or not page_type.strip():
            raise ValueError("page_type must be a non-empty string")
        self.page_type = page_type.strip().upper()

    def process(
        self,
        raw_content: str,
        previous_snapshot: Mapping[str, Any] | None,
    ) -> ProcessResult:
        """Normalize, hash, compare, and generate the existing single event."""

        from backend.flask.change_detection.service import (
            derive_change_type,
            summarize_diff,
        )
        from .service import (
            compare_hashes,
            generate_diff,
            hash_content,
            normalize_content,
        )

        normalized_content = normalize_content(raw_content)
        if previous_snapshot is None:
            return ProcessResult(
                changed=False,
                snapshot_content=normalized_content,
                change_events=[],
            )
        if not isinstance(previous_snapshot, Mapping):
            raise TypeError("previous_snapshot must be a mapping or None")

        previous_hash = previous_snapshot.get("content_hash")
        current_hash = hash_content(normalized_content)
        if isinstance(previous_hash, str) and previous_hash.strip() and compare_hashes(
            previous_hash,
            current_hash,
        ):
            return ProcessResult(
                changed=False,
                snapshot_content=normalized_content,
                change_events=[],
            )

        previous_content = _previous_content(previous_snapshot)
        if not isinstance(previous_hash, str) or not previous_hash.strip():
            previous_hash = hash_content(previous_content)
            if compare_hashes(previous_hash, current_hash):
                return ProcessResult(
                    changed=False,
                    snapshot_content=normalized_content,
                    change_events=[],
                )

        diff = generate_diff(
            _diff_text(previous_content),
            _diff_text(normalized_content),
        )
        if not diff:
            raise ContentProcessingError(
                "snapshot hashes differ but generate_diff returned no content"
            )

        change_type = derive_change_type(self.page_type)
        return ProcessResult(
            changed=True,
            snapshot_content=normalized_content,
            change_events=[
                {
                    "change_type": change_type,
                    "summary": summarize_diff(change_type, diff),
                }
            ],
        )


def resolve_content_processor(
    page_type: str,
    processors: Mapping[str, ContentProcessor] | None = None,
) -> ContentProcessor:
    """Resolve a processor by page type, defaulting to ``TextBlobProcessor``."""

    if not isinstance(page_type, str) or not page_type.strip():
        raise ValueError("page_type must be a non-empty string")
    normalized_page_type = page_type.strip().upper()
    configured = processors or {}
    processor = configured.get(normalized_page_type)
    if processor is not None:
        return processor
    return TextBlobProcessor(page_type=normalized_page_type)


def _previous_content(snapshot: Mapping[str, Any]) -> str:
    for field in ("content", "normalized_content"):
        content = snapshot.get(field)
        if isinstance(content, str):
            return content
    raise ContentProcessingError(
        "previous snapshot content is unavailable; inject a snapshot content loader"
    )


def _diff_text(content: str) -> str:
    """Give line-oriented diffs a terminator without changing page content."""

    return content if content.endswith("\n") else f"{content}\n"


__all__ = [
    "ContentProcessingError",
    "ContentProcessor",
    "ProcessResult",
    "TextBlobProcessor",
    "resolve_content_processor",
]
