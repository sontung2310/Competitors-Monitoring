"""MongoDB repository for change/event records."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from backend.flask.database.base_repository import (
    BaseMongoRepository,
    serialize_document,
    to_object_id,
    utc_now,
)


class ChangeRepository(BaseMongoRepository):
    """Persistence operations for the ``changes`` collection."""

    collection_name = "changes"

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
    ) -> dict[str, Any]:
        """Insert a change record and return its serialized representation."""

        _require_timestamp(detected_at)
        _require_text(change_type, "change_type")
        _require_text(summary, "summary")
        _require_text(status, "status")

        timestamp = now or utc_now()
        document = {
            "monitoring_target_id": to_object_id(monitoring_target_id),
            "previous_snapshot_id": to_object_id(previous_snapshot_id),
            "current_snapshot_id": to_object_id(current_snapshot_id),
            "detected_at": detected_at,
            "change_type": change_type,
            "summary": summary,
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

    def list_for_target(self, monitoring_target_id: Any) -> list[dict[str, Any]]:
        """Return change history for one target, newest first."""

        return self._find_sorted(
            {"monitoring_target_id": to_object_id(monitoring_target_id)},
            [("detected_at", -1)],
        )


def _require_text(value: Any, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")


def _require_timestamp(value: Any) -> None:
    if not isinstance(value, datetime):
        raise ValueError("detected_at must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("detected_at must be timezone-aware")
