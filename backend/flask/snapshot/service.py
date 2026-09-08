"""Snapshot creation orchestration.

The service accepts fetched HTML, applies the Layer 2 canonical normalizer,
hashes that canonical representation, writes the exact normalized UTF-8 bytes
through :mod:`snapshot.storage`, and then persists matching MongoDB metadata
through :mod:`snapshot.repository`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from backend.flask.database.base_repository import utc_now
from backend.flask.website_monitoring.service import (
    HTTP_FETCH_METHOD,
    hash_content,
    normalize_content,
)

from .repository import SnapshotRepository
from .storage import SnapshotStorage


class SnapshotError(RuntimeError):
    """Raised when a snapshot cannot be created consistently."""

    status_code = 500
    code = "snapshot_error"


class SnapshotService:
    """Coordinate normalized content, local storage, and snapshot metadata."""

    def __init__(
        self,
        snapshot_repository: SnapshotRepository,
        storage: Optional[SnapshotStorage] = None,
    ) -> None:
        self.snapshot_repository = snapshot_repository
        self.storage = storage or SnapshotStorage()

    @classmethod
    def from_database(
        cls,
        database: Any,
        *,
        storage_root: str | None = None,
    ) -> "SnapshotService":
        """Build the service from a database handle and optional local root."""

        storage = SnapshotStorage(storage_root)
        return cls(SnapshotRepository.from_database(database), storage)

    def create_snapshot(
        self,
        target_id: Any,
        content: str,
        *,
        fetch_method: str = HTTP_FETCH_METHOD,
        http_status: int = 200,
        is_simulated: bool = False,
        captured_at: Optional[datetime] = None,
    ) -> dict[str, Any]:
        """Create one snapshot from fetched content on every successful check.

        ``content`` may be raw fetched HTML or content already normalized by
        the caller. Normalization is idempotent for the canonical form, so the
        service owns the invariant that the bytes stored, hashed, and compared
        are the normalized representation.
        """

        if not isinstance(content, str):
            raise TypeError("snapshot content must be a string")
        if not isinstance(fetch_method, str) or not fetch_method.strip():
            raise ValueError("fetch_method must be a non-empty string")
        if isinstance(http_status, bool) or not isinstance(http_status, int):
            raise ValueError("http_status must be an HTTP status code")
        timestamp = captured_at or utc_now()
        normalized_content = normalize_content(content)
        content_hash = hash_content(normalized_content)
        content_size = len(normalized_content.encode("utf-8"))

        storage_path = self.storage.write_snapshot(
            target_id,
            normalized_content,
            timestamp,
        )
        try:
            return self.snapshot_repository.create(
                monitoring_target_id=target_id,
                captured_at=timestamp,
                content_hash=content_hash,
                content_size=content_size,
                storage_path=storage_path,
                fetch_method=fetch_method,
                http_status=http_status,
                is_simulated=is_simulated,
            )
        except Exception as exc:
            self.storage.delete_snapshot(storage_path)
            raise SnapshotError(
                "snapshot metadata could not be persisted after content was stored"
            ) from exc


def create_snapshot(
    target_id: Any,
    content: str,
    *,
    snapshot_repository: SnapshotRepository,
    storage: Optional[SnapshotStorage] = None,
    fetch_method: str = HTTP_FETCH_METHOD,
    http_status: int = 200,
    is_simulated: bool = False,
    captured_at: Optional[datetime] = None,
) -> dict[str, Any]:
    """Functional entry point backed by injected repository and storage objects."""

    return SnapshotService(snapshot_repository, storage).create_snapshot(
        target_id,
        content,
        fetch_method=fetch_method,
        http_status=http_status,
        is_simulated=is_simulated,
        captured_at=captured_at,
    )
