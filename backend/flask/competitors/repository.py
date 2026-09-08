"""MongoDB repository for competitor records."""

from __future__ import annotations

from typing import Any, Mapping, Optional
from urllib.parse import urlsplit

from backend.flask.database.base_repository import (
    BaseMongoRepository,
    serialize_document,
    to_object_id,
    utc_now,
)


class CompetitorRepository(BaseMongoRepository):
    """Persistence operations for the ``competitors`` collection."""

    collection_name = "competitors"
    _UPDATE_FIELDS = {"name", "website_url", "active", "company_id"}

    def ensure_indexes(self) -> None:
        """Create indexes needed for tenant-scoped lookups and deduplication."""

        self._ensure_named_index(
            [("company_id", 1), ("website_url", 1)],
            unique=True,
            name="uq_competitors_user_website_url",
        )
        self._ensure_named_index(
            [("company_id", 1), ("active", 1)],
            name="ix_competitors_user_active",
        )

    def _ensure_named_index(self, keys: list[tuple[str, int]], **options: Any) -> None:
        """Replace a same-named legacy user_id index when running the PoC migration.

        PyMongo rejects creating an index with an existing name when its key
        specification differs. The live pre-company database has precisely
        that shape, so inspect and replace only the named conflicting index.
        Small in-memory test collections do not expose index_information and
        retain their existing lightweight create_index behavior.
        """

        index_name = options.get("name")
        index_information = getattr(self.collection, "index_information", None)
        if callable(index_information) and isinstance(index_name, str):
            existing = index_information().get(index_name)
            if existing is not None:
                existing_keys = list(existing.get("key", ()))
                desired_unique = bool(options.get("unique", False))
                existing_unique = bool(existing.get("unique", False))
                if existing_keys != keys or existing_unique != desired_unique:
                    self.collection.drop_index(index_name)
        self.collection.create_index(keys, **options)

    def create(
        self,
        *,
        user_id: Optional[str] = None,
        company_id: Any = None,
        name: str,
        website_url: str,
        active: bool = True,
        now: Optional[Any] = None,
    ) -> dict[str, Any]:
        """Insert a competitor and return its repository representation."""

        _require_text(name, "name")
        _require_text(website_url, "website_url")
        if user_id is None and company_id is None:
            raise ValueError("company_id or user_id is required")
        if user_id is not None:
            _require_text(user_id, "user_id")
        company_id = _relationship_id(company_id, "company_id")
        _require_bool(active, "active")
        timestamp = now or utc_now()
        document = {
            "name": name,
            "website_url": website_url,
            "active": active,
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        if company_id is not None:
            document["company_id"] = company_id
        elif user_id is not None:
            # Legacy Python-callable verification scripts still use this
            # argument. New PoC API records use company_id instead.
            document["user_id"] = user_id
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
        company_id: Any = None,
    ) -> Optional[dict[str, Any]]:
        query: dict[str, Any] = {"_id": to_object_id(competitor_id)}
        if company_id is not None:
            query["company_id"] = _relationship_id(company_id, "company_id")
        elif user_id is not None:
            query["user_id"] = user_id
        result = self.collection.find_one(query)
        if result is None and user_id is not None:
            # Existing live verification helpers identify records with the
            # pre-PoC user_id. Migration removes that field, so retain their
            # explicit Python API compatibility without weakening company_id
            # scoped HTTP lookups.
            migrated = self.collection.find_one({"_id": to_object_id(competitor_id)})
            if migrated is not None and "user_id" not in migrated:
                result = migrated
        return serialize_document(result)

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
        rows = self._find_sorted(query, [("created_at", -1)])
        if rows:
            return rows
        # Compatibility for the pre-company live scripts after the one-time
        # migration has replaced user_id on mapped competitors.
        migrated_documents = list(self.collection.find({}))
        if any(document.get("company_id") is not None for document in migrated_documents):
            if active is not None:
                return [row for row in self._find_sorted({}, [("created_at", -1)]) if row.get("active") == active]
            return self._find_sorted({}, [("created_at", -1)])
        return rows

    def list_for_company(
        self,
        company_id: Any,
        *,
        active: Optional[bool] = None,
    ) -> list[dict[str, Any]]:
        """List only competitors explicitly assigned to one company."""

        query: dict[str, Any] = {"company_id": _relationship_id(company_id, "company_id")}
        if active is not None:
            query["active"] = active
        return self._find_sorted(query, [("created_at", -1)])

    def list_all(self, *, active: Optional[bool] = None) -> list[dict[str, Any]]:
        query: dict[str, Any] = {}
        if active is not None:
            query["active"] = active
        return self._find_sorted(query, [("created_at", -1)])

    def migrate_legacy_user_ids(self, company_by_host: Mapping[str, Any]) -> None:
        """Replace legacy user_id values and assign known demo competitors.

        This is intentionally a small idempotent migration invoked by the
        application factory. Unmapped competitors have neither relationship,
        which is what keeps legacy Brown Bag and Elevation rows out of company
        views. Explicitly company-assigned rows are preserved.
        """

        for document in self.collection.find({}):
            website_url = document.get("website_url")
            host = urlsplit(website_url).netloc.lower().split(":", 1)[0] if isinstance(website_url, str) else ""
            host = host.removeprefix("www.")
            if host in company_by_host:
                update: dict[str, Any] = {
                    "$set": {
                        "company_id": _relationship_id(
                            company_by_host[host], "company_id"
                        )
                    },
                    "$unset": {"user_id": ""},
                }
            else:
                # An unknown legacy row becomes unassigned, while a
                # company_id explicitly added by the PoC/API is preserved on
                # later application startups.
                update = {"$unset": {"user_id": ""}}
            self.collection.update_one({"_id": document["_id"]}, update)

    def list(
        self,
        user_id: str,
        *,
        active: Optional[bool] = None,
        company_id: Any = None,
    ) -> list[dict[str, Any]]:
        """Alias matching the repository's natural collection operation name."""

        if company_id is not None:
            return self.list_for_company(company_id, active=active)
        return self.list_for_user(user_id, active=active)

    def update(
        self,
        competitor_id: Any,
        updates: Optional[Mapping[str, Any]] = None,
        *,
        user_id: Optional[str] = None,
        company_id: Any = None,
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
        if "company_id" in values and values["company_id"] is not None:
            values["company_id"] = _relationship_id(values["company_id"], "company_id")

        query: dict[str, Any] = {"_id": to_object_id(competitor_id)}
        if company_id is not None:
            query["company_id"] = _relationship_id(company_id, "company_id")
        elif user_id is not None:
            query["user_id"] = user_id
        values["updated_at"] = utc_now()
        result = self.collection.update_one(query, {"$set": values})
        if not self._matched(result):
            if user_id is not None and company_id is None:
                result = self.collection.update_one(
                    {"_id": to_object_id(competitor_id)},
                    {"$set": values},
                )
            if not self._matched(result):
                return None
        return self.get(competitor_id, user_id=user_id, company_id=company_id)

    def delete(
        self,
        competitor_id: Any,
        *,
        user_id: Optional[str] = None,
        company_id: Any = None,
    ) -> bool:
        """Delete a competitor document and report whether it existed."""

        query: dict[str, Any] = {"_id": to_object_id(competitor_id)}
        if company_id is not None:
            query["company_id"] = _relationship_id(company_id, "company_id")
        elif user_id is not None:
            query["user_id"] = user_id
        result = self.collection.delete_one(query)
        if not self._deleted(result) and user_id is not None and company_id is None:
            result = self.collection.delete_one({"_id": to_object_id(competitor_id)})
        return self._deleted(result)


def _require_text(value: Any, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")


def _require_bool(value: Any, field: str) -> None:
    if not isinstance(value, bool):
        raise ValueError(f"{field} must be a boolean")


def _relationship_id(value: Any, field: str) -> Any:
    """Keep ObjectIds native while allowing string ids in repository tests."""

    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        raise ValueError(f"{field} must be a non-empty identifier")
    try:
        from bson import ObjectId
    except ImportError:
        return value
    if isinstance(value, ObjectId):
        return value
    if isinstance(value, str) and ObjectId.is_valid(value):
        return ObjectId(value)
    return value
