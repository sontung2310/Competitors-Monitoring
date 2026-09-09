"""Opt-in live Step 1.14 simulated-change verification.

Run from the repository root with the dedicated Atlas test database and the
OpenAI provider configured:

    set -a; source .env.mongodb; set +a
    export MONGODB_DATABASE=competitors_monitoring_test
    RUN_LIVE_SIMULATED_CHANGE=1 \
      /private/tmp/cm-venv.cckOER/bin/python -u \
      tests/live_simulated_change_verification.py

This script is intentionally read-only against Atlas. It fetches real content,
reads an existing historical snapshot for the blog baseline, and invokes only
the in-memory simulation functions. It never calls monitor_target,
create_snapshot, or create_change.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.flask.change_detection.repository import ChangeRepository
from backend.flask.competitors.repository import CompetitorRepository
from backend.flask.database.connection import MongoSettings, connect_database
from backend.flask.llm_provider import OpenAIProvider
from backend.flask.snapshot.repository import SnapshotRepository
from backend.flask.snapshot.storage import SnapshotStorage
from backend.flask.website_monitoring.repository import (
    MonitoringRunRepository,
    MonitoringTargetRepository,
)
from backend.flask.website_monitoring.service import fetch_page
from backend.flask.website_monitoring.simulated_verification import (
    simulate_blog_change,
    simulate_product_listing_change,
)


TEST_DATABASE = "competitors_monitoring_test"
USER_ID = "live-verification"
LYFE_WEBSITE_URL = "https://www.lyfemarketing.com/"
JD_WEBSITE_URL = "https://www.jd-sports.com.au/"
LYFE_BLOG_PATH = "/blog"
JD_SALE_PATH = "/sale"


def run_live_verification() -> dict[str, Any]:
    """Run both LLM-backed simulations and prove Atlas counts do not change."""

    if os.environ.get("RUN_LIVE_SIMULATED_CHANGE") != "1":
        raise SystemExit(
            "Set RUN_LIVE_SIMULATED_CHANGE=1 to run live simulated-change verification"
        )

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
        competitors = CompetitorRepository.from_database(database)
        targets = MonitoringTargetRepository.from_database(database)
        snapshots = SnapshotRepository.from_database(database)
        changes = ChangeRepository.from_database(database)
        runs = MonitoringRunRepository.from_database(database)
        storage = SnapshotStorage()
        before_counts = _counts(competitors, targets, snapshots, changes, runs)

        provider = OpenAIProvider.from_env()
        lyfe = _find_competitor(competitors, LYFE_WEBSITE_URL)
        jd = _find_competitor(competitors, JD_WEBSITE_URL)
        lyfe_target = _find_active_target(targets, lyfe["id"], LYFE_BLOG_PATH)
        jd_target = _find_active_target(targets, jd["id"], JD_SALE_PATH)
        if lyfe_target is None:
            raise AssertionError("no active Lyfe BLOG target was found")
        if jd_target is None or jd_target.get("page_type") != "PRODUCT_LISTING":
            raise AssertionError("no active JD PRODUCT_LISTING target was found")

        lyfe_fetched = fetch_page(lyfe_target["url"])
        lyfe_previous = _latest_snapshot(
            snapshots,
            storage,
            lyfe_target["id"],
        )
        blog_result = simulate_blog_change(
            lyfe_fetched.content,
            provider,
            previous_snapshot=lyfe_previous,
        )
        blog_events = blog_result.process_result.change_events
        if not blog_result.process_result.changed:
            raise AssertionError("LLM blog mutation was not detected")
        if [event["change_type"] for event in blog_events] != ["NEW_BLOG"]:
            raise AssertionError(
                f"expected one NEW_BLOG event, got "
                f"{[event.get('change_type') for event in blog_events]}"
            )

        jd_fetched = fetch_page(jd_target["url"])
        product_result = simulate_product_listing_change(jd_fetched.content, provider)
        product_events = list(product_result.events)
        if [event["change_type"] for event in product_events] != [
            "NEW_PRODUCT",
            "PRODUCT_REMOVED",
            "PRICE_CHANGE",
        ]:
            raise AssertionError(
                f"expected the three product event types, got "
                f"{[event.get('change_type') for event in product_events]}"
            )

        after_counts = _counts(competitors, targets, snapshots, changes, runs)
        if after_counts != before_counts:
            raise AssertionError(
                f"simulated verification changed Atlas counts: "
                f"before={before_counts} after={after_counts}"
            )

        report = {
            "database": database.name,
            "before_counts": before_counts,
            "after_counts": after_counts,
            "counts_unchanged": before_counts == after_counts,
            "lyfe_target_id": lyfe_target["id"],
            "lyfe_fetch": f"{lyfe_fetched.fetch_method}/{lyfe_fetched.http_status}",
            "lyfe_baseline_snapshot_id": (
                lyfe_previous.get("id") if lyfe_previous else None
            ),
            "blog_changed": blog_result.process_result.changed,
            "blog_event_count": len(blog_events),
            "blog_event": {
                "change_type": blog_events[0]["change_type"],
                "summary": blog_events[0]["summary"],
            },
            "jd_target_id": jd_target["id"],
            "jd_fetch": f"{jd_fetched.fetch_method}/{jd_fetched.http_status}",
            "jd_product_count": len(product_result.original_products),
            "jd_mutation_plan": dict(product_result.mutation_plan),
            "product_event_count": len(product_events),
            "product_events": [
                {
                    "change_type": event["change_type"],
                    "summary": event["summary"],
                }
                for event in product_events
            ],
        }
        _print_report(report)
        return report
    finally:
        client.close()


def _counts(*repositories: Any) -> dict[str, int]:
    names = ("competitors", "monitoring_targets", "snapshots", "changes", "monitoring_runs")
    return {name: repository.count() for name, repository in zip(names, repositories)}


def _find_competitor(
    repository: CompetitorRepository,
    website_url: str,
) -> dict[str, Any]:
    for competitor in repository.list_for_user(USER_ID):
        if competitor.get("website_url") == website_url:
            return competitor
    raise AssertionError(f"no live-verification competitor found for {website_url}")


def _find_active_target(
    repository: MonitoringTargetRepository,
    competitor_id: Any,
    path: str,
) -> dict[str, Any] | None:
    wanted_path = path.rstrip("/") or "/"
    for target in repository.list_active_targets(competitor_id):
        target_path = urlsplit(str(target.get("url", ""))).path.rstrip("/") or "/"
        if target_path == wanted_path:
            return target
    return None


def _latest_snapshot(
    repository: SnapshotRepository,
    storage: SnapshotStorage,
    target_id: Any,
) -> dict[str, Any] | None:
    # Simulations must always build on the latest real baseline.  A tagged
    # simulated snapshot is evidence for a demo, not a monitoring baseline.
    rows = repository.list_for_target(target_id, include_simulated=False)
    if not rows:
        return None
    latest = dict(rows[0])
    latest["content"] = storage.read_snapshot_bytes(
        latest["storage_path"]
    ).decode("utf-8")
    return latest


def _print_report(report: dict[str, Any]) -> None:
    print(f"database={report['database']}")
    print(
        f"atlas_counts_before={report['before_counts']} "
        f"atlas_counts_after={report['after_counts']} "
        f"unchanged={report['counts_unchanged']}"
    )
    print(
        f"lyfe_target_id={report['lyfe_target_id']} "
        f"fetch={report['lyfe_fetch']} "
        f"baseline_snapshot_id={report['lyfe_baseline_snapshot_id']}"
    )
    print(
        f"blog_changed={report['blog_changed']} "
        f"blog_event_count={report['blog_event_count']} "
        f"change_type={report['blog_event']['change_type']} "
        f"summary={report['blog_event']['summary']}"
    )
    print(
        f"jd_target_id={report['jd_target_id']} fetch={report['jd_fetch']} "
        f"product_count={report['jd_product_count']} "
        f"mutation_plan={report['jd_mutation_plan']}"
    )
    print(f"product_event_count={report['product_event_count']}")
    for event in report["product_events"]:
        print(
            f"change_type={event['change_type']} summary={event['summary']}"
        )


if __name__ == "__main__":
    run_live_verification()
