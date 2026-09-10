"""Small helpers shared by opt-in acceptance checks and their unit tests."""

from __future__ import annotations

from typing import Any, Callable, Mapping


MAX_ATTEMPTS = 2
CaseAction = Callable[[], Mapping[str, Any]]


def run_case_with_retries(
    case_name: str,
    action: CaseAction,
    *,
    max_attempts: int = MAX_ATTEMPTS,
) -> dict[str, Any]:
    """Run one acceptance case at most twice and return a structured result."""

    if (
        isinstance(max_attempts, bool)
        or not isinstance(max_attempts, int)
        or not 1 <= max_attempts <= MAX_ATTEMPTS
    ):
        raise ValueError(f"max_attempts must be between 1 and {MAX_ATTEMPTS}")

    errors: list[str] = []
    for attempt in range(1, max_attempts + 1):
        try:
            output = dict(action())
            return {
                "case_name": case_name,
                "passed": True,
                "change_type": output.get("change_type"),
                "summary": output.get("summary"),
                "error": None,
                "attempt": attempt,
                "details": output.get("details", {}),
            }
        except Exception as exc:
            errors.append(f"attempt {attempt}: {type(exc).__name__}: {exc}")

    return {
        "case_name": case_name,
        "passed": False,
        "change_type": None,
        "summary": None,
        "error": "; ".join(errors),
        "attempt": max_attempts,
        "details": {},
    }
