"""Opt-in live evidence for 1.6b narratives and detected URLs.

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
import re
import sys
import uuid
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
from backend.flask.change_detection.service import ChangeService
from backend.flask.competitors.repository import CompetitorRepository
from backend.flask.database.connection import MongoSettings, connect_database
from backend.flask.llm_provider import OpenAIProvider
from backend.flask.snapshot.repository import SnapshotRepository
from backend.flask.website_monitoring.repository import MonitoringTargetRepository
from backend.flask.website_monitoring.service import (
    FetchResult,
    MonitoringRunService,
    fetch_page,
    hash_content,
    normalize_content,
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


class StructuredProvider:
    """Deterministic structured output used for real-content validation cases."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.calls = 0

    def generate_json(self, prompt, *, instructions, response_format):
        self.calls += 1
        return self.payload


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
        if len(provider.generate_calls) != 1 or len(provider.generate_json_calls) != 1:
            raise AssertionError(
                f"blog simulation did not make one mutation and one narrative call: "
                f"generate={len(provider.generate_calls)} "
                f"json={len(provider.generate_json_calls)}"
            )
        if not blog_change.get("detected_url"):
            raise AssertionError("real NEW_BLOG simulation did not extract a post URL")
        blog_host = (urlsplit(blog_change["detected_url"]).hostname or "").removeprefix("www.")
        target_host = (urlsplit(lyfe_target["url"]).hostname or "").removeprefix("www.")
        if blog_host != target_host:
            raise AssertionError("real NEW_BLOG URL was not on the monitored domain")
        blog_evidence = {
            "change_id": blog_change["id"],
            "change_type": blog_change["change_type"],
            "narrative_summary": blog_change["narrative_summary"],
            "mechanical_summary": blog_change["summary"],
            "detected_url": blog_change["detected_url"],
            "domain_validation": "passed",
            "liveness_validation": "passed",
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
            "detected_url": product_change.get("detected_url"),
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
        forced_run_marker = uuid.uuid4().hex
        forced_fragment = (
            "<section><h2>Forced narrative failure verification marker</h2>"
            f"<p>This content exists only to force a real change: {forced_run_marker}.</p>"
            "</section>"
        )
        if "</body>" in fetched.content:
            forced_content = fetched.content.replace(
                "</body>",
                f"{forced_fragment}</body>",
                1,
            )
        elif "</html>" in fetched.content:
            forced_content = fetched.content.replace(
                "</html>",
                f"{forced_fragment}</html>",
                1,
            )
        else:
            forced_content = f"{fetched.content}{forced_fragment}"
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
            "detected_url": failure_change.get("detected_url"),
            "fallback_url": lyfe_target["url"],
            "run_status": forced_failure["run"]["status"],
            "failing_provider_calls": failing_provider.calls,
        }

        # Confirm the persisted API row carries the same nullable field.
        persisted_product = changes.get(product_change["id"])
        if persisted_product.get("narrative_summary") is not None:
            raise AssertionError("persisted product change narrative is not null")

        provider.generate_calls.clear()
        provider.generate_json_calls.clear()
        real_blog_evidence = _run_real_blog_extraction_case(
            app.extensions["api_services"]["changes"],
            lyfe_target,
            fetched.content,
            provider,
        )
        validation_evidence = _run_real_content_validation_cases(
            app.extensions["api_services"]["changes"],
            lyfe_target,
            fetched.content,
        )

        report = {
            "database": database.name,
            "blog_simulation": blog_evidence,
            "product_simulation": product_evidence,
            "forced_failure": failure_evidence,
            "real_blog_extraction": real_blog_evidence,
            "validation_cases": validation_evidence,
            "real_change_records_created": 1,
        }
        _print_report(report)
        return report
    finally:
        client.close()


def _run_real_content_validation_cases(
    changes: ChangeService,
    target: dict[str, Any],
    live_content: str,
) -> dict[str, Any]:
    """Exercise fallback policy against a live target's captured content."""

    previous = {
        "id": "000000000000000000000024",
        "content": live_content,
        "content_hash": hash_content(live_content),
    }
    minor_content = f"{live_content}\n<p>Minor wording edit marker for TON-31.</p>"
    minor = {
        "id": "000000000000000000000025",
        "content": minor_content,
        "content_hash": hash_content(minor_content),
    }
    page_provider = StructuredProvider(
        {"narrative_summary": "A minor wording edit was detected.", "detected_url": None}
    )
    page_liveness_calls: list[str] = []
    page_change = ChangeService(
        changes.change_repository,
        changes.monitoring_target_repository,
        narrative_provider_factory=lambda: page_provider,
        detected_url_liveness_checker=lambda url: page_liveness_calls.append(url),
    ).create_change(
        target["id"],
        previous,
        minor,
        change_type="PAGE_UPDATE",
    )
    if page_change["detected_url"] != target["url"] or page_liveness_calls:
        raise AssertionError("PAGE_UPDATE did not use its expected tracked-page fallback")

    wrong_domain_provider = StructuredProvider(
        {
            "narrative_summary": "A candidate URL was returned.",
            "detected_url": "https://example.com/ton31-wrong-domain",
        }
    )
    wrong_domain_calls: list[str] = []
    wrong_domain_change = ChangeService(
        changes.change_repository,
        changes.monitoring_target_repository,
        narrative_provider_factory=lambda: wrong_domain_provider,
        detected_url_liveness_checker=lambda url: wrong_domain_calls.append(url) or True,
    ).create_change(target["id"], previous, minor)
    if wrong_domain_change["detected_url"] != target["url"] or wrong_domain_calls:
        raise AssertionError("wrong-domain URL was not rejected before liveness")

    dead_path = f"{urlsplit(target['url']).scheme}://{urlsplit(target['url']).netloc}/ton31-definitely-dead-url"
    dead_provider = StructuredProvider(
        {
            "narrative_summary": "A dead candidate URL was returned.",
            "detected_url": dead_path,
        }
    )
    dead_calls: list[str] = []
    dead_change = ChangeService(
        changes.change_repository,
        changes.monitoring_target_repository,
        narrative_provider_factory=lambda: dead_provider,
        detected_url_liveness_checker=lambda url: dead_calls.append(url) or fetch_page(url),
    ).create_change(target["id"], previous, minor)
    if dead_change["detected_url"] != target["url"]:
        raise AssertionError("dead same-domain URL did not fall back to the tracked page")

    return {
        "page_update": {
            "change_id": page_change["id"],
            "detected_url": page_change["detected_url"],
            "expected_outcome": "tracked-page fallback for minor non-structural edit",
            "liveness_calls": page_liveness_calls,
        },
        "wrong_domain": {
            "change_id": wrong_domain_change["id"],
            "candidate_url": "https://example.com/ton31-wrong-domain",
            "detected_url": wrong_domain_change["detected_url"],
            "expected_outcome": "rejected before liveness; tracked-page fallback",
            "liveness_calls": wrong_domain_calls,
        },
        "dead_url": {
            "change_id": dead_change["id"],
            "candidate_url": dead_path,
            "detected_url": dead_change["detected_url"],
            "expected_outcome": "same-domain candidate failed usable-response check; tracked-page fallback",
            "liveness_calls": dead_calls,
        },
    }


def _run_real_blog_extraction_case(
    changes: ChangeService,
    target: dict[str, Any],
    live_content: str,
    provider: CountingProvider,
) -> dict[str, Any]:
    """Use a real captured article URL in a real NEW_BLOG diff."""

    article = _first_live_article(live_content)
    article_fragment = (
        f"<article><h2><a href=\"{article['url']}\">{article['title']}</a></h2>"
        "<p>Captured post content was added for the live URL extraction check.</p>"
        "</article>"
    )
    if "</body>" in live_content:
        current_content = live_content.replace(
            "</body>", f"{article_fragment}</body>", 1
        )
    elif "</html>" in live_content:
        current_content = live_content.replace(
            "</html>", f"{article_fragment}</html>", 1
        )
    else:
        current_content = f"{live_content}{article_fragment}"
    previous_normalized = normalize_content(live_content)
    current_normalized = normalize_content(current_content)
    previous = {
        "id": "000000000000000000000026",
        "content": previous_normalized,
        "content_hash": hash_content(previous_normalized),
    }
    current = {
        "id": "000000000000000000000027",
        "content": current_normalized,
        "content_hash": hash_content(current_normalized),
    }
    change = changes.create_change(
        target["id"],
        previous,
        current,
        change_type="NEW_BLOG",
        narrative_provider=provider,
    )
    if not change.get("detected_url") or change["detected_url"] == target["url"]:
        raise AssertionError(
            f"real NEW_BLOG extraction fell back instead of selecting a specific post: {change!r}"
        )
    if (urlsplit(change["detected_url"]).hostname or "").removeprefix("www.") != (
        urlsplit(article["url"]).hostname or ""
    ).removeprefix("www."):
        raise AssertionError("real NEW_BLOG extraction selected the wrong domain")
    return {
        "change_id": change["id"],
        "source_article_url": article["url"],
        "source_article_title": article["title"],
        "detected_url": change["detected_url"],
        "domain_validation": "passed",
        "liveness_validation": "passed",
        "provider_generate_calls": len(provider.generate_calls),
        "provider_generate_json_calls": len(provider.generate_json_calls),
    }


def _first_live_article(live_content: str) -> dict[str, str]:
    match = re.search(
        r'<div class="category-post">.*?'
        r'<h2 class="category-post-title"><a href=(?:"([^"]+)"|([^\s>]+))[^>]*>(.*?)</a>',
        live_content,
        flags=re.DOTALL,
    )
    if match is None:
        raise AssertionError("the live blog capture did not contain a post link")
    return {
        "url": match.group(1) or match.group(2),
        "title": re.sub(r"\s+", " ", match.group(3)).strip(),
        "html": match.group(0),
    }


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
