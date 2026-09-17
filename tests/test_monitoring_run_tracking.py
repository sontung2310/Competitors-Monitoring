from __future__ import annotations

import unittest
from copy import deepcopy
from datetime import datetime, timedelta, timezone

from backend.flask.website_monitoring.repository import (
    DEFAULT_RUN_STALE_AFTER,
    MonitoringRunRepository,
    MonitoringTargetRepository,
    RunAlreadyClaimedError,
)
from backend.flask.website_monitoring.service import (
    AlreadyRunningError,
    FetchResult,
    MonitoringError,
    MonitoringRunService,
    hash_content,
    normalize_content,
)

try:
    from bson import ObjectId
except ImportError:  # pragma: no cover - exercised only without PyMongo
    ObjectId = None


class _InsertResult:
    def __init__(self, inserted_id):
        self.inserted_id = inserted_id


class _WriteResult:
    def __init__(self, *, matched_count=0):
        self.matched_count = matched_count


class _Cursor(list):
    def sort(self, fields):
        for field, direction in reversed(fields):
            super().sort(
                key=lambda document: document.get(field),
                reverse=direction < 0,
            )
        return self


class _FakeCollection:
    def __init__(self):
        self.documents = []
        self.indexes = []
        self._next_id = 1

    def create_index(self, keys, **options):
        self.indexes.append((keys, options))
        return options.get("name")

    def insert_one(self, document):
        stored = deepcopy(document)
        raw_id = f"{self._next_id:024x}"
        stored["_id"] = ObjectId(raw_id) if ObjectId else raw_id
        self._next_id += 1
        self.documents.append(stored)
        return _InsertResult(stored["_id"])

    def find_one(self, query):
        for document in self.documents:
            if _matches(document, query):
                return deepcopy(document)
        return None

    def find(self, query):
        return _Cursor(
            deepcopy(document)
            for document in self.documents
            if _matches(document, query)
        )

    def update_one(self, query, update):
        for document in self.documents:
            if _matches(document, query):
                document.update(deepcopy(update["$set"]))
                for field in update.get("$unset", {}):
                    document.pop(field, None)
                return _WriteResult(matched_count=1)
        return _WriteResult(matched_count=0)


class _DuplicateKeyError(RuntimeError):
    code = 11000


class _UniqueRunningCollection(_FakeCollection):
    """Fake Mongo collection that models the partial unique RUNNING index."""

    def insert_one(self, document):
        if document.get("status") == "RUNNING" and any(
            existing.get("status") == "RUNNING"
            and existing.get("monitoring_target_id")
            == document.get("monitoring_target_id")
            for existing in self.documents
        ):
            raise _DuplicateKeyError("duplicate RUNNING target claim")
        return super().insert_one(document)


def _matches(document, query):
    return all(document.get(field) == value for field, value in query.items())


class _TargetRepository:
    def __init__(self, target):
        self.target = deepcopy(target)
        self.updates = []

    def get(self, target_id, *, competitor_id=None):
        if self.target["id"] != target_id:
            return None
        return deepcopy(self.target)

    def update(self, target_id, updates, *, competitor_id=None):
        if self.target["id"] != target_id:
            return None
        self.updates.append(dict(updates))
        self.target.update(updates)
        return deepcopy(self.target)


class _RunRepository:
    def __init__(self):
        self.records = []
        self.transitions = []

    def create(self, *, monitoring_target_id, started_at, status, **kwargs):
        record = {
            "id": f"run-{len(self.records) + 1}",
            "monitoring_target_id": monitoring_target_id,
            "idempotency_key": kwargs.get("idempotency_key"),
            "started_at": started_at,
            "finished_at": None,
            "status": status,
            "error_message": kwargs.get("error_message"),
        }
        self.records.append(record)
        self.transitions.append((record["id"], status))
        return deepcopy(record)

    def find_by_idempotency_key(self, monitoring_target_id, idempotency_key):
        for record in self.records:
            if (
                record["monitoring_target_id"] == monitoring_target_id
                and record.get("idempotency_key") == idempotency_key
            ):
                return deepcopy(record)
        return None

    def claim(
        self,
        *,
        monitoring_target_id,
        started_at,
        status="RUNNING",
        stale_after,
        now,
        idempotency_key=None,
    ):
        return self.create(
            monitoring_target_id=monitoring_target_id,
            started_at=started_at,
            status=status,
            idempotency_key=idempotency_key,
        )

    def finish(self, run_id, *, status, finished_at, error_message=None):
        for record in self.records:
            if record["id"] == run_id:
                record.update(
                    {
                        "status": status,
                        "finished_at": finished_at,
                        "error_message": error_message,
                    }
                )
                self.transitions.append((run_id, status))
                return deepcopy(record)
        return None


class _SnapshotRepository:
    def __init__(self, snapshots=()):
        self.snapshots = [deepcopy(snapshot) for snapshot in snapshots]

    def list_for_target(self, monitoring_target_id):
        return [
            deepcopy(snapshot)
            for snapshot in self.snapshots
            if snapshot["monitoring_target_id"] == monitoring_target_id
        ]


class _SnapshotService:
    def __init__(self, repository):
        self.repository = repository
        self.calls = []

    def create_snapshot(
        self,
        target_id,
        content,
        *,
        fetch_method,
        http_status,
        captured_at,
    ):
        self.calls.append(
            {
                "target_id": target_id,
                "content": content,
                "fetch_method": fetch_method,
                "http_status": http_status,
                "captured_at": captured_at,
            }
        )
        normalized = normalize_content(content)
        record = {
            "id": f"snapshot-{len(self.repository.snapshots) + 1}",
            "monitoring_target_id": target_id,
            "content_hash": hash_content(normalized),
            "content": normalized,
            "fetch_method": fetch_method,
            "http_status": http_status,
            "captured_at": captured_at,
        }
        self.repository.snapshots.append(record)
        return deepcopy(record)


class _ChangeService:
    def __init__(self):
        self.calls = []

    def create_change(
        self,
        target_id,
        previous_snapshot,
        current_snapshot,
        *,
        detected_at,
        change_type=None,
        summary=None,
    ):
        self.calls.append(
            {
                "target_id": target_id,
                "previous_snapshot": deepcopy(previous_snapshot),
                "current_snapshot": deepcopy(current_snapshot),
                "detected_at": detected_at,
                "change_type": change_type,
                "summary": summary,
            }
        )
        return {
            "id": f"change-{len(self.calls)}",
            "detected_at": detected_at,
        }


class _RejectingRunRepository(_RunRepository):
    def claim(self, **kwargs):
        raise RunAlreadyClaimedError(
            "monitoring target 'target-1' already has active RUNNING run 'run-existing'"
        )


class _Clock:
    def __init__(self):
        self.current = datetime(2026, 9, 4, 12, tzinfo=timezone.utc)

    def __call__(self):
        value = self.current
        self.current += timedelta(microseconds=1)
        return value


class MonitoringRunRepositoryTests(unittest.TestCase):
    def test_run_repository_defines_queryable_indexes_and_lifecycle_shape(self):
        collection = _UniqueRunningCollection()
        repository = MonitoringRunRepository(collection)
        repository.ensure_indexes()

        self.assertEqual(
            {options["name"] for _, options in collection.indexes},
            {
                "ix_monitoring_runs_target_started_at",
                "ix_monitoring_runs_target_status",
                "uq_monitoring_runs_running_target",
                "uq_monitoring_runs_target_idempotency_key",
            },
        )
        unique_index = next(
            options
            for _, options in collection.indexes
            if options["name"] == "uq_monitoring_runs_running_target"
        )
        self.assertTrue(unique_index["unique"])
        self.assertEqual(
            unique_index["partialFilterExpression"],
            {"status": "RUNNING"},
        )
        target_id = "000000000000000000000001"
        started_at = datetime(2026, 9, 4, 12, tzinfo=timezone.utc)
        run = repository.create(
            monitoring_target_id=target_id,
            started_at=started_at,
        )
        self.assertEqual(run["status"], "RUNNING")
        self.assertIsNone(run["finished_at"])
        self.assertIsNone(run["error_message"])
        self.assertEqual(repository.list_for_target(target_id)[0]["id"], run["id"])

        finished = repository.finish(
            run["id"],
            status="FAILED",
            finished_at=started_at + timedelta(seconds=1),
            error_message="HTTP fetch failed: connection refused",
        )
        self.assertEqual(finished["status"], "FAILED")
        self.assertIn("connection refused", finished["error_message"])

    def test_atomic_claim_rejects_fresh_duplicate_but_allows_other_targets(self):
        collection = _UniqueRunningCollection()
        repository = MonitoringRunRepository(collection)
        repository.ensure_indexes()
        now = datetime(2026, 9, 4, 12, tzinfo=timezone.utc)

        first = repository.claim(
            monitoring_target_id="000000000000000000000001",
            started_at=now,
            now=now,
        )
        with self.assertRaisesRegex(RunAlreadyClaimedError, "active RUNNING run"):
            repository.claim(
                monitoring_target_id="000000000000000000000001",
                started_at=now + timedelta(seconds=1),
                now=now + timedelta(seconds=1),
            )
        second = repository.claim(
            monitoring_target_id="000000000000000000000002",
            started_at=now + timedelta(seconds=1),
            now=now + timedelta(seconds=1),
        )

        self.assertEqual(first["status"], "RUNNING")
        self.assertEqual(second["status"], "RUNNING")
        self.assertEqual(len(collection.documents), 2)

    def test_failed_idempotent_run_releases_key_for_retry(self):
        collection = _UniqueRunningCollection()
        repository = MonitoringRunRepository(collection)
        repository.ensure_indexes()
        now = datetime(2026, 9, 4, 12, tzinfo=timezone.utc)

        run = repository.claim(
            monitoring_target_id="000000000000000000000001",
            started_at=now,
            now=now,
            idempotency_key="sqs:retry-me",
        )
        failed = repository.finish(
            run["id"],
            status="FAILED",
            finished_at=now + timedelta(seconds=1),
            error_message="temporary failure",
        )

        self.assertNotIn("idempotency_key", failed)
        self.assertIsNone(
            repository.find_by_idempotency_key(
                "000000000000000000000001",
                "sqs:retry-me",
            )
        )

    def test_stale_claim_is_failed_then_replaced(self):
        collection = _UniqueRunningCollection()
        repository = MonitoringRunRepository(collection)
        repository.ensure_indexes()
        now = datetime(2026, 9, 4, 12, tzinfo=timezone.utc)
        stale_started_at = now - DEFAULT_RUN_STALE_AFTER - timedelta(seconds=1)

        stale = repository.claim(
            monitoring_target_id="000000000000000000000001",
            started_at=stale_started_at,
            now=stale_started_at,
        )
        replacement = repository.claim(
            monitoring_target_id="000000000000000000000001",
            started_at=now,
            now=now,
        )

        failed = repository.get(stale["id"])
        self.assertEqual(failed["status"], "FAILED")
        self.assertIn("orphaned", failed["error_message"])
        self.assertIn("staleness threshold", failed["error_message"])
        self.assertEqual(replacement["status"], "RUNNING")
        self.assertEqual(len(collection.documents), 2)


class MonitoringRunServiceTests(unittest.TestCase):
    target_id = "target-1"

    def _make_service(
        self,
        *,
        previous_content=None,
        fetcher=None,
        run_repository=None,
    ):
        target = {
            "id": self.target_id,
            "url": "https://example.com/blog",
            "page_type": "BLOG",
            "active": True,
            "discovery_status": "ACTIVE",
            "last_checked_at": None,
            "last_changed_at": "unchanged",
        }
        snapshots = _SnapshotRepository()
        if previous_content is not None:
            normalized = normalize_content(previous_content)
            snapshots.snapshots.append(
                {
                    "id": "snapshot-old",
                    "monitoring_target_id": self.target_id,
                    "content_hash": hash_content(normalized),
                    "content": normalized,
                }
            )
        snapshot_service = _SnapshotService(snapshots)
        change_service = _ChangeService()
        run_repository = run_repository or _RunRepository()
        target_repository = _TargetRepository(target)
        service = MonitoringRunService(
            target_repository,
            run_repository,
            snapshots,
            snapshot_service,
            change_service,
            fetcher=fetcher
            or (
                lambda url: FetchResult(
                    "<main>Stable page content with enough visible text to monitor.</main>",
                    "HTTP",
                    200,
                )
            ),
            clock=_Clock(),
        )
        return (
            service,
            target_repository,
            snapshots,
            snapshot_service,
            change_service,
            run_repository,
        )

    def test_already_running_is_distinct_and_has_no_monitoring_side_effects(self):
        service, target, snapshots, snapshot_service, change_service, runs = self._make_service(
            run_repository=_RejectingRunRepository(),
        )

        with self.assertRaisesRegex(AlreadyRunningError, "active RUNNING run"):
            service.monitor_target(self.target_id)

        self.assertEqual(target.updates, [])
        self.assertEqual(snapshot_service.calls, [])
        self.assertEqual(change_service.calls, [])
        self.assertEqual(runs.records, [])

    def test_success_transitions_running_to_success_and_skips_change_when_hash_matches(self):
        service, target, snapshots, snapshot_service, change_service, runs = self._make_service(
            previous_content="<main>Stable page content with enough visible text to monitor.</main>"
        )
        old_last_changed_at = target.target["last_changed_at"]

        result = service.monitor_target(self.target_id)

        self.assertEqual(
            runs.transitions,
            [("run-1", "RUNNING"), ("run-1", "SUCCESS")],
        )
        self.assertEqual(result["run"]["status"], "SUCCESS")
        self.assertEqual(len(snapshot_service.calls), 1)
        self.assertEqual(len(snapshots.snapshots), 2)
        self.assertEqual(snapshots.snapshots[0]["content_hash"], snapshots.snapshots[1]["content_hash"])
        self.assertEqual(change_service.calls, [])
        self.assertIsNotNone(target.target["last_checked_at"])
        self.assertEqual(target.target["last_changed_at"], old_last_changed_at)

    def test_changed_success_creates_change_and_updates_last_changed_at(self):
        service, target, snapshots, snapshot_service, change_service, runs = self._make_service(
            previous_content="<main>Old page content with enough visible text to monitor.</main>",
            fetcher=lambda url: FetchResult(
                "<main>New page content with enough visible text to monitor.</main>",
                "BROWSER",
                200,
            ),
        )
        old_last_changed_at = target.target["last_changed_at"]

        result = service.monitor_target(self.target_id)

        self.assertEqual(result["run"]["status"], "SUCCESS")
        self.assertEqual(result["change"]["id"], "change-1")
        self.assertEqual(len(change_service.calls), 1)
        self.assertEqual(change_service.calls[0]["previous_snapshot"]["id"], "snapshot-old")
        self.assertNotEqual(target.target["last_changed_at"], old_last_changed_at)
        self.assertEqual(snapshot_service.calls[0]["fetch_method"], "BROWSER")
        self.assertEqual(len(snapshots.snapshots), 2)
        self.assertEqual(runs.transitions[-1], ("run-1", "SUCCESS"))

    def test_sqs_idempotency_key_replays_completed_run_without_fetching_or_resnapshotting(self):
        service, target, snapshots, snapshot_service, change_service, runs = self._make_service()

        first = service.monitor_target(self.target_id, idempotency_key="sqs:message-1")
        second = service.monitor_target(self.target_id, idempotency_key="sqs:message-1")

        self.assertEqual(first["run"]["status"], "SUCCESS")
        self.assertTrue(second["idempotent"])
        self.assertEqual(len(runs.records), 1)
        self.assertEqual(len(snapshot_service.calls), 1)
        self.assertEqual(len(snapshots.snapshots), 1)
        self.assertEqual(change_service.calls, [])

    def test_fetch_failure_marks_failed_without_snapshot_or_change_and_preserves_previous(self):
        previous_content = "<main>Previously valid content with enough visible text to monitor.</main>"

        def failing_fetch(url):
            raise MonitoringError("temporary upstream connection refused")

        service, target, snapshots, snapshot_service, change_service, runs = self._make_service(
            previous_content=previous_content,
            fetcher=failing_fetch,
        )
        previous_before = deepcopy(snapshots.snapshots[0])
        old_last_changed_at = target.target["last_changed_at"]

        result = service.monitor_target(self.target_id)

        self.assertEqual(runs.transitions, [("run-1", "RUNNING"), ("run-1", "FAILED")])
        self.assertEqual(result["run"]["status"], "FAILED")
        self.assertIn("fetch failed", result["run"]["error_message"])
        self.assertIn("connection refused", result["run"]["error_message"])
        self.assertEqual(snapshot_service.calls, [])
        self.assertEqual(change_service.calls, [])
        self.assertEqual(snapshots.snapshots, [previous_before])
        self.assertIsNotNone(target.target["last_checked_at"])
        self.assertEqual(target.target["last_changed_at"], old_last_changed_at)


if __name__ == "__main__":
    unittest.main()
