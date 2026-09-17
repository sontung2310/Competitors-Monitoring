"""Thin boto3 SQS polling wrapper for production ingestion."""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from threading import Event
from typing import Any, Callable

from backend.flask.database.base_repository import utc_now

from .sqs_handler import MessageValidationError, handle_message, parse_message
from .strategy_lookup import StrategyLookupService


WAIT_TIME_SECONDS = 20
MAX_NUMBER_OF_MESSAGES = 10

logger = logging.getLogger(__name__)


class SQSConfigurationError(RuntimeError):
    """Raised when the worker cannot read its required environment settings."""


@dataclass(frozen=True)
class SQSWorkerConfig:
    region: str
    queue_url: str


@dataclass
class PollResult:
    """Operational summary for one receive/process/delete pass."""

    received_count: int = 0
    acknowledged_count: int = 0
    malformed_count: int = 0
    failed_count: int = 0
    delete_failed_count: int = 0
    outcomes: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "received_count": self.received_count,
            "acknowledged_count": self.acknowledged_count,
            "malformed_count": self.malformed_count,
            "failed_count": self.failed_count,
            "delete_failed_count": self.delete_failed_count,
            "outcomes": [dict(outcome) for outcome in self.outcomes],
        }


@dataclass(frozen=True)
class RecordResult:
    acknowledged: bool
    malformed: bool = False
    failed: bool = False
    delete_failed: bool = False
    outcome: dict[str, Any] | None = None


def load_worker_config(
    environ: Mapping[str, str] | None = None,
) -> SQSWorkerConfig:
    """Load queue settings from the same dotenv-backed environment pattern."""

    if environ is None:
        _load_dotenv()
        values: Mapping[str, str] = os.environ
    else:
        values = environ
    region = values.get("AWS_REGION", "").strip()
    queue_url = values.get("AWS_SQS_QUEUE_URL", "").strip()
    if not region:
        raise SQSConfigurationError("AWS_REGION is not configured")
    if not queue_url:
        raise SQSConfigurationError("AWS_SQS_QUEUE_URL is not configured")
    return SQSWorkerConfig(region=region, queue_url=queue_url)


def create_sqs_client(config: SQSWorkerConfig) -> Any:
    """Create boto3's SQS client; boto3 reads AWS credential env vars itself."""

    try:
        import boto3
    except ImportError as exc:
        raise SQSConfigurationError(
            "boto3 is required for the SQS worker; install requirements.txt"
        ) from exc
    return boto3.client("sqs", region_name=config.region)


def process_message_record(
    sqs_client: Any,
    queue_url: str,
    record: Mapping[str, Any],
    services: Mapping[str, Any],
    *,
    clock: Callable[[], datetime] = utc_now,
    log: logging.Logger | None = None,
) -> RecordResult:
    """Handle one received record and acknowledge only after success."""

    output_log = log or logger
    try:
        message = parse_message(record.get("Body"))
    except MessageValidationError as exc:
        output_log.warning("leaving malformed SQS message unacknowledged: %s", exc)
        return RecordResult(acknowledged=False, malformed=True)

    try:
        outcome = handle_message(
            message,
            services,
            clock=clock,
            message_id=record.get("MessageId"),
        )
    except Exception as exc:  # noqa: BLE001 - leave failed messages for DLQ retry
        output_log.exception("leaving failed SQS message unacknowledged: %s", exc)
        return RecordResult(acknowledged=False, failed=True)

    receipt_handle = record.get("ReceiptHandle")
    if not isinstance(receipt_handle, str) or not receipt_handle.strip():
        output_log.error("processed SQS message has no receipt handle; cannot acknowledge")
        return RecordResult(acknowledged=False, failed=True, outcome=outcome)
    try:
        sqs_client.delete_message(
            QueueUrl=queue_url,
            ReceiptHandle=receipt_handle,
        )
    except Exception as exc:  # noqa: BLE001 - message remains retryable
        output_log.exception("processed SQS message could not be acknowledged: %s", exc)
        return RecordResult(
            acknowledged=False,
            delete_failed=True,
            outcome=outcome,
        )
    return RecordResult(acknowledged=True, outcome=outcome)


def poll_once(
    sqs_client: Any,
    queue_url: str,
    services: Mapping[str, Any],
    *,
    clock: Callable[[], datetime] = utc_now,
    log: logging.Logger | None = None,
) -> PollResult:
    """Receive up to ten messages with a 20-second long poll and process them."""

    response = sqs_client.receive_message(
        QueueUrl=queue_url,
        MaxNumberOfMessages=MAX_NUMBER_OF_MESSAGES,
        WaitTimeSeconds=WAIT_TIME_SECONDS,
    )
    result = PollResult()
    for record in response.get("Messages", ()):
        result.received_count += 1
        processed = process_message_record(
            sqs_client,
            queue_url,
            record,
            services,
            clock=clock,
            log=log,
        )
        if processed.acknowledged:
            result.acknowledged_count += 1
            if processed.outcome is not None:
                result.outcomes.append(processed.outcome)
        if processed.malformed:
            result.malformed_count += 1
        if processed.failed:
            result.failed_count += 1
        if processed.delete_failed:
            result.delete_failed_count += 1
    return result


def run_worker_forever(
    services: Mapping[str, Any],
    *,
    sqs_client: Any | None = None,
    config: SQSWorkerConfig | None = None,
    clock: Callable[[], datetime] = utc_now,
    stop_event: Event | None = None,
    log: logging.Logger | None = None,
) -> None:
    """Poll continuously until ``stop_event`` is set.

    Retry/DLQ policy remains an AWS queue concern. This loop only controls
    acknowledgement: malformed and failed records are intentionally left
    invisible until the queue makes them available again.
    """

    resolved_config = config or load_worker_config()
    client = sqs_client or create_sqs_client(resolved_config)
    event = stop_event or Event()
    output_log = log or logger
    while not event.is_set():
        try:
            poll_once(
                client,
                resolved_config.queue_url,
                services,
                clock=clock,
                log=output_log,
            )
        except Exception:  # noqa: BLE001 - keep polling after transient receive errors
            output_log.exception("SQS receive loop failed")
            event.wait(1.0)


@dataclass(frozen=True)
class SqsQueuePublisher:
    """Re-publishes a message onto the same production queue (multi-competitor fan-out)."""

    sqs_client: Any
    queue_url: str

    def publish(self, message: Mapping[str, Any]) -> None:
        self.sqs_client.send_message(
            QueueUrl=self.queue_url,
            MessageBody=json.dumps(dict(message), sort_keys=True),
        )


def build_application_services() -> Mapping[str, Any]:
    """Build the normal repository-backed service graph for the process entry point.

    Adds ``strategy_lookup`` (a pure MongoDB read against the external RM
    database, safe to construct without AWS credentials) on top of the Flask
    app's own service graph. ``queue_publisher`` is deliberately not included
    here since it needs a live SQS client/queue URL; see
    ``build_worker_services``.
    """

    from backend.flask.app import create_app

    app = create_app()
    services = dict(app.extensions["api_services"])
    services["strategy_lookup"] = StrategyLookupService()
    return services


def build_worker_services(sqs_client: Any, queue_url: str) -> Mapping[str, Any]:
    """Build the full service graph the SQS worker process needs, publisher included."""

    services = dict(build_application_services())
    services["queue_publisher"] = SqsQueuePublisher(sqs_client, queue_url)
    return services


def main() -> int:
    config = load_worker_config()
    sqs_client = create_sqs_client(config)
    run_worker_forever(
        build_worker_services(sqs_client, config.queue_url),
        config=config,
        sqs_client=sqs_client,
    )
    return 0


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(override=False)


__all__ = [
    "MAX_NUMBER_OF_MESSAGES",
    "PollResult",
    "RecordResult",
    "SQSConfigurationError",
    "SQSWorkerConfig",
    "SqsQueuePublisher",
    "WAIT_TIME_SECONDS",
    "build_application_services",
    "build_worker_services",
    "create_sqs_client",
    "load_worker_config",
    "main",
    "poll_once",
    "process_message_record",
    "run_worker_forever",
]


if __name__ == "__main__":
    raise SystemExit(main())
