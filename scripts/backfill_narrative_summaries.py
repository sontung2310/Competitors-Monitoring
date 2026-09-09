"""Backfill narratives and detected URLs for existing change records.

The command reads both snapshot contents through SnapshotStorage and writes
the optional enrichment fields through ChangeRepository. It is safe to re-run:
already-populated detected URLs are not selected.

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
    generate_narrative_summary_with_url,
    resolve_blog_detected_url,
    resolve_product_detected_url,
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
        rows = changes.list_needing_detected_url(limit=limit)
        provider = None
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
                "before_detected_url": change.get("detected_url"),
            }
            if dry_run:
                entry["after_narrative_summary"] = before
                target = targets.get(change["monitoring_target_id"])
                if target is None:
                    entry["error"] = "monitoring target metadata is missing"
                    report["failed"] += 1
                else:
                    entry["after_detected_url"] = _dry_run_detected_url(
                        change,
                        target_url=str(target["url"]),
                    )
                report["changes"].append(entry)
                print(json.dumps(entry, ensure_ascii=False))
                continue
            try:
                target = targets.get(change["monitoring_target_id"])
                if target is None:
                    raise RuntimeError("monitoring target metadata is missing")
                change_type = str(change["change_type"])
                if change_type in {"NEW_PRODUCT", "PRICE_CHANGE", "PRODUCT_REMOVED"}:
                    detected_url = resolve_product_detected_url(
                        change_type=change_type,
                        detected_url=change.get("detected_url"),
                        summary=str(change.get("summary", "")),
                        target_url=str(target["url"]),
                    )
                    updated = changes.update_enrichment(
                        change_id,
                        detected_url=detected_url,
                    )
                    if updated is None:
                        raise RuntimeError("change row could not be updated")
                    after = updated.get("narrative_summary")
                    after_url = updated.get("detected_url")
                else:
                    previous = snapshots.get(change["previous_snapshot_id"])
                    current = snapshots.get(change["current_snapshot_id"])
                    if previous is None or current is None:
                        raise RuntimeError("snapshot metadata is missing")
                    previous_content = _read_snapshot(storage, previous)
                    current_content = _read_snapshot(storage, current)
                    diff = generate_diff(
                        _with_final_newline(previous_content),
                        _with_final_newline(current_content),
                    )
                    if not diff:
                        raise RuntimeError("stored snapshots produced no diff")
                    if provider is None:
                        provider = OpenAIProvider.from_env()
                    result = generate_narrative_summary_with_url(
                        change_type=change_type,
                        diff=diff,
                        target_url=str(target["url"]),
                        page_type=str(target["page_type"]),
                        provider=provider,
                    )
                    values: dict[str, Any] = {
                        "detected_url": resolve_blog_detected_url(
                            result.detected_url,
                            str(target["url"]),
                        ),
                    }
                    if not isinstance(before, str) or not before.strip():
                        values["narrative_summary"] = result.narrative_summary
                    updated = changes.update_enrichment(change_id, **values)
                    if updated is None:
                        raise RuntimeError("change row could not be updated")
                    after = updated.get("narrative_summary")
                    after_url = updated.get("detected_url")
                report["updated"] += 1
                entry["after_narrative_summary"] = after
                entry["after_detected_url"] = after_url
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


def _dry_run_detected_url(change: dict[str, Any], *, target_url: str) -> str:
    """Show backfill output without network or LLM calls."""

    if change.get("change_type") not in {
        "NEW_PRODUCT",
        "PRICE_CHANGE",
        "PRODUCT_REMOVED",
    }:
        return target_url
    summary = str(change.get("summary", ""))
    return resolve_product_detected_url(
        change_type=str(change["change_type"]),
        detected_url=change.get("detected_url"),
        summary=summary,
        target_url=target_url,
    )


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
