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
    company_id = request.args.get("company_id")
    competitor_kwargs = {"company_id": company_id} if company_id is not None else {}
    service("competitors").get_competitor(competitor_id, **competitor_kwargs)
    status = request.args.get("status", "SUGGESTED")
    discovery_kwargs = {"company_id": company_id} if company_id is not None else {}
    return json_response(service("discovery").list_candidates(competitor_id, status=status, **discovery_kwargs))


@discovery_blueprint.post("/competitors/<competitor_id>/candidates")
def add_candidate(competitor_id: str):
    company_id = request.args.get("company_id")
    competitor_kwargs = {"company_id": company_id} if company_id is not None else {}
    service("competitors").get_competitor(competitor_id, **competitor_kwargs)
    payload = request_object()
    discovery_kwargs = {"company_id": company_id} if company_id is not None else {}
    candidate = service("discovery").add_candidate(
        competitor_id,
        required_text(payload, "url"),
        **discovery_kwargs,
    )
    return json_response(candidate, 201)


@discovery_blueprint.post("/candidates/<candidate_id>/activate")
def activate_candidate(candidate_id: str):
    kwargs = {"company_id": request.args["company_id"]} if "company_id" in request.args else {}
    return json_response(service("discovery").activate_candidate(candidate_id, **kwargs))


@discovery_blueprint.post("/candidates/<candidate_id>/discard")
def discard_candidate(candidate_id: str):
    kwargs = {"company_id": request.args["company_id"]} if "company_id" in request.args else {}
    return json_response(service("discovery").discard_candidate(candidate_id, **kwargs))


@discovery_blueprint.patch("/candidates/<candidate_id>")
def edit_candidate(candidate_id: str):
    payload = request_object()
    if set(payload) != {"url"}:
        raise RequestValidationError("candidate edits support only the url field")
    kwargs = {"company_id": request.args["company_id"]} if "company_id" in request.args else {}
    return json_response(
        service("discovery").edit_candidate(
            candidate_id,
            required_text(payload, "url"),
            **kwargs,
        )
    )


@discovery_blueprint.delete("/candidates/<candidate_id>")
def remove_candidate(candidate_id: str):
    discovery = service("discovery")
    kwargs = {"company_id": request.args["company_id"]} if "company_id" in request.args else {}
    discovery.remove_candidate(candidate_id, **kwargs)
    remaining = service("targets").get_target(candidate_id, **kwargs)
    if remaining is None:
        return empty_response()
    return json_response(remaining)


@discovery_blueprint.post("/competitors/<competitor_id>/discover")
def discover_competitor(competitor_id: str):
    """Run real Layer 1 discovery synchronously for the selected company."""

    company_id = request.args.get("company_id")
    kwargs = {"company_id": company_id} if company_id is not None else {}
    service("competitors").get_competitor(competitor_id, **kwargs)
    discovered = service("discovery").discover_website(competitor_id, **kwargs)
    summary = getattr(service("discovery"), "last_summary", None)
    summary_payload = None
    if summary is not None:
        summary_payload = {
            "website_url": summary.website_url,
            "raw_count": summary.raw_count,
            "normalized_count": summary.normalized_count,
            "suggested_count": summary.suggested_count,
            "discarded_count": summary.discarded_count,
            "source_breakdown": {
                source: {
                    "raw_count": details.raw_count,
                    "normalized_count": details.normalized_count,
                    "sampled_count": details.sampled_count,
                    "declared_sitemaps": details.declared_sitemaps,
                }
                for source, details in summary.source_breakdown.items()
            },
        }
    return json_response(
        {
            "competitor_id": competitor_id,
            "candidates": discovered,
            "summary": summary_payload,
        }
    )
