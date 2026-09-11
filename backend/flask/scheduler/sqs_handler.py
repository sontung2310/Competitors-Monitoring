"""SQS-independent orchestration for production competitor ingestion."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from urllib.parse import urlsplit, urlunsplit

from backend.flask.database.base_repository import utc_now


SUPPORTED_STRATEGY_ID = 1
DISCOVERY_STALE_AFTER = timedelta(days=30)
_DOMAIN_PATTERN = re.compile(
    r"^(?=.{1,253}$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$"
)


class MessageValidationError(ValueError):
    """Raised when an inbound SQS message is not usable."""


class MessageProcessingError(RuntimeError):
    """Raised when an otherwise valid message cannot be processed."""


def parse_message(body: str | bytes | Mapping[str, Any]) -> dict[str, Any]:
    """Parse and normalize the supported inbound message schema.

    ``host`` is retained as normalized metadata only. It is intentionally
    never consulted by ``handle_message`` when deciding whether to process a
    message.
    """

    if isinstance(body, Mapping):
        payload = dict(body)
    else:
        if isinstance(body, bytes):
            try:
                body = body.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise MessageValidationError("message body must be UTF-8 JSON") from exc
        if not isinstance(body, str) or not body.strip():
            raise MessageValidationError("message body must be a non-empty JSON object")
        try:
            decoded = json.loads(body)
        except json.JSONDecodeError as exc:
            raise MessageValidationError("message body must be valid JSON") from exc
        if not isinstance(decoded, Mapping):
            raise MessageValidationError("message body must be a JSON object")
        payload = dict(decoded)

    return {
        "strategy_id": _normalize_strategy_id(payload.get("strategy_id")),
        "company_domain_id": _normalize_domain(
            payload.get("company_domain_id"),
            field="company_domain_id",
        ),
        "company_url": _normalize_company_url(payload.get("company_url")),
        "host": _normalize_metadata(payload.get("host"), field="host"),
    }


def handle_message(
    message: Mapping[str, Any],
    services: Mapping[str, Any],
    *,
    clock: Callable[[], datetime] = utc_now,
) -> dict[str, Any]:
    """Process one parsed message without SQS or direct database coupling.

    The injected services are the same application services used elsewhere by
    the Flask app. This function deliberately ends after discovery and
    reconciliation; it never invokes monitoring or snapshot operations.
    """

    normalized = parse_message(message)
    if not isinstance(services, Mapping):
        raise MessageProcessingError("services must be a mapping")
    companies = _required_service(services, "companies")
    competitors = _required_service(services, "competitors")
    discovery = _required_service(services, "discovery")

    now = _as_utc(_clock_value(clock))
    company = _call_service(
        companies,
        "find_or_create_by_domain",
        normalized["company_domain_id"],
    )
    company_id = _required_identifier(company, "company")
    competitor = _call_service(
        competitors,
        "find_or_create_competitor",
        company_id=company_id,
        name=_competitor_name(normalized["company_url"]),
        website_url=normalized["company_url"],
    )
    competitor_id = _required_identifier(competitor, "competitor")

    latest = _call_service(
        discovery,
        "latest_successful_run",
        competitor_id,
        company_id=company_id,
    )
    if _is_stale(latest, now):
        reconciliation = _call_service(
            discovery,
            "discover_and_reconcile",
            competitor_id,
            company_id=company_id,
        )
        action = "reconciled"
    else:
        reconciliation = None
        action = "skipped_fresh"

    return {
        "action": action,
        "company": dict(company),
        "competitor": dict(competitor),
        "latest_successful_run": dict(latest) if isinstance(latest, Mapping) else None,
        "reconciliation": _result_mapping(reconciliation),
    }


def _normalize_strategy_id(value: Any) -> int:
    if isinstance(value, bool):
        raise MessageValidationError("strategy_id must be an integer")
    if isinstance(value, int):
        strategy_id = value
    elif isinstance(value, str) and re.fullmatch(r"[0-9]+", value.strip()):
        strategy_id = int(value.strip())
    else:
        raise MessageValidationError("strategy_id must be an integer")
    if strategy_id != SUPPORTED_STRATEGY_ID:
        raise MessageValidationError(
            f"unsupported strategy_id {strategy_id!r}; expected {SUPPORTED_STRATEGY_ID}"
        )
    return strategy_id


def _normalize_domain(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MessageValidationError(f"{field} must be a non-empty domain")
    domain = value.strip().lower().rstrip(".")
    if not _DOMAIN_PATTERN.fullmatch(domain):
        raise MessageValidationError(f"{field} must be a valid domain")
    return domain


def _normalize_company_url(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MessageValidationError("company_url must be a non-empty URL")
    parsed = urlsplit(value.strip())
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise MessageValidationError("company_url must be an http(s) URL")
    if parsed.username is not None or parsed.password is not None:
        raise MessageValidationError("company_url must not contain credentials")
    try:
        port = parsed.port
    except ValueError as exc:
        raise MessageValidationError("company_url has an invalid port") from exc

    hostname = parsed.hostname.lower()
    netloc = f"[{hostname}]" if ":" in hostname else hostname
    if port is not None:
        netloc = f"{netloc}:{port}"
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/") or "/"
    return urlunsplit((parsed.scheme.lower(), netloc, path, parsed.query, ""))


def _normalize_metadata(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MessageValidationError(f"{field} must be a non-empty string")
    return value.strip().lower()


def _required_service(services: Mapping[str, Any], name: str) -> Any:
    service = services.get(name)
    if service is None:
        raise MessageProcessingError(f"services must provide {name!r}")
    return service


def _call_service(service: Any, method: str, *args: Any, **kwargs: Any) -> Any:
    operation = getattr(service, method, None)
    if not callable(operation):
        raise MessageProcessingError(f"injected service lacks {method}()")
    try:
        return operation(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001 - expose a queue-retryable failure
        raise MessageProcessingError(f"{method} failed: {exc}") from exc


def _required_identifier(value: Any, label: str) -> Any:
    if not isinstance(value, Mapping) or value.get("id") is None:
        raise MessageProcessingError(f"{label} service returned no id")
    return value["id"]


def _competitor_name(company_url: str) -> str:
    hostname = urlsplit(company_url).hostname
    return hostname or company_url


def _clock_value(clock: Callable[[], datetime]) -> datetime:
    if not callable(clock):
        raise ValueError("clock must be callable")
    value = clock()
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("clock must return a timezone-aware datetime")
    return value


def _is_stale(latest: Mapping[str, Any] | None, now: datetime) -> bool:
    if not isinstance(latest, Mapping):
        return True
    finished_at = _parse_timestamp(latest.get("finished_at"))
    if finished_at is None:
        return True
    return now - finished_at >= DISCOVERY_STALE_AFTER


def _parse_timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return _as_utc(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return _as_utc(parsed)
    return None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _result_mapping(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    as_dict = getattr(value, "as_dict", None)
    if callable(as_dict):
        value = as_dict()
    if isinstance(value, Mapping):
        return dict(value)
    return {"value": value}


__all__ = [
    "DISCOVERY_STALE_AFTER",
    "MessageProcessingError",
    "MessageValidationError",
    "SUPPORTED_STRATEGY_ID",
    "handle_message",
    "parse_message",
]
