"""Opt-in live Layer 2 verification against Atlas and three real websites.

Run from the repository root with a dedicated Atlas test database configured:

    set -a; source .env.mongodb; set +a
    export MONGODB_DATABASE=competitors_monitoring_test
    RUN_LIVE_MONITORING=1 \
      /private/tmp/competitors-monitoring-venv/bin/python -u \
      tests/live_monitoring_verification.py

This script intentionally uses the real competitor and monitoring-target
repositories. It discovers and persists candidates, activates one target per
site through DiscoveryService, then performs two quick fetch/normalize/hash
passes. It never writes snapshots, changes, or monitoring-run records.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.flask.competitors.repository import CompetitorRepository
from backend.flask.database.connection import MongoSettings, connect_database
from backend.flask.discovery.classification import DeterministicStubClassifier
from backend.flask.discovery.service import DiscoveryService
from backend.flask.website_monitoring.service import (
    compare_hashes,
    fetch_page,
    hash_content,
    normalize_content,
)
from backend.flask.website_monitoring.repository import MonitoringTargetRepository


TEST_DATABASE = "competitors_monitoring_test"
USER_ID = "live-verification"
SITES = (
    ("lyfemarketing.com", "LYFE Marketing", "https://www.lyfemarketing.com/", "/blog"),
    ("brownbagmarketing.com", "Brown Bag Marketing", "https://brownbagmarketing.com/", "/blog"),
    # /blog-posts is a discovered index candidate, but the live site currently
    # returns 404 for it. Use a valid suggested target for the fetch/hash check.
    ("elevationmarketing.au", "Elevation Marketing", "https://elevationmarketing.au/", "/about-us"),
)


def run_live_verification() -> list[dict[str, object]]:
    """Run the real persistence and fetch/hash checks for every test site."""

    if os.environ.get("RUN_LIVE_MONITORING") != "1":
        raise SystemExit("Set RUN_LIVE_MONITORING=1 to run live verification")

    settings = MongoSettings.from_env()
    if settings.database_name != TEST_DATABASE:
        raise RuntimeError(
            f"refusing to write outside the dedicated test database {TEST_DATABASE!r}; "
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
        competitors.ensure_indexes()
        targets.ensure_indexes()

        reports: list[dict[str, object]] = []
        for label, name, website_url, target_path in SITES:
            competitor = _get_or_create_competitor(
                competitors,
                name=name,
                website_url=website_url,
            )
            service = DiscoveryService(
                competitors,
                targets,
                fallback_classifier=DeterministicStubClassifier(),
            )
            discovered = service.discover_website(
                competitor["id"],
                user_id=USER_ID,
            )
            summary = service.last_summary
            if summary is None:
                raise AssertionError(f"{label}: discovery returned no summary")

            candidate = _find_path(
                targets.list_for_competitor(competitor["id"]),
                target_path,
            )
            if candidate is None:
                raise AssertionError(
                    f"{label}: discovered target {target_path!r} was not persisted; "
                    f"suggested paths={_suggested_paths(discovered)}"
                )
            if candidate.get("discovery_status") != "ACTIVE":
                if candidate.get("discovery_status") != "SUGGESTED":
                    raise AssertionError(
                        f"{label}: target {candidate['url']!r} is not activatable: "
                        f"{candidate.get('discovery_status')!r}"
                    )
                candidate = service.activate_candidate(candidate["id"])

            active_targets = service.list_active_targets(competitor["id"])
            active_ids = {target["id"] for target in active_targets}
            if candidate["id"] not in active_ids:
                raise AssertionError(
                    f"{label}: activated target {candidate['id']!r} was not returned "
                    "by list_active_targets"
                )

            first = fetch_page(candidate["url"])
            second = fetch_page(candidate["url"])
            first_hash = hash_content(normalize_content(first.content))
            second_hash = hash_content(normalize_content(second.content))
            stable = compare_hashes(first_hash, second_hash)
            if not stable:
                raise AssertionError(
                    f"{label}: quick successive normalized hashes differ: "
                    f"{first_hash} != {second_hash}"
                )

            rows = targets.list_for_competitor(competitor["id"])
            report = {
                "label": label,
                "competitor_id": competitor["id"],
                "target_id": candidate["id"],
                "target_url": candidate["url"],
                "discovered_rows": len(discovered),
                "total_rows": len(rows),
                "suggested": sum(row.get("discovery_status") == "SUGGESTED" for row in rows),
                "discarded": sum(row.get("discovery_status") == "DISCARDED" for row in rows),
                "active": len(active_targets),
                "fetch_1_method": first.fetch_method,
                "fetch_1_status": first.http_status,
                "fetch_1_hash": first_hash,
                "fetch_2_method": second.fetch_method,
                "fetch_2_status": second.http_status,
                "fetch_2_hash": second_hash,
                "hashes_match": stable,
            }
            reports.append(report)
            _print_report(report, summary)
        return reports
    finally:
        client.close()


def _get_or_create_competitor(
    repository: CompetitorRepository,
    *,
    name: str,
    website_url: str,
) -> dict[str, object]:
    for competitor in repository.list_for_user(USER_ID):
        if competitor.get("website_url") == website_url:
            return competitor
    return repository.create(
        user_id=USER_ID,
        name=name,
        website_url=website_url,
    )


def _find_path(rows: list[dict[str, object]], path: str) -> dict[str, object] | None:
    normalized_path = path.rstrip("/") or "/"
    for row in rows:
        candidate_path = urlsplit(str(row.get("url", ""))).path.rstrip("/") or "/"
        if candidate_path == normalized_path:
            return row
    return None


def _suggested_paths(rows: list[dict[str, object]]) -> list[str]:
    return sorted(
        urlsplit(str(row["url"])).path.rstrip("/") or "/"
        for row in rows
        if row.get("discovery_status") == "SUGGESTED"
    )


def _print_report(report: dict[str, object], summary: object) -> None:
    print(f"\n=== {report['label']} ===")
    print(
        f"competitor_id={report['competitor_id']} target_id={report['target_id']} "
        f"target={report['target_url']}"
    )
    print(
        f"discovered={report['discovered_rows']} persisted_total={report['total_rows']} "
        f"suggested={report['suggested']} discarded={report['discarded']} "
        f"active={report['active']}"
    )
    print(
        f"fetch_1={report['fetch_1_method']}/{report['fetch_1_status']} "
        f"hash={report['fetch_1_hash']}"
    )
    print(
        f"fetch_2={report['fetch_2_method']}/{report['fetch_2_status']} "
        f"hash={report['fetch_2_hash']} "
        f"stable={report['hashes_match']}"
    )
    source_breakdown = getattr(summary, "source_breakdown", {})
    print(
        "discovery_summary="
        f"raw={getattr(summary, 'raw_count', '?')} "
        f"normalized={getattr(summary, 'normalized_count', '?')} "
        f"sources={source_breakdown}"
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    run_live_verification()
