"""Local gzip storage for snapshot content.

Only this module touches the snapshot filesystem.  Callers exchange relative
paths such as ``snapshots/<target_id>/<timestamp>.txt.gz`` so the storage root
can be moved to another volume or object-storage adapter later.
"""

from __future__ import annotations

import gzip
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any


class SnapshotStorageError(RuntimeError):
    """Raised when snapshot content cannot be stored or read safely."""


class SnapshotStorage:
    """Write and read gzip-compressed snapshot content under a local root."""

    def __init__(self, root: str | Path | None = None) -> None:
        default_root = Path(__file__).resolve().parents[3] / "storage"
        self.root = Path(root or default_root).expanduser().resolve()
        self._write_lock = Lock()

    def write_snapshot(
        self,
        target_id: Any,
        content: str,
        captured_at: datetime,
    ) -> str:
        """Write UTF-8 content and return its portable relative storage path."""

        if not isinstance(content, str):
            raise TypeError("snapshot content must be a string")
        target_key = _safe_target_key(target_id)
        timestamp = _utc_timestamp(captured_at)
        content_bytes = content.encode("utf-8")
        relative_directory = Path("snapshots") / target_key

        with self._write_lock:
            directory = self.root / relative_directory
            directory.mkdir(parents=True, exist_ok=True)
            filename, final_path = self._next_filename(directory, timestamp)
            temporary_path: Path | None = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="wb",
                    prefix=f".{filename}.",
                    suffix=".tmp",
                    dir=directory,
                    delete=False,
                ) as temporary_file:
                    temporary_path = Path(temporary_file.name)
                    with gzip.GzipFile(
                        fileobj=temporary_file,
                        mode="wb",
                        mtime=0,
                    ) as archive:
                        archive.write(content_bytes)
                os.replace(temporary_path, final_path)
            except Exception as exc:
                if temporary_path is not None:
                    temporary_path.unlink(missing_ok=True)
                raise SnapshotStorageError(
                    f"could not write snapshot content for target {target_id!r}"
                ) from exc

        return (relative_directory / filename).as_posix()

    def read_snapshot_bytes(self, storage_path: str) -> bytes:
        """Decompress a stored snapshot and return its exact UTF-8 bytes."""

        path = self.absolute_path(storage_path)
        try:
            with gzip.open(path, mode="rb") as archive:
                return archive.read()
        except OSError as exc:
            raise SnapshotStorageError(
                f"could not read snapshot content at {storage_path!r}"
            ) from exc

    def absolute_path(self, storage_path: str) -> Path:
        """Resolve a relative metadata path beneath this storage root."""

        if not isinstance(storage_path, str) or not storage_path.strip():
            raise ValueError("storage_path must be a non-empty string")
        relative_path = Path(storage_path)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise ValueError("storage_path must remain relative to the storage root")
        resolved = (self.root / relative_path).resolve()
        try:
            resolved.relative_to(self.root)
        except ValueError as exc:
            raise ValueError("storage_path must remain beneath the storage root") from exc
        return resolved

    def delete_snapshot(self, storage_path: str) -> None:
        """Remove one stored file when metadata persistence cannot complete."""

        self.absolute_path(storage_path).unlink(missing_ok=True)

    @staticmethod
    def _next_filename(directory: Path, timestamp: str) -> tuple[str, Path]:
        # Keep a fixed-width sequence before the extension.  It makes the
        # filenames lexically sortable even when two calls share a timestamp
        # (for example, when a clock has only microsecond precision).
        suffix = 0
        while True:
            filename = f"{timestamp}-{suffix:06d}.txt.gz"
            candidate = directory / filename
            if not candidate.exists():
                return filename, candidate
            suffix += 1


def _safe_target_key(target_id: Any) -> str:
    value = str(target_id)
    if (
        not value
        or value in {".", ".."}
        or "/" in value
        or "\\" in value
    ):
        raise ValueError("target_id cannot be used as a snapshot path component")
    return value


def _utc_timestamp(value: datetime) -> str:
    if not isinstance(value, datetime):
        raise TypeError("captured_at must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("captured_at must be timezone-aware")
    return value.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
