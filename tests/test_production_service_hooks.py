"""Tests for the two small injectable hooks added for the DynamoDB backend:
MonitoringRunService.active_target_check and ChangeService.snapshot_reference_extractor.
Both default to today's exact Mongo-oriented behavior (zero change for dev),
and can be overridden for production's presence-based DynamoDB model.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from backend.flask.change_detection.service import ChangeError, ChangeService
from backend.flask.website_monitoring.service import (
    MonitoringRunError,
    MonitoringRunService,
)


NOW = datetime(2026, 9, 17, 6, 0, tzinfo=timezone.utc)

DYNAMODB_SHAPED_TARGET = {
    "id": "target-1",
    "competitor_id": "competitor-1",
    "url": "https://example.com/blog",
    "page_type": "BLOG",
    "discovery_status": "SUGGESTED",
    "check_interval_minutes": 60,
}

MONGO_SHAPED_ACTIVE_TARGET = {
    **DYNAMODB_SHAPED_TARGET,
    "active": True,
    "discovery_status": "ACTIVE",
}


class _TargetRepository:
    def __init__(self, target):
        self.target = dict(target)
        self.updates = []

    def get(self, target_id):
        return dict(self.target) if target_id == self.target["id"] else None

    def update(self, target_id, values):
        self.updates.append(values)
        self.target.update(values)
        return dict(self.target)


class _RunRepository:
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"

    def __init__(self):
        self.claimed = None
        self.finished = None

    def claim(self, *, monitoring_target_id, started_at, stale_after, now, **_):
        self.claimed = monitoring_target_id
        return {"id": "run-1", "status": self.RUNNING}

    def finish(self, run_id, *, status, finished_at, error_message=None):
        self.finished = status
        return {"id": run_id, "status": status}


class _SnapshotService:
    def list_for_target(self, target_id, *, include_simulated=True):
        return []

    def create_snapshot(self, target_id, content, *, fetch_method, http_status, captured_at):
        return {
            "monitoring_target_id": target_id,
            "captured_at": captured_at.isoformat(),
            "content_hash": "hash-1",
            "content": content,
        }


class _ChangeService:
    def create_change(self, *args, **kwargs):
        raise AssertionError("no change expected on the very first snapshot")


def _fetcher(url):
    from backend.flask.website_monitoring.service import FetchResult

    return FetchResult(content="<html>hello</html>", http_status=200, fetch_method="HTTP")


class ActiveTargetCheckTests(unittest.TestCase):
    def _service(self, **kwargs):
        snapshot_service = _SnapshotService()
        return MonitoringRunService(
            _TargetRepository(kwargs.pop("target", DYNAMODB_SHAPED_TARGET)),
            _RunRepository(),
            snapshot_service,
            snapshot_service,
            _ChangeService(),
            fetcher=_fetcher,
            clock=lambda: NOW,
            **kwargs,
        )

    def test_default_check_rejects_a_dynamodb_shaped_target(self):
        service = self._service()
        with self.assertRaises(MonitoringRunError):
            service.monitor_target("target-1")

    def test_default_check_accepts_a_mongo_active_target(self):
        service = self._service(target=MONGO_SHAPED_ACTIVE_TARGET)
        result = service.monitor_target("target-1")
        self.assertEqual(result["run"]["status"], "SUCCESS")

    def test_injected_check_accepts_a_dynamodb_shaped_target(self):
        service = self._service(active_target_check=lambda target: True)
        result = service.monitor_target("target-1")
        self.assertEqual(result["run"]["status"], "SUCCESS")

    def test_injected_check_can_still_reject(self):
        service = self._service(active_target_check=lambda target: False)
        with self.assertRaises(MonitoringRunError):
            service.monitor_target("target-1")


class _MongoStyleChangeRepository:
    def __init__(self):
        self.calls = []

    def create(self, *, previous_snapshot_id, current_snapshot_id, **kwargs):
        self.calls.append((previous_snapshot_id, current_snapshot_id))
        return {"id": "change-1", **kwargs}


class _TargetReader:
    def get(self, target_id, *, competitor_id=None):
        return {"id": target_id, "page_type": "PAGE_UPDATE", "url": "https://example.com/x"}


MONGO_PREVIOUS_SNAPSHOT = {"id": "snapshot-old", "content_hash": "aaa", "content": "old"}
MONGO_CURRENT_SNAPSHOT = {"id": "snapshot-new", "content_hash": "bbb", "content": "new"}

DYNAMODB_PREVIOUS_SNAPSHOT = {
    "monitoring_target_id": "target-1",
    "captured_at": "2026-01-01T00:00:00+00:00",
    "content_hash": "aaa",
    "content": "old",
}
DYNAMODB_CURRENT_SNAPSHOT = {
    "monitoring_target_id": "target-1",
    "captured_at": "2026-01-02T00:00:00+00:00",
    "content_hash": "bbb",
    "content": "new",
}


class SnapshotReferenceExtractorTests(unittest.TestCase):
    def test_default_extractor_uses_the_single_snapshot_id(self):
        repository = _MongoStyleChangeRepository()
        service = ChangeService(repository, _TargetReader())
        service.create_change(
            "target-1", MONGO_PREVIOUS_SNAPSHOT, MONGO_CURRENT_SNAPSHOT, detected_at=NOW
        )
        self.assertEqual(repository.calls, [("snapshot-old", "snapshot-new")])

    def test_injected_extractor_returns_the_dynamodb_reference_pair(self):
        def extractor(snapshot, label):
            return {
                "monitoring_target_id": snapshot["monitoring_target_id"],
                "captured_at": snapshot["captured_at"],
            }

        repository = _MongoStyleChangeRepository()
        service = ChangeService(
            repository,
            _TargetReader(),
            snapshot_reference_extractor=extractor,
        )
        service.create_change(
            "target-1", DYNAMODB_PREVIOUS_SNAPSHOT, DYNAMODB_CURRENT_SNAPSHOT, detected_at=NOW
        )
        self.assertEqual(
            repository.calls,
            [
                (
                    {"monitoring_target_id": "target-1", "captured_at": "2026-01-01T00:00:00+00:00"},
                    {"monitoring_target_id": "target-1", "captured_at": "2026-01-02T00:00:00+00:00"},
                )
            ],
        )

    def test_default_extractor_raises_for_a_dynamodb_shaped_snapshot(self):
        repository = _MongoStyleChangeRepository()
        service = ChangeService(repository, _TargetReader())
        with self.assertRaises(ChangeError):
            service.create_change(
                "target-1", DYNAMODB_PREVIOUS_SNAPSHOT, DYNAMODB_CURRENT_SNAPSHOT, detected_at=NOW
            )


if __name__ == "__main__":
    unittest.main()
