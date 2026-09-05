"""Opt-in live Step 1.11 verification against the dedicated Atlas database.

Run from the repository root after loading the MongoDB settings:

    set -a; source .env.mongodb; set +a
    export MONGODB_DATABASE=competitors_monitoring_test
    RUN_LIVE_DELETE_DEACTIVATE=1 python3 -u tests/live_delete_deactivate_verification.py

This intentionally changes the dedicated test data: Lyfe's history-bearing
``/blog`` target is deactivated, while Brown Bag's historyless ACTIVE
``/about-us`` and historyless SUGGESTED ``/careers`` rows are deleted.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.flask.change_detection.repository import ChangeRepository
from backend.flask.competitors.repository import CompetitorRepository
from backend.flask.database.connection import MongoSettings, connect_database
from backend.flask.discovery.service import DiscoveryService
from backend.flask.scheduler.service import SchedulerService
from backend.flask.snapshot.repository import SnapshotRepository
from backend.flask.website_monitoring.repository import MonitoringTargetRepository


TEST_DATABASE = "competitors_monitoring_test"
USER_ID = "live-verification"
LYFE_URL = "https://www.lyfemarketing.com/"
BROWN_URL = "https://brownbagmarketing.com/"
LYFE_BLOG_PATH = "/blog"
BROWN_ABOUT_PATH = "/about-us"
BROWN_SUGGESTED_PATH = "/careers"


def run_live_verification() -> dict[str, object]:
    """Run the four Step 1.11 acceptance checks against real Atlas data."""

    if os.environ.get("RUN_LIVE_DELETE_DEACTIVATE") != "1":
        raise SystemExit(
            "Set RUN_LIVE_DELETE_DEACTIVATE=1 to run live delete/deactivate verification"
        )

    settings = MongoSettings.from_env()
    if settings.database_name != TEST_DATABASE:
        raise RuntimeError(
            f"refusing to write outside the dedicated test database {TEST_DATABASE!r}; "
            f"configured database is {settings.database_name!r}"
        )

    client, database = connect_database(settings, serverSelectionTimeoutMS=15_000)
    try:
        client.admin.command("ping")
        competitors = CompetitorRepository.from_database(database)
        targets = MonitoringTargetRepository.from_database(database)
        snapshots = SnapshotRepository.from_database(database)
        changes = ChangeRepository.from_database(database)

        lyfe = _find_competitor(competitors, LYFE_URL)
        brown = _find_competitor(competitors, BROWN_URL)
        lyfe_target = _find_target(targets, lyfe["id"], LYFE_BLOG_PATH)
        brown_about = _find_target(targets, brown["id"], BROWN_ABOUT_PATH)
        brown_suggested = _find_target(targets, brown["id"], BROWN_SUGGESTED_PATH)

        lyfe_snapshots_before = snapshots.list_for_target(lyfe_target["id"])
        lyfe_changes_before = changes.list_for_target(lyfe_target["id"])
        if not lyfe_snapshots_before and not lyfe_changes_before:
            raise AssertionError("Lyfe /blog does not have history for deactivation test")
        if lyfe_target["active"] is not True or lyfe_target["discovery_status"] != "ACTIVE":
            raise AssertionError("Lyfe /blog is not ACTIVE before the deactivation test")

        brown_about_snapshots = snapshots.list_for_target(brown_about["id"])
        brown_about_changes = changes.list_for_target(brown_about["id"])
        if brown_about_snapshots or brown_about_changes:
            raise AssertionError("Brown /about-us unexpectedly has history")
        if brown_about["active"] is not True or brown_about["discovery_status"] != "ACTIVE":
            raise AssertionError("Brown /about-us is not ACTIVE before the delete test")

        brown_suggested_snapshots = snapshots.list_for_target(brown_suggested["id"])
        brown_suggested_changes = changes.list_for_target(brown_suggested["id"])
        if brown_suggested_snapshots or brown_suggested_changes:
            raise AssertionError("Brown /careers unexpectedly has history")
        if (
            brown_suggested["active"] is not False
            or brown_suggested["discovery_status"] != "SUGGESTED"
        ):
            raise AssertionError("Brown /careers is not an unactivated SUGGESTED candidate")

        discovery = DiscoveryService(
            competitors,
            targets,
            fallback_classifier=_NoopClassifier(),
            snapshot_repository=snapshots,
            change_repository=changes,
        )

        if not discovery.remove_candidate(lyfe_target["id"]):
            raise AssertionError("Lyfe /blog removal did not complete")
        lyfe_after = targets.get(lyfe_target["id"])
        if lyfe_after is None:
            raise AssertionError("history-bearing Lyfe /blog was hard-deleted")
        if lyfe_after["active"] is not False or lyfe_after["discovery_status"] != "ACTIVE":
            raise AssertionError("Lyfe /blog was not deactivated with status ACTIVE preserved")
        lyfe_snapshots_after = snapshots.list_for_target(lyfe_target["id"])
        lyfe_changes_after = changes.list_for_target(lyfe_target["id"])
        if lyfe_snapshots_after != lyfe_snapshots_before:
            raise AssertionError("Lyfe snapshot history changed during deactivation")
        if lyfe_changes_after != lyfe_changes_before:
            raise AssertionError("Lyfe change history changed during deactivation")
        if any(row.get("monitoring_target_id") != lyfe_target["id"] for row in lyfe_snapshots_after):
            raise AssertionError("a Lyfe snapshot is not linked to the retained target")
        if any(row.get("monitoring_target_id") != lyfe_target["id"] for row in lyfe_changes_after):
            raise AssertionError("a Lyfe change is not linked to the retained target")

        if not discovery.remove_candidate(brown_about["id"]):
            raise AssertionError("Brown /about-us removal did not complete")
        if targets.get(brown_about["id"]) is not None:
            raise AssertionError("historyless ACTIVE Brown /about-us was not deleted")

        if not discovery.remove_candidate(brown_suggested["id"]):
            raise AssertionError("Brown /careers removal did not complete")
        if targets.get(brown_suggested["id"]) is not None:
            raise AssertionError("unactivated Brown /careers was not deleted")

        active_lyfe_ids = {row["id"] for row in discovery.list_active_targets(lyfe["id"])}
        if lyfe_target["id"] in active_lyfe_ids:
            raise AssertionError("deactivated Lyfe /blog is still in list_active_targets")

        dispatched: list[object] = []

        class _OnlyDeactivatedTargetReader:
            def list_active_targets(self, competitor_id=None):
                return [
                    row
                    for row in targets.list_active_targets(competitor_id)
                    if row["id"] == lyfe_target["id"]
                ]

        scheduler = SchedulerService(
            _OnlyDeactivatedTargetReader(),
            lambda target_id: dispatched.append(target_id),
        )
        scheduler_result = scheduler.run_due_targets()
        if scheduler_result.evaluated_target_ids or dispatched:
            raise AssertionError("scheduler considered the deactivated Lyfe target")

        report = {
            "database": database.name,
            "lyfe_target_id": lyfe_target["id"],
            "lyfe_target_before": {
                "active": lyfe_target["active"],
                "discovery_status": lyfe_target["discovery_status"],
            },
            "lyfe_target_after": {
                "active": lyfe_after["active"],
                "discovery_status": lyfe_after["discovery_status"],
            },
            "lyfe_snapshot_ids": [row["id"] for row in lyfe_snapshots_after],
            "lyfe_change_ids": [row["id"] for row in lyfe_changes_after],
            "brown_about_target_id": brown_about["id"],
            "brown_about_deleted": True,
            "brown_suggested_target_id": brown_suggested["id"],
            "brown_suggested_deleted": True,
            "scheduler_evaluated_after_deactivation": scheduler_result.evaluated_target_ids,
            "scheduler_dispatched_after_deactivation": dispatched,
        }
        _print_report(report)
        return report
    finally:
        client.close()


class _NoopClassifier:
    def classify(self, candidates):
        return ()


def _find_competitor(repository, website_url):
    for competitor in repository.list_for_user(USER_ID):
        if competitor.get("website_url") == website_url:
            return competitor
    raise AssertionError(f"no live-verification competitor found for {website_url}")


def _find_target(repository, competitor_id, path):
    for target in repository.list_for_competitor(competitor_id):
        url = str(target.get("url", "")).rstrip("/") or "/"
        if url.endswith(path):
            return target
    raise AssertionError(f"no target found for competitor {competitor_id} at {path}")


def _print_report(report):
    print(f"database={report['database']}")
    print(
        f"lyfe_target_id={report['lyfe_target_id']} "
        f"before={report['lyfe_target_before']} after={report['lyfe_target_after']}"
    )
    print(
        f"lyfe_snapshot_ids={report['lyfe_snapshot_ids']} "
        f"lyfe_change_ids={report['lyfe_change_ids']}"
    )
    print(
        f"brown_about_target_id={report['brown_about_target_id']} "
        f"deleted={report['brown_about_deleted']} "
        f"brown_suggested_target_id={report['brown_suggested_target_id']} "
        f"deleted={report['brown_suggested_deleted']}"
    )
    print(
        f"scheduler_evaluated_after_deactivation="
        f"{report['scheduler_evaluated_after_deactivation']} "
        f"dispatched={report['scheduler_dispatched_after_deactivation']}"
    )


if __name__ == "__main__":
    run_live_verification()
