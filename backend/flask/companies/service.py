"""Company identity business operations."""

from __future__ import annotations

from typing import Any

from .repository import CompanyRepository


DEMO_COMPANIES = (
    {"name": "Marketing Eye", "website_url": "marketingeye.com.au"},
    {"name": "The Athletes Foot", "website_url": "theathletesfoot.com.au"},
)


class CompanyService:
    """Expose the company dropdown and idempotent PoC seed operation."""

    def __init__(self, repository: CompanyRepository) -> None:
        self.repository = repository

    def list_companies(self) -> list[dict[str, Any]]:
        return self.repository.list()

    def get_company(self, company_id: Any) -> dict[str, Any] | None:
        return self.repository.get(company_id)

    def ensure_demo_companies(self) -> list[dict[str, Any]]:
        """Create the two demo identities exactly once and return them."""

        seeded: list[dict[str, Any]] = []
        for definition in DEMO_COMPANIES:
            company = self.repository.find_by_website_url(definition["website_url"])
            if company is None:
                company = self.repository.create(**definition)
            seeded.append(company)
        return seeded


__all__ = ["DEMO_COMPANIES", "CompanyService"]
