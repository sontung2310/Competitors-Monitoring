"""Opt-in live Step 1.9 scheduler verification against Atlas.

Run from the repository root with the dedicated Atlas test database configured:

    set -a; source .env.mongodb; set +a
    export MONGODB_DATABASE=competitors_monitoring_test
    RUN_LIVE_SCHEDULER=1 \
      /private/tmp/competitors-monitoring-venv/bin/python -u \
      tests/live_scheduler_verification.py

The script uses real Atlas repositories, real active Lyfe/Brown Bag targets,
and the real MonitoringRunService for successful dispatches. It changes only
the two test targets' scheduling timestamps/intervals during the checks and
restores their original scheduling metadata before exiting.
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.flask.competitors.repository import CompetitorRepository
from backend.flask.database.connection import MongoSettings, connect_database
from backend.flask.scheduler.service import SchedulerService
from backend.flask.snapshot.repository import SnapshotRepository
from backend.flask.website_monitoring.repository import (
    MonitoringRunRepository,
    MonitoringTargetRepository,
)
from backend.flask.website_monitoring.service import MonitoringRunService, fetch_page


TEST_DATABASE = "competitors_monitoring_test"
USER_ID = "live-verification"
LYFE_URL = "https://www.lyfemarketing.com/"
BROWN_URL = "https://brownbagmarketing.com/"
TARGET_PATH = "/blog"


class _SelectedTargetReader:
    """Delegate active-target selection to Mongo, limited to this live pass."""

    def __init__(self, repository, target_ids):
        self.repository = repository
        self.target_ids = set(target_ids)

    def list_active_targets(self, competitor_id=None):
        return [
            target
            for target in self.repository.list_active_targets(competitor_id)
            if target.get("id") in self.target_ids
        ]


def run_live_verification() -> dict[str, object]:
    """Run the four real-data acceptance checks for the scheduler."""

    if os.environ.get("RUN_LIVE_SCHEDULER") != "1":
        raise SystemExit("Set RUN_LIVE_SCHEDULER=1 to run live scheduler verification")

    settings = MongoSettings.from_env()
    if settings.database_name != TEST_DATABASE:
        raise RuntimeError(
            f"refusing to write outside the dedicated test database {TEST_DATABASE!r}; "
            f"configured database is {settings.database_name!r}"
        )

    logging.basicConfig(level=logging.ERROR)
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

        lyfe_competitor = _find_competitor(competitors, LYFE_URL)
        brown_competitor = _find_competitor(competitors, BROWN_URL)
        lyfe_target = _find_blog_target(targets, lyfe_competitor["id"])
        brown_target = _find_blog_target(targets, brown_competitor["id"])
        original = {
            lyfe_target["id"]: {
                "check_interval_minutes": lyfe_target["check_interval_minutes"],
                "last_checked_at": lyfe_target.get("last_checked_at"),
            },
            brown_target["id"]: {
                "check_interval_minutes": brown_target["check_interval_minutes"],
                "last_checked_at": brown_target.get("last_checked_at"),
            },
        }

        monitoring = MonitoringRunService.from_database(database, fetcher=fetch_page)
        # The shared test database retains an old Elevation target from earlier
        # work. Delegate through the real repository but scope this verification
        # to the two active sites that are in the current standard test set.
        scheduler = SchedulerService(
            _SelectedTargetReader(
                targets,
                [lyfe_target["id"], brown_target["id"]],
            ),
            monitoring.monitor_target,
        )
        now = datetime.now(timezone.utc)

        try:
            due_and_skip = _verify_due_and_not_due(
                scheduler,
                targets,
                runs,
                snapshots,
                lyfe_target,
                brown_target,
                now,
            )
            isolated_failure = _verify_exception_isolation(
                scheduler,
                targets,
                runs,
                snapshots,
                monitoring,
                lyfe_target,
                brown_target,
                now + timedelta(minutes=1),
            )
            independent_intervals = _verify_independent_intervals(
                scheduler,
                targets,
                runs,
                snapshots,
                monitoring,
                lyfe_target,
                brown_target,
                now + timedelta(minutes=2),
            )
        finally:
            for target in (lyfe_target, brown_target):
                targets.update(
                    target["id"],
                    original[target["id"]],
                    competitor_id=target["competitor_id"],
                )

        report = {
            "database": database.name,
            "intervals_before_test": {
                "lyfe": original[lyfe_target["id"]]["check_interval_minutes"],
                "brown_bag": original[brown_target["id"]]["check_interval_minutes"],
            },
            "backfill": "not needed; both values were explicitly 1440 minutes",
            "due_and_not_due": due_and_skip,
            "exception_isolation": isolated_failure,
            "independent_intervals": independent_intervals,
        }
        print(f"database={report['database']}")
        print(f"intervals_before_test={report['intervals_before_test']}")
        print(f"backfill={report['backfill']}")
        print(f"due_and_not_due={report['due_and_not_due']}")
        print(f"exception_isolation={report['exception_isolation']}")
        print(f"independent_intervals={report['independent_intervals']}")
        return report
    finally:
        client.close()


def _verify_due_and_not_due(
    scheduler,
    targets,
    runs,
    snapshots,
    lyfe_target,
    brown_target,
    now,
):
    """Make Lyfe due and Brown Bag recent, then dispatch one real tick."""

    _set_schedule(targets, lyfe_target, interval=1440, last_checked_at=now - timedelta(days=2))
    _set_schedule(targets, brown_target, interval=1440, last_checked_at=now)
    before_runs = _ids(runs.list_for_target(lyfe_target["id"]))
    before_snapshots = _ids(snapshots.list_for_target(lyfe_target["id"]))

    tick = scheduler.run_due_targets(now=now)
    after_runs = _ids(runs.list_for_target(lyfe_target["id"]))
    after_snapshots = _ids(snapshots.list_for_target(lyfe_target["id"]))
    new_runs = sorted(after_runs - before_runs)
    new_snapshots = sorted(after_snapshots - before_snapshots)
    if tick.due_target_ids != [lyfe_target["id"]]:
        raise AssertionError(f"unexpected due targets: {tick.as_dict()!r}")
    if brown_target["id"] not in tick.skipped_target_ids:
        raise AssertionError(f"recent Brown Bag target was not skipped: {tick.as_dict()!r}")
    if tick.succeeded_target_ids != [lyfe_target["id"]]:
        raise AssertionError(f"Lyfe was not successfully dispatched: {tick.as_dict()!r}")
    if len(new_runs) != 1 or len(new_snapshots) != 1:
        raise AssertionError("real due tick did not create one run and snapshot")
    return {
        "due_target_id": lyfe_target["id"],
        "new_run_id": new_runs[0],
        "new_snapshot_id": new_snapshots[0],
        "skipped_target_id": brown_target["id"],
        "due_target_ids": tick.due_target_ids,
        "skipped_target_ids": tick.skipped_target_ids,
    }


def _verify_exception_isolation(
    scheduler,
    targets,
    runs,
    snapshots,
    monitoring,
    lyfe_target,
    brown_target,
    now,
):
    """Fail Lyfe at dispatch and let Brown Bag use the real monitor path."""

    _set_schedule(targets, lyfe_target, interval=1440, last_checked_at=now - timedelta(days=2))
    _set_schedule(targets, brown_target, interval=1440, last_checked_at=now - timedelta(days=2))
    brown_before_runs = _ids(runs.list_for_target(brown_target["id"]))
    brown_before_snapshots = _ids(snapshots.list_for_target(brown_target["id"]))

    def fail_lyfe_and_monitor_brown(target_id):
        if target_id == lyfe_target["id"]:
            raise RuntimeError("forced scheduler verification failure")
        return monitoring.monitor_target(target_id)

    original_monitor = scheduler.monitor_target
    scheduler.monitor_target = fail_lyfe_and_monitor_brown
    try:
        tick = scheduler.run_due_targets(now=now)
    finally:
        scheduler.monitor_target = original_monitor

    brown_new_runs = _ids(runs.list_for_target(brown_target["id"])) - brown_before_runs
    brown_new_snapshots = _ids(snapshots.list_for_target(brown_target["id"])) - brown_before_snapshots
    failure = next(
        failure
        for failure in tick.failed_targets
        if failure["target_id"] == lyfe_target["id"]
    )
    if brown_target["id"] not in tick.succeeded_target_ids:
        raise AssertionError(f"Brown Bag did not complete after Lyfe failure: {tick.as_dict()!r}")
    if len(brown_new_runs) != 1 or len(brown_new_snapshots) != 1:
        raise AssertionError("Brown Bag did not create its real run and snapshot")
    return {
        "failed_target_id": lyfe_target["id"],
        "failure_message": failure["error_message"],
        "healthy_target_id": brown_target["id"],
        "healthy_run_id": sorted(brown_new_runs)[0],
        "healthy_snapshot_id": sorted(brown_new_snapshots)[0],
        "succeeded_target_ids": tick.succeeded_target_ids,
    }


def _verify_independent_intervals(
    scheduler,
    targets,
    runs,
    snapshots,
    monitoring,
    lyfe_target,
    brown_target,
    now,
):
    """Use different intervals: Lyfe due, Brown Bag not due."""

    _set_schedule(targets, lyfe_target, interval=60, last_checked_at=now - timedelta(hours=2))
    _set_schedule(targets, brown_target, interval=1440, last_checked_at=now)
    lyfe_before_runs = _ids(runs.list_for_target(lyfe_target["id"]))
    brown_before_runs = _ids(runs.list_for_target(brown_target["id"]))

    calls = []

    def record_and_monitor(target_id):
        calls.append(target_id)
        return monitoring.monitor_target(target_id)

    original_monitor = scheduler.monitor_target
    scheduler.monitor_target = record_and_monitor
    try:
        tick = scheduler.run_due_targets(now=now)
    finally:
        scheduler.monitor_target = original_monitor

    lyfe_new_runs = _ids(runs.list_for_target(lyfe_target["id"])) - lyfe_before_runs
    brown_new_runs = _ids(runs.list_for_target(brown_target["id"])) - brown_before_runs
    if calls != [lyfe_target["id"]] or brown_target["id"] not in tick.skipped_target_ids:
        raise AssertionError(f"intervals were not evaluated independently: {tick.as_dict()!r}")
    if len(lyfe_new_runs) != 1 or brown_new_runs:
        raise AssertionError("different target intervals produced incorrect dispatch")
    return {
        "intervals": {
            lyfe_target["id"]: 60,
            brown_target["id"]: 1440,
        },
        "called_target_ids": calls,
        "due_target_ids": tick.due_target_ids,
        "skipped_target_ids": tick.skipped_target_ids,
        "lyfe_run_id": sorted(lyfe_new_runs)[0],
    }


def _set_schedule(repository, target, *, interval, last_checked_at):
    updated = repository.update(
        target["id"],
        {
            "check_interval_minutes": interval,
            "last_checked_at": last_checked_at,
        },
        competitor_id=target["competitor_id"],
    )
    if updated is None:
        raise AssertionError(f"could not update live target {target['id']}")


def _ids(rows):
    return {row["id"] for row in rows}


def _find_competitor(repository, website_url):
    for competitor in repository.list_for_user(USER_ID):
        if competitor.get("website_url") == website_url:
            return competitor
    raise AssertionError(f"missing live-verification competitor: {website_url}")


def _find_blog_target(repository, competitor_id):
    for target in repository.list_active_targets(competitor_id):
        path = urlsplit(str(target.get("url", ""))).path.rstrip("/") or "/"
        if path == TARGET_PATH:
            return target
    raise AssertionError(f"missing active /blog target for competitor {competitor_id}")


if __name__ == "__main__":
    run_live_verification()
