"""MongoDB repository for competitor records."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from backend.flask.database.base_repository import (
    BaseMongoRepository,
    serialize_document,
    to_object_id,
    utc_now,
)


class CompetitorRepository(BaseMongoRepository):
    """Persistence operations for the ``competitors`` collection."""

    collection_name = "competitors"
    _UPDATE_FIELDS = {"name", "website_url", "active"}

    def ensure_indexes(self) -> None:
        """Create indexes needed for tenant-scoped lookups and deduplication."""

        self.collection.create_index(
            [("user_id", 1), ("website_url", 1)],
            unique=True,
            name="uq_competitors_user_website_url",
        )
        self.collection.create_index(
            [("user_id", 1), ("active", 1)],
            name="ix_competitors_user_active",
        )

    def create(
        self,
        *,
        user_id: str,
        name: str,
        website_url: str,
        active: bool = True,
        now: Optional[Any] = None,
    ) -> dict[str, Any]:
        """Insert a competitor and return its repository representation."""

        _require_text(name, "name")
        _require_text(website_url, "website_url")
        _require_text(user_id, "user_id")
        _require_bool(active, "active")
        timestamp = now or utc_now()
        document = {
            "user_id": user_id,
            "name": name,
            "website_url": website_url,
            "active": active,
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
        competitor_id: Any,
        *,
        user_id: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        query: dict[str, Any] = {"_id": to_object_id(competitor_id)}
        if user_id is not None:
            query["user_id"] = user_id
        return serialize_document(self.collection.find_one(query))

    def list_for_user(
        self,
        user_id: str,
        *,
        active: Optional[bool] = None,
    ) -> list[dict[str, Any]]:
        _require_text(user_id, "user_id")
        query: dict[str, Any] = {"user_id": user_id}
        if active is not None:
            query["active"] = active
        return self._find_sorted(query, [("created_at", -1)])

    def list(
        self,
        user_id: str,
        *,
        active: Optional[bool] = None,
    ) -> list[dict[str, Any]]:
        """Alias matching the repository's natural collection operation name."""

        return self.list_for_user(user_id, active=active)

    def update(
        self,
        competitor_id: Any,
        updates: Optional[Mapping[str, Any]] = None,
        *,
        user_id: Optional[str] = None,
        **fields: Any,
    ) -> Optional[dict[str, Any]]:
        """Update allowed mutable fields and return the updated competitor."""

        values = dict(updates or {})
        values.update(fields)
        if not values:
            raise ValueError("at least one competitor field is required")
        unknown = set(values) - self._UPDATE_FIELDS
        if unknown:
            raise ValueError(f"unsupported competitor fields: {sorted(unknown)}")
        if "name" in values:
            _require_text(values["name"], "name")
        if "website_url" in values:
            _require_text(values["website_url"], "website_url")
        if "active" in values and not isinstance(values["active"], bool):
            raise ValueError("active must be a boolean")

        query: dict[str, Any] = {"_id": to_object_id(competitor_id)}
        if user_id is not None:
            query["user_id"] = user_id
        values["updated_at"] = utc_now()
        result = self.collection.update_one(query, {"$set": values})
        if not self._matched(result):
            return None
        return self.get(competitor_id, user_id=user_id)

    def delete(
        self,
        competitor_id: Any,
        *,
        user_id: Optional[str] = None,
    ) -> bool:
        """Delete a competitor document and report whether it existed."""

        query: dict[str, Any] = {"_id": to_object_id(competitor_id)}
        if user_id is not None:
            query["user_id"] = user_id
        return self._deleted(self.collection.delete_one(query))


def _require_text(value: Any, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")


def _require_bool(value: Any, field: str) -> None:
    if not isinstance(value, bool):
        raise ValueError(f"{field} must be a boolean")
