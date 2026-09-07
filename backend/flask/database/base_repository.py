"""Small MongoDB repository primitives shared by backend modules.

This module deliberately imports neither Flask nor PyMongo at import time. The
application can therefore load repository classes in environments that only
provide a test double, while the connection module gives a clear error when a
real MongoDB client is requested without PyMongo installed.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Optional


class InvalidIdentifierError(ValueError):
    """Raised when a MongoDB document identifier cannot be used safely."""


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp for persisted metadata."""

    return datetime.now(timezone.utc)


def to_object_id(value: Any) -> Any:
    """Convert a string identifier to ``bson.ObjectId`` when available.

    Repository unit tests can use string identifiers without requiring PyMongo.
    In a real application, PyMongo's bundled ``bson`` package is available and
    identifiers are converted before querying ObjectId-backed ``_id`` fields.
    """

    if value is None:
        raise InvalidIdentifierError("document identifier cannot be null")

    try:
        from bson import ObjectId
    except ImportError:
        return value

    if isinstance(value, ObjectId):
        return value
    if isinstance(value, str) and ObjectId.is_valid(value):
        return ObjectId(value)
    raise InvalidIdentifierError(f"invalid MongoDB ObjectId: {value!r}")


_ID_FIELDS = {
    "_id",
    "user_id",
    "company_id",
    "competitor_id",
    "monitoring_target_id",
    "previous_snapshot_id",
    "current_snapshot_id",
}


def serialize_document(document: Optional[Mapping[str, Any]]) -> Optional[dict[str, Any]]:
    """Return an API-friendly copy of a MongoDB document.

    MongoDB keeps its primary key as ``_id``. The rest of the application uses
    the contract's ``id`` field, so all known identifier fields are converted
    to strings at the repository boundary.
    """

    if document is None:
        return None

    serialized = dict(document)
    if "_id" in serialized:
        serialized["id"] = str(serialized.pop("_id"))

    for field in _ID_FIELDS - {"_id"}:
        if field in serialized and serialized[field] is not None:
            serialized[field] = str(serialized[field])

    return serialized


class BaseMongoRepository:
    """Base class that owns a single MongoDB collection handle."""

    collection_name: str

    def __init__(self, collection: Any) -> None:
        self.collection = collection

    @classmethod
    def from_database(cls, database: Any) -> "BaseMongoRepository":
        """Construct a repository from a database-like object."""

        return cls(database[cls.collection_name])

    def _find_sorted(
        self,
        query: Mapping[str, Any],
        sort: Optional[Iterable[tuple[str, int]]] = None,
    ) -> list[dict[str, Any]]:
        cursor = self.collection.find(dict(query))
        if sort and hasattr(cursor, "sort"):
            cursor = cursor.sort(list(sort))
        return [serialize_document(document) for document in cursor]

    def count(self, query: Optional[Mapping[str, Any]] = None) -> int:
        """Count documents through the repository boundary."""

        return int(self.collection.count_documents(dict(query or {})))

    @staticmethod
    def _matched(result: Any) -> bool:
        """Read PyMongo's match count while remaining friendly to test doubles."""

        return getattr(result, "matched_count", 1) > 0

    @staticmethod
    def _deleted(result: Any) -> bool:
        """Read PyMongo's delete count while remaining friendly to test doubles."""

        return getattr(result, "deleted_count", 1) > 0
