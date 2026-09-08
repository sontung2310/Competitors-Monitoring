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

    status_code = 400
    code = "validation_error"


class ChangeNotFoundError(ChangeError):
    """Raised when a requested target used to scope changes is absent."""

    status_code = 404
    code = "not_found"


class MonitoringTargetReader(Protocol):
    """Repository boundary used to resolve a target's page type."""

    def get(self, target_id: Any, *, competitor_id: Any | None = None) -> Optional[dict[str, Any]]:
        """Return target metadata."""


SnapshotContentLoader = Callable[[Mapping[str, Any]], str]

CHANGE_TYPE_BY_PAGE_TYPE = {
    "BLOG": "NEW_BLOG",
    "PRICING": "PRICE_CHANGE",
}
PROCESSOR_CHANGE_TYPES = frozenset(
    {"NEW_PRODUCT", "PRODUCT_REMOVED", "PRICE_CHANGE"}
)
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
        competitor_repository: Any | None = None,
    ) -> None:
        self.change_repository = change_repository
        self.monitoring_target_repository = monitoring_target_repository
        self.snapshot_content_loader = snapshot_content_loader
        self.competitor_repository = competitor_repository

    @classmethod
    def from_database(
        cls,
        database: Any,
        monitoring_target_repository: MonitoringTargetReader,
        *,
        snapshot_content_loader: Optional[SnapshotContentLoader] = None,
        competitor_repository: Any | None = None,
    ) -> "ChangeService":
        """Build a service with a repository backed by a database handle."""

        return cls(
            ChangeRepository.from_database(database),
            monitoring_target_repository,
            snapshot_content_loader=snapshot_content_loader,
            competitor_repository=competitor_repository,
        )

    def create_change(
        self,
        target_id: Any,
        previous_snapshot: Mapping[str, Any],
        current_snapshot: Mapping[str, Any],
        *,
        detected_at: Optional[datetime] = None,
        change_type: Optional[str] = None,
        summary: Optional[str] = None,
        is_simulated: bool = False,
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
        diff = generate_diff(
            _diff_text(previous_content),
            _diff_text(current_content),
        )
        if not diff:
            raise ChangeError(
                "snapshot hashes differ but generate_diff returned no content"
            )

        if change_type is None:
            resolved_change_type = derive_change_type(page_type)
        else:
            if not isinstance(change_type, str) or not change_type.strip():
                raise ChangeError("change_type override must be a non-empty string")
            resolved_change_type = change_type.strip().upper()
        if summary is None:
            resolved_summary = summarize_diff(resolved_change_type, diff)
        else:
            if not isinstance(summary, str) or not summary.strip():
                raise ChangeError("summary override must be a non-empty string")
            resolved_summary = summary.strip()
        if not isinstance(is_simulated, bool):
            raise ChangeError("is_simulated must be a boolean")
        return self.change_repository.create(
            monitoring_target_id=target_id,
            previous_snapshot_id=_snapshot_id(previous_snapshot, "previous_snapshot"),
            current_snapshot_id=_snapshot_id(current_snapshot, "current_snapshot"),
            detected_at=detected_at or utc_now(),
            change_type=resolved_change_type,
            summary=resolved_summary,
            status=DEFAULT_CHANGE_STATUS,
            is_simulated=is_simulated,
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

    def get_change(
        self,
        change_id: Any,
        *,
        company_id: Any | None = None,
    ) -> dict[str, Any] | None:
        """Return one persisted change for the read-only changes endpoint."""

        change = self.change_repository.get(change_id)
        if change is None or company_id is None:
            return change
        self._require_company_repository()
        target = self.monitoring_target_repository.get(change.get("monitoring_target_id"))
        if target is None:
            return None
        competitor = self.competitor_repository.get(
            target.get("competitor_id"),
            company_id=company_id,
        )
        return change if competitor is not None else None

    def list_changes(
        self,
        *,
        competitor_id: Any | None = None,
        target_id: Any | None = None,
        company_id: Any | None = None,
        since: datetime | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Read a bounded latest-change feed without bypassing repositories."""

        target_ids: list[Any] | None = None
        if company_id is not None:
            self._require_company_repository()
            scoped_competitors = self.competitor_repository.list_for_company(company_id)
            scoped_competitor_ids = [competitor["id"] for competitor in scoped_competitors]
            if competitor_id is not None and str(competitor_id) not in {
                str(value) for value in scoped_competitor_ids
            }:
                return []
            if target_id is not None:
                target = self.monitoring_target_repository.get(target_id)
                if target is None or str(target.get("competitor_id")) not in {
                    str(value) for value in scoped_competitor_ids
                }:
                    return []
            if competitor_id is None:
                target_ids = []
                for scoped_competitor_id in scoped_competitor_ids:
                    target_ids.extend(
                        target["id"]
                        for target in self.monitoring_target_repository.list_for_competitor(
                            scoped_competitor_id
                        )
                    )
        if target_id is not None:
            target = self.monitoring_target_repository.get(target_id)
            if target is None:
                raise ChangeNotFoundError(f"monitoring target {target_id!r} was not found")
            target_ids = [target_id]

        if competitor_id is not None:
            list_for_competitor = getattr(
                self.monitoring_target_repository,
                "list_for_competitor",
                None,
            )
            if not callable(list_for_competitor):
                raise ChangeError("target repository cannot scope changes by competitor")
            competitor_targets = list_for_competitor(competitor_id)
            competitor_target_ids = [target["id"] for target in competitor_targets]
            if target_ids is None:
                target_ids = competitor_target_ids
            else:
                allowed_ids = set(competitor_target_ids)
                target_ids = [value for value in target_ids if value in allowed_ids]

        return self.change_repository.list(
            monitoring_target_ids=target_ids,
            since=since,
            limit=limit,
        )

    def _require_company_repository(self) -> None:
        if self.competitor_repository is None:
            raise ChangeError("company-scoped changes require a competitor repository")


def create_change(
    target_id: Any,
    previous_snapshot: Mapping[str, Any],
    current_snapshot: Mapping[str, Any],
    *,
    change_repository: ChangeRepository,
    monitoring_target_repository: MonitoringTargetReader,
    snapshot_content_loader: Optional[SnapshotContentLoader] = None,
    detected_at: Optional[datetime] = None,
    change_type: Optional[str] = None,
    summary: Optional[str] = None,
    is_simulated: bool = False,
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
        change_type=change_type,
        summary=summary,
        is_simulated=is_simulated,
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


def _diff_text(content: str) -> str:
    """Give line-oriented diffs a terminator without changing page content."""

    return content if content.endswith("\n") else f"{content}\n"


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
