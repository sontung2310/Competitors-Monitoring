"""Opt-in live acceptance suite for the deterministic change pipeline.

Run from the repository root with the dedicated Atlas test database and the
OpenAI provider configured:

    set -a
    source .env.mongodb
    source .env
    set +a
    export MONGODB_DATABASE=competitors_monitoring_test
    RUN_LIVE_ACCEPTANCE=1 \
      /Users/sontung/miniconda3/bin/python -u tests/live_acceptance_suite.py

The suite captures real pages, asks the reusable provider for one mutation per
case, and sends the mutation through the real deterministic processors in
memory. It only reads Atlas to compare collection counts and never calls the
monitoring persistence services.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import urlsplit

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.flask.change_detection.repository import ChangeRepository
from backend.flask.competitors.repository import CompetitorRepository
from backend.flask.database.connection import MongoSettings, connect_database
from backend.flask.llm_provider import OpenAIProvider
from backend.flask.snapshot.repository import SnapshotRepository
from backend.flask.website_monitoring.repository import (
    MonitoringRunRepository,
    MonitoringTargetRepository,
)
from backend.flask.website_monitoring.service import fetch_page
from backend.flask.website_monitoring.simulated_verification import (
    simulate_product_mutation,
    simulate_text_change,
)


TEST_DATABASE = "competitors_monitoring_test"
MAX_ATTEMPTS_PER_CASE = 2
LYFE_BLOG_URL = "https://www.lyfemarketing.com/blog/"
LYFE_SERVICES_URL = "https://www.lyfemarketing.com/services/"
JD_SALE_URL = "https://www.jd-sports.com.au/sale/"


class AcceptanceSuiteError(RuntimeError):
    """Raised when a case cannot produce an authoritative acceptance result."""


CaseAction = Callable[[], Mapping[str, Any]]


def run_case_with_retries(
    case_name: str,
    action: CaseAction,
    *,
    max_attempts: int = MAX_ATTEMPTS_PER_CASE,
) -> dict[str, Any]:
    """Run one live case at most twice and return a structured result."""

    if (
        isinstance(max_attempts, bool)
        or not isinstance(max_attempts, int)
        or not 1 <= max_attempts <= MAX_ATTEMPTS_PER_CASE
    ):
        raise ValueError(
            f"max_attempts must be between 1 and {MAX_ATTEMPTS_PER_CASE}"
        )

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


def run_acceptance_suite() -> dict[str, Any]:
    """Run all five cases and return results suitable for later consumers."""

    if os.environ.get("RUN_LIVE_ACCEPTANCE") != "1":
        raise SystemExit("Set RUN_LIVE_ACCEPTANCE=1 to run live acceptance verification")

    settings = MongoSettings.from_env()
    if settings.database_name != TEST_DATABASE:
        raise RuntimeError(
            f"refusing to inspect outside the dedicated test database {TEST_DATABASE!r}; "
            f"configured database is {settings.database_name!r}"
        )

    client, database = connect_database(
        settings,
        serverSelectionTimeoutMS=15_000,
    )
    try:
        client.admin.command("ping")
        before_counts = _atlas_counts(database)
        provider = OpenAIProvider.from_env()
        cases: list[tuple[str, CaseAction]] = [
            (
                "new_blog_post",
                lambda: _run_text_case(
                    LYFE_BLOG_URL,
                    "BLOG",
                    "NEW_BLOG",
                    provider,
                ),
            ),
            (
                "new_services_content",
                lambda: _run_text_case(
                    LYFE_SERVICES_URL,
                    "SERVICES",
                    "PAGE_UPDATE",
                    provider,
                ),
            ),
            (
                "new_product",
                lambda: _run_product_case(
                    JD_SALE_URL,
                    "NEW_PRODUCT",
                    provider,
                ),
            ),
            (
                "product_price_change",
                lambda: _run_product_case(
                    JD_SALE_URL,
                    "PRICE_CHANGE",
                    provider,
                ),
            ),
            (
                "product_removed",
                lambda: _run_product_case(
                    JD_SALE_URL,
                    "PRODUCT_REMOVED",
                    provider,
                ),
            ),
        ]
        results = [
            run_case_with_retries(case_name, action)
            for case_name, action in cases
        ]
        after_counts = _atlas_counts(database)
        report = {
            "database": database.name,
            "before_counts": before_counts,
            "after_counts": after_counts,
            "counts_unchanged": before_counts == after_counts,
            "results": results,
        }
        _print_report(report)
        return report
    finally:
        client.close()


def _atlas_counts(database: Any) -> dict[str, int]:
    repositories = (
        CompetitorRepository.from_database(database),
        MonitoringTargetRepository.from_database(database),
        SnapshotRepository.from_database(database),
        ChangeRepository.from_database(database),
        MonitoringRunRepository.from_database(database),
    )
    names = ("competitors", "monitoring_targets", "snapshots", "changes", "monitoring_runs")
    return {name: repository.count() for name, repository in zip(names, repositories)}


def _run_text_case(
    url: str,
    page_type: str,
    expected_change_type: str,
    provider: OpenAIProvider,
) -> dict[str, Any]:
    fetched = fetch_page(url)
    result = simulate_text_change(
        fetched.content,
        provider,
        page_type=page_type,
    )
    events = result.process_result.change_events
    if not result.process_result.changed or len(events) != 1:
        raise AcceptanceSuiteError(
            f"{page_type} mutation produced {len(events)} events instead of one"
        )
    event = events[0]
    if event.get("change_type") != expected_change_type:
        raise AcceptanceSuiteError(
            f"expected {expected_change_type}, got {event.get('change_type')}"
        )
    summary = event.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise AcceptanceSuiteError(f"{page_type} event summary was empty")
    if _is_uninformative_large_one_line_summary(summary):
        raise AcceptanceSuiteError(
            f"{page_type} summary still has the giant one-line diff shape: {summary}"
        )
    return {
        "change_type": event["change_type"],
        "summary": summary,
        "details": {
            "url": url,
            "path": urlsplit(url).path,
            "fetch_method": fetched.fetch_method,
            "http_status": fetched.http_status,
        },
    }


def _run_product_case(
    url: str,
    mutation_type: str,
    provider: OpenAIProvider,
) -> dict[str, Any]:
    fetched = fetch_page(url)
    result = simulate_product_mutation(
        fetched.content,
        provider,
        mutation_type=mutation_type,
    )
    if len(result.events) != 1:
        raise AcceptanceSuiteError(
            f"{mutation_type} mutation produced {len(result.events)} events instead of one"
        )
    event = result.events[0]
    if event.get("change_type") != mutation_type:
        raise AcceptanceSuiteError(
            f"expected {mutation_type}, got {event.get('change_type')}"
        )
    summary = event.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise AcceptanceSuiteError(f"{mutation_type} event summary was empty")
    return {
        "change_type": event["change_type"],
        "summary": summary,
        "details": {
            "url": url,
            "path": urlsplit(url).path,
            "fetch_method": fetched.fetch_method,
            "http_status": fetched.http_status,
            "product_count": len(result.original_products),
            "mutation_plan": dict(result.mutation_plan),
        },
    }


def _is_uninformative_large_one_line_summary(summary: str) -> bool:
    match = re.search(
        r"(\d+) line\(s\) added, (\d+) line\(s\) removed "
        r"\((\d+) characters added, (\d+) removed\)",
        summary,
    )
    if match is None:
        return False
    added_lines, removed_lines, added_chars, removed_chars = map(int, match.groups())
    return (
        added_lines <= 1
        and removed_lines <= 1
        and max(added_chars, removed_chars) >= 10_000
    )


def _print_report(report: Mapping[str, Any]) -> None:
    print(f"database={report['database']}")
    print(
        f"atlas_counts_before={report['before_counts']} "
        f"atlas_counts_after={report['after_counts']} "
        f"unchanged={report['counts_unchanged']}"
    )
    for result in report["results"]:
        outcome = "PASS" if result["passed"] else "FAIL"
        print(
            f"case={result['case_name']} {outcome} attempt={result['attempt']} "
            f"change_type={result['change_type']} summary={result['summary']}"
        )
        if result["error"]:
            print(f"error={result['error']}")
        if result["details"]:
            print(f"details={result['details']}")


if __name__ == "__main__":
    live_report = run_acceptance_suite()
    all_passed = all(result["passed"] for result in live_report["results"])
    raise SystemExit(0 if all_passed and live_report["counts_unchanged"] else 1)
