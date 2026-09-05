from __future__ import annotations

import logging
import unittest
from datetime import datetime, timedelta, timezone

from backend.flask.scheduler.service import (
    DEFAULT_SCHEDULER_CADENCE_SECONDS,
    SchedulerService,
    run_scheduler_forever,
)
from backend.flask.website_monitoring.service import AlreadyRunningError


NOW = datetime(2026, 9, 5, 12, tzinfo=timezone.utc)


class _TargetRepository:
    def __init__(self, targets):
        self.targets = targets
        self.calls = 0

    def list_active_targets(self, competitor_id=None):
        self.calls += 1
        return list(self.targets)


class _OneTickEvent:
    def __init__(self):
        self.wait_calls = []

    def is_set(self):
        return False

    def wait(self, timeout):
        self.wait_calls.append(timeout)
        return True


class SchedulerServiceTests(unittest.TestCase):
    def test_due_and_not_due_targets_are_evaluated_independently(self):
        targets = [
            {
                "id": "never-checked",
                "check_interval_minutes": 180,
                "last_checked_at": None,
            },
            {
                "id": "recent-blog",
                "check_interval_minutes": 180,
                "last_checked_at": NOW - timedelta(minutes=30),
            },
            {
                "id": "short-interval",
                "check_interval_minutes": 60,
                "last_checked_at": NOW - timedelta(minutes=61),
            },
        ]
        repository = _TargetRepository(targets)
        monitor_calls = []

        def monitor_target(target_id):
            monitor_calls.append(target_id)
            return {"run": {"status": "SUCCESS"}}

        service = SchedulerService(repository, monitor_target)
        result = service.run_due_targets(now=NOW)

        self.assertEqual(repository.calls, 1)
        self.assertEqual(result.evaluated_target_ids, [
            "never-checked",
            "recent-blog",
            "short-interval",
        ])
        self.assertEqual(result.due_target_ids, ["never-checked", "short-interval"])
        self.assertEqual(result.skipped_target_ids, ["recent-blog"])
        self.assertEqual(monitor_calls, ["never-checked", "short-interval"])
        self.assertEqual(result.succeeded_target_ids, monitor_calls)

    def test_monitoring_exception_is_logged_and_does_not_stop_next_target(self):
        repository = _TargetRepository([
            {
                "id": "already-running",
                "check_interval_minutes": 180,
                "last_checked_at": NOW - timedelta(hours=4),
            },
            {
                "id": "healthy",
                "check_interval_minutes": 180,
                "last_checked_at": NOW - timedelta(hours=4),
            },
        ])
        monitor_calls = []

        def monitor_target(target_id):
            monitor_calls.append(target_id)
            if target_id == "already-running":
                raise AlreadyRunningError("target is already running")
            return {"run": {"status": "SUCCESS"}}

        service = SchedulerService(
            repository,
            monitor_target,
            log=logging.getLogger("tests.scheduler"),
        )
        with self.assertLogs("tests.scheduler", level="ERROR") as logs:
            result = service.run_due_targets(now=NOW)

        self.assertEqual(monitor_calls, ["already-running", "healthy"])
        self.assertEqual(result.succeeded_target_ids, ["healthy"])
        self.assertEqual(result.failed_targets[0]["target_id"], "already-running")
        self.assertIn("target is already running", result.failed_targets[0]["error_message"])
        self.assertTrue(any("already-running" in message for message in logs.output))

    def test_failed_monitoring_result_is_recorded_and_next_target_runs(self):
        repository = _TargetRepository([
            {
                "id": "failed-run",
                "check_interval_minutes": 60,
                "last_checked_at": NOW - timedelta(hours=2),
            },
            {
                "id": "successful-run",
                "check_interval_minutes": 60,
                "last_checked_at": NOW - timedelta(hours=2),
            },
        ])

        def monitor_target(target_id):
            if target_id == "failed-run":
                return {"run": {"status": "FAILED", "error_message": "fetch outage"}}
            return {"run": {"status": "SUCCESS"}}

        result = SchedulerService(repository, monitor_target).run_due_targets(now=NOW)

        self.assertEqual(result.succeeded_target_ids, ["successful-run"])
        self.assertEqual(result.failed_targets, [{
            "target_id": "failed-run",
            "phase": "monitoring result",
            "error_message": "fetch outage",
        }])

    def test_naive_persisted_mongo_timestamp_is_interpreted_as_utc(self):
        repository = _TargetRepository([
            {
                "id": "mongo-row",
                "check_interval_minutes": 60,
                "last_checked_at": datetime(2026, 9, 5, 10, 30),
            },
        ])
        calls = []

        def monitor_target(target_id):
            calls.append(target_id)
            return {"run": {"status": "SUCCESS"}}

        result = SchedulerService(repository, monitor_target).run_due_targets(now=NOW)

        self.assertEqual(calls, ["mongo-row"])
        self.assertEqual(result.due_target_ids, ["mongo-row"])

    def test_fixed_cadence_wrapper_runs_tick_then_waits(self):
        calls = []

        class _Scheduler:
            logger = logging.getLogger("tests.scheduler.wrapper")

            def run_due_targets(self):
                calls.append(True)

        event = _OneTickEvent()
        run_scheduler_forever(
            _Scheduler(),
            cadence_seconds=DEFAULT_SCHEDULER_CADENCE_SECONDS,
            stop_event=event,
        )

        self.assertEqual(calls, [True])
        self.assertEqual(event.wait_calls, [DEFAULT_SCHEDULER_CADENCE_SECONDS])


if __name__ == "__main__":
    unittest.main()
