"""Primary-strategy competitor resolution against the external RM database.

This mirrors a reference lookup already used elsewhere in the RM platform: for
a company domain, walk its associated strategies in order and take the first
one flagged ``strategy_priority == "Primary"`` (no filtering on
``strategy_status``), then read that strategy's ``competitors_client`` list.

This is a genuinely different MongoDB database from the one
``backend/flask/database`` connects to for this application's own data, so it
gets its own settings/connection helpers rather than reusing
``MongoSettings.from_env()``.
"""

from __future__ import annotations

import os
from typing import Any, Callable, Mapping, Optional
from urllib.parse import quote_plus

from backend.flask.database.connection import MongoSettings, connect_database
from backend.flask.scheduler.sqs_handler import try_normalize_company_url


DEFAULT_RM_DATABASE_DEV = "rm_dev_testing"
DEFAULT_RM_DATABASE_PROD = "rm_pre_release"


class RmMongoConfigurationError(RuntimeError):
    """Raised when the RM database connection cannot be configured."""


def _assemble_rm_mongodb_uri_from_parts(values: Mapping[str, str]) -> Optional[str]:
    """Build an RM Mongo SRV URI from ``DATABASE_HOST``/``_USERNAME``/``_PASSWORD``.

    These are the RM cluster's actual credentials (a different cluster from
    the one ``MONGODB_URI`` points at for this application's own data), but
    nothing assembles them into a URI on its own. Without this, an
    unset ``RM_MONGODB_URI`` falls through to ``MONGODB_URI`` and silently
    queries the wrong cluster instead of failing loudly.
    """

    host = values.get("DATABASE_HOST")
    username = values.get("DATABASE_USERNAME")
    password = values.get("DATABASE_PASSWORD")
    if not (host and username and password):
        return None
    return (
        f"mongodb+srv://{quote_plus(username)}:{quote_plus(password)}@{host}/"
        "?retryWrites=true&w=majority"
    )


def rm_mongo_settings_for_host(
    host: str,
    environ: Optional[Mapping[str, str]] = None,
) -> MongoSettings:
    """Select RM database settings for a message's ``host`` field.

    ``host == "prod"`` routes to the production RM database; anything else
    (including a missing/unrecognized value) routes to the dev database, per
    the documented default.
    """

    values = environ if environ is not None else os.environ
    uri = (
        values.get("RM_MONGODB_URI")
        or _assemble_rm_mongodb_uri_from_parts(values)
        or values.get("MONGODB_URI")
    )
    if not uri:
        raise RmMongoConfigurationError(
            "RM_MONGODB_URI is not configured, DATABASE_HOST/DATABASE_USERNAME/"
            "DATABASE_PASSWORD are not all set, and MONGODB_URI is not configured"
        )
    if host == "prod":
        database_name = values.get("RM_MONGODB_DATABASE_PROD") or DEFAULT_RM_DATABASE_PROD
    else:
        database_name = values.get("RM_MONGODB_DATABASE_DEV") or DEFAULT_RM_DATABASE_DEV
    return MongoSettings(uri=uri, database_name=database_name)


def _connect_rm_database(host: str) -> Any:
    settings = rm_mongo_settings_for_host(host)
    _, database = connect_database(settings)
    return database


class StrategyLookupService:
    """Resolves a company's Primary-strategy competitor URLs from the RM database."""

    def __init__(self, connector: Callable[[str], Any] = _connect_rm_database) -> None:
        self._connector = connector
        self._databases: dict[str, Any] = {}

    def resolve_primary_competitor_urls(
        self,
        company_domain_id: str,
        host: str,
    ) -> list[str]:
        database = self._database_for_host(host)
        account_company = database["account_company"]
        strategy_strategy = database["strategy_strategy"]

        matched_document = account_company.find_one({"company_domain": company_domain_id})
        if not matched_document:
            return []

        strategy_ids = matched_document.get("strategies_associated_id") or []
        primary_strategy = None
        for strategy_id in strategy_ids:
            strategy_doc = strategy_strategy.find_one({"id": strategy_id})
            if not strategy_doc:
                continue
            if strategy_doc.get("strategy_priority") == "Primary":
                primary_strategy = strategy_doc
                break

        if primary_strategy is None:
            return []

        urls: list[str] = []
        seen: set[str] = set()
        for competitor in primary_strategy.get("competitors_client") or []:
            if not isinstance(competitor, Mapping):
                continue
            normalized = try_normalize_company_url(competitor.get("website"))
            if normalized is None or normalized in seen:
                continue
            seen.add(normalized)
            urls.append(normalized)
        return urls

    def _database_for_host(self, host: str) -> Any:
        route = "prod" if host == "prod" else "dev"
        if route not in self._databases:
            self._databases[route] = self._connector(route)
        return self._databases[route]


__all__ = [
    "DEFAULT_RM_DATABASE_DEV",
    "DEFAULT_RM_DATABASE_PROD",
    "RmMongoConfigurationError",
    "StrategyLookupService",
    "rm_mongo_settings_for_host",
]
