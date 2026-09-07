"""Competitor business operations for the Flask API."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from backend.flask.errors import NotFoundError, RequestValidationError

from .repository import CompetitorRepository


class CompetitorService:
    """Apply current-user scoping and business validation to competitor CRUD."""

    def __init__(self, repository: CompetitorRepository, *, user_id: str) -> None:
        if not isinstance(user_id, str) or not user_id.strip():
            raise ValueError("user_id must be a non-empty string")
        self.repository = repository
        self.user_id = user_id

    def list_competitors(self, *, active: Optional[bool] = None) -> list[dict[str, Any]]:
        return self.repository.list_for_user(self.user_id, active=active)

    def get_competitor(self, competitor_id: Any) -> dict[str, Any]:
        competitor = self.repository.get(competitor_id, user_id=self.user_id)
        if competitor is None:
            raise NotFoundError(f"competitor {competitor_id!r} was not found")
        return competitor

    def create_competitor(
        self,
        *,
        name: str,
        website_url: str,
        active: bool = True,
    ) -> dict[str, Any]:
        if not isinstance(name, str) or not name.strip():
            raise RequestValidationError("name must be a non-empty string")
        if not isinstance(website_url, str) or not website_url.strip():
            raise RequestValidationError("website_url must be a non-empty string")
        if not isinstance(active, bool):
            raise RequestValidationError("active must be a boolean")
        return self.repository.create(
            user_id=self.user_id,
            name=name.strip(),
            website_url=website_url.strip(),
            active=active,
        )

    def update_competitor(
        self,
        competitor_id: Any,
        updates: Mapping[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(updates, Mapping) or not updates:
            raise RequestValidationError("at least one competitor field is required")
        updated = self.repository.update(
            competitor_id,
            updates,
            user_id=self.user_id,
        )
        if updated is None:
            raise NotFoundError(f"competitor {competitor_id!r} was not found")
        return updated

    def delete_competitor(self, competitor_id: Any) -> None:
        if not self.repository.delete(competitor_id, user_id=self.user_id):
            raise NotFoundError(f"competitor {competitor_id!r} was not found")
