from __future__ import annotations

import unittest
from datetime import datetime, timezone

from backend.flask.scheduler.sqs_worker import (
    SQSConfigurationError,
    load_worker_config,
    poll_once,
    process_message_record,
)


NOW = datetime(2026, 9, 11, 6, 0, tzinfo=timezone.utc)


class _CompanyService:
    def find_or_create_by_domain(self, domain):
        return {"id": "company-1", "website_url": domain}


class _CompetitorService:
    def find_or_create_competitor(self, **kwargs):
        return {"id": "competitor-1", **kwargs}

    def find_or_create_competitor_with_status(self, **kwargs):
        return {"id": "competitor-1", **kwargs}, True


class _DiscoveryService:
    def __init__(self, error=None):
        self.error = error

    def latest_successful_run(self, competitor_id, *, company_id):
        if self.error:
            raise self.error
        return None

    def discover_and_reconcile(self, competitor_id, *, company_id):
        if self.error:
            raise self.error
        return {"run_id": "run-1", "competitor_id": competitor_id}

    def list_active_targets(self, competitor_id, *, company_id):
        return []


class _MonitoringService:
    def monitor_target(self, target_id, *, idempotency_key):
        return {"run": {"status": "SUCCESS"}, "snapshot": None, "changes": []}


def _services(error=None):
    return {
        "companies": _CompanyService(),
        "competitors": _CompetitorService(),
        "discovery": _DiscoveryService(error=error),
        "monitoring": _MonitoringService(),
    }


def _record(body, receipt):
    return {"Body": body, "ReceiptHandle": receipt, "MessageId": receipt}


class _SQSClient:
    def __init__(self, messages):
        self.messages = messages
        self.receive_calls = []
        self.delete_calls = []

    def receive_message(self, **kwargs):
        self.receive_calls.append(kwargs)
        return {"Messages": self.messages}

    def delete_message(self, **kwargs):
        self.delete_calls.append(kwargs)


VALID_BODY = (
    '{"strategy_id": 1, "company_domain_id": "tenant.example", '
    '"company_url": "https://example.com", "host": "prod"}'
)


class WorkerTests(unittest.TestCase):
    def test_poll_long_polls_and_only_deletes_successful_messages(self):
        client = _SQSClient(
            [
                _record(VALID_BODY, "valid-receipt"),
                _record("not-json", "malformed-receipt"),
            ]
        )

        result = poll_once(
            client,
            "https://sqs.example/queue",
            _services(),
            clock=lambda: NOW,
        )

        self.assertEqual(result.received_count, 2)
        self.assertEqual(result.acknowledged_count, 1)
        self.assertEqual(result.malformed_count, 1)
        self.assertEqual(result.failed_count, 0)
        self.assertEqual(
            client.receive_calls,
            [
                {
                    "QueueUrl": "https://sqs.example/queue",
                    "MaxNumberOfMessages": 10,
                    "WaitTimeSeconds": 20,
                }
            ],
        )
        self.assertEqual(
            client.delete_calls,
            [
                {
                    "QueueUrl": "https://sqs.example/queue",
                    "ReceiptHandle": "valid-receipt",
                }
            ],
        )

    def test_failed_processing_is_left_for_queue_retry(self):
        client = _SQSClient([])
        result = process_message_record(
            client,
            "queue-url",
            _record(VALID_BODY, "failed-receipt"),
            _services(error=RuntimeError("database unavailable")),
            clock=lambda: NOW,
        )

        self.assertFalse(result.acknowledged)
        self.assertTrue(result.failed)
        self.assertEqual(client.delete_calls, [])

    def test_worker_config_requires_region_and_queue_url(self):
        self.assertEqual(
            load_worker_config(
                {
                    "AWS_REGION": " ap-southeast-2 ",
                    "AWS_SQS_QUEUE_URL": " queue-url ",
                }
            ).region,
            "ap-southeast-2",
        )
        with self.assertRaisesRegex(SQSConfigurationError, "AWS_REGION"):
            load_worker_config({"AWS_SQS_QUEUE_URL": "queue-url"})
        with self.assertRaisesRegex(SQSConfigurationError, "AWS_SQS_QUEUE_URL"):
            load_worker_config({"AWS_REGION": "ap-southeast-2"})


if __name__ == "__main__":
    unittest.main()
