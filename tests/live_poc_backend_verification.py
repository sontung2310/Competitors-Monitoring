"""Opt-in read-only live verification for the company-scoped backend PoC.

Run from the repository root with the dedicated Atlas test database and the
OpenAI provider configured:

    RUN_LIVE_POC=1 MONGODB_DATABASE=competitors_monitoring_test \
      python -u tests/live_poc_backend_verification.py

The verifier reads existing company, competitor, target, and real-baseline
records, then fetches the two live pages. Simulated content is processed by
the real simulation and change-service boundaries using in-memory snapshots
and changes. It never calls the persistence-enabled ``/simulate`` endpoint,
``monitor_target``, or any repository write method.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.flask.change_detection.repository import ChangeRepository
from backend.flask.change_detection.service import ChangeService
from backend.flask.competitors.repository import CompetitorRepository
from backend.flask.database.connection import MongoSettings, connect_database
from backend.flask.llm_provider import OpenAIProvider
from backend.flask.snapshot.repository import SnapshotRepository
from backend.flask.snapshot.storage import SnapshotStorage
from backend.flask.website_monitoring.repository import (
    MonitoringRunRepository,
    MonitoringTargetRepository,
)
from backend.flask.website_monitoring.service import (
    fetch_page,
    hash_content,
    normalize_content,
)
from backend.flask.website_monitoring.simulated_verification import (
    simulate_blog_change,
    simulate_product_mutation,
)


TEST_DATABASE = "competitors_monitoring_test"
LYFE_WEBSITE_URL = "https://www.lyfemarketing.com/"
JD_WEBSITE_URL = "https://www.jd-sports.com.au/"
LYFE_BLOG_PATH = "/blog"
JD_SALE_PATH = "/sale"
TEST_SCAFFOLDING_MARKERS = re.compile(
    r"(forced narrative|verification marker|ton[- ]?21|synthetic product|test fixture)",
    re.IGNORECASE,
)


class _InMemoryChangeRepository:
    """Minimal repository boundary for verification-only change records."""

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def create(self, **values: Any) -> dict[str, Any]:
        record = dict(values)
        record["id"] = f"in-memory-{len(self.records) + 1}"
        self.records.append(record)
        return record


def run_live_verification() -> dict[str, Any]:
    """Run live read checks plus in-memory blog and product simulations."""

    if os.environ.get("RUN_LIVE_POC") != "1":
        raise SystemExit("Set RUN_LIVE_POC=1 to run live PoC verification")

    settings = MongoSettings.from_env()
    if settings.database_name != TEST_DATABASE:
        raise RuntimeError(
            f"refusing to inspect outside {TEST_DATABASE!r}; "
            f"configured database is {settings.database_name!r}"
        )

    mongo_client, database = connect_database(
        settings,
        serverSelectionTimeoutMS=15_000,
    )
    try:
        mongo_client.admin.command("ping")
        competitors = CompetitorRepository.from_database(database)
        targets = MonitoringTargetRepository.from_database(database)
        snapshots = SnapshotRepository.from_database(database)
        changes = ChangeRepository.from_database(database)
        runs = MonitoringRunRepository.from_database(database)
        storage = SnapshotStorage()
        before_counts = _counts(competitors, targets, snapshots, changes, runs)

        lyfe = _find_competitor(competitors, LYFE_WEBSITE_URL)
        jd = _find_competitor(competitors, JD_WEBSITE_URL)
        lyfe_target = _find_active_target(targets, lyfe["id"], LYFE_BLOG_PATH)
        jd_target = _find_active_target(targets, jd["id"], JD_SALE_PATH)
        if lyfe_target is None:
            raise AssertionError("no active Lyfe BLOG target was found")
        if jd_target is None or jd_target.get("page_type") != "PRODUCT_LISTING":
            raise AssertionError("no active JD PRODUCT_LISTING target was found")

        provider = OpenAIProvider.from_env()
        lyfe_fetch = fetch_page(lyfe_target["url"])
        lyfe_baseline = _latest_real_snapshot(
            snapshots,
            storage,
            lyfe_target["id"],
        )
        blog_result = simulate_blog_change(
            lyfe_fetch.content,
            provider,
            previous_snapshot=lyfe_baseline,
        )
        blog_event = blog_result.process_result.change_events[0]
        if blog_event.get("change_type") != "NEW_BLOG":
            raise AssertionError(f"unexpected blog event: {blog_event!r}")

        in_memory_changes = _InMemoryChangeRepository()
        change_service = ChangeService(
            in_memory_changes,
            targets,
            narrative_provider_factory=lambda: provider,
            detected_url_liveness_checker=fetch_page,
        )
        blog_snapshot = _in_memory_snapshot(
            "in-memory-blog-before",
            lyfe_fetch.content,
        )
        mutated_blog_snapshot = _in_memory_snapshot(
            "in-memory-blog-after",
            blog_result.mutated_content,
        )
        blog_change = change_service.create_change(
            lyfe_target["id"],
            blog_snapshot,
            mutated_blog_snapshot,
            change_type=blog_event["change_type"],
            summary=blog_event["summary"],
            is_simulated=True,
        )
        narrative = blog_change.get("narrative_summary") or ""
        if TEST_SCAFFOLDING_MARKERS.search(narrative):
            raise AssertionError(
                f"generated narrative contains test scaffolding: {narrative!r}"
            )

        jd_fetch = fetch_page(jd_target["url"])
        product_result = simulate_product_mutation(
            jd_fetch.content,
            provider,
            mutation_type="NEW_PRODUCT",
        )
        product_event = product_result.events[0]
        if product_event.get("change_type") != "NEW_PRODUCT":
            raise AssertionError(f"unexpected product event: {product_event!r}")

        after_counts = _counts(competitors, targets, snapshots, changes, runs)
        if after_counts != before_counts:
            raise AssertionError(
                f"read-only PoC verification changed Atlas counts: "
                f"before={before_counts} after={after_counts}"
            )

        report = {
            "database": database.name,
            "before_counts": before_counts,
            "after_counts": after_counts,
            "counts_unchanged": before_counts == after_counts,
            "persisted_test_records_created": 0,
            "in_memory_change_ids": [record["id"] for record in in_memory_changes.records],
            "lyfe_target_id": lyfe_target["id"],
            "lyfe_fetch": f"{lyfe_fetch.fetch_method}/{lyfe_fetch.http_status}",
            "lyfe_baseline_snapshot_id": lyfe_baseline["id"],
            "blog_change_type": blog_change["change_type"],
            "blog_narrative": narrative,
            "blog_narrative_test_scaffolding_markers": sorted(
                set(match.group(0) for match in TEST_SCAFFOLDING_MARKERS.finditer(narrative))
            ),
            "jd_target_id": jd_target["id"],
            "jd_fetch": f"{jd_fetch.fetch_method}/{jd_fetch.http_status}",
            "jd_product_event": {
                "change_type": product_event["change_type"],
                "summary": product_event["summary"],
            },
        }
        _print_report(report)
        return report
    finally:
        mongo_client.close()


def _counts(*repositories: Any) -> dict[str, int]:
    names = ("competitors", "monitoring_targets", "snapshots", "changes", "monitoring_runs")
    return {name: repository.count() for name, repository in zip(names, repositories)}


def _find_competitor(
    repository: CompetitorRepository,
    website_url: str,
) -> dict[str, Any]:
    wanted_host = urlsplit(website_url).netloc
    for competitor in repository.list_all(active=True):
        if urlsplit(str(competitor.get("website_url", ""))).netloc == wanted_host:
            return competitor
    raise AssertionError(f"no active competitor matched {website_url!r}")


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


def _latest_real_snapshot(
    repository: SnapshotRepository,
    storage: SnapshotStorage,
    target_id: Any,
) -> dict[str, Any]:
    rows = repository.list_for_target(target_id, include_simulated=False)
    if not rows:
        raise AssertionError(f"no real baseline snapshot for {target_id!r}")
    snapshot = dict(rows[0])
    snapshot["content"] = storage.read_snapshot_bytes(
        snapshot["storage_path"]
    ).decode("utf-8")
    return snapshot


def _in_memory_snapshot(snapshot_id: str, content: str) -> dict[str, str]:
    normalized = normalize_content(content)
    return {
        "id": snapshot_id,
        "content": normalized,
        "content_hash": hash_content(normalized),
    }


def _print_report(report: dict[str, Any]) -> None:
    print(f"database={report['database']}")
    print(
        f"atlas_counts_before={report['before_counts']} "
        f"atlas_counts_after={report['after_counts']} "
        f"unchanged={report['counts_unchanged']}"
    )
    print(f"persisted_test_records_created={report['persisted_test_records_created']}")
    print(f"in_memory_change_ids={report['in_memory_change_ids']}")
    print(
        f"lyfe_target_id={report['lyfe_target_id']} fetch={report['lyfe_fetch']} "
        f"baseline_snapshot_id={report['lyfe_baseline_snapshot_id']}"
    )
    print(
        f"blog_change_type={report['blog_change_type']} "
        f"narrative={report['blog_narrative']!r} "
        f"narrative_test_scaffolding_markers="
        f"{report['blog_narrative_test_scaffolding_markers']}"
    )
    print(
        f"jd_target_id={report['jd_target_id']} fetch={report['jd_fetch']} "
        f"product_event={report['jd_product_event']}"
    )


if __name__ == "__main__":
    run_live_verification()
