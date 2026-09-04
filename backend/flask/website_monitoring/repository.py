"""MongoDB repository for Layer 2 monitoring targets."""

from __future__ import annotations

from datetime import datetime
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
    DEFAULT_CANDIDATE_CHECK_INTERVAL_MINUTES = 1440
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
        _validate_active_discovery_status(active, discovery_status)
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

    def list_active_targets(
        self,
        competitor_id: Optional[Any] = None,
    ) -> list[dict[str, Any]]:
        """Return only rows safe for the monitoring engine or scheduler.

        Candidates and monitoring targets share this collection. Both fields
        are required here so malformed or stale candidate rows cannot enter a
        monitoring run merely because their ``active`` field is truthy.
        Callers that need work to process must use this method instead of
        constructing their own active-target query.
        """

        query: dict[str, Any] = {
            "active": True,
            "discovery_status": "ACTIVE",
        }
        if competitor_id is not None:
            query["competitor_id"] = to_object_id(competitor_id)
        return self._find_sorted(query, [("created_at", -1)])

    def find_by_url(
        self,
        competitor_id: Any,
        url: str,
    ) -> Optional[dict[str, Any]]:
        """Find a target by its competitor and normalized URL."""

        _require_text(url, "url")
        query = {
            "competitor_id": to_object_id(competitor_id),
            "url": url,
        }
        return serialize_document(self.collection.find_one(query))

    def upsert_discovered_candidate(
        self,
        *,
        competitor_id: Any,
        raw_url: str,
        url: str,
        page_type: str,
        discovery_source: str,
        discovery_status: str,
        classification_method: str,
        now: Optional[Any] = None,
    ) -> dict[str, Any]:
        """Persist a discovered candidate without regressing user decisions.

        Discovery may run repeatedly. Existing active or explicitly activated
        targets retain their activation state and classification metadata while
        their discovery provenance can be refreshed.
        """

        _require_text(raw_url, "raw_url")
        _require_text(url, "url")
        _require_text(page_type, "page_type")
        _require_text(discovery_source, "discovery_source")
        _require_text(discovery_status, "discovery_status")
        _require_text(classification_method, "classification_method")

        existing = self.find_by_url(competitor_id, url)
        if existing is not None:
            updates: dict[str, Any] = {
                "raw_url": raw_url,
                "discovery_source": discovery_source,
            }
            is_user_activated = existing.get("active") or existing.get(
                "discovery_status"
            ) == "ACTIVE"
            if not is_user_activated:
                updates.update(
                    {
                        "page_type": page_type,
                        "discovery_status": discovery_status,
                        "classification_method": classification_method,
                    }
                )
            updated = self.update(
                existing["id"],
                updates,
                competitor_id=competitor_id,
            )
            return updated or existing

        return self.create(
            competitor_id=competitor_id,
            raw_url=raw_url,
            url=url,
            page_type=page_type,
            discovery_source=discovery_source,
            discovery_status=discovery_status,
            classification_method=classification_method,
            active=False,
            check_interval_minutes=self.DEFAULT_CANDIDATE_CHECK_INTERVAL_MINUTES,
            now=now,
        )

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
        current = self.get(target_id, competitor_id=competitor_id)
        if current is None:
            return None
        _validate_active_discovery_status(
            values.get("active", current.get("active", False)),
            values.get("discovery_status", current.get("discovery_status")),
        )
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


class MonitoringRunRepository(BaseMongoRepository):
    """Persistence operations for the ``monitoring_runs`` collection."""

    collection_name = "monitoring_runs"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    _STATUSES = frozenset({RUNNING, SUCCESS, FAILED})

    def ensure_indexes(self) -> None:
        """Create the target/status history index used by run readers and 1.8."""

        self.collection.create_index(
            [("monitoring_target_id", 1), ("started_at", -1)],
            name="ix_monitoring_runs_target_started_at",
        )
        self.collection.create_index(
            [("monitoring_target_id", 1), ("status", 1)],
            name="ix_monitoring_runs_target_status",
        )

    def create(
        self,
        *,
        monitoring_target_id: Any,
        started_at: datetime,
        status: str = RUNNING,
        error_message: Optional[str] = None,
        now: Optional[Any] = None,
    ) -> dict[str, Any]:
        """Insert a run, normally in the ``RUNNING`` state."""

        _require_timestamp(started_at, "started_at")
        _require_run_status(status)
        if status == self.FAILED:
            _require_text(error_message, "error_message")
        elif error_message is not None:
            _require_text(error_message, "error_message")

        timestamp = now or utc_now()
        document = {
            "monitoring_target_id": to_object_id(monitoring_target_id),
            "started_at": started_at,
            "finished_at": None,
            "status": status,
            "error_message": error_message,
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        result = self.collection.insert_one(document)
        inserted_id = getattr(result, "inserted_id", None)
        if inserted_id is not None:
            document["_id"] = inserted_id
        return serialize_document(document) or {}

    def finish(
        self,
        run_id: Any,
        *,
        status: str,
        finished_at: datetime,
        error_message: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        """Transition a run to a terminal state and return the updated record."""

        _require_timestamp(finished_at, "finished_at")
        _require_run_status(status)
        if status == self.RUNNING:
            raise ValueError("a RUNNING run cannot have finished_at")
        if status == self.FAILED:
            _require_text(error_message, "error_message")
        elif error_message is not None:
            raise ValueError("successful runs cannot have an error_message")

        query = {"_id": to_object_id(run_id)}
        values = {
            "status": status,
            "finished_at": finished_at,
            "error_message": error_message,
            "updated_at": utc_now(),
        }
        result = self.collection.update_one(query, {"$set": values})
        if not self._matched(result):
            return None
        return self.get(run_id)

    def get(self, run_id: Any) -> Optional[dict[str, Any]]:
        """Return one monitoring-run record by id."""

        return serialize_document(
            self.collection.find_one({"_id": to_object_id(run_id)})
        )

    def list_for_target(self, monitoring_target_id: Any) -> list[dict[str, Any]]:
        """Return a target's runs, newest first."""

        return self._find_sorted(
            {"monitoring_target_id": to_object_id(monitoring_target_id)},
            [("started_at", -1)],
        )


def _require_text(value: Any, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")


def _require_positive_interval(value: Any) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("check_interval_minutes must be a positive integer")


def _require_bool(value: Any, field: str) -> None:
    if not isinstance(value, bool):
        raise ValueError(f"{field} must be a boolean")


def _require_timestamp(value: Any, field: str) -> None:
    if not isinstance(value, datetime):
        raise ValueError(f"{field} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")


def _require_run_status(value: Any) -> None:
    if not isinstance(value, str) or value not in MonitoringRunRepository._STATUSES:
        raise ValueError(
            "status must be one of RUNNING, SUCCESS, or FAILED"
        )


def _validate_active_discovery_status(active: Any, discovery_status: Any) -> None:
    if active is True and discovery_status == "DISCARDED":
        raise ValueError("a DISCARDED candidate cannot be active")
