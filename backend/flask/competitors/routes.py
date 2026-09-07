"""Presentation routes for competitor CRUD."""

from __future__ import annotations

from flask import Blueprint

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
    return json_response(
        service("competitors").list_competitors(active=optional_bool_query("active"))
    )


@competitors_blueprint.post("/competitors")
def create_competitor():
    payload = request_object()
    active = payload.get("active", True)
    if not isinstance(active, bool):
        from backend.flask.errors import RequestValidationError

        raise RequestValidationError("active must be a boolean")
    competitor = service("competitors").create_competitor(
        name=required_text(payload, "name"),
        website_url=required_text(payload, "website_url"),
        active=active,
    )
    return json_response(competitor, 201)


@competitors_blueprint.get("/competitors/<competitor_id>")
def get_competitor(competitor_id: str):
    return json_response(service("competitors").get_competitor(competitor_id))


@competitors_blueprint.patch("/competitors/<competitor_id>")
def update_competitor(competitor_id: str):
    payload = request_object()
    allowed = {"name", "website_url", "active"}
    unknown = set(payload) - allowed
    if unknown:
        from backend.flask.errors import RequestValidationError

        raise RequestValidationError(f"unsupported competitor fields: {sorted(unknown)}")
    updates = dict(payload)
    if "name" in updates:
        updates["name"] = required_text(updates, "name")
    if "website_url" in updates:
        updates["website_url"] = required_text(updates, "website_url")
    if "active" in updates and not isinstance(updates["active"], bool):
        from backend.flask.errors import RequestValidationError

        raise RequestValidationError("active must be a boolean")
    return json_response(service("competitors").update_competitor(competitor_id, updates))


@competitors_blueprint.delete("/competitors/<competitor_id>")
def delete_competitor(competitor_id: str):
    service("competitors").delete_competitor(competitor_id)
    return empty_response()
