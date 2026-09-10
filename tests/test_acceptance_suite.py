from __future__ import annotations

from tests.acceptance_helpers import run_case_with_retries


def test_case_retry_returns_second_attempt_and_structured_event() -> None:
    attempts = 0

    def action():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("transient provider failure")
        return {
            "change_type": "NEW_BLOG",
            "summary": "NEW_BLOG: one new article",
            "details": {"url": "https://example.test/blog"},
        }

    result = run_case_with_retries("new_blog_post", action)

    assert attempts == 2
    assert result == {
        "case_name": "new_blog_post",
        "passed": True,
        "change_type": "NEW_BLOG",
        "summary": "NEW_BLOG: one new article",
        "error": None,
        "attempt": 2,
        "details": {"url": "https://example.test/blog"},
    }


def test_case_retry_reports_all_attempt_errors_without_fallback() -> None:
    def action():
        raise ValueError("provider unavailable")

    result = run_case_with_retries("new_product", action)

    assert result["passed"] is False
    assert result["attempt"] == 2
    assert result["change_type"] is None
    assert "attempt 1: ValueError: provider unavailable" in result["error"]
    assert "attempt 2: ValueError: provider unavailable" in result["error"]
