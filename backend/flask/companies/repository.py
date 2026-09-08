"""MongoDB repository for lightweight company identity records."""

from __future__ import annotations

from typing import Any, Optional

from backend.flask.database.base_repository import (
    BaseMongoRepository,
    serialize_document,
    utc_now,
)


class CompanyRepository(BaseMongoRepository):
    """Persistence operations for the ``companies`` collection."""

    collection_name = "companies"

    def ensure_indexes(self) -> None:
        """Create the idempotent company seed lookup index."""

        self.collection.create_index(
            [("website_url", 1)],
            unique=True,
            name="uq_companies_website_url",
        )

    def create(
        self,
        *,
        name: str,
        website_url: str,
        now: Optional[Any] = None,
    ) -> dict[str, Any]:
        _require_text(name, "name")
        _require_text(website_url, "website_url")
        timestamp = now or utc_now()
        document = {
            "name": name.strip(),
            "website_url": website_url.strip(),
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        result = self.collection.insert_one(document)
        inserted_id = getattr(result, "inserted_id", None)
        if inserted_id is not None:
            document["_id"] = inserted_id
        return serialize_document(document) or {}

    def get(self, company_id: Any) -> Optional[dict[str, Any]]:
        """Return one company by its serialized or native identifier."""

        from backend.flask.database.base_repository import to_object_id

        return serialize_document(
            self.collection.find_one({"_id": to_object_id(company_id)})
        )

    def find_by_website_url(self, website_url: str) -> Optional[dict[str, Any]]:
        _require_text(website_url, "website_url")
        return serialize_document(
            self.collection.find_one({"website_url": website_url.strip()})
        )

    def list(self) -> list[dict[str, Any]]:
        """Return all companies in stable creation order."""

        return self._find_sorted({}, [("created_at", 1)])


def _require_text(value: Any, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
