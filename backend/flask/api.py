"""Shared presentation-layer helpers for the Flask HTTP API."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Mapping

from flask import current_app, jsonify, request

from backend.flask.errors import RequestValidationError


def service(name: str) -> Any:
    """Resolve a business service registered by the application factory."""

    return current_app.extensions["api_services"][name]


def json_response(payload: Any, status_code: int = 200):
    """Return a JSON response after converting Mongo/Python timestamps."""

    return jsonify(_json_safe(payload)), status_code


def empty_response(status_code: int = 204):
    """Return a response with no body for successful delete operations."""

    return "", status_code


def request_object() -> dict[str, Any]:
    """Require an object JSON body and reject malformed request payloads."""

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise RequestValidationError("request body must be a JSON object")
    return payload


def required_text(payload: Mapping[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise RequestValidationError(f"{field} must be a non-empty string")
    return value.strip()


def optional_bool_query(name: str) -> bool | None:
    value = request.args.get(name)
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized in {"true", "1"}:
        return True
    if normalized in {"false", "0"}:
        return False
    raise RequestValidationError(f"{name} must be true or false")


def optional_positive_int(payload: Mapping[str, Any], field: str) -> int | None:
    value = payload.get(field)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise RequestValidationError(f"{field} must be a positive integer")
    return value


def _json_safe(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat().replace("+00:00", "Z")
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value
