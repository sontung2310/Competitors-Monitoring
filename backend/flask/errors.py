"""Shared service/API error types used by the Flask presentation boundary."""

from __future__ import annotations

from typing import Any


class APIError(RuntimeError):
    """A safe, intentional error that can be exposed by the HTTP API."""

    status_code = 400
    code = "validation_error"

    def __init__(self, message: str, *, status_code: int | None = None, code: str | None = None) -> None:
        super().__init__(message)
        if status_code is not None:
            self.status_code = status_code
        if code is not None:
            self.code = code


class NotFoundError(APIError):
    """Raised when a requested resource does not exist in the current scope."""

    status_code = 404
    code = "not_found"


class ConflictError(APIError):
    """Raised when a request conflicts with current resource state."""

    status_code = 409
    code = "conflict"


class RequestValidationError(APIError):
    """Raised when a request body or query parameter is invalid."""

    status_code = 400
    code = "validation_error"


def duplicate_key_error(error: BaseException) -> bool:
    """Recognize PyMongo duplicate-key errors without importing it eagerly."""

    if getattr(error, "code", None) == 11000:
        return True
    return error.__class__.__name__ == "DuplicateKeyError"


def api_error_payload(error: APIError) -> dict[str, dict[str, str]]:
    """Build the single error envelope used by every API response."""

    return {"error": {"code": error.code, "message": str(error)}}


def error_from_exception(error: BaseException) -> APIError | None:
    """Map known domain/repository failures to a safe HTTP error."""

    if isinstance(error, APIError):
        return error
    if duplicate_key_error(error):
        return ConflictError("the requested resource already exists")

    status_code = getattr(error, "status_code", None)
    code = getattr(error, "code", None)
    if isinstance(status_code, int) and 400 <= status_code <= 599:
        return APIError(str(error) or error.__class__.__name__, status_code=status_code, code=code)

    # Repository identifier and domain validation errors are safe to expose.
    if isinstance(error, (ValueError, TypeError)):
        return RequestValidationError(str(error) or "request is invalid")
    return None
