"""MongoDB repository for Layer 2 monitoring targets."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from backend.flask.database.base_repository import (
    BaseMongoRepository,
    serialize_document,
    to_object_id,
    utc_now,
)


class MonitoringTargetRepository(BaseMongoRepository):
    """Persistence operations for the ``monitoring_targets`` collection."""

    collection_name = "monitoring_targets"
    _UPDATE_FIELDS = {
        "raw_url",
        "url",
        "page_type",
        "discovery_source",
        "discovery_status",
        "classification_method",
        "active",
        "check_interval_minutes",
        "last_checked_at",
        "last_changed_at",
    }

    def ensure_indexes(self) -> None:
        """Create indexes for target deduplication, review, and scheduling."""

        self.collection.create_index(
            [("competitor_id", 1), ("url", 1)],
            unique=True,
            name="uq_monitoring_targets_competitor_url",
        )
        self.collection.create_index(
            [("competitor_id", 1), ("active", 1)],
            name="ix_monitoring_targets_competitor_active",
        )
        self.collection.create_index(
            [("competitor_id", 1), ("discovery_status", 1)],
            name="ix_monitoring_targets_competitor_discovery_status",
        )
        self.collection.create_index(
            [("active", 1), ("last_checked_at", 1)],
            name="ix_monitoring_targets_scheduler",
        )

    def create(
        self,
        *,
        competitor_id: Any,
        url: str,
        page_type: str,
        check_interval_minutes: int,
        raw_url: Optional[str] = None,
        discovery_source: str = "MANUAL",
        discovery_status: str = "ACTIVE",
        classification_method: str = "MANUAL",
        active: bool = True,
        last_checked_at: Optional[Any] = None,
        last_changed_at: Optional[Any] = None,
        now: Optional[Any] = None,
    ) -> dict[str, Any]:
        """Insert a Layer 2 target with discovery and monitoring metadata."""

        _require_text(url, "url")
        _require_text(page_type, "page_type")
        _require_positive_interval(check_interval_minutes)
        _require_bool(active, "active")
        timestamp = now or utc_now()
        document = {
            "competitor_id": to_object_id(competitor_id),
            "raw_url": raw_url or url,
            "url": url,
            "page_type": page_type,
            "discovery_source": discovery_source,
            "discovery_status": discovery_status,
            "classification_method": classification_method,
            "active": active,
            "check_interval_minutes": check_interval_minutes,
            "last_checked_at": last_checked_at,
            "last_changed_at": last_changed_at,
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        result = self.collection.insert_one(document)
        inserted_id = getattr(result, "inserted_id", None)
        if inserted_id is not None:
            document["_id"] = inserted_id
        return serialize_document(document) or {}

    def get(
        self,
        target_id: Any,
        *,
        competitor_id: Optional[Any] = None,
    ) -> Optional[dict[str, Any]]:
        query: dict[str, Any] = {"_id": to_object_id(target_id)}
        if competitor_id is not None:
            query["competitor_id"] = to_object_id(competitor_id)
        return serialize_document(self.collection.find_one(query))

    def list_for_competitor(
        self,
        competitor_id: Any,
        *,
        active: Optional[bool] = None,
        discovery_status: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        query: dict[str, Any] = {"competitor_id": to_object_id(competitor_id)}
        if active is not None:
            query["active"] = active
        if discovery_status is not None:
            query["discovery_status"] = discovery_status
        return self._find_sorted(query, [("created_at", -1)])

    def list(
        self,
        *,
        competitor_id: Optional[Any] = None,
        active: Optional[bool] = None,
        discovery_status: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """List targets, optionally scoped to a competitor or review state."""

        if competitor_id is None:
            query: dict[str, Any] = {}
            if active is not None:
                query["active"] = active
            if discovery_status is not None:
                query["discovery_status"] = discovery_status
            return self._find_sorted(query, [("created_at", -1)])
        return self.list_for_competitor(
            competitor_id,
            active=active,
            discovery_status=discovery_status,
        )

    def update(
        self,
        target_id: Any,
        updates: Optional[Mapping[str, Any]] = None,
        *,
        competitor_id: Optional[Any] = None,
        **fields: Any,
    ) -> Optional[dict[str, Any]]:
        """Update mutable target metadata and return the updated target."""

        values = dict(updates or {})
        values.update(fields)
        if not values:
            raise ValueError("at least one monitoring-target field is required")
        unknown = set(values) - self._UPDATE_FIELDS
        if unknown:
            raise ValueError(f"unsupported monitoring-target fields: {sorted(unknown)}")
        if "url" in values:
            _require_text(values["url"], "url")
        if "raw_url" in values:
            _require_text(values["raw_url"], "raw_url")
        if "page_type" in values:
            _require_text(values["page_type"], "page_type")
        if "check_interval_minutes" in values:
            _require_positive_interval(values["check_interval_minutes"])
        if "active" in values and not isinstance(values["active"], bool):
            raise ValueError("active must be a boolean")

        query: dict[str, Any] = {"_id": to_object_id(target_id)}
        if competitor_id is not None:
            query["competitor_id"] = to_object_id(competitor_id)
        values["updated_at"] = utc_now()
        result = self.collection.update_one(query, {"$set": values})
        if not self._matched(result):
            return None
        return self.get(target_id, competitor_id=competitor_id)

    def delete(
        self,
        target_id: Any,
        *,
        competitor_id: Optional[Any] = None,
    ) -> bool:
        """Delete a target document; history-aware deactivation is service logic."""

        query: dict[str, Any] = {"_id": to_object_id(target_id)}
        if competitor_id is not None:
            query["competitor_id"] = to_object_id(competitor_id)
        return self._deleted(self.collection.delete_one(query))


def _require_text(value: Any, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")


def _require_positive_interval(value: Any) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("check_interval_minutes must be a positive integer")


def _require_bool(value: Any, field: str) -> None:
    if not isinstance(value, bool):
        raise ValueError(f"{field} must be a boolean")
