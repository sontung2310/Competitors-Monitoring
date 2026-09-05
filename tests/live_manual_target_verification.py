"""Opt-in live Step 1.10 verification against the dedicated Atlas database.

Run from the repository root after loading the MongoDB connection settings:

    set -a; source .env.mongodb; set +a
    export MONGODB_DATABASE=competitors_monitoring_test
    RUN_LIVE_MANUAL_TARGET=1 python3 -u tests/live_manual_target_verification.py

The positive case uses Brown Bag's public ``/sales-tool`` page, which was
confirmed absent from the existing candidate/target rows before the run.  The
script intentionally leaves the manually-created target and its snapshot in
the dedicated test database as evidence.  The duplicate check uses Lyfe's
existing active ``/blog`` target and must not create another row.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.flask.competitors.repository import CompetitorRepository
from backend.flask.database.connection import MongoSettings, connect_database
from backend.flask.discovery.classification import DeterministicStubClassifier
from backend.flask.discovery.service import DiscoveryError, DiscoveryService
from backend.flask.snapshot.repository import SnapshotRepository
from backend.flask.snapshot.storage import SnapshotStorage
from backend.flask.website_monitoring.repository import MonitoringTargetRepository
from backend.flask.website_monitoring.service import (
    MonitoringRunService,
    fetch_page,
    hash_content,
)


TEST_DATABASE = "competitors_monitoring_test"
USER_ID = "live-verification"
BROWN_URL = "https://brownbagmarketing.com/"
LYFE_URL = "https://www.lyfemarketing.com/"
NEW_PATH = "/sales-tool"
DEAD_PATH = "/this-page-definitely-does-not-exist-for-manual-target-verification-20260905"
BLOG_PATH = "/blog"


def run_live_verification() -> dict[str, object]:
    """Run the four Step 1.10 acceptance checks against Atlas and live HTTP."""

    if os.environ.get("RUN_LIVE_MANUAL_TARGET") != "1":
        raise SystemExit(
            "Set RUN_LIVE_MANUAL_TARGET=1 to run live manual-target verification"
        )

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
        snapshots = SnapshotRepository.from_database(database)
        targets.ensure_indexes()
        snapshots.ensure_indexes()

        brown = _find_competitor(competitors, BROWN_URL)
        lyfe = _find_competitor(competitors, LYFE_URL)
        service = DiscoveryService(
            competitors,
            targets,
            fallback_classifier=DeterministicStubClassifier(),
        )

        existing_new_target = targets.find_by_url(brown["id"], f"{BROWN_URL.rstrip('/')}{NEW_PATH}")
        if existing_new_target is not None:
            raise AssertionError(
                f"selected positive URL is no longer new: {existing_new_target['id']}"
            )

        created = service.add_manual_target(
            brown["id"],
            f"{BROWN_URL.rstrip('/')}{NEW_PATH}/",
        )
        if created["discovery_status"] != "ACTIVE" or created["active"] is not True:
            raise AssertionError("manual target was not created ACTIVE")
        if created["classification_method"] != "MANUAL":
            raise AssertionError("manual target did not record MANUAL classification")
        if created["page_type"] != "OTHER" or created["check_interval_minutes"] != 1440:
            raise AssertionError(
                "unmatched manual page did not receive the documented OTHER/daily default"
            )
        active_ids = {target["id"] for target in service.list_active_targets(brown["id"])}
        if created["id"] not in active_ids:
            raise AssertionError("manual target is missing from list_active_targets")

        monitoring = MonitoringRunService.from_database(database, fetcher=fetch_page)
        before_snapshots = snapshots.list_for_target(created["id"])
        monitored = monitoring.monitor_target(created["id"])
        run = monitored["run"]
        snapshot = monitored["snapshot"]
        if run["status"] != "SUCCESS" or snapshot is None:
            raise AssertionError("manual target did not complete with a snapshot")
        stored_bytes = SnapshotStorage().read_snapshot_bytes(snapshot["storage_path"])
        recomputed_hash = hash_content(stored_bytes.decode("utf-8"))
        if recomputed_hash != snapshot["content_hash"]:
            raise AssertionError("manual target snapshot hash could not be re-derived")
        after_snapshots = snapshots.list_for_target(created["id"])
        if len(after_snapshots) != len(before_snapshots) + 1:
            raise AssertionError("manual target monitoring did not create one snapshot")

        dead_url = f"{BROWN_URL.rstrip('/')}{DEAD_PATH}"
        if targets.find_by_url(brown["id"], dead_url) is not None:
            raise AssertionError("dead-url test row already exists")
        try:
            service.add_manual_target(brown["id"], dead_url)
        except DiscoveryError as exc:
            dead_error = str(exc)
        else:
            raise AssertionError("dead URL was accepted as a manual target")
        if targets.find_by_url(brown["id"], dead_url) is not None:
            raise AssertionError("dead URL created a monitoring target")

        lyfe_blog = _find_blog_target(targets, lyfe["id"])
        brown_active_before_duplicate = targets.list_active_targets(brown["id"])
        lyfe_active_before_duplicate = targets.list_active_targets(lyfe["id"])
        duplicate = service.add_manual_target(
            lyfe["id"],
            f"{LYFE_URL.rstrip('/')}{BLOG_PATH}/",
        )
        lyfe_active_after_duplicate = targets.list_active_targets(lyfe["id"])
        if duplicate["id"] != lyfe_blog["id"]:
            raise AssertionError("active duplicate did not return the existing Lyfe target")
        if len(lyfe_active_after_duplicate) != len(lyfe_active_before_duplicate):
            raise AssertionError("active duplicate changed the Lyfe active-target count")
        if len(targets.list_active_targets(brown["id"])) != len(brown_active_before_duplicate):
            raise AssertionError("duplicate check unexpectedly changed Brown's active count")

        report = {
            "database": database.name,
            "competitor_id": brown["id"],
            "new_url": created["url"],
            "new_target_id": created["id"],
            "new_page_type": created["page_type"],
            "new_check_interval_minutes": created["check_interval_minutes"],
            "new_active": created["active"],
            "monitor_run_id": run["id"],
            "monitor_run_status": run["status"],
            "snapshot_id": snapshot["id"],
            "snapshot_hash": snapshot["content_hash"],
            "snapshot_hash_rederived": recomputed_hash,
            "dead_url": dead_url,
            "dead_url_error": dead_error,
            "dead_url_target_exists": False,
            "duplicate_existing_target_id": duplicate["id"],
            "duplicate_created_new_row": False,
        }
        _print_report(report)
        return report
    finally:
        client.close()


def _find_competitor(repository: CompetitorRepository, website_url: str) -> dict[str, object]:
    for competitor in repository.list_for_user(USER_ID):
        if competitor.get("website_url") == website_url:
            return competitor
    raise AssertionError(f"no live-verification competitor found for {website_url}")


def _find_blog_target(
    repository: MonitoringTargetRepository,
    competitor_id: object,
) -> dict[str, object]:
    for target in repository.list_active_targets(competitor_id):
        if target.get("page_type") == "BLOG":
            return target
    raise AssertionError(f"no active BLOG target found for competitor {competitor_id}")


def _print_report(report: dict[str, object]) -> None:
    print(f"database={report['database']}")
    print(
        f"new_target_id={report['new_target_id']} url={report['new_url']} "
        f"page_type={report['new_page_type']} "
        f"check_interval_minutes={report['new_check_interval_minutes']} "
        f"active={report['new_active']}"
    )
    print(
        f"monitor_run_id={report['monitor_run_id']} status={report['monitor_run_status']} "
        f"snapshot_id={report['snapshot_id']} hash={report['snapshot_hash']} "
        f"rederived_hash={report['snapshot_hash_rederived']}"
    )
    print(
        f"dead_url={report['dead_url']} target_exists={report['dead_url_target_exists']} "
        f"error={report['dead_url_error']}"
    )
    print(
        f"duplicate_existing_target_id={report['duplicate_existing_target_id']} "
        f"duplicate_created_new_row={report['duplicate_created_new_row']}"
    )


if __name__ == "__main__":
    run_live_verification()
