"""Presentation routes for Layer 1 candidate review."""

from __future__ import annotations

from flask import Blueprint, request

from backend.flask.api import (
    empty_response,
    json_response,
    request_object,
    required_text,
    service,
)
from backend.flask.errors import RequestValidationError


discovery_blueprint = Blueprint("discovery", __name__)


@discovery_blueprint.get("/competitors/<competitor_id>/candidates")
def list_candidates(competitor_id: str):
    service("competitors").get_competitor(competitor_id)
    status = request.args.get("status", "SUGGESTED")
    return json_response(service("discovery").list_candidates(competitor_id, status=status))


@discovery_blueprint.post("/competitors/<competitor_id>/candidates")
def add_candidate(competitor_id: str):
    service("competitors").get_competitor(competitor_id)
    payload = request_object()
    candidate = service("discovery").add_candidate(
        competitor_id,
        required_text(payload, "url"),
    )
    return json_response(candidate, 201)


@discovery_blueprint.post("/candidates/<candidate_id>/activate")
def activate_candidate(candidate_id: str):
    return json_response(service("discovery").activate_candidate(candidate_id))


@discovery_blueprint.post("/candidates/<candidate_id>/discard")
def discard_candidate(candidate_id: str):
    return json_response(service("discovery").discard_candidate(candidate_id))


@discovery_blueprint.patch("/candidates/<candidate_id>")
def edit_candidate(candidate_id: str):
    payload = request_object()
    if set(payload) != {"url"}:
        raise RequestValidationError("candidate edits support only the url field")
    return json_response(
        service("discovery").edit_candidate(
            candidate_id,
            required_text(payload, "url"),
        )
    )


@discovery_blueprint.delete("/candidates/<candidate_id>")
def remove_candidate(candidate_id: str):
    discovery = service("discovery")
    discovery.remove_candidate(candidate_id)
    remaining = service("targets").get_target(candidate_id)
    if remaining is None:
        return empty_response()
    return json_response(remaining)
