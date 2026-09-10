"""MongoDB repository for change/event records."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable, Optional

from backend.flask.database.base_repository import (
    BaseMongoRepository,
    serialize_document,
    to_object_id,
    utc_now,
)


_UNSET = object()


class ChangeRepository(BaseMongoRepository):
    """Persistence operations for the ``changes`` collection."""

    collection_name = "changes"
    narrative_backfill_change_types = ("NEW_BLOG", "PAGE_UPDATE")
    detected_url_backfill_change_types = (
        "NEW_BLOG",
        "PAGE_UPDATE",
        "NEW_PRODUCT",
        "PRICE_CHANGE",
        "PRODUCT_REMOVED",
    )

    def ensure_indexes(self) -> None:
        """Create the target-scoped history index used by change readers."""

        self.collection.create_index(
            [("monitoring_target_id", 1), ("detected_at", -1)],
            name="ix_changes_target_detected_at",
        )

    def create(
        self,
        *,
        monitoring_target_id: Any,
        previous_snapshot_id: Any,
        current_snapshot_id: Any,
        detected_at: datetime,
        change_type: str,
        summary: str,
        status: str,
        now: Optional[Any] = None,
        narrative_summary: Optional[str] = None,
        detected_url: Optional[str] = None,
    ) -> dict[str, Any]:
        """Insert a change record and return its serialized representation."""

        _require_timestamp(detected_at)
        _require_text(change_type, "change_type")
        _require_text(summary, "summary")
        if narrative_summary is not None:
            _require_text(narrative_summary, "narrative_summary")
        if detected_url is not None:
            _require_text(detected_url, "detected_url")
        _require_text(status, "status")
        timestamp = now or utc_now()
        document = {
            "monitoring_target_id": to_object_id(monitoring_target_id),
            "previous_snapshot_id": to_object_id(previous_snapshot_id),
            "current_snapshot_id": to_object_id(current_snapshot_id),
            "detected_at": detected_at,
            "change_type": change_type,
            "summary": summary,
            "narrative_summary": narrative_summary,
            "detected_url": detected_url,
            "status": status,
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        result = self.collection.insert_one(document)
        inserted_id = getattr(result, "inserted_id", None)
        if inserted_id is not None:
            document["_id"] = inserted_id
        return serialize_document(document) or {}

    def get(self, change_id: Any) -> Optional[dict[str, Any]]:
        """Return one change record by id."""

        return serialize_document(
            self.collection.find_one({"_id": to_object_id(change_id)})
        )

    def delete_by_id(self, change_id: Any) -> bool:
        """Delete exactly one change record by id and report whether it existed."""

        result = self.collection.delete_one({"_id": to_object_id(change_id)})
        return self._deleted(result)

    def list_for_target(self, monitoring_target_id: Any) -> list[dict[str, Any]]:
        """Return change history for one target, newest first."""

        return self._find_sorted(
            {"monitoring_target_id": to_object_id(monitoring_target_id)},
            [("detected_at", -1)],
        )

    def list(
        self,
        *,
        monitoring_target_ids: Optional[Iterable[Any]] = None,
        since: Optional[datetime] = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Return a bounded newest-first change feed through the repository."""

        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError("limit must be an integer between 1 and 100")
        if since is not None:
            _require_timestamp(since, "since")

        query: dict[str, Any] = {}
        if monitoring_target_ids is not None:
            target_ids = [to_object_id(value) for value in monitoring_target_ids]
            if not target_ids:
                return []
            query["monitoring_target_id"] = {"$in": target_ids}
        if since is not None:
            query["detected_at"] = {"$gte": since}

        cursor = self.collection.find(query)
        if hasattr(cursor, "sort"):
            cursor = cursor.sort([("detected_at", -1)])
        if hasattr(cursor, "limit"):
            cursor = cursor.limit(limit)
        return [serialize_document(document) for document in cursor]

    def list_needing_narrative_summary(
        self,
        *,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return eligible changes whose narrative field is missing or null."""

        if limit is not None and (
            isinstance(limit, bool) or not isinstance(limit, int) or limit < 1
        ):
            raise ValueError("limit must be a positive integer")
        query = {
            "change_type": {"$in": list(self.narrative_backfill_change_types)},
            "$or": [
                {"narrative_summary": {"$exists": False}},
                {"narrative_summary": None},
                {"narrative_summary": ""},
            ],
        }
        cursor = self.collection.find(query)
        if hasattr(cursor, "sort"):
            cursor = cursor.sort([("detected_at", 1)])
        if limit is not None and hasattr(cursor, "limit"):
            cursor = cursor.limit(limit)
        return [serialize_document(document) for document in cursor]

    def update_narrative_summary(
        self,
        change_id: Any,
        narrative_summary: str,
        *,
        now: Optional[Any] = None,
    ) -> Optional[dict[str, Any]]:
        """Set one eligible change's narrative summary exactly once."""

        _require_text(narrative_summary, "narrative_summary")
        result = self.collection.update_one(
            {
                "_id": to_object_id(change_id),
                "change_type": {"$in": list(self.narrative_backfill_change_types)},
                "$or": [
                    {"narrative_summary": {"$exists": False}},
                    {"narrative_summary": None},
                    {"narrative_summary": ""},
                ],
            },
            {
                "$set": {
                    "narrative_summary": narrative_summary.strip(),
                    "updated_at": now or utc_now(),
                }
            },
        )
        if not self._matched(result):
            return None
        return self.get(change_id)

    def list_needing_detected_url(
        self,
        *,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return all change types eligible for detected-URL backfill."""

        if limit is not None and (
            isinstance(limit, bool) or not isinstance(limit, int) or limit < 1
        ):
            raise ValueError("limit must be a positive integer")
        query = {
            "change_type": {"$in": list(self.detected_url_backfill_change_types)},
            "$or": [
                {"detected_url": {"$exists": False}},
                {"detected_url": None},
                {"detected_url": ""},
            ],
        }
        cursor = self.collection.find(query)
        if hasattr(cursor, "sort"):
            cursor = cursor.sort([("detected_at", 1)])
        if limit is not None and hasattr(cursor, "limit"):
            cursor = cursor.limit(limit)
        return [serialize_document(document) for document in cursor]

    def update_detected_url(
        self,
        change_id: Any,
        detected_url: str,
        *,
        now: Optional[Any] = None,
    ) -> Optional[dict[str, Any]]:
        """Populate a missing detected URL without changing other fields."""

        return self.update_enrichment(
            change_id,
            detected_url=detected_url,
            now=now,
        )

    def update_enrichment(
        self,
        change_id: Any,
        *,
        narrative_summary: Any = _UNSET,
        detected_url: Any = _UNSET,
        now: Optional[Any] = None,
    ) -> Optional[dict[str, Any]]:
        """Set one or both enrichment fields while preserving the rest."""

        values: dict[str, Any] = {}
        if narrative_summary is not _UNSET:
            if narrative_summary is not None:
                _require_text(narrative_summary, "narrative_summary")
            values["narrative_summary"] = (
                narrative_summary.strip() if isinstance(narrative_summary, str) else None
            )
        if detected_url is not _UNSET:
            if detected_url is not None:
                _require_text(detected_url, "detected_url")
            values["detected_url"] = (
                detected_url.strip() if isinstance(detected_url, str) else None
            )
        if not values:
            raise ValueError("at least one enrichment field is required")
        values["updated_at"] = now or utc_now()
        result = self.collection.update_one(
            {"_id": to_object_id(change_id)},
            {"$set": values},
        )
        if not self._matched(result):
            return None
        return self.get(change_id)


def _require_text(value: Any, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")


def _require_timestamp(value: Any, field: str = "detected_at") -> None:
    if not isinstance(value, datetime):
        raise ValueError(f"{field} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
