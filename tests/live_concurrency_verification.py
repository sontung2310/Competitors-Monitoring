"""Opt-in live Step 1.8 concurrency/stale-run verification against Atlas.

Run from the repository root with the dedicated Atlas test database configured:

    set -a; source .env.mongodb; set +a
    export MONGODB_DATABASE=competitors_monitoring_test
    RUN_LIVE_CONCURRENCY=1 \
      /private/tmp/competitors-monitoring-venv/bin/python -u \
      tests/live_concurrency_verification.py

The script uses real Atlas repositories and real active Lyfe/Brown Bag targets.
It deliberately injects only coordination around the real fetcher so the
threads overlap deterministically; every claim, run, snapshot, and status
transition still goes through the production service/repository path. It does
not delete test data.
"""

from __future__ import annotations

import os
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.flask.competitors.repository import CompetitorRepository
from backend.flask.database.connection import MongoSettings, connect_database
from backend.flask.website_monitoring.repository import (
    DEFAULT_RUN_STALE_AFTER,
    MonitoringRunRepository,
    MonitoringTargetRepository,
)
from backend.flask.website_monitoring.service import (
    AlreadyRunningError,
    MonitoringRunService,
    fetch_page,
)


TEST_DATABASE = "competitors_monitoring_test"
USER_ID = "live-verification"
SITES = (
    ("lyfemarketing.com", "https://www.lyfemarketing.com/"),
    ("brownbagmarketing.com", "https://brownbagmarketing.com/"),
)
TARGET_PATH = "/blog"


def run_live_verification() -> dict[str, object]:
    """Run the four real-data acceptance checks for the concurrency guard."""

    if os.environ.get("RUN_LIVE_CONCURRENCY") != "1":
        raise SystemExit(
            "Set RUN_LIVE_CONCURRENCY=1 to run live concurrency verification"
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
        runs = MonitoringRunRepository.from_database(database)
        snapshots = _snapshot_repository(database)
        runs.ensure_indexes()
        snapshots.ensure_indexes()

        lyfe_competitor = _find_competitor(competitors, SITES[0][1])
        brown_competitor = _find_competitor(competitors, SITES[1][1])
        lyfe_target = _find_active_target(
            targets.list_active_targets(lyfe_competitor["id"])
        )
        brown_target = _find_active_target(
            targets.list_active_targets(brown_competitor["id"])
        )
        if lyfe_target is None or brown_target is None:
            raise AssertionError("both active /blog targets are required")

        same_target = _verify_same_target_concurrency(
            database,
            lyfe_target,
            runs,
            snapshots,
        )
        isolation = _verify_per_target_isolation(
            database,
            lyfe_target,
            brown_target,
            runs,
            snapshots,
        )
        stale = _verify_stale_takeover(
            database,
            lyfe_target,
            runs,
            snapshots,
        )
        regression = _verify_single_call(
            database,
            brown_target,
            runs,
            snapshots,
        )

        report = {
            "database": database.name,
            "same_target_concurrency": same_target,
            "per_target_isolation": isolation,
            "stale_takeover": stale,
            "single_call_regression": regression,
            "stale_threshold": str(DEFAULT_RUN_STALE_AFTER),
        }
        _print_report(report)
        return report
    finally:
        client.close()


def _snapshot_repository(database):
    from backend.flask.snapshot.repository import SnapshotRepository

    return SnapshotRepository.from_database(database)


def _find_competitor(
    repository: CompetitorRepository,
    website_url: str,
) -> dict[str, object]:
    for competitor in repository.list_for_user(USER_ID):
        if competitor.get("website_url") == website_url:
            return competitor
    raise AssertionError(f"no live-verification competitor found for {website_url}")


def _find_active_target(rows: list[dict[str, object]]) -> dict[str, object] | None:
    normalized_path = TARGET_PATH.rstrip("/") or "/"
    for row in rows:
        row_path = urlsplit(str(row.get("url", ""))).path.rstrip("/") or "/"
        if row_path == normalized_path:
            return row
    return None


def _new_service(database, fetcher):
    return MonitoringRunService.from_database(
        database,
        fetcher=fetcher,
        stale_after=DEFAULT_RUN_STALE_AFTER,
    )


def _run_in_thread(service, target_id, outcomes, label):
    try:
        outcomes[label] = ("SUCCESS", service.monitor_target(target_id))
    except Exception as exc:  # noqa: BLE001 - report the real thread outcome
        outcomes[label] = ("ERROR", exc)


def _verify_same_target_concurrency(database, target, runs, snapshots):
    target_id = target["id"]
    before_runs = runs.list_for_target(target_id)
    before_snapshots = snapshots.list_for_target(target_id)
    first_fetch_started = threading.Event()
    release_first_fetch = threading.Event()
    call_lock = threading.Lock()
    fetch_calls = 0

    def blocking_real_fetch(url):
        nonlocal fetch_calls
        with call_lock:
            fetch_calls += 1
            call_number = fetch_calls
        if call_number == 1:
            first_fetch_started.set()
            if not release_first_fetch.wait(timeout=30):
                raise TimeoutError("timed out holding first concurrent fetch")
        return fetch_page(url)

    service = _new_service(database, blocking_real_fetch)
    outcomes = {}
    first = threading.Thread(
        target=_run_in_thread,
        args=(service, target_id, outcomes, "first"),
    )
    second = threading.Thread(
        target=_run_in_thread,
        args=(service, target_id, outcomes, "second"),
    )
    first.start()
    if not first_fetch_started.wait(timeout=30):
        raise AssertionError("first real fetch did not reach its overlap point")
    second.start()
    second.join(timeout=30)
    release_first_fetch.set()
    first.join(timeout=30)
    if first.is_alive() or second.is_alive():
        raise AssertionError("same-target concurrent verification threads did not finish")

    successes = [value for status, value in outcomes.values() if status == "SUCCESS"]
    errors = [value for status, value in outcomes.values() if status == "ERROR"]
    if len(successes) != 1 or len(errors) != 1:
        raise AssertionError(f"unexpected same-target outcomes: {outcomes!r}")
    if not isinstance(errors[0], AlreadyRunningError):
        raise AssertionError(f"wrong rejection signal: {errors[0]!r}")

    after_runs = runs.list_for_target(target_id)
    after_snapshots = snapshots.list_for_target(target_id)
    if len(after_runs) != len(before_runs) + 1:
        raise AssertionError("same-target race created more than one run")
    if len(after_snapshots) != len(before_snapshots) + 1:
        raise AssertionError("same-target race created more than one snapshot")
    if any(run["status"] == MonitoringRunRepository.RUNNING for run in after_runs):
        raise AssertionError("same-target race left an unexpected RUNNING record")

    success_run = successes[0]["run"]
    return {
        "target_id": target_id,
        "success_run_id": success_run["id"],
        "rejected_error": str(errors[0]),
        "runs_added": len(after_runs) - len(before_runs),
        "snapshots_added": len(after_snapshots) - len(before_snapshots),
        "real_fetch_calls": fetch_calls,
    }


def _verify_per_target_isolation(database, lyfe_target, brown_target, runs, snapshots):
    targets = (lyfe_target, brown_target)
    before = {
        target["id"]: (
            len(runs.list_for_target(target["id"])),
            len(snapshots.list_for_target(target["id"])),
        )
        for target in targets
    }
    barrier = threading.Barrier(2)

    def simultaneous_real_fetch(url):
        barrier.wait(timeout=30)
        return fetch_page(url)

    service = _new_service(database, simultaneous_real_fetch)
    outcomes = {}
    threads = [
        threading.Thread(
            target=_run_in_thread,
            args=(service, target["id"], outcomes, index),
        )
        for index, target in enumerate(targets)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    if any(thread.is_alive() for thread in threads):
        raise AssertionError("per-target isolation threads did not finish")
    if any(status != "SUCCESS" for status, _ in outcomes.values()):
        raise AssertionError(f"per-target isolation outcomes: {outcomes!r}")

    added = {}
    for index, target in enumerate(targets):
        target_id = target["id"]
        run_rows = runs.list_for_target(target_id)
        snapshot_rows = snapshots.list_for_target(target_id)
        if len(run_rows) != before[target_id][0] + 1:
            raise AssertionError(f"target {target_id}: unexpected run count")
        if len(snapshot_rows) != before[target_id][1] + 1:
            raise AssertionError(f"target {target_id}: unexpected snapshot count")
        outcome = outcomes[index][1]
        added[target_id] = {
            "run_id": outcome["run"]["id"],
            "status": outcome["run"]["status"],
        }
    return {"targets": added}


def _verify_stale_takeover(database, target, runs, snapshots):
    target_id = target["id"]
    before_snapshots = snapshots.list_for_target(target_id)
    now = datetime.now(timezone.utc)
    stale_started_at = now - DEFAULT_RUN_STALE_AFTER - timedelta(seconds=1)
    stale = runs.create(
        monitoring_target_id=target_id,
        started_at=stale_started_at,
        now=stale_started_at,
    )

    service = _new_service(database, fetch_page)
    result = service.monitor_target(target_id)
    stale_after = runs.get(stale["id"])
    if stale_after["status"] != MonitoringRunRepository.FAILED:
        raise AssertionError("stale RUNNING record was not marked FAILED")
    if "orphaned" not in stale_after["error_message"]:
        raise AssertionError("stale failure reason is not explicit")
    if result["run"]["status"] != MonitoringRunRepository.SUCCESS:
        raise AssertionError("replacement run did not succeed")
    after_snapshots = snapshots.list_for_target(target_id)
    if len(after_snapshots) != len(before_snapshots) + 1:
        raise AssertionError("stale takeover created an unexpected snapshot count")
    return {
        "stale_run_id": stale["id"],
        "stale_status": stale_after["status"],
        "stale_error": stale_after["error_message"],
        "replacement_run_id": result["run"]["id"],
        "replacement_status": result["run"]["status"],
        "snapshot_id": result["snapshot"]["id"],
    }


def _verify_single_call(database, target, runs, snapshots):
    target_id = target["id"]
    before_runs = len(runs.list_for_target(target_id))
    before_snapshots = len(snapshots.list_for_target(target_id))
    service = _new_service(database, fetch_page)
    result = service.monitor_target(target_id)
    if result["run"]["status"] != MonitoringRunRepository.SUCCESS:
        raise AssertionError("normal single call did not finish SUCCESS")
    if len(runs.list_for_target(target_id)) != before_runs + 1:
        raise AssertionError("normal single call did not create exactly one run")
    if len(snapshots.list_for_target(target_id)) != before_snapshots + 1:
        raise AssertionError("normal single call did not create exactly one snapshot")
    return {
        "target_id": target_id,
        "run_id": result["run"]["id"],
        "run_status": result["run"]["status"],
        "snapshot_id": result["snapshot"]["id"],
    }


def _print_report(report):
    print(f"database={report['database']} stale_threshold={report['stale_threshold']}")
    print(f"same_target_concurrency={report['same_target_concurrency']}")
    print(f"per_target_isolation={report['per_target_isolation']}")
    print(f"stale_takeover={report['stale_takeover']}")
    print(f"single_call_regression={report['single_call_regression']}")


if __name__ == "__main__":
    run_live_verification()
