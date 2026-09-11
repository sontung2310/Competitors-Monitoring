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

    def find_or_create_by_domain(self, company_domain_id: str) -> dict[str, Any]:
        """Resolve a tenant domain, creating its identity exactly once."""

        domain = _normalize_domain(company_domain_id)
        existing = self.repository.find_by_website_url(domain)
        if existing is not None:
            return existing

        try:
            return self.repository.create(name=domain, website_url=domain)
        except Exception as exc:  # noqa: BLE001 - recover only a unique-key race
            if not _is_duplicate_key_error(exc):
                raise
            existing = self.repository.find_by_website_url(domain)
            if existing is None:
                raise
            return existing

    def ensure_demo_companies(self) -> list[dict[str, Any]]:
        """Create the two demo identities exactly once and return them."""

        seeded: list[dict[str, Any]] = []
        for definition in DEMO_COMPANIES:
            company = self.repository.find_by_website_url(definition["website_url"])
            if company is None:
                company = self.repository.create(**definition)
            seeded.append(company)
        return seeded


def _normalize_domain(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("company_domain_id must be a non-empty domain")
    return value.strip().lower().rstrip(".")


def _is_duplicate_key_error(error: Exception) -> bool:
    try:
        from pymongo.errors import DuplicateKeyError
    except ImportError:
        return False
    return isinstance(error, DuplicateKeyError)


__all__ = ["DEMO_COMPANIES", "CompanyService"]
