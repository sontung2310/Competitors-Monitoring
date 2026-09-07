"""Presentation routes for monitoring-target CRUD."""

from __future__ import annotations

from flask import Blueprint, request

from backend.flask.api import (
    empty_response,
    json_response,
    optional_positive_int,
    request_object,
    required_text,
    service,
)
from backend.flask.errors import RequestValidationError


monitoring_blueprint = Blueprint("monitoring", __name__)


@monitoring_blueprint.get("/monitoring-targets")
def list_targets():
    return json_response(
        service("targets").list_targets(competitor_id=request.args.get("competitor_id"))
    )


@monitoring_blueprint.post("/monitoring-targets")
def add_manual_target():
    payload = request_object()
    competitor_id = required_text(payload, "competitor_id")
    url = required_text(payload, "url")
    page_type = payload.get("page_type")
    if page_type is not None and (not isinstance(page_type, str) or not page_type.strip()):
        raise RequestValidationError("page_type must be a non-empty string when supplied")
    target = service("targets").add_manual_target(
        competitor_id,
        url,
        page_type=page_type.strip().upper() if isinstance(page_type, str) else None,
    )
    return json_response(target, 201)


@monitoring_blueprint.get("/monitoring-targets/<target_id>")
def get_target(target_id: str):
    target = service("targets").get_target(target_id)
    if target is None:
        from backend.flask.errors import NotFoundError

        raise NotFoundError(f"monitoring target {target_id!r} was not found")
    return json_response(target)


@monitoring_blueprint.patch("/monitoring-targets/<target_id>")
def update_target(target_id: str):
    payload = request_object()
    allowed = {"active", "check_interval_minutes"}
    unknown = set(payload) - allowed
    if unknown:
        raise RequestValidationError(f"unsupported monitoring-target fields: {sorted(unknown)}")
    if "active" in payload and not isinstance(payload["active"], bool):
        raise RequestValidationError("active must be a boolean")
    optional_positive_int(payload, "check_interval_minutes")
    return json_response(service("targets").update_target(target_id, payload))


@monitoring_blueprint.delete("/monitoring-targets/<target_id>")
def remove_target(target_id: str):
    service("targets").remove_target(target_id)
    return empty_response()
