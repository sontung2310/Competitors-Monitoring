"""Backfill LLM narratives for existing blog and generic page changes.

The command reads both snapshot contents through SnapshotStorage and writes
only the optional narrative_summary field through ChangeRepository. It is
safe to re-run: already-populated rows are not selected.

Example:

    MONGODB_DATABASE=competitors_monitoring_test \
      python scripts/backfill_narrative_summaries.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - requirements.txt provides this package
    load_dotenv = None

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.flask.change_detection.repository import ChangeRepository
from backend.flask.change_detection.service import (
    generate_narrative_summary,
)
from backend.flask.database.connection import MongoSettings, connect_database
from backend.flask.llm_provider import OpenAIProvider
from backend.flask.snapshot.repository import SnapshotRepository
from backend.flask.snapshot.storage import SnapshotStorage
from backend.flask.website_monitoring.repository import MonitoringTargetRepository
from backend.flask.website_monitoring.service import generate_diff


def run_backfill(
    *,
    dry_run: bool = False,
    limit: int | None = None,
    storage_root: str | None = None,
) -> dict[str, Any]:
    """Generate narratives for every eligible existing change row."""

    if load_dotenv is not None:
        load_dotenv(override=False)
    settings = MongoSettings.from_env()
    client, database = connect_database(
        settings,
        serverSelectionTimeoutMS=15_000,
    )
    try:
        client.admin.command("ping")
        changes = ChangeRepository.from_database(database)
        targets = MonitoringTargetRepository.from_database(database)
        snapshots = SnapshotRepository.from_database(database)
        storage = SnapshotStorage(storage_root)
        rows = changes.list_needing_narrative_summary(limit=limit)
        provider = None if dry_run else OpenAIProvider.from_env()
        report: dict[str, Any] = {
            "database": settings.database_name,
            "selected": len(rows),
            "updated": 0,
            "failed": 0,
            "dry_run": dry_run,
            "changes": [],
        }

        for change in rows:
            change_id = str(change["id"])
            before = change.get("narrative_summary")
            entry: dict[str, Any] = {
                "change_id": change_id,
                "change_type": change.get("change_type"),
                "before_narrative_summary": before,
            }
            if dry_run:
                entry["after_narrative_summary"] = None
                report["changes"].append(entry)
                print(json.dumps(entry, ensure_ascii=False))
                continue
            try:
                target = targets.get(change["monitoring_target_id"])
                previous = snapshots.get(change["previous_snapshot_id"])
                current = snapshots.get(change["current_snapshot_id"])
                if target is None or previous is None or current is None:
                    raise RuntimeError("target or snapshot metadata is missing")
                previous_content = _read_snapshot(storage, previous)
                current_content = _read_snapshot(storage, current)
                diff = generate_diff(
                    _with_final_newline(previous_content),
                    _with_final_newline(current_content),
                )
                if not diff:
                    raise RuntimeError("stored snapshots produced no diff")
                narrative = generate_narrative_summary(
                    change_type=str(change["change_type"]),
                    diff=diff,
                    target_url=str(target["url"]),
                    page_type=str(target["page_type"]),
                    provider=provider,
                )
                if dry_run:
                    after = narrative
                else:
                    updated = changes.update_narrative_summary(change_id, narrative)
                    if updated is None:
                        raise RuntimeError(
                            "row was already populated or is no longer eligible"
                        )
                    after = updated.get("narrative_summary")
                    report["updated"] += 1
                entry["after_narrative_summary"] = after
            except Exception as exc:
                report["failed"] += 1
                entry["error"] = str(exc)
            report["changes"].append(entry)
            print(json.dumps(entry, ensure_ascii=False))

        return report
    finally:
        client.close()


def _read_snapshot(storage: SnapshotStorage, snapshot: dict[str, Any]) -> str:
    return storage.read_snapshot_bytes(snapshot["storage_path"]).decode("utf-8")


def _with_final_newline(content: str) -> str:
    return content if content.endswith("\n") else f"{content}\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--storage-root")
    args = parser.parse_args()
    report = run_backfill(
        dry_run=args.dry_run,
        limit=args.limit,
        storage_root=args.storage_root,
    )
    print(
        f"database={report['database']} selected={report['selected']} "
        f"updated={report['updated']} failed={report['failed']} "
        f"dry_run={report['dry_run']}"
    )
    return 1 if report["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
