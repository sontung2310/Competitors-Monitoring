"""Opt-in live Step 1.5 verification against Atlas and real active targets.

Run from the repository root with the dedicated Atlas test database configured:

    set -a; source .env.mongodb; set +a
    export MONGODB_DATABASE=competitors_monitoring_test
    RUN_LIVE_SNAPSHOT=1 \
      /private/tmp/competitors-monitoring-venv/bin/python -u \
      tests/live_snapshot_verification.py

The script creates new snapshot records and files for the already-active
Lyfe/Brown Bag /blog targets. It does not delete existing test data.
"""

from __future__ import annotations

import gzip
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.flask.competitors.repository import CompetitorRepository
from backend.flask.database.connection import MongoSettings, connect_database
from backend.flask.snapshot.repository import SnapshotRepository
from backend.flask.snapshot.service import SnapshotService
from backend.flask.snapshot.storage import SnapshotStorage
from backend.flask.website_monitoring.service import (
    fetch_page,
    hash_content,
    normalize_content,
)
from backend.flask.website_monitoring.repository import MonitoringTargetRepository


TEST_DATABASE = "competitors_monitoring_test"
USER_ID = "live-verification"
SITES = (
    ("lyfemarketing.com", "https://www.lyfemarketing.com/", "/blog"),
    ("brownbagmarketing.com", "https://brownbagmarketing.com/", "/blog"),
)


def run_live_verification() -> list[dict[str, object]]:
    """Run the real fetch, gzip, metadata, and round-trip checks."""

    if os.environ.get("RUN_LIVE_SNAPSHOT") != "1":
        raise SystemExit("Set RUN_LIVE_SNAPSHOT=1 to run live snapshot verification")

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
        snapshots.ensure_indexes()
        storage = SnapshotStorage()
        service = SnapshotService(snapshots, storage)

        reports: list[dict[str, object]] = []
        for label, website_url, target_path in SITES:
            competitor = _find_competitor(competitors, website_url)
            target = _find_active_target(
                targets.list_active_targets(competitor["id"]),
                target_path,
            )
            if target is None:
                raise AssertionError(
                    f"{label}: active target {target_path!r} was not found"
                )

            before = len(snapshots.list_for_target(target["id"]))
            first = _capture(service, storage, target, label)
            second = None
            if label == "lyfemarketing.com":
                second = _capture(service, storage, target, label)
            after = len(snapshots.list_for_target(target["id"]))

            if label == "lyfemarketing.com":
                if second is None or first["content_hash"] != second["content_hash"]:
                    raise AssertionError(f"{label}: immediate snapshot hashes differ")
                if first["storage_path"] == second["storage_path"]:
                    raise AssertionError(f"{label}: immediate snapshot paths collide")
                if after != before + 2:
                    raise AssertionError(
                        f"{label}: expected two new metadata records, "
                        f"before={before} after={after}"
                    )
            elif after != before + 1:
                raise AssertionError(
                    f"{label}: expected one new metadata record, before={before} after={after}"
                )

            report = {
                "label": label,
                "competitor_id": competitor["id"],
                "target_id": target["id"],
                "target_url": target["url"],
                "new_snapshot_count": after - before,
                "first_snapshot_id": first["id"],
                "first_storage_path": first["storage_path"],
                "first_absolute_path": str(storage.absolute_path(first["storage_path"])),
                "first_hash": first["content_hash"],
                "first_fetch": f"{first['fetch_method']}/{first['http_status']}",
                "first_round_trip_hash": first["round_trip_hash"],
                "second_snapshot_id": second["id"] if second else None,
                "second_storage_path": second["storage_path"] if second else None,
                "second_absolute_path": (
                    str(storage.absolute_path(second["storage_path"]))
                    if second
                    else None
                ),
                "second_hash": second["content_hash"] if second else None,
                "hashes_match": (
                    second is None or first["content_hash"] == second["content_hash"]
                ),
            }
            reports.append(report)
            _print_report(report)
        return reports
    finally:
        client.close()


def _find_competitor(
    repository: CompetitorRepository,
    website_url: str,
) -> dict[str, object]:
    for competitor in repository.list_for_user(USER_ID):
        if competitor.get("website_url") == website_url:
            return competitor
    raise AssertionError(f"no live-verification competitor found for {website_url}")


def _find_active_target(
    rows: list[dict[str, object]],
    target_path: str,
) -> dict[str, object] | None:
    normalized_path = target_path.rstrip("/") or "/"
    for row in rows:
        row_path = urlsplit(str(row.get("url", ""))).path.rstrip("/") or "/"
        if row_path == normalized_path:
            return row
    return None


def _capture(
    service: SnapshotService,
    storage: SnapshotStorage,
    target: dict[str, object],
    label: str,
) -> dict[str, object]:
    fetched = fetch_page(str(target["url"]))
    normalized = normalize_content(fetched.content)
    expected_hash = hash_content(normalized)
    snapshot = service.create_snapshot(
        target["id"],
        normalized,
        fetch_method=fetched.fetch_method,
        http_status=fetched.http_status or 0,
    )
    stored_bytes = storage.read_snapshot_bytes(snapshot["storage_path"])
    if stored_bytes != normalized.encode("utf-8"):
        raise AssertionError(f"{label}: gzip round-trip changed snapshot bytes")
    if snapshot["content_hash"] != expected_hash:
        raise AssertionError(f"{label}: metadata hash differs from normalized content")
    recomputed_hash = hash_content(stored_bytes.decode("utf-8"))
    if snapshot["content_hash"] != recomputed_hash:
        raise AssertionError(f"{label}: hash differs when recomputed from gzip bytes")
    if not storage.absolute_path(snapshot["storage_path"]).is_file():
        raise AssertionError(f"{label}: snapshot file does not exist")
    with gzip.open(storage.absolute_path(snapshot["storage_path"]), "rb") as archive:
        if archive.read() != stored_bytes:
            raise AssertionError(f"{label}: gzip archive could not be reopened")
    return {**snapshot, "round_trip_hash": recomputed_hash}


def _print_report(report: dict[str, object]) -> None:
    print(f"\n=== {report['label']} ===")
    print(
        f"competitor_id={report['competitor_id']} target_id={report['target_id']} "
        f"target={report['target_url']} new_snapshots={report['new_snapshot_count']}"
    )
    print(
        f"first id={report['first_snapshot_id']} "
        f"path={report['first_storage_path']} "
        f"absolute={report['first_absolute_path']}"
    )
    print(
        f"first fetch={report['first_fetch']} hash={report['first_hash']} "
        f"round_trip_hash={report['first_round_trip_hash']}"
    )
    if report["second_snapshot_id"]:
        print(
            f"second id={report['second_snapshot_id']} "
            f"path={report['second_storage_path']} "
            f"absolute={report['second_absolute_path']}"
        )
        print(
            f"second hash={report['second_hash']} "
            f"hashes_match={report['hashes_match']}"
        )


if __name__ == "__main__":
    run_live_verification()

