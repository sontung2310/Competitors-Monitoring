"""Presentation routes for company identity records."""

from __future__ import annotations

from flask import Blueprint

from backend.flask.api import json_response, service


companies_blueprint = Blueprint("companies", __name__)


@companies_blueprint.get("/companies")
def list_companies():
    return json_response(service("companies").list_companies())
