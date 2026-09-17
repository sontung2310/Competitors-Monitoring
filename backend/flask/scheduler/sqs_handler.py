"""SQS-independent orchestration for production competitor ingestion."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from urllib.parse import urlsplit, urlunsplit

from backend.flask.database.base_repository import utc_now


DISCOVERY_STALE_AFTER = timedelta(days=30)
_DOMAIN_PATTERN = re.compile(
    r"^(?=.{1,253}$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$"
)

logger = logging.getLogger(__name__)


class MessageValidationError(ValueError):
    """Raised when an inbound SQS message is not usable."""


class MessageProcessingError(RuntimeError):
    """Raised when an otherwise valid message cannot be processed."""


def parse_message(body: str | bytes | Mapping[str, Any]) -> dict[str, Any]:
    """Parse and normalize the supported inbound message schema.

    ``host`` selects which external RM database ``handle_message`` reads from
    when it has to resolve competitors automatically (see
    ``backend.flask.scheduler.strategy_lookup``); it defaults to ``"dev"``
    when absent.
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
        "company_domain_id": _normalize_domain(
            payload.get("company_domain_id"),
            field="company_domain_id",
        ),
        "competitor_lst": _normalize_competitor_list(payload.get("competitor_lst")),
        "host": _normalize_host(payload.get("host")),
    }


def handle_message(
    message: Mapping[str, Any],
    services: Mapping[str, Any],
    *,
    clock: Callable[[], datetime] = utc_now,
    message_id: str | None = None,
) -> dict[str, Any]:
    """Process one parsed message through discovery and monitoring services.

    The injected services are the same application services used elsewhere by
    the Flask app. Discovery/reconciliation remains snapshot-free; active
    targets are handed to ``monitor_target`` afterward. ``message_id`` is the
    SQS at-least-once delivery identity used to make monitoring idempotent.

    ``services["strategy_lookup"]`` and ``services["queue_publisher"]`` are
    only required when actually needed (empty ``competitor_lst``, and a
    multi-competitor resolution, respectively) so a message that already
    names exactly one competitor never needs them.
    """

    normalized = parse_message(message)
    if not isinstance(services, Mapping):
        raise MessageProcessingError("services must be a mapping")
    companies = _required_service(services, "companies")
    competitors = _required_service(services, "competitors")
    discovery = _required_service(services, "discovery")
    monitoring = _required_service(services, "monitoring")

    if message_id is not None and (
        not isinstance(message_id, str) or not message_id.strip()
    ):
        raise MessageProcessingError("message_id must be a non-empty string")

    now = _as_utc(_clock_value(clock))
    company = _call_service(
        companies,
        "find_or_create_by_domain",
        normalized["company_domain_id"],
    )
    company_id = _required_identifier(company, "company")

    competitor_urls = normalized["competitor_lst"]
    if not competitor_urls:
        strategy_lookup = _required_service(services, "strategy_lookup")
        competitor_urls = _call_service(
            strategy_lookup,
            "resolve_primary_competitor_urls",
            normalized["company_domain_id"],
            normalized["host"],
        )
        if not isinstance(competitor_urls, (list, tuple)):
            raise MessageProcessingError(
                "strategy lookup service returned invalid competitor URLs"
            )

    if not competitor_urls:
        logger.info(
            "no trackable competitors resolved for company_domain_id %s; skipping",
            normalized["company_domain_id"],
        )
        return {
            "action": "skipped_no_competitors",
            "company": dict(company),
        }

    if len(competitor_urls) > 1:
        queue_publisher = _required_service(services, "queue_publisher")
        for url in competitor_urls:
            _call_service(
                queue_publisher,
                "publish",
                {
                    "company_domain_id": normalized["company_domain_id"],
                    "competitor_lst": [url],
                    "host": normalized["host"],
                },
            )
        return {
            "action": "fanned_out",
            "company": dict(company),
            "fanned_out_urls": list(competitor_urls),
        }

    company_url = competitor_urls[0]
    ensure_with_status = getattr(
        competitors,
        "find_or_create_competitor_with_status",
        None,
    )
    if callable(ensure_with_status):
        competitor, competitor_created = _call_service(
            competitors,
            "find_or_create_competitor_with_status",
            company_id=company_id,
            name=_competitor_name(company_url),
            website_url=company_url,
        )
        if not isinstance(competitor_created, bool):
            raise MessageProcessingError(
                "competitor status service returned a non-boolean created flag"
            )
    else:
        # Keep direct P.3-style service doubles usable while the production
        # CompetitorService exposes the authoritative created/not-created bit.
        competitor = _call_service(
            competitors,
            "find_or_create_competitor",
            company_id=company_id,
            name=_competitor_name(company_url),
            website_url=company_url,
        )
        competitor_created = False
    competitor_id = _required_identifier(competitor, "competitor")

    if competitor_created:
        latest = None
        reconciliation = _call_service(
            discovery,
            "discover_and_reconcile",
            competitor_id,
            company_id=company_id,
        )
        action = "first_run"
    else:
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
            logger.info(
                "skipping discovery for competitor %s: latest successful run is fresh",
                competitor_id,
            )

    active_targets = _call_service(
        discovery,
        "list_active_targets",
        competitor_id,
        company_id=company_id,
    )
    if not isinstance(active_targets, (list, tuple)):
        raise MessageProcessingError("discovery service returned invalid active targets")

    resolved_message_id = (
        message_id.strip() if isinstance(message_id, str) else None
    )
    idempotency_key = _message_idempotency_key(normalized, resolved_message_id)
    monitoring_results: list[dict[str, Any]] = []
    monitored_target_ids: list[Any] = []
    for target in active_targets:
        target_id = _required_identifier(target, "monitoring target")
        monitoring_result = _call_service(
            monitoring,
            "monitor_target",
            target_id,
            idempotency_key=idempotency_key,
        )
        monitoring_results.append(_result_mapping(monitoring_result) or {})
        monitored_target_ids.append(target_id)

    return {
        "action": action,
        "competitor_created": competitor_created,
        "company": dict(company),
        "competitor": dict(competitor),
        "latest_successful_run": dict(latest) if isinstance(latest, Mapping) else None,
        "reconciliation": _result_mapping(reconciliation),
        "monitored_target_ids": monitored_target_ids,
        "monitoring": monitoring_results,
    }


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


def try_normalize_company_url(value: Any) -> str | None:
    """Normalize a URL, returning ``None`` instead of raising when malformed.

    Shared with ``strategy_lookup.py`` for filtering the (often messy)
    ``competitors_client.website`` values pulled from the external RM
    database, and used here to drop malformed entries from an explicit
    ``competitor_lst`` without failing the whole message.
    """

    try:
        return _normalize_company_url(value)
    except MessageValidationError:
        return None


def _normalize_competitor_list(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise MessageValidationError("competitor_lst must be a list or null")
    urls: list[str] = []
    seen: set[str] = set()
    for entry in value:
        normalized = try_normalize_company_url(entry)
        if normalized is None or normalized in seen:
            continue
        seen.add(normalized)
        urls.append(normalized)
    return urls


def _normalize_host(value: Any) -> str:
    if value is None:
        return "dev"
    if not isinstance(value, str) or not value.strip():
        raise MessageValidationError("host must be a non-empty string when provided")
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


def _message_idempotency_key(
    message: Mapping[str, Any],
    message_id: str | None,
) -> str:
    """Build a stable key for SQS delivery retries and direct callers."""

    if message_id is not None:
        return f"sqs:{message_id}"
    encoded = json.dumps(
        dict(message),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"message:{hashlib.sha256(encoded).hexdigest()}"


__all__ = [
    "DISCOVERY_STALE_AFTER",
    "MessageProcessingError",
    "MessageValidationError",
    "handle_message",
    "parse_message",
    "try_normalize_company_url",
]
