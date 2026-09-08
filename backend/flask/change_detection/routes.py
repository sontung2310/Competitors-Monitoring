"""Presentation routes for the latest changes/events feed."""

from __future__ import annotations

from datetime import datetime, timezone

from flask import Blueprint, request

from backend.flask.api import json_response, service
from backend.flask.errors import NotFoundError, RequestValidationError


changes_blueprint = Blueprint("changes", __name__)


@changes_blueprint.get("/changes")
def list_changes():
    limit_text = request.args.get("limit", "50")
    try:
        limit = int(limit_text)
    except (TypeError, ValueError) as exc:
        raise RequestValidationError("limit must be an integer between 1 and 100") from exc
    if not 1 <= limit <= 100:
        raise RequestValidationError("limit must be an integer between 1 and 100")
    since = _parse_since(request.args.get("since"))
    kwargs = {
        "competitor_id": request.args.get("competitor_id"),
        "target_id": request.args.get("target_id"),
        "since": since,
        "limit": limit,
    }
    if request.args.get("company_id") is not None:
        kwargs["company_id"] = request.args["company_id"]
    return json_response(service("changes").list_changes(**kwargs))


@changes_blueprint.get("/changes/<change_id>")
def get_change(change_id: str):
    kwargs = {"company_id": request.args["company_id"]} if "company_id" in request.args else {}
    change = service("changes").get_change(change_id, **kwargs)
    if change is None:
        raise NotFoundError(f"change {change_id!r} was not found")
    return json_response(change)


def _parse_since(value: str | None) -> datetime | None:
    if value is None:
        return None
    candidate = value.strip()
    if candidate.endswith("Z"):
        candidate = f"{candidate[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise RequestValidationError("since must be an ISO 8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise RequestValidationError("since must include a UTC offset")
    return parsed.astimezone(timezone.utc)
