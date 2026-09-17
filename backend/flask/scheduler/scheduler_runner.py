"""Process entry point for the production scheduler.

Deploys as a second, standalone process alongside the SQS worker
(``sqs_worker.py``) — not a replacement for it. The SQS worker handles
ingestion (new competitors, on-demand re-discovery); this process is what
actually checks each tracked page on its own ``check_interval_minutes``,
closing the gap where nothing ran that job for the DynamoDB-backed target
set (see docs/production-plan.md 5.5/5.6 and the P.6 gap review).

Run with:

    python -m backend.flask.scheduler.scheduler_runner
"""

from __future__ import annotations

from .production_services import build_production_scheduler
from .service import DEFAULT_SCHEDULER_CADENCE_SECONDS, run_scheduler_forever


def main() -> int:
    scheduler = build_production_scheduler()
    run_scheduler_forever(scheduler, cadence_seconds=DEFAULT_SCHEDULER_CADENCE_SECONDS)
    return 0


__all__ = ["main"]


if __name__ == "__main__":
    raise SystemExit(main())
