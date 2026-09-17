"""Opt-in live evidence for the P.3/P.4 SQS handler and worker.

This verification sends two clearly labeled messages to the configured real
queue, writes only to the dedicated test Mongo database, proves first-run
monitoring behavior, and removes every test company, competitor, target,
discovery-run, snapshot, monitoring-run, and change row before returning.

Run from the repository root with:

    MONGODB_DATABASE=competitors_monitoring_test \
    RUN_LIVE_SQS=1 \
      ./.venv/bin/python -u tests/live_sqs_verification.py
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from uuid import uuid4

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import boto3
from dotenv import load_dotenv

from backend.flask.app import create_app
from backend.flask.companies.repository import CompanyRepository
from backend.flask.competitors.repository import CompetitorRepository
from backend.flask.database.connection import MongoSettings, connect_database
from backend.flask.database.base_repository import to_object_id
from backend.flask.discovery.repository import DiscoveryRunRepository
from backend.flask.scheduler.sqs_handler import handle_message, parse_message
from backend.flask.scheduler.sqs_worker import (
    SQSWorkerConfig,
    load_worker_config,
    process_message_record,
)
from backend.flask.snapshot.storage import SnapshotStorage
from backend.flask.website_monitoring.repository import MonitoringTargetRepository


TEST_DATABASE = "competitors_monitoring_test"
MAX_RECEIVE_SECONDS = 45


def run_live_verification() -> dict[str, object]:
    if os.environ.get("RUN_LIVE_SQS") != "1":
        raise SystemExit("Set RUN_LIVE_SQS=1 to run live SQS verification")

    load_dotenv(override=False)
    settings = MongoSettings.from_env()
    if settings.database_name != TEST_DATABASE:
        raise RuntimeError(
            f"refusing to write outside {TEST_DATABASE!r}; "
            f"configured database is {settings.database_name!r}"
        )
    config = load_worker_config()
    sqs = boto3.client("sqs", region_name=config.region)
    queue_attributes = sqs.get_queue_attributes(
        QueueUrl=config.queue_url,
        AttributeNames=["All"],
    )["Attributes"]
    if queue_attributes.get("VisibilityTimeout") != "900":
        raise AssertionError(
            "expected the configured queue visibility timeout to remain 900 seconds"
        )
    redrive_policy = json.loads(queue_attributes.get("RedrivePolicy", "{}"))
    if str(redrive_policy.get("maxReceiveCount")) != "10":
        raise AssertionError("expected the configured queue DLQ maxReceiveCount to be 10")

    approximate_visible = int(queue_attributes.get("ApproximateNumberOfMessages", "0"))
    approximate_in_flight = int(
        queue_attributes.get("ApproximateNumberOfMessagesNotVisible", "0")
    )
    if approximate_visible or approximate_in_flight:
        raise RuntimeError(
            "refusing live test because the real queue is not empty; "
            f"visible={approximate_visible}, in_flight={approximate_in_flight}"
        )

    mongo_client, database = connect_database(
        settings,
        serverSelectionTimeoutMS=15_000,
    )
    test_domain = f"p3-sqs-test-{uuid4().hex}.example.invalid"
    test_url = f"https://example.com/p3-sqs-test-{uuid4().hex}"
    message_body = json.dumps(
        {
            "company_domain_id": test_domain,
            "competitor_lst": [test_url],
            "host": "DEV",
        }
    )
    malformed_body = json.dumps(
        {
            "competitor_lst": [test_url],
            "host": "DEV",
        }
    )

    companies = CompanyRepository.from_database(database)
    competitors = CompetitorRepository.from_database(database)
    targets = MonitoringTargetRepository.from_database(database)
    runs = DiscoveryRunRepository.from_database(database)
    services = create_app(
        database=database,
        user_id="p3-sqs-live-verification",
        testing=True,
    ).extensions["api_services"]
    created_company_id = None
    created_competitor_id = None
    valid_record = None
    malformed_record = None
    valid_acknowledged = False
    malformed_acknowledged = False
    try:
        mongo_client.admin.command("ping")
        company = companies.find_by_website_url(test_domain)
        if company is not None:
            raise AssertionError("generated test company unexpectedly already exists")

        sent = sqs.send_message(QueueUrl=config.queue_url, MessageBody=message_body)
        snapshot_count_before = database["snapshots"].count_documents({})
        monitoring_run_count_before = database["monitoring_runs"].count_documents({})
        valid_record = _receive_body(
            sqs,
            config,
            message_body,
            visibility_timeout=60,
        )
        valid_result = process_message_record(
            sqs,
            config.queue_url,
            valid_record,
            services,
            clock=_utc_now,
        )
        valid_acknowledged = valid_result.acknowledged
        if not valid_acknowledged:
            raise AssertionError(f"valid live message was not processed: {valid_result}")

        company = companies.find_by_website_url(test_domain)
        if company is None:
            raise AssertionError("worker did not create the test company")
        created_company_id = company["id"]
        competitor = competitors.find_by_company_and_website_url(
            created_company_id,
            _normalized_test_url(test_url),
        )
        if competitor is None:
            raise AssertionError("worker did not create the test competitor")
        created_competitor_id = competitor["id"]
        active_targets = targets.list_active_targets(created_competitor_id)
        test_runs = _runs_for_competitor(database, created_competitor_id)
        snapshot_count_after = database["snapshots"].count_documents({})
        monitoring_run_count_after = database["monitoring_runs"].count_documents({})
        if len(test_runs) != 1 or test_runs[0].get("status") != "SUCCESS":
            raise AssertionError(f"expected one successful discovery run: {test_runs}")
        if valid_result.outcome is None or valid_result.outcome.get("action") != "first_run":
            raise AssertionError(f"worker did not reconcile the new competitor: {valid_result}")
        if snapshot_count_after - snapshot_count_before != len(active_targets):
            raise AssertionError("new-competitor flow did not create one snapshot per active target")
        if monitoring_run_count_after - monitoring_run_count_before != len(active_targets):
            raise AssertionError(
                "new-competitor flow did not create one monitoring run per active target"
            )

        parsed = parse_message(message_body)
        first_duplicate_call = handle_message(
            parsed,
            services,
            clock=_utc_now,
            message_id=valid_record.get("MessageId"),
        )
        state_after_first_duplicate = _state(database, created_company_id, created_competitor_id)
        second_duplicate_call = handle_message(
            parsed,
            services,
            clock=_utc_now,
            message_id=valid_record.get("MessageId"),
        )
        state_after_second_duplicate = _state(database, created_company_id, created_competitor_id)
        if state_after_first_duplicate != state_after_second_duplicate:
            raise AssertionError("identical handle_message calls changed the persisted state")
        if len(competitors.list_for_company(created_company_id)) != 1:
            raise AssertionError("identical messages created a duplicate competitor")
        if first_duplicate_call["action"] != "skipped_fresh" or second_duplicate_call["action"] != "skipped_fresh":
            raise AssertionError("fresh duplicate calls did not skip discovery")
        if not all(
            item.get("idempotent") is True
            for item in first_duplicate_call.get("monitoring", ())
        ):
            raise AssertionError("duplicate delivery did not reuse completed monitoring runs")
        if database["snapshots"].count_documents({}) != snapshot_count_after:
            raise AssertionError("duplicate delivery created another snapshot")
        if database["monitoring_runs"].count_documents({}) != monitoring_run_count_after:
            raise AssertionError("duplicate delivery created another monitoring run")

        malformed_sent = sqs.send_message(
            QueueUrl=config.queue_url,
            MessageBody=malformed_body,
        )
        malformed_record = _receive_body(
            sqs,
            config,
            malformed_body,
            visibility_timeout=2,
        )
        malformed_result = process_message_record(
            sqs,
            config.queue_url,
            malformed_record,
            services,
            clock=_utc_now,
        )
        if malformed_result.acknowledged:
            raise AssertionError("malformed message was acknowledged")
        if not malformed_result.malformed:
            raise AssertionError("malformed message was not classified as malformed")
        sqs.change_message_visibility(
            QueueUrl=config.queue_url,
            ReceiptHandle=malformed_record["ReceiptHandle"],
            VisibilityTimeout=0,
        )
        redelivered = _receive_body(
            sqs,
            config,
            malformed_body,
            visibility_timeout=2,
        )
        if redelivered.get("Body") != malformed_body:
            raise AssertionError("malformed message could not be observed after redelivery")
        sqs.delete_message(
            QueueUrl=config.queue_url,
            ReceiptHandle=redelivered["ReceiptHandle"],
        )
        malformed_acknowledged = False

        evidence = {
            "queue_region": config.region,
            "queue_visibility_timeout_seconds": int(queue_attributes["VisibilityTimeout"]),
            "queue_dlq_max_receive_count": int(redrive_policy["maxReceiveCount"]),
            "sent_message_id": sent.get("MessageId"),
            "valid_worker_record": {
                "acknowledged": valid_result.acknowledged,
                "action": valid_result.outcome.get("action") if valid_result.outcome else None,
            },
            "test_company_id": created_company_id,
            "test_competitor_id": created_competitor_id,
            "active_target_count_after_reconciliation": len(active_targets),
            "successful_discovery_runs": len(test_runs),
            "initial_snapshots_created": snapshot_count_after - snapshot_count_before,
            "initial_monitoring_runs_created": (
                monitoring_run_count_after - monitoring_run_count_before
            ),
            "idempotency": {
                "first_action": first_duplicate_call["action"],
                "second_action": second_duplicate_call["action"],
                "competitor_count": len(competitors.list_for_company(created_company_id)),
                "state_identical": state_after_first_duplicate == state_after_second_duplicate,
            },
            "malformed_message": {
                "sent_message_id": malformed_sent.get("MessageId"),
                "worker_acknowledged": malformed_result.acknowledged,
                "redelivered_same_body": redelivered.get("Body") == malformed_body,
                "manually_deleted_after_proof": True,
            },
        }
        print(json.dumps(evidence, default=str, indent=2, sort_keys=True))
        return evidence
    finally:
        if malformed_record is not None and not malformed_acknowledged:
            _best_effort_delete(sqs, config.queue_url, malformed_record)
        if valid_record is not None and not valid_acknowledged:
            _best_effort_delete(sqs, config.queue_url, valid_record)
        if created_competitor_id is not None:
            target_ids = [
                target["id"]
                for target in targets.list_for_competitor(created_competitor_id)
            ]
            storage = SnapshotStorage()
            for target_id in target_ids:
                snapshot_documents = list(
                    database["snapshots"].find(
                        {"monitoring_target_id": to_object_id(target_id)},
                        {"storage_path": 1},
                    )
                )
                for snapshot in snapshot_documents:
                    if snapshot.get("storage_path"):
                        storage.delete_snapshot(snapshot["storage_path"])
                database["snapshots"].delete_many(
                    {"monitoring_target_id": to_object_id(target_id)}
                )
                database["monitoring_runs"].delete_many(
                    {"monitoring_target_id": to_object_id(target_id)}
                )
                database["changes"].delete_many(
                    {"monitoring_target_id": to_object_id(target_id)}
                )
            for target in targets.list_for_competitor(created_competitor_id):
                targets.delete(target["id"], competitor_id=created_competitor_id)
            database["discovery_runs"].delete_many(
                {"competitor_id": to_object_id(created_competitor_id)}
            )
            competitors.delete(created_competitor_id, company_id=created_company_id)
        if created_company_id is not None:
            database["companies"].delete_one({"_id": to_object_id(created_company_id)})
        mongo_client.close()


def _receive_body(
    sqs: object,
    config: SQSWorkerConfig,
    expected_body: str,
    *,
    visibility_timeout: int,
) -> dict[str, str]:
    deadline = time.monotonic() + MAX_RECEIVE_SECONDS
    while time.monotonic() < deadline:
        response = sqs.receive_message(
            QueueUrl=config.queue_url,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=20,
            VisibilityTimeout=visibility_timeout,
        )
        for record in response.get("Messages", ()):
            if record.get("Body") == expected_body:
                return record
            sqs.change_message_visibility(
                QueueUrl=config.queue_url,
                ReceiptHandle=record["ReceiptHandle"],
                VisibilityTimeout=0,
            )
    raise AssertionError("expected live test message was not received")


def _state(database: object, company_id: str, competitor_id: str) -> dict[str, object]:
    targets = MonitoringTargetRepository.from_database(database)
    return {
        "competitors": [
            {
                key: competitor[key]
                for key in ("id", "company_id", "website_url", "active", "name")
                if key in competitor
            }
            for competitor in CompetitorRepository.from_database(database).list_for_company(
                company_id
            )
        ],
        "targets": [
            {
                key: target[key]
                for key in ("id", "url", "active", "discovery_status")
                if key in target
            }
            for target in targets.list_for_competitor(competitor_id)
        ],
        "runs": [
            {
                key: run[key]
                for key in ("run_id", "status", "candidate_count")
                if key in run
            }
            for run in _runs_for_competitor(database, competitor_id)
        ],
    }


def _runs_for_competitor(database: object, competitor_id: str) -> list[dict[str, object]]:
    return list(
        database["discovery_runs"].find(
            {"competitor_id": to_object_id(competitor_id)}
        )
    )


def _normalized_test_url(value: str) -> str:
    return value.rstrip("/")


def _best_effort_delete(sqs: object, queue_url: str, record: dict[str, str]) -> None:
    try:
        sqs.delete_message(
            QueueUrl=queue_url,
            ReceiptHandle=record["ReceiptHandle"],
        )
    except Exception:
        pass


def _utc_now():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)


if __name__ == "__main__":
    run_live_verification()
