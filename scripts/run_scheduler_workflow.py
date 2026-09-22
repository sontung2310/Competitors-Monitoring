"""Manually trigger the production SQS-message workflow for one company domain.

This calls exactly what a real inbound SQS message triggers
(``backend.flask.scheduler.sqs_handler.handle_message``) against the real
production service graph (``backend.flask.scheduler.sqs_worker.build_worker_services``):
DynamoDB monitoring targets/snapshots, RM Mongo for changes and strategy
lookup, and this app's own MongoDB for companies/competitors/discovery runs.

If ``--competitors`` is omitted (or passed empty), the RM Primary-strategy
lookup resolves the competitor list for you. When that resolves to more than
one competitor, the handler fans the message out into that many real
messages on the live SQS queue; this script then drains and fully processes
each one in turn (real discovery per competitor), exactly like the
production worker would.

Example:

    ./.venv/bin/python scripts/run_scheduler_workflow.py --domain roboticmarketer.com --host dev

    ./.venv/bin/python scripts/run_scheduler_workflow.py \\
      --domain theathletesfoot.com.au \\
      --competitors https://www.jd-sports.com.au/ \\
      --host dev
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - requirements.txt provides this package
    load_dotenv = None

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.flask.scheduler.sqs_handler import handle_message
from backend.flask.scheduler.sqs_worker import (
    build_worker_services,
    create_sqs_client,
    load_worker_config,
    poll_once,
)

DEFAULT_MAX_POLL_ROUNDS = 20
DEFAULT_IDLE_ROUNDS_CUTOFF = 3  # stop draining after this many consecutive empty polls


def _log(event: str, **fields: Any) -> None:
    print(json.dumps({"event": event, **fields}, default=str, sort_keys=True), flush=True)


def run_workflow(
    *,
    company_domain_id: str,
    competitor_lst: list[str] | None,
    host: str,
    max_poll_rounds: int = DEFAULT_MAX_POLL_ROUNDS,
    idle_rounds_cutoff: int = DEFAULT_IDLE_ROUNDS_CUTOFF,
) -> dict[str, Any]:
    """Run the workflow once, draining any fan-out it produces, and time it.

    Returns a summary including ``elapsed_seconds`` covering the full
    start-to-finish wall time: the initial call plus every fanned-out message
    this call drains and processes (if any).
    """

    if load_dotenv is not None:
        load_dotenv(override=False)

    config = load_worker_config()
    sqs_client = create_sqs_client(config)
    services = build_worker_services(sqs_client, config.queue_url)

    message = {
        "company_domain_id": company_domain_id,
        "competitor_lst": competitor_lst or None,
        "host": host,
    }

    started = time.monotonic()
    _log("initial_call_start", message=message)
    initial_result = handle_message(message, services, message_id="manual-run-initial")
    _log("initial_call_result", result=initial_result)

    fanned_outcomes: list[dict[str, Any]] = []
    if initial_result.get("action") == "fanned_out":
        fanned_out_urls = initial_result.get("fanned_out_urls") or []
        _log("fanout_published", count=len(fanned_out_urls), urls=fanned_out_urls)

        idle_rounds = 0
        for round_number in range(1, max_poll_rounds + 1):
            if len(fanned_outcomes) >= len(fanned_out_urls):
                break
            result = poll_once(sqs_client, config.queue_url, services)
            _log(
                "poll_round_result",
                round=round_number,
                received=result.received_count,
                acknowledged=result.acknowledged_count,
                failed=result.failed_count,
            )
            for outcome in result.outcomes:
                fanned_outcomes.append(outcome)
                _log(
                    "processed_fanned_message",
                    action=outcome.get("action"),
                    competitor=(outcome.get("competitor") or {}).get("website_url"),
                    reconciliation=outcome.get("reconciliation"),
                )
            if result.received_count == 0:
                idle_rounds += 1
                if idle_rounds >= idle_rounds_cutoff:
                    _log("stopping_after_idle_rounds", idle_rounds=idle_rounds)
                    break
            else:
                idle_rounds = 0

    elapsed_seconds = time.monotonic() - started

    summary = {
        "company_domain_id": company_domain_id,
        "initial_action": initial_result.get("action"),
        "fanned_out_processed_count": len(fanned_outcomes),
        "elapsed_seconds": round(elapsed_seconds, 2),
    }
    _log("summary", **summary)
    return {
        "initial_result": initial_result,
        "fanned_outcomes": fanned_outcomes,
        "summary": summary,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domain", required=True, help="company_domain_id, e.g. roboticmarketer.com")
    parser.add_argument(
        "--competitors",
        nargs="*",
        default=None,
        help="Explicit competitor URL(s). Omit to resolve via RM strategy lookup instead.",
    )
    parser.add_argument("--host", default="dev", help="RM strategy-lookup host routing (default: dev)")
    args = parser.parse_args()

    run_workflow(
        company_domain_id=args.domain,
        competitor_lst=args.competitors,
        host=args.host,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
