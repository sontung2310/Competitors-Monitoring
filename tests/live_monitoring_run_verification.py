"""Opt-in live Step 1.7 verification against Atlas and Lyfe's active /blog target.

Run from the repository root with the dedicated Atlas test database configured:

    RUN_LIVE_MONITORING=1 \
      /private/tmp/competitors-monitoring-venv/bin/python -u \
      tests/live_monitoring_run_verification.py

The success path uses the real HTTP fetcher. The failure path injects a real
fetch-layer exception into ``monitor_target`` so the repository-backed run
failure and snapshot-preservation path are exercised without altering a live
website or relying on a fabricated database assertion. The script creates one
real run and one real snapshot on each invocation and does not delete data.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.flask.change_detection.repository import ChangeRepository
from backend.flask.competitors.repository import CompetitorRepository
from backend.flask.database.connection import MongoSettings, connect_database
from backend.flask.website_monitoring.repository import (
    MonitoringRunRepository,
    MonitoringTargetRepository,
)
from backend.flask.website_monitoring.service import (
    MonitoringError,
    MonitoringRunService,
    fetch_page,
)
from backend.flask.snapshot.repository import SnapshotRepository
from backend.flask.snapshot.storage import SnapshotStorage


TEST_DATABASE = "competitors_monitoring_test"
USER_ID = "live-verification"
WEBSITE_URL = "https://www.lyfemarketing.com/"
TARGET_PATH = "/blog"


def run_live_verification() -> dict[str, object]:
    """Run one real success and one injected-failure monitoring attempt."""

    if os.environ.get("RUN_LIVE_MONITORING") != "1":
        raise SystemExit("Set RUN_LIVE_MONITORING=1 to run live monitoring verification")

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
        runs = MonitoringRunRepository.from_database(database)
        snapshots = SnapshotRepository.from_database(database)
        changes = ChangeRepository.from_database(database)
        runs.ensure_indexes()
        snapshots.ensure_indexes()
        changes.ensure_indexes()

        competitor = _find_competitor(competitors)
        target = _find_active_target(
            targets.list_active_targets(competitor["id"]),
        )
        if target is None:
            raise AssertionError(f"active target {TARGET_PATH!r} was not found")

        before_snapshots = snapshots.list_for_target(target["id"])
        before_changes = changes.list_for_target(target["id"])
        if not before_snapshots:
            raise AssertionError(
                "the real Lyfe target has no prior snapshot; the negative hash case "
                "cannot be verified"
            )
        previous = before_snapshots[0]

        success_service = MonitoringRunService.from_database(
            database,
            fetcher=fetch_page,
        )
        success = success_service.monitor_target(target["id"])
        success_run = success["run"]
        success_snapshot = success["snapshot"]
        if success_run["status"] != MonitoringRunRepository.SUCCESS:
            raise AssertionError(f"success run ended as {success_run['status']!r}")
        if success_snapshot is None:
            raise AssertionError("successful run did not create a snapshot")

        after_snapshots = snapshots.list_for_target(target["id"])
        after_changes = changes.list_for_target(target["id"])
        if len(after_snapshots) != len(before_snapshots) + 1:
            raise AssertionError(
                f"expected one new snapshot, before={len(before_snapshots)} "
                f"after={len(after_snapshots)}"
            )
        if len(after_changes) != len(before_changes):
            raise AssertionError(
                "Lyfe /blog changed during the live check; a change record was created"
            )
        if previous["content_hash"] != success_snapshot["content_hash"]:
            raise AssertionError("Lyfe /blog hashes differed during the live negative case")

        valid_snapshot_before_failure = snapshots.get(success_snapshot["id"])
        valid_content_before_failure = SnapshotStorage().read_snapshot_bytes(
            valid_snapshot_before_failure["storage_path"]
        )
        target_before_failure = targets.get(target["id"])

        def failing_fetch(url: str):
            raise MonitoringError("simulated transient fetch outage for verification")

        failure_service = MonitoringRunService.from_database(
            database,
            fetcher=failing_fetch,
        )
        failure = failure_service.monitor_target(target["id"])
        failure_run = failure["run"]
        if failure_run["status"] != MonitoringRunRepository.FAILED:
            raise AssertionError(f"failure run ended as {failure_run['status']!r}")
        if not failure_run.get("error_message"):
            raise AssertionError("failure run has no useful error_message")

        after_failure_snapshots = snapshots.list_for_target(target["id"])
        if len(after_failure_snapshots) != len(after_snapshots):
            raise AssertionError("failed run created a snapshot")
        valid_snapshot_after_failure = snapshots.get(success_snapshot["id"])
        valid_content_after_failure = SnapshotStorage().read_snapshot_bytes(
            valid_snapshot_after_failure["storage_path"]
        )
        if valid_snapshot_after_failure != valid_snapshot_before_failure:
            raise AssertionError("failed run modified the prior snapshot metadata")
        if valid_content_after_failure != valid_content_before_failure:
            raise AssertionError("failed run modified the prior snapshot content")

        target_after_failure = targets.get(target["id"])
        if target_after_failure["last_checked_at"] == target_before_failure["last_checked_at"]:
            raise AssertionError("failed run did not update last_checked_at")
        if target_after_failure["last_changed_at"] != target_before_failure["last_changed_at"]:
            raise AssertionError("unchanged content updated last_changed_at")

        report = {
            "database": database.name,
            "competitor_id": competitor["id"],
            "target_id": target["id"],
            "target_url": target["url"],
            "previous_snapshot_id": previous["id"],
            "previous_hash": previous["content_hash"],
            "success_run_id": success_run["id"],
            "success_run_status": success_run["status"],
            "success_snapshot_id": success_snapshot["id"],
            "success_snapshot_hash": success_snapshot["content_hash"],
            "changes_before": len(before_changes),
            "changes_after_success": len(after_changes),
            "failure_run_id": failure_run["id"],
            "failure_run_status": failure_run["status"],
            "failure_error_message": failure_run["error_message"],
            "snapshot_count_after_failure": len(after_failure_snapshots),
            "last_checked_updated_on_failure": True,
            "last_changed_unchanged": True,
        }
        _print_report(report)
        return report
    finally:
        client.close()


def _find_competitor(repository: CompetitorRepository) -> dict[str, object]:
    for competitor in repository.list_for_user(USER_ID):
        if competitor.get("website_url") == WEBSITE_URL:
            return competitor
    raise AssertionError(f"no live-verification competitor found for {WEBSITE_URL}")


def _find_active_target(
    rows: list[dict[str, object]],
) -> dict[str, object] | None:
    normalized_path = TARGET_PATH.rstrip("/") or "/"
    for row in rows:
        row_path = urlsplit(str(row.get("url", ""))).path.rstrip("/") or "/"
        if row_path == normalized_path:
            return row
    return None


def _print_report(report: dict[str, object]) -> None:
    print(f"database={report['database']}")
    print(
        f"target_id={report['target_id']} target={report['target_url']} "
        f"previous_snapshot_id={report['previous_snapshot_id']} "
        f"previous_hash={report['previous_hash']}"
    )
    print(
        f"success_run_id={report['success_run_id']} status={report['success_run_status']} "
        f"snapshot_id={report['success_snapshot_id']} "
        f"hash={report['success_snapshot_hash']} "
        f"changes_before={report['changes_before']} "
        f"changes_after_success={report['changes_after_success']}"
    )
    print(
        f"failure_run_id={report['failure_run_id']} status={report['failure_run_status']} "
        f"error={report['failure_error_message']} "
        f"snapshots_after_failure={report['snapshot_count_after_failure']}"
    )
    print(
        f"last_checked_updated_on_failure={report['last_checked_updated_on_failure']} "
        f"last_changed_unchanged={report['last_changed_unchanged']}"
    )


if __name__ == "__main__":
    run_live_verification()
