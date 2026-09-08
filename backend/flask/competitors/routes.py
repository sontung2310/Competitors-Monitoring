"""Presentation routes for competitor CRUD."""

from __future__ import annotations

from flask import Blueprint, request

from backend.flask.api import (
    empty_response,
    json_response,
    optional_bool_query,
    request_object,
    required_text,
    service,
)


competitors_blueprint = Blueprint("competitors", __name__)


@competitors_blueprint.get("/competitors")
def list_competitors():
    company_id = request.args.get("company_id")
    kwargs = {"active": optional_bool_query("active")}
    if company_id is not None:
        kwargs["company_id"] = company_id
    return json_response(
        service("competitors").list_competitors(**kwargs)
    )


@competitors_blueprint.post("/competitors")
def create_competitor():
    payload = request_object()
    active = payload.get("active", True)
    if not isinstance(active, bool):
        from backend.flask.errors import RequestValidationError

        raise RequestValidationError("active must be a boolean")
    company_id = payload.get("company_id")
    if company_id is not None:
        company_id = required_text(payload, "company_id")
    competitor = service("competitors").create_competitor(
        name=required_text(payload, "name"),
        website_url=required_text(payload, "website_url"),
        active=active,
        **({"company_id": company_id} if company_id is not None else {}),
    )
    return json_response(competitor, 201)


@competitors_blueprint.get("/competitors/<competitor_id>")
def get_competitor(competitor_id: str):
    kwargs = {}
    if request.args.get("company_id") is not None:
        kwargs["company_id"] = request.args["company_id"]
    return json_response(service("competitors").get_competitor(competitor_id, **kwargs))


@competitors_blueprint.patch("/competitors/<competitor_id>")
def update_competitor(competitor_id: str):
    payload = request_object()
    allowed = {"name", "website_url", "active"}
    allowed.add("company_id")
    unknown = set(payload) - allowed
    if unknown:
        from backend.flask.errors import RequestValidationError

        raise RequestValidationError(f"unsupported competitor fields: {sorted(unknown)}")
    updates = dict(payload)
    if "name" in updates:
        updates["name"] = required_text(updates, "name")
    if "website_url" in updates:
        updates["website_url"] = required_text(updates, "website_url")
    if "company_id" in updates and updates["company_id"] is not None:
        updates["company_id"] = required_text(updates, "company_id")
    if "active" in updates and not isinstance(updates["active"], bool):
        from backend.flask.errors import RequestValidationError

        raise RequestValidationError("active must be a boolean")
    kwargs = {}
    if request.args.get("company_id") is not None:
        kwargs["company_id"] = request.args["company_id"]
    return json_response(service("competitors").update_competitor(competitor_id, updates, **kwargs))


@competitors_blueprint.delete("/competitors/<competitor_id>")
def delete_competitor(competitor_id: str):
    kwargs = {}
    if request.args.get("company_id") is not None:
        kwargs["company_id"] = request.args["company_id"]
    service("competitors").delete_competitor(competitor_id, **kwargs)
    return empty_response()
