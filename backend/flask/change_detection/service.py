"""Deterministic change creation from already-different snapshots.

No LLM is used here. Hash comparison remains upstream in the monitoring
engine; this service defensively rejects equal hashes so an accidental call
cannot create a false change record.

Only BLOG and PRICING receive special event types because those are the page
types with explicit, justified mappings in the current specification and
discovery data. PRODUCTS and the other supported page types do not provide
enough evidence for NEW_PRODUCT, NEW_PROMOTION, NEW_CAMPAIGN, or NEW_AWARD,
so they safely use PAGE_UPDATE until a relevant page type is defined.

The default change status is ``NEW``. It means the change was detected and has
not yet been reviewed by a future presentation layer. A later frontend can add
reviewed/read states without changing the persistence contract or conflating
detection with user acknowledgement.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Mapping, Optional, Protocol

from backend.flask.database.base_repository import utc_now
from backend.flask.website_monitoring.service import (
    compare_hashes,
    generate_diff,
)

from .repository import ChangeRepository


class ChangeError(RuntimeError):
    """Raised when a change cannot be created safely."""


class MonitoringTargetReader(Protocol):
    """Repository boundary used to resolve a target's page type."""

    def get(self, target_id: Any, *, competitor_id: Any | None = None) -> Optional[dict[str, Any]]:
        """Return target metadata."""


SnapshotContentLoader = Callable[[Mapping[str, Any]], str]

CHANGE_TYPE_BY_PAGE_TYPE = {
    "BLOG": "NEW_BLOG",
    "PRICING": "PRICE_CHANGE",
}
DEFAULT_CHANGE_TYPE = "PAGE_UPDATE"
DEFAULT_CHANGE_STATUS = "NEW"


class ChangeService:
    """Generate a deterministic diff, classify it, and persist one record."""

    def __init__(
        self,
        change_repository: ChangeRepository,
        monitoring_target_repository: MonitoringTargetReader,
        *,
        snapshot_content_loader: Optional[SnapshotContentLoader] = None,
    ) -> None:
        self.change_repository = change_repository
        self.monitoring_target_repository = monitoring_target_repository
        self.snapshot_content_loader = snapshot_content_loader

    @classmethod
    def from_database(
        cls,
        database: Any,
        monitoring_target_repository: MonitoringTargetReader,
        *,
        snapshot_content_loader: Optional[SnapshotContentLoader] = None,
    ) -> "ChangeService":
        """Build a service with a repository backed by a database handle."""

        return cls(
            ChangeRepository.from_database(database),
            monitoring_target_repository,
            snapshot_content_loader=snapshot_content_loader,
        )

    def create_change(
        self,
        target_id: Any,
        previous_snapshot: Mapping[str, Any],
        current_snapshot: Mapping[str, Any],
        *,
        detected_at: Optional[datetime] = None,
    ) -> dict[str, Any]:
        """Persist a change from two snapshots whose hashes differ.

        Snapshot records may include their loaded content under ``content`` or
        ``normalized_content``. For metadata-only records, callers inject a
        ``snapshot_content_loader`` that reads the content through the snapshot
        storage layer; this service never touches the filesystem directly.
        """

        _require_snapshot_mapping(previous_snapshot, "previous_snapshot")
        _require_snapshot_mapping(current_snapshot, "current_snapshot")
        previous_hash = _snapshot_hash(previous_snapshot, "previous_snapshot")
        current_hash = _snapshot_hash(current_snapshot, "current_snapshot")
        if compare_hashes(previous_hash, current_hash):
            raise ChangeError(
                "create_change requires snapshots with different content_hash values"
            )

        target = self.monitoring_target_repository.get(target_id)
        if target is None:
            raise ChangeError(f"monitoring target {target_id!r} was not found")
        page_type = target.get("page_type")
        if not isinstance(page_type, str) or not page_type.strip():
            raise ChangeError(f"monitoring target {target_id!r} has no page_type")

        previous_content = self._load_content(previous_snapshot, "previous_snapshot")
        current_content = self._load_content(current_snapshot, "current_snapshot")
        diff = generate_diff(previous_content, current_content)
        if not diff:
            raise ChangeError(
                "snapshot hashes differ but generate_diff returned no content"
            )

        change_type = derive_change_type(page_type)
        summary = summarize_diff(change_type, diff)
        return self.change_repository.create(
            monitoring_target_id=target_id,
            previous_snapshot_id=_snapshot_id(previous_snapshot, "previous_snapshot"),
            current_snapshot_id=_snapshot_id(current_snapshot, "current_snapshot"),
            detected_at=detected_at or utc_now(),
            change_type=change_type,
            summary=summary,
            status=DEFAULT_CHANGE_STATUS,
        )

    def _load_content(
        self,
        snapshot: Mapping[str, Any],
        label: str,
    ) -> str:
        if self.snapshot_content_loader is not None:
            content = self.snapshot_content_loader(snapshot)
        else:
            content = snapshot.get("content")
            if content is None:
                content = snapshot.get("normalized_content")
        if not isinstance(content, str):
            raise ChangeError(
                f"{label} content is unavailable; inject a snapshot_content_loader"
            )
        return content


def create_change(
    target_id: Any,
    previous_snapshot: Mapping[str, Any],
    current_snapshot: Mapping[str, Any],
    *,
    change_repository: ChangeRepository,
    monitoring_target_repository: MonitoringTargetReader,
    snapshot_content_loader: Optional[SnapshotContentLoader] = None,
    detected_at: Optional[datetime] = None,
) -> dict[str, Any]:
    """Functional entry point for repository-backed change creation."""

    return ChangeService(
        change_repository,
        monitoring_target_repository,
        snapshot_content_loader=snapshot_content_loader,
    ).create_change(
        target_id,
        previous_snapshot,
        current_snapshot,
        detected_at=detected_at,
    )


def derive_change_type(page_type: str) -> str:
    """Map supported page types to event types with a safe update fallback."""

    if not isinstance(page_type, str) or not page_type.strip():
        raise ValueError("page_type must be a non-empty string")
    return CHANGE_TYPE_BY_PAGE_TYPE.get(page_type.strip().upper(), DEFAULT_CHANGE_TYPE)


def summarize_diff(change_type: str, diff: str) -> str:
    """Return a short deterministic summary based on unified-diff statistics."""

    added_lines = 0
    removed_lines = 0
    added_characters = 0
    removed_characters = 0
    for line in diff.splitlines(keepends=True):
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            added_lines += 1
            added_characters += len(line[1:])
        elif line.startswith("-"):
            removed_lines += 1
            removed_characters += len(line[1:])
    return (
        f"{change_type}: {added_lines} line(s) added, {removed_lines} line(s) removed "
        f"({added_characters} characters added, {removed_characters} removed)."
    )


def _require_snapshot_mapping(snapshot: Any, label: str) -> None:
    if not isinstance(snapshot, Mapping):
        raise TypeError(f"{label} must be a mapping")


def _snapshot_hash(snapshot: Mapping[str, Any], label: str) -> str:
    value = snapshot.get("content_hash")
    if not isinstance(value, str) or not value.strip():
        raise ChangeError(f"{label} has no content_hash")
    return value


def _snapshot_id(snapshot: Mapping[str, Any], label: str) -> Any:
    value = snapshot.get("id", snapshot.get("_id"))
    if value is None:
        raise ChangeError(f"{label} has no id")
    return value
