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
    kwargs = {"competitor_id": request.args.get("competitor_id")}
    if request.args.get("company_id") is not None:
        kwargs["company_id"] = request.args["company_id"]
    return json_response(
        service("targets").list_targets(**kwargs)
    )


@monitoring_blueprint.post("/monitoring-targets")
def add_manual_target():
    payload = request_object()
    competitor_id = required_text(payload, "competitor_id")
    url = required_text(payload, "url")
    page_type = payload.get("page_type")
    if page_type is not None and (not isinstance(page_type, str) or not page_type.strip()):
        raise RequestValidationError("page_type must be a non-empty string when supplied")
    kwargs = {}
    if payload.get("company_id") is not None:
        kwargs["company_id"] = required_text(payload, "company_id")
    target = service("targets").add_manual_target(
        competitor_id,
        url,
        page_type=page_type.strip().upper() if isinstance(page_type, str) else None,
        **kwargs,
    )
    return json_response(target, 201)


@monitoring_blueprint.get("/monitoring-targets/<target_id>")
def get_target(target_id: str):
    kwargs = {"company_id": request.args["company_id"]} if "company_id" in request.args else {}
    target = service("targets").get_target(target_id, **kwargs)
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
    kwargs = {"company_id": request.args["company_id"]} if "company_id" in request.args else {}
    return json_response(service("targets").update_target(target_id, payload, **kwargs))


@monitoring_blueprint.delete("/monitoring-targets/<target_id>")
def remove_target(target_id: str):
    kwargs = {"company_id": request.args["company_id"]} if "company_id" in request.args else {}
    service("targets").remove_target(target_id, **kwargs)
    return empty_response()


@monitoring_blueprint.post("/monitoring-targets/<target_id>/simulate")
def simulate_target(target_id: str):
    """Run the explicitly tagged, persistence-enabled PoC simulation."""

    payload = request.get_json(silent=True)
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise RequestValidationError("request body must be a JSON object")
    unknown = set(payload) - {"mutation_type", "company_id"}
    if unknown:
        raise RequestValidationError(f"unsupported simulation fields: {sorted(unknown)}")
    mutation_type = payload.get("mutation_type")
    if mutation_type is not None and (
        not isinstance(mutation_type, str) or not mutation_type.strip()
    ):
        raise RequestValidationError("mutation_type must be a non-empty string when supplied")
    company_id = (
        required_text(payload, "company_id")
        if "company_id" in payload
        else request.args.get("company_id")
    )
    if company_id is not None:
        if not isinstance(company_id, str) or not company_id.strip():
            raise RequestValidationError("company_id must be a non-empty string")
        company_id = company_id.strip()
    kwargs = {"company_id": company_id} if company_id is not None else {}
    return json_response(
        service("simulation").simulate_and_persist_change(
            target_id,
            mutation_type=mutation_type,
            **kwargs,
        )
    )
