"""Opt-in end-to-end evidence for P.4 against the seeded Lyfe demo pair.

This exercises the real Mongo-backed application service graph and real HTTP
monitoring fetches. It verifies the existing fresh Lyfe competitor path, then
creates a temporary Lyfe URL to exercise the new-competitor first-run path,
replays the same SQS identities, and cleans up only the records created by this
verification.

Run from the repository root with::

    MONGODB_DATABASE=competitors_monitoring_test RUN_LIVE_P4=1 \
      ./.venv/bin/python -u tests/live_p4_verification.py
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

from backend.flask.app import create_app
from backend.flask.companies.repository import CompanyRepository
from backend.flask.competitors.repository import CompetitorRepository
from backend.flask.database.base_repository import to_object_id, utc_now
from backend.flask.database.connection import MongoSettings, connect_database
from backend.flask.scheduler.sqs_handler import handle_message, parse_message
from backend.flask.snapshot.storage import SnapshotStorage
from backend.flask.website_monitoring.repository import MonitoringTargetRepository


TEST_DATABASE = "competitors_monitoring_test"
COMPANY_DOMAIN = "marketingeye.com.au"
COMPETITOR_URL = "https://www.lyfemarketing.com/"


def run_live_verification() -> dict[str, object]:
    if os.environ.get("RUN_LIVE_P4") != "1":
        raise SystemExit("Set RUN_LIVE_P4=1 to run live P.4 verification")

    load_dotenv(override=False)
    settings = MongoSettings.from_env()
    if settings.database_name != TEST_DATABASE:
        raise RuntimeError(
            f"refusing to write outside {TEST_DATABASE!r}; "
            f"configured database is {settings.database_name!r}"
        )

    mongo_client, database = connect_database(
        settings,
        serverSelectionTimeoutMS=15_000,
    )
    created_snapshot_ids: list[object] = []
    created_run_ids: list[object] = []
    created_change_ids: list[object] = []
    target_before: dict[str, dict[str, object]] = {}
    message_id = f"live-p4-{uuid4().hex}"
    new_competitor_id: object | None = None
    new_competitor_url = f"{COMPETITOR_URL}?p4_live={uuid4().hex}"
    try:
        mongo_client.admin.command("ping")
        companies = CompanyRepository.from_database(database)
        competitors = CompetitorRepository.from_database(database)
        targets = MonitoringTargetRepository.from_database(database)
        company = companies.find_by_website_url(COMPANY_DOMAIN)
        if company is None:
            raise AssertionError("Marketing Eye demo company was not found")
        competitor = competitors.find_by_company_and_website_url(
            company["id"],
            COMPETITOR_URL,
        )
        if competitor is None:
            raise AssertionError("Lyfe Marketing demo competitor was not found")

        services = create_app(
            database=database,
            user_id="p4-live-verification",
            testing=True,
        ).extensions["api_services"]
        latest = services["discovery"].latest_successful_run(
            competitor["id"],
            company_id=company["id"],
        )
        if latest is None:
            raise AssertionError("Lyfe Marketing has no successful discovery run")
        finished_at = _as_utc(latest["finished_at"])
        if utc_now() - finished_at >= timedelta(days=30):
            raise AssertionError("demo prerequisite is not fresh enough for P.4.1 proof")

        active_targets = targets.list_active_targets(competitor["id"])
        if not active_targets:
            raise AssertionError("Lyfe Marketing has no active targets for monitoring")
        target_ids = {str(target["id"]) for target in active_targets}
        for target in active_targets:
            target_before[str(target["id"])] = {
                "last_checked_at": target.get("last_checked_at"),
                "last_changed_at": target.get("last_changed_at"),
            }

        before_snapshots = _documents_for_targets(database["snapshots"], target_ids)
        before_runs = _documents_for_targets(database["monitoring_runs"], target_ids)
        before_changes = _documents_for_targets(database["changes"], target_ids)
        message = parse_message(
            {
                "strategy_id": 1,
                "company_domain_id": COMPANY_DOMAIN,
                "company_url": COMPETITOR_URL,
                "host": "prod",
            }
        )

        first = handle_message(
            message,
            services,
            clock=utc_now,
            message_id=message_id,
        )
        if first["action"] != "skipped_fresh":
            raise AssertionError(f"expected fresh-discovery skip: {first}")
        if first["reconciliation"] is not None:
            raise AssertionError("fresh P.4.1 processing unexpectedly reconciled")
        if set(map(str, first["monitored_target_ids"])) != target_ids:
            raise AssertionError("P.4 did not monitor every active Lyfe target")
        if any(item["run"]["status"] != "SUCCESS" for item in first["monitoring"]):
            raise AssertionError(f"a live monitor run failed: {first['monitoring']}")
        changed_target_count = sum(
            bool(item.get("changes")) for item in first["monitoring"]
        )
        unchanged_target_count = len(first["monitoring"]) - changed_target_count
        if changed_target_count < 1 or unchanged_target_count < 1:
            raise AssertionError(
                "live monitoring did not demonstrate both changed and unchanged targets"
            )

        after_snapshots = _documents_for_targets(database["snapshots"], target_ids)
        after_runs = _documents_for_targets(database["monitoring_runs"], target_ids)
        after_changes = _documents_for_targets(database["changes"], target_ids)
        created_snapshot_ids = _new_ids(before_snapshots, after_snapshots)
        created_run_ids = _new_ids(before_runs, after_runs)
        created_change_ids = _new_ids(before_changes, after_changes)
        if len(created_snapshot_ids) != len(target_ids):
            raise AssertionError(
                f"expected one fresh snapshot per target, created {len(created_snapshot_ids)}"
            )
        if len(created_run_ids) != len(target_ids):
            raise AssertionError(
                f"expected one fresh monitoring run per target, created {len(created_run_ids)}"
            )

        duplicate = handle_message(
            message,
            services,
            clock=utc_now,
            message_id=message_id,
        )
        if duplicate["action"] != "skipped_fresh":
            raise AssertionError("duplicate delivery did not retain fresh-discovery skip")
        if not all(item.get("idempotent") is True for item in duplicate["monitoring"]):
            raise AssertionError("duplicate delivery did not reuse completed monitor runs")
        if len(_documents_for_targets(database["snapshots"], target_ids)) != len(after_snapshots):
            raise AssertionError("duplicate delivery created another snapshot")
        if len(_documents_for_targets(database["monitoring_runs"], target_ids)) != len(after_runs):
            raise AssertionError("duplicate delivery created another monitoring run")

        new_message = parse_message(
            {
                "strategy_id": 1,
                "company_domain_id": COMPANY_DOMAIN,
                "company_url": new_competitor_url,
                "host": "prod",
            }
        )
        new_message_id = f"live-p4-new-{uuid4().hex}"
        new_first = handle_message(
            new_message,
            services,
            clock=utc_now,
            message_id=new_message_id,
        )
        new_competitor_id = new_first["competitor"]["id"]
        new_targets = targets.list_active_targets(new_competitor_id)
        if new_first["action"] != "first_run":
            raise AssertionError(f"expected new-competitor first run: {new_first}")
        if not new_targets:
            raise AssertionError("new-competitor discovery produced no live targets")
        new_target_ids = {str(target["id"]) for target in new_targets}
        new_snapshots = _documents_for_targets(database["snapshots"], new_target_ids)
        new_runs = _documents_for_targets(database["monitoring_runs"], new_target_ids)
        new_changes = _documents_for_targets(database["changes"], new_target_ids)
        if len(new_snapshots) != len(new_targets):
            raise AssertionError("new-competitor flow did not create one initial snapshot per target")
        if len(new_runs) != len(new_targets):
            raise AssertionError("new-competitor flow did not create one monitoring run per target")
        if new_changes:
            raise AssertionError("new-competitor initial snapshots created change records")

        new_duplicate = handle_message(
            new_message,
            services,
            clock=utc_now,
            message_id=new_message_id,
        )
        if not all(item.get("idempotent") is True for item in new_duplicate["monitoring"]):
            raise AssertionError("new-competitor duplicate did not reuse monitoring runs")
        if len(_documents_for_targets(database["snapshots"], new_target_ids)) != len(new_snapshots):
            raise AssertionError("new-competitor duplicate created another snapshot")

        new_initial_snapshot_count = len(new_snapshots)
        new_initial_change_count = len(new_changes)

        evidence = {
            "competitor": competitor["name"],
            "competitor_id": competitor["id"],
            "latest_successful_run": latest,
            "active_target_count": len(target_ids),
            "fresh_action": first["action"],
            "fresh_monitoring_runs": len(created_run_ids),
            "fresh_snapshots": len(created_snapshot_ids),
            "fresh_changes": len(created_change_ids),
            "fresh_changed_targets": changed_target_count,
            "fresh_unchanged_targets": unchanged_target_count,
            "duplicate_action": duplicate["action"],
            "duplicate_monitoring_idempotent": True,
            "new_competitor_action": new_first["action"],
            "new_active_target_count": len(new_targets),
            "new_initial_snapshots": new_initial_snapshot_count,
            "new_initial_changes": new_initial_change_count,
            "new_duplicate_monitoring_idempotent": True,
        }
        print(json.dumps(evidence, default=str, indent=2, sort_keys=True))
        return evidence
    finally:
        if new_competitor_id is None:
            new_competitor = competitors.find_by_company_and_website_url(
                company["id"],
                new_competitor_url,
            ) if "company" in locals() else None
            if new_competitor is not None:
                new_competitor_id = new_competitor["id"]
        if new_competitor_id is not None:
            _cleanup_competitor_artifacts(database, targets, competitors, new_competitor_id)
        storage = SnapshotStorage()
        if created_snapshot_ids:
            for document in database["snapshots"].find(
                {"_id": {"$in": created_snapshot_ids}},
                {"storage_path": 1},
            ):
                if document.get("storage_path"):
                    storage.delete_snapshot(document["storage_path"])
            database["snapshots"].delete_many({"_id": {"$in": created_snapshot_ids}})
        if created_run_ids:
            database["monitoring_runs"].delete_many({"_id": {"$in": created_run_ids}})
        if created_change_ids:
            database["changes"].delete_many({"_id": {"$in": created_change_ids}})
        for target_id, values in target_before.items():
            database["monitoring_targets"].update_one(
                {"_id": to_object_id(target_id)},
                {"$set": values},
            )
        mongo_client.close()


def _documents_for_targets(collection: object, target_ids: set[str]) -> list[dict[str, object]]:
    return list(
        collection.find(
            {"monitoring_target_id": {"$in": [to_object_id(target_id) for target_id in target_ids]}}
        )
    )


def _cleanup_competitor_artifacts(
    database: object,
    targets: MonitoringTargetRepository,
    competitors: CompetitorRepository,
    competitor_id: object,
) -> None:
    target_rows = targets.list_for_competitor(competitor_id)
    storage = SnapshotStorage()
    for target in target_rows:
        target_id = to_object_id(target["id"])
        for snapshot in database["snapshots"].find(
            {"monitoring_target_id": target_id},
            {"storage_path": 1},
        ):
            if snapshot.get("storage_path"):
                storage.delete_snapshot(snapshot["storage_path"])
        database["snapshots"].delete_many({"monitoring_target_id": target_id})
        database["monitoring_runs"].delete_many({"monitoring_target_id": target_id})
        database["changes"].delete_many({"monitoring_target_id": target_id})
        targets.delete(target["id"], competitor_id=competitor_id)
    database["discovery_runs"].delete_many(
        {"competitor_id": to_object_id(competitor_id)}
    )
    competitors.delete(competitor_id, company_id=None)


def _new_ids(before: list[dict[str, object]], after: list[dict[str, object]]) -> list[object]:
    before_ids = {str(document["_id"]) for document in before}
    return [document["_id"] for document in after if str(document["_id"]) not in before_ids]


def _as_utc(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise AssertionError(f"expected a datetime, got {value!r}")
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


if __name__ == "__main__":
    run_live_verification()
