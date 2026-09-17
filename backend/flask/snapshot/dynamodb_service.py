"""DynamoDB-backed snapshot storage for production.

Per ``docs/production-plan.md`` section 5.2, snapshot content itself (not
just metadata) lives directly in the DynamoDB item, replacing local
``.txt.gz`` files and the ``storage_path`` pointer entirely. This collapses
dev's two-step design (``snapshot/storage.py`` for content,
``snapshot/repository.py`` for metadata) into one class, since there is no
longer a separate content store to coordinate with.

Implements the same ``create_snapshot``/``list_for_target`` shapes as
``snapshot.service.SnapshotService`` / ``snapshot.repository.SnapshotRepository``
(the ``SnapshotCreator``/``SnapshotHistoryReader`` protocols in
``website_monitoring/service.py``), so ``MonitoringRunService`` needs no
changes to use this instead.
"""

from __future__ import annotations

import gzip
import io
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Optional

from backend.flask.database.base_repository import utc_now
from backend.flask.database.dynamodb_connection import (
    DynamoDBSettings,
    create_dynamodb_resource,
)
from backend.flask.website_monitoring.service import (
    HTTP_FETCH_METHOD,
    hash_content,
    normalize_content,
)


SNAPSHOT_TTL = timedelta(days=30)


class SnapshotError(RuntimeError):
    """Raised when a snapshot cannot be created consistently."""

    status_code = 500
    code = "snapshot_error"


class DynamoDBSnapshotService:
    """Coordinate normalization, hashing, and DynamoDB persistence."""

    def __init__(self, table: Any) -> None:
        self.table = table

    @classmethod
    def from_settings(
        cls,
        settings: Optional[DynamoDBSettings] = None,
    ) -> "DynamoDBSnapshotService":
        resolved = settings or DynamoDBSettings.from_env()
        resource = create_dynamodb_resource(resolved)
        return cls(resource.Table(resolved.snapshots_table))

    def create_snapshot(
        self,
        target_id: Any,
        content: str,
        *,
        fetch_method: str = HTTP_FETCH_METHOD,
        http_status: int = 200,
        captured_at: Optional[datetime] = None,
    ) -> dict[str, Any]:
        if not isinstance(content, str):
            raise TypeError("snapshot content must be a string")
        if not isinstance(fetch_method, str) or not fetch_method.strip():
            raise ValueError("fetch_method must be a non-empty string")
        if isinstance(http_status, bool) or not isinstance(http_status, int):
            raise ValueError("http_status must be an HTTP status code")
        timestamp = captured_at or utc_now()
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("captured_at must be timezone-aware")
        normalized_content = normalize_content(content)
        content_hash = hash_content(normalized_content)
        content_size = len(normalized_content.encode("utf-8"))
        compressed = _gzip_compress(normalized_content)
        captured_at_iso = timestamp.astimezone(timezone.utc).isoformat()
        expires_at = int((timestamp + SNAPSHOT_TTL).timestamp())

        item = {
            "monitoring_target_id": str(target_id),
            "captured_at": captured_at_iso,
            "content_hash": content_hash,
            "content_size": content_size,
            "content": compressed,
            "fetch_method": fetch_method,
            "http_status": http_status,
            "created_at": captured_at_iso,
            "expires_at": expires_at,
        }
        try:
            self.table.put_item(Item=item)
        except Exception as exc:
            raise SnapshotError(
                "snapshot could not be persisted to DynamoDB"
            ) from exc
        return _to_dict(item)

    def list_for_target(
        self,
        monitoring_target_id: Any,
        *,
        include_simulated: bool = True,
    ) -> list[dict[str, Any]]:
        """Newest-first snapshot history for one target.

        ``include_simulated`` is accepted for interface parity only:
        production never creates simulated snapshots, so every stored row is
        already real regardless of this flag.
        """

        from boto3.dynamodb.conditions import Key

        items: list[dict[str, Any]] = []
        query_kwargs: dict[str, Any] = {
            "KeyConditionExpression": Key("monitoring_target_id").eq(str(monitoring_target_id)),
            "ScanIndexForward": False,
        }
        while True:
            response = self.table.query(**query_kwargs)
            items.extend(response.get("Items", []))
            if "LastEvaluatedKey" not in response:
                break
            query_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
        return [_to_dict(item) for item in items]

    def get(
        self,
        monitoring_target_id: Any,
        captured_at: str,
    ) -> Optional[dict[str, Any]]:
        """Fetch one snapshot by its real DynamoDB key."""

        response = self.table.get_item(
            Key={"monitoring_target_id": str(monitoring_target_id), "captured_at": captured_at}
        )
        item = response.get("Item")
        return _to_dict(item) if item is not None else None


def _gzip_compress(content: str) -> bytes:
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode="wb", mtime=0) as archive:
        archive.write(content.encode("utf-8"))
    return buffer.getvalue()


def _gzip_decompress(content: bytes) -> str:
    with gzip.GzipFile(fileobj=io.BytesIO(bytes(content)), mode="rb") as archive:
        return archive.read().decode("utf-8")


def _to_dict(item: Mapping[str, Any]) -> dict[str, Any]:
    from decimal import Decimal

    result = dict(item)
    raw_content = result.pop("content", None)
    if raw_content is not None:
        result["normalized_content"] = _gzip_decompress(raw_content)
    result.pop("expires_at", None)
    for field in ("content_size", "http_status"):
        if isinstance(result.get(field), Decimal):
            result[field] = int(result[field])
    return result


__all__ = ["DynamoDBSnapshotService", "SnapshotError", "SNAPSHOT_TTL"]
