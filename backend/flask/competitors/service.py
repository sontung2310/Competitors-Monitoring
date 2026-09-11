"""Competitor business operations for the Flask API."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from backend.flask.errors import NotFoundError, RequestValidationError

from .repository import CompetitorRepository


class CompetitorService:
    """Apply current-user scoping and business validation to competitor CRUD."""

    def __init__(self, repository: CompetitorRepository, *, user_id: str | None = None) -> None:
        if user_id is not None and (not isinstance(user_id, str) or not user_id.strip()):
            raise ValueError("user_id must be a non-empty string")
        self.repository = repository
        self.user_id = user_id

    def list_competitors(
        self,
        *,
        active: Optional[bool] = None,
        company_id: Any = None,
    ) -> list[dict[str, Any]]:
        if company_id is not None:
            return self.repository.list_for_company(company_id, active=active)
        if self.user_id is not None:
            return self.repository.list_for_user(self.user_id, active=active)
        return self.repository.list_all(active=active)

    def get_competitor(self, competitor_id: Any, *, company_id: Any = None) -> dict[str, Any]:
        competitor = self.repository.get(
            competitor_id,
            user_id=self.user_id if company_id is None else None,
            company_id=company_id,
        )
        if competitor is None:
            raise NotFoundError(f"competitor {competitor_id!r} was not found")
        return competitor

    def create_competitor(
        self,
        *,
        name: str,
        website_url: str,
        active: bool = True,
        company_id: Any = None,
    ) -> dict[str, Any]:
        if not isinstance(name, str) or not name.strip():
            raise RequestValidationError("name must be a non-empty string")
        if not isinstance(website_url, str) or not website_url.strip():
            raise RequestValidationError("website_url must be a non-empty string")
        if not isinstance(active, bool):
            raise RequestValidationError("active must be a boolean")
        return self.repository.create(
            user_id=self.user_id if company_id is None else None,
            company_id=company_id,
            name=name.strip(),
            website_url=website_url.strip(),
            active=active,
        )

    def find_or_create_competitor(
        self,
        *,
        company_id: Any,
        name: str,
        website_url: str,
        active: bool = True,
    ) -> dict[str, Any]:
        """Resolve one tenant-scoped competitor without duplicate inserts."""

        if company_id is None:
            raise RequestValidationError("company_id is required")
        if not isinstance(name, str) or not name.strip():
            raise RequestValidationError("name must be a non-empty string")
        if not isinstance(website_url, str) or not website_url.strip():
            raise RequestValidationError("website_url must be a non-empty string")
        if not isinstance(active, bool):
            raise RequestValidationError("active must be a boolean")

        normalized_name = name.strip()
        normalized_url = website_url.strip()
        existing = self.repository.find_by_company_and_website_url(
            company_id,
            normalized_url,
        )
        if existing is not None:
            return existing

        try:
            return self.repository.create(
                company_id=company_id,
                name=normalized_name,
                website_url=normalized_url,
                active=active,
            )
        except Exception as exc:  # noqa: BLE001 - recover only a unique-key race
            if not _is_duplicate_key_error(exc):
                raise
            existing = self.repository.find_by_company_and_website_url(
                company_id,
                normalized_url,
            )
            if existing is None:
                raise
            return existing

    def update_competitor(
        self,
        competitor_id: Any,
        updates: Mapping[str, Any],
        *,
        company_id: Any = None,
    ) -> dict[str, Any]:
        if not isinstance(updates, Mapping) or not updates:
            raise RequestValidationError("at least one competitor field is required")
        updated = self.repository.update(
            competitor_id,
            updates,
            user_id=self.user_id if company_id is None else None,
            company_id=company_id,
        )
        if updated is None:
            raise NotFoundError(f"competitor {competitor_id!r} was not found")
        return updated

    def delete_competitor(self, competitor_id: Any, *, company_id: Any = None) -> None:
        if not self.repository.delete(
            competitor_id,
            user_id=self.user_id if company_id is None else None,
            company_id=company_id,
        ):
            raise NotFoundError(f"competitor {competitor_id!r} was not found")


def _is_duplicate_key_error(error: Exception) -> bool:
    try:
        from pymongo.errors import DuplicateKeyError
    except ImportError:
        return False
    return isinstance(error, DuplicateKeyError)
