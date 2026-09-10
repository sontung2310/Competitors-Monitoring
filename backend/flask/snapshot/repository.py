"""MongoDB repository for snapshot metadata."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from backend.flask.database.base_repository import (
    BaseMongoRepository,
    serialize_document,
    to_object_id,
    utc_now,
)


class SnapshotRepository(BaseMongoRepository):
    """Persistence operations for the ``snapshots`` collection."""

    collection_name = "snapshots"

    def ensure_indexes(self) -> None:
        """Create the target-history index used to retrieve snapshot history."""

        self.collection.create_index(
            [("monitoring_target_id", 1), ("captured_at", -1)],
            name="ix_snapshots_target_captured_at",
        )

    def create(
        self,
        *,
        monitoring_target_id: Any,
        captured_at: datetime,
        content_hash: str,
        content_size: int,
        storage_path: str,
        fetch_method: str,
        http_status: int,
        now: Optional[Any] = None,
    ) -> dict[str, Any]:
        """Insert snapshot metadata and return its serialized representation."""

        _require_timestamp(captured_at)
        _require_text(content_hash, "content_hash")
        _require_non_negative_integer(content_size, "content_size")
        _require_relative_storage_path(storage_path)
        _require_text(fetch_method, "fetch_method")
        _require_http_status(http_status)
        timestamp = now or utc_now()
        document = {
            "monitoring_target_id": to_object_id(monitoring_target_id),
            "captured_at": captured_at,
            "content_hash": content_hash,
            "content_size": content_size,
            "storage_path": storage_path,
            "fetch_method": fetch_method,
            "http_status": http_status,
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        result = self.collection.insert_one(document)
        inserted_id = getattr(result, "inserted_id", None)
        if inserted_id is not None:
            document["_id"] = inserted_id
        return serialize_document(document) or {}

    def get(self, snapshot_id: Any) -> Optional[dict[str, Any]]:
        """Return one snapshot metadata document by id."""

        return serialize_document(
            self.collection.find_one({"_id": to_object_id(snapshot_id)})
        )

    def list_for_target(
        self,
        monitoring_target_id: Any,
        *,
        include_simulated: bool = True,
    ) -> list[dict[str, Any]]:
        """Return a target's snapshot history, newest first.

        ``include_simulated=False`` is the explicit real-history query used by
        the monitoring engine. Legacy rows without the flag are real rows.
        """

        query: dict[str, Any] = {
            "monitoring_target_id": to_object_id(monitoring_target_id),
        }
        if not isinstance(include_simulated, bool):
            raise ValueError("include_simulated must be a boolean")
        if not include_simulated:
            query["is_simulated"] = {"$ne": True}
        return self._find_sorted(
            query,
            [("captured_at", -1)],
        )


def _require_text(value: Any, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")


def _require_timestamp(value: Any) -> None:
    if not isinstance(value, datetime):
        raise ValueError("captured_at must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("captured_at must be timezone-aware")


def _require_non_negative_integer(value: Any, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")


def _require_http_status(value: Any) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not 100 <= value <= 599:
        raise ValueError("http_status must be an HTTP status code")


def _require_relative_storage_path(value: Any) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("storage_path must be a non-empty relative path")
    from pathlib import PurePosixPath

    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("storage_path must be relative")
