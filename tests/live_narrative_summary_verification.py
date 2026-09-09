"""Opt-in live evidence for 1.6b narrative summaries.

This script writes simulated records and one forced-failure real monitoring
record to the dedicated Atlas test database. It never runs against the default
database.

    RUN_LIVE_NARRATIVE_SUMMARY=1 \
      MONGODB_DATABASE=competitors_monitoring_test \
      python -u tests/live_narrative_summary_verification.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - requirements.txt provides this package
    load_dotenv = None

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.flask.app import create_app
from backend.flask.change_detection.repository import ChangeRepository
from backend.flask.competitors.repository import CompetitorRepository
from backend.flask.database.connection import MongoSettings, connect_database
from backend.flask.llm_provider import OpenAIProvider
from backend.flask.snapshot.repository import SnapshotRepository
from backend.flask.website_monitoring.repository import MonitoringTargetRepository
from backend.flask.website_monitoring.service import (
    FetchResult,
    MonitoringRunService,
    fetch_page,
)
from backend.flask.website_monitoring.simulated_persistence import (
    SimulationPersistenceService,
)


TEST_DATABASE = "competitors_monitoring_test"
LYFE_HOST_FRAGMENT = "lyfemarketing.com"
JD_HOST_FRAGMENT = "jd-sports.com.au"
BLOG_PATH = "/blog"
PRODUCT_PATH = "/sale"


class CountingProvider:
    """Count calls while delegating to the real shared OpenAI provider."""

    def __init__(self) -> None:
        self.delegate = OpenAIProvider.from_env()
        self.generate_calls: list[dict[str, Any]] = []
        self.generate_json_calls: list[dict[str, Any]] = []

    def generate(self, prompt, *, instructions, response_format=None):
        self.generate_calls.append(
            {
                "prompt": prompt,
                "instructions": instructions,
                "response_format": response_format,
            }
        )
        return self.delegate.generate(
            prompt,
            instructions=instructions,
            response_format=response_format,
        )

    def generate_json(self, prompt, *, instructions, response_format):
        self.generate_json_calls.append(
            {
                "prompt": prompt,
                "instructions": instructions,
                "response_format": response_format,
            }
        )
        return self.delegate.generate_json(
            prompt,
            instructions=instructions,
            response_format=response_format,
        )


class FailingProvider:
    def __init__(self) -> None:
        self.calls = 0

    def generate(self, prompt, *, instructions, response_format=None):
        self.calls += 1
        raise RuntimeError("forced narrative provider failure")


def run_live_verification() -> dict[str, Any]:
    if os.environ.get("RUN_LIVE_NARRATIVE_SUMMARY") != "1":
        raise SystemExit(
            "Set RUN_LIVE_NARRATIVE_SUMMARY=1 to run live narrative verification"
        )

    if load_dotenv is not None:
        load_dotenv(override=False)
    settings = MongoSettings.from_env()
    if settings.database_name != TEST_DATABASE:
        raise RuntimeError(
            f"refusing to write outside {TEST_DATABASE!r}; "
            f"configured database is {settings.database_name!r}"
        )

    client, database = connect_database(
        settings,
        serverSelectionTimeoutMS=15_000,
    )
    try:
        client.admin.command("ping")
        competitors = CompetitorRepository.from_database(database)
        targets = MonitoringTargetRepository.from_database(database)
        snapshots = SnapshotRepository.from_database(database)
        changes = ChangeRepository.from_database(database)
        lyfe = _find_competitor(competitors, LYFE_HOST_FRAGMENT)
        jd = _find_competitor(competitors, JD_HOST_FRAGMENT)
        lyfe_target = _find_target(targets, lyfe["id"], BLOG_PATH, "BLOG")
        jd_target = _find_target(targets, jd["id"], PRODUCT_PATH, "PRODUCT_LISTING")

        app = create_app(database=database, user_id="live-verification", testing=True)
        provider = CountingProvider()
        app.extensions["api_services"]["simulation"] = (
            SimulationPersistenceService.from_database(
                database,
                provider_factory=lambda: provider,
                narrative_provider_factory=lambda: provider,
            )
        )
        http = app.test_client()

        blog_simulation = _expect(
            http.post(f"/api/monitoring-targets/{lyfe_target['id']}/simulate"),
            200,
        )
        blog_change = blog_simulation["change"]
        if blog_change.get("change_type") != "NEW_BLOG":
            raise AssertionError(f"unexpected blog simulation: {blog_simulation!r}")
        if not blog_change.get("narrative_summary"):
            raise AssertionError("real blog simulation did not produce a narrative")
        if len(provider.generate_calls) != 2 or provider.generate_json_calls:
            raise AssertionError(
                f"blog simulation did not make one mutation and one narrative call: "
                f"generate={len(provider.generate_calls)} "
                f"json={len(provider.generate_json_calls)}"
            )
        blog_evidence = {
            "change_id": blog_change["id"],
            "change_type": blog_change["change_type"],
            "narrative_summary": blog_change["narrative_summary"],
            "mechanical_summary": blog_change["summary"],
            "provider_generate_calls": len(provider.generate_calls),
            "provider_generate_json_calls": len(provider.generate_json_calls),
        }

        provider.generate_calls.clear()
        provider.generate_json_calls.clear()
        product_simulation = _expect(
            http.post(
                f"/api/monitoring-targets/{jd_target['id']}/simulate",
                json={"mutation_type": "NEW_PRODUCT"},
            ),
            200,
        )
        product_change = product_simulation["change"]
        if product_change.get("change_type") != "NEW_PRODUCT":
            raise AssertionError(f"unexpected product simulation: {product_simulation!r}")
        if product_change.get("narrative_summary") is not None:
            raise AssertionError("product change unexpectedly received a narrative")
        if provider.generate_calls:
            raise AssertionError(
                "product simulation made a narrative text-generation call"
            )
        product_evidence = {
            "change_id": product_change["id"],
            "change_type": product_change["change_type"],
            "narrative_summary": product_change.get("narrative_summary"),
            "mechanical_summary": product_change["summary"],
            "provider_generate_calls": len(provider.generate_calls),
            "provider_generate_json_calls": len(provider.generate_json_calls),
            "narrative_calls": 0,
            "expected_existing_mutation_calls": 1,
        }
        if (
            len(provider.generate_calls) + len(provider.generate_json_calls)
            != product_evidence["expected_existing_mutation_calls"]
        ):
            raise AssertionError(
                f"product simulation made unexpected provider calls: {product_evidence!r}"
            )

        failing_provider = FailingProvider()
        fetched = fetch_page(lyfe_target["url"])
        forced_content = (
            f"{fetched.content}\n"
            "<section><h2>Forced narrative failure verification marker</h2>"
            "<p>This content exists only to force a real change.</p></section>"
        )
        failure_service = MonitoringRunService.from_database(
            database,
            fetcher=lambda _url: FetchResult(
                forced_content,
                fetched.fetch_method,
                fetched.http_status,
            ),
            narrative_provider_factory=lambda: failing_provider,
        )
        forced_failure = failure_service.monitor_target(lyfe_target["id"])
        if forced_failure["run"]["status"] != "SUCCESS":
            raise AssertionError(f"forced-failure monitor did not succeed: {forced_failure!r}")
        if len(forced_failure["changes"]) != 1:
            raise AssertionError(f"forced-failure monitor did not create one change: {forced_failure!r}")
        failure_change = forced_failure["changes"][0]
        if failure_change.get("narrative_summary") is not None:
            raise AssertionError("forced failure populated a narrative unexpectedly")
        failure_evidence = {
            "change_id": failure_change["id"],
            "change_type": failure_change["change_type"],
            "narrative_summary": failure_change.get("narrative_summary"),
            "mechanical_summary": failure_change["summary"],
            "run_status": forced_failure["run"]["status"],
            "failing_provider_calls": failing_provider.calls,
        }

        # Confirm the persisted API row carries the same nullable field.
        persisted_product = changes.get(product_change["id"])
        if persisted_product.get("narrative_summary") is not None:
            raise AssertionError("persisted product change narrative is not null")

        report = {
            "database": database.name,
            "blog_simulation": blog_evidence,
            "product_simulation": product_evidence,
            "forced_failure": failure_evidence,
            "real_change_records_created": 1,
        }
        _print_report(report)
        return report
    finally:
        client.close()


def _find_competitor(repository: CompetitorRepository, host_fragment: str) -> dict[str, Any]:
    for competitor in repository.list_all(active=True):
        if host_fragment in str(competitor.get("website_url", "")):
            return competitor
    raise AssertionError(f"no active competitor matched {host_fragment!r}")


def _find_target(
    repository: MonitoringTargetRepository,
    competitor_id: Any,
    path: str,
    page_type: str,
) -> dict[str, Any]:
    wanted_path = path.rstrip("/") or "/"
    for target in repository.list_active_targets(competitor_id):
        target_path = urlsplit(str(target.get("url", ""))).path.rstrip("/") or "/"
        if target_path == wanted_path and target.get("page_type") == page_type:
            return target
    raise AssertionError(
        f"no active {page_type} target at {path!r} for competitor {competitor_id!r}"
    )


def _expect(response, status_code: int) -> Any:
    if response.status_code != status_code:
        raise AssertionError(
            f"expected HTTP {status_code}, got {response.status_code}: {response.get_data(as_text=True)}"
        )
    return response.get_json()


def _print_report(report: dict[str, Any]) -> None:
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    raise SystemExit(0 if run_live_verification() else 1)
