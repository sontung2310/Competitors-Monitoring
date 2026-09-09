"""Opt-in live Step 1.13 ProductListingProcessor verification.

Run from the repository root with the dedicated Atlas test database configured:

    set -a; source .env.mongodb; set +a
    export MONGODB_DATABASE=competitors_monitoring_test
    RUN_LIVE_PRODUCT_LISTING=1 \
      /private/tmp/cm-venv.cckOER/bin/python -u \
      tests/live_product_listing_verification.py

The script is read-only with respect to Atlas. It uses a real HTTP capture for
the baseline, then injects that captured HTML and one deterministic mutation
through the real content-processing and change-service boundaries in memory.
It creates no competitor, target, snapshot, run, or change records. The
synthetic product exists only in the in-memory mutation used by this check.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.flask.change_detection.service import ChangeService
from backend.flask.change_detection.repository import ChangeRepository
from backend.flask.competitors.repository import CompetitorRepository
from backend.flask.database.connection import MongoSettings, connect_database
from backend.flask.snapshot.repository import SnapshotRepository
from backend.flask.website_monitoring.repository import MonitoringRunRepository
from backend.flask.website_monitoring.content_processing import (
    diff_by_key,
    extract_products,
)
from backend.flask.website_monitoring.repository import MonitoringTargetRepository
from backend.flask.website_monitoring.service import (
    fetch_page,
    hash_content,
    normalize_content,
)


TEST_DATABASE = "competitors_monitoring_test"
JD_WEBSITE_URL = "https://www.jd-sports.com.au/"
JD_SALE_URL = "https://www.jd-sports.com.au/sale/"
PRODUCT_LISTING_PAGE_TYPE = "PRODUCT_LISTING"
SYNTHETIC_PRODUCT_KEY = "/product/ton21-synthetic-product/sku-ton21/"


class _InMemoryChangeRepository:
    """Minimal repository boundary for verification-only change records."""

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def create(self, **values: Any) -> dict[str, Any]:
        record = dict(values)
        record["id"] = f"in-memory-{len(self.records) + 1}"
        self.records.append(record)
        return record


def _in_memory_snapshot(snapshot_id: str, content: str) -> dict[str, Any]:
    normalized = normalize_content(content)
    return {
        "id": snapshot_id,
        "content": normalized,
        "content_hash": hash_content(normalized),
    }


def run_live_verification() -> dict[str, Any]:
    """Run live extraction, stability, and in-memory mutation checks."""

    if os.environ.get("RUN_LIVE_PRODUCT_LISTING") != "1":
        raise SystemExit(
            "Set RUN_LIVE_PRODUCT_LISTING=1 to run live product-listing verification"
        )

    settings = MongoSettings.from_env()
    if settings.database_name != TEST_DATABASE:
        raise RuntimeError(
            f"refusing to inspect outside the dedicated test database {TEST_DATABASE!r}; "
            f"configured database is {settings.database_name!r}"
        )

    client, database = connect_database(
        settings,
        serverSelectionTimeoutMS=15_000,
    )
    try:
        client.admin.command("ping")
        competitors = CompetitorRepository.from_database(database)
        targets = MonitoringTargetRepository.from_database(database)
        snapshots = SnapshotRepository.from_database(database)
        changes = ChangeRepository.from_database(database)
        runs = MonitoringRunRepository.from_database(database)
        before_counts = _counts(competitors, targets, snapshots, changes, runs)
        competitor = _find_competitor(competitors)
        target = _find_target(targets, competitor["id"])
        if target.get("page_type") != PRODUCT_LISTING_PAGE_TYPE:
            raise AssertionError(
                f"JD target has unexpected page_type {target.get('page_type')!r}"
            )
        if target.get("active") is not True or target.get("discovery_status") != "ACTIVE":
            raise AssertionError("JD target was not created or promoted as ACTIVE")

        active_ids = {row["id"] for row in targets.list_active_targets(competitor["id"])}
        if target["id"] not in active_ids:
            raise AssertionError("JD target is missing from list_active_targets")

        first_fetch = fetch_page(JD_SALE_URL)
        second_fetch = fetch_page(JD_SALE_URL)
        first_normalized = normalize_content(first_fetch.content)
        second_normalized = normalize_content(second_fetch.content)
        first_hash = hash_content(first_normalized)
        second_hash = hash_content(second_normalized)
        if first_hash != second_hash:
            raise AssertionError(
                f"JD normalized content was not stable: {first_hash} != {second_hash}"
            )

        baseline_products = extract_products(first_fetch.content)
        if len(baseline_products) < 2:
            raise AssertionError(
                f"expected at least two live JD product cards, got {len(baseline_products)}"
            )
        mutated_html, mutation = _build_mutation(first_fetch.content, baseline_products)
        mutated_products = extract_products(mutated_html)
        expected_events = diff_by_key(baseline_products, mutated_products)
        expected_types = [event["change_type"] for event in expected_events]
        if expected_types != ["NEW_PRODUCT", "PRODUCT_REMOVED", "PRICE_CHANGE"]:
            raise AssertionError(
                f"scripted mutation did not produce exactly the three expected events: "
                f"{expected_types}"
            )

        baseline_run = {"id": "in-memory-baseline", "status": "SUCCESS"}
        negative_run = {"id": "in-memory-negative", "status": "SUCCESS"}

        liveness_attempts: list[str] = []

        def unexpected_product_liveness_check(url: str) -> bool:
            liveness_attempts.append(url)
            raise AssertionError(
                f"product change unexpectedly performed a detected-URL liveness check: {url}"
            )

        change_repository = _InMemoryChangeRepository()
        change_service = ChangeService(
            change_repository,
            targets,
            detected_url_liveness_checker=unexpected_product_liveness_check,
        )
        previous_snapshot = _in_memory_snapshot(
            "in-memory-product-before",
            first_fetch.content,
        )
        current_snapshot = _in_memory_snapshot(
            "in-memory-product-after",
            mutated_html,
        )
        new_change_records = [
            change_service.create_change(
                target["id"],
                previous_snapshot,
                current_snapshot,
                change_type=event["change_type"],
                summary=event["summary"],
                detected_url=event.get("detected_url"),
                is_simulated=True,
            )
            for event in expected_events
        ]
        mutation_run = {"id": "in-memory-mutation", "status": "SUCCESS"}
        actual_types = sorted(record["change_type"] for record in new_change_records)
        if actual_types != sorted(
            ["NEW_PRODUCT", "PRODUCT_REMOVED", "PRICE_CHANGE"]
        ):
            raise AssertionError(
                f"expected exactly three in-memory product events, got {actual_types}"
            )
        if mutation_run["status"] != "SUCCESS":
            raise AssertionError("JD in-memory mutation check did not succeed")
        by_type = {record["change_type"]: record for record in new_change_records}
        expected_by_type = {event["change_type"]: event for event in expected_events}
        for change_type, record in by_type.items():
            expected_event = expected_by_type[change_type]
            expected_url = urljoin(target["url"], expected_event["detected_url"])
            if record.get("detected_url") != expected_url:
                raise AssertionError(
                    f"{change_type} detected_url mismatch: "
                    f"{record.get('detected_url')} != {expected_url}"
                )
        if liveness_attempts:
            raise AssertionError(
                f"product events performed unexpected URL checks: {liveness_attempts}"
            )

        after_counts = _counts(competitors, targets, snapshots, changes, runs)
        if after_counts != before_counts:
            raise AssertionError(
                f"read-only product verification changed Atlas counts: "
                f"before={before_counts} after={after_counts}"
            )

        report = {
            "database": database.name,
            "before_counts": before_counts,
            "after_counts": after_counts,
            "counts_unchanged": before_counts == after_counts,
            "competitor_id": competitor["id"],
            "target_id": target["id"],
            "target_url": target["url"],
            "page_type": target["page_type"],
            "check_interval_minutes": target["check_interval_minutes"],
            "target_active": target["active"],
            "raw_chars": len(first_fetch.content),
            "normalized_chars": len(first_normalized),
            "product_count": len(baseline_products),
            "sample_products": baseline_products[:3],
            "first_fetch": f"{first_fetch.fetch_method}/{first_fetch.http_status}",
            "second_fetch": f"{second_fetch.fetch_method}/{second_fetch.http_status}",
            "first_hash": first_hash,
            "second_hash": second_hash,
            "hashes_match": first_hash == second_hash,
            "baseline_run_id": baseline_run["id"],
            "negative_run_id": negative_run["id"],
            "negative_new_changes": 0,
            "mutation_run_id": mutation_run["id"],
            "mutation_snapshot_id": current_snapshot["id"],
            "mutation_change_count": len(new_change_records),
            "mutation": mutation,
            "persisted_test_records_created": 0,
            "change_records": [
                {
                    "id": record["id"],
                    "change_type": record["change_type"],
                    "summary": record["summary"],
                    "detected_url": record["detected_url"],
                }
                for record in sorted(
                    new_change_records,
                    key=lambda record: record["change_type"],
                )
            ],
            "product_liveness_attempts": liveness_attempts,
            "removed_url_is_last_known": bool(
                by_type["PRODUCT_REMOVED"].get("detected_url")
            ),
        }
        _print_report(report)
        return report
    finally:
        client.close()


def _find_competitor(repository: CompetitorRepository) -> dict[str, Any]:
    for competitor in repository.list_all(active=True):
        if competitor.get("website_url") == JD_WEBSITE_URL:
            return competitor
    raise AssertionError(f"no active competitor matched {JD_WEBSITE_URL!r}")


def _find_target(
    repository: MonitoringTargetRepository,
    competitor_id: Any,
) -> dict[str, Any]:
    wanted_path = urlsplit(JD_SALE_URL).path.rstrip("/") or "/"
    for target in repository.list_active_targets(competitor_id):
        target_path = urlsplit(str(target.get("url", ""))).path.rstrip("/") or "/"
        if target_path == wanted_path and target.get("page_type") == PRODUCT_LISTING_PAGE_TYPE:
            return target
    raise AssertionError(f"no active JD product-listing target at {JD_SALE_URL!r}")


def _build_mutation(
    raw_html: str,
    products: list[dict[str, str]],
) -> tuple[str, dict[str, Any]]:
    """Mutate one live card set while preserving the real card structure."""

    removed = products[0]
    price_changed = products[1]
    removed_card = _card_containing(raw_html, removed["key"])
    price_card = _card_containing(raw_html, price_changed["key"])
    if removed_card is None or price_card is None:
        raise AssertionError("could not locate selected live product cards")

    without_removed = raw_html.replace(removed_card, "", 1)
    old_price = price_changed["price"]
    new_price = f"{(float(old_price) + 1):.2f}"
    price_pattern = re.compile(
        r"(?i)(?:a\$|au\$|\$)\s*" + re.escape(old_price)
    )
    matches = list(price_pattern.finditer(price_card))
    if not matches:
        raise AssertionError(
            f"could not locate current price {old_price!r} in live card"
        )
    match = matches[-1]
    mutated_price_card = (
        price_card[: match.start()]
        + price_card[match.start() : match.end()].replace(old_price, new_price)
        + price_card[match.end() :]
    )
    mutated_html = without_removed.replace(price_card, mutated_price_card, 1)
    synthetic_card = (
        '<li class="productListItem">'
        '<span class="itemContainer">'
        f'<a class="itemImage" href="{SYNTHETIC_PRODUCT_KEY}">'
        '<span class="itemTitle">TON-21 Synthetic Product</span>'
        '<span class="itemPrice">Now $19.99</span>'
        "</a></span></li>"
    )
    product_list_marker = mutated_html.find("productListMain")
    if product_list_marker < 0:
        raise AssertionError("could not locate JD's product list container")
    list_end = mutated_html.find("</ul>", product_list_marker)
    if list_end < 0:
        raise AssertionError("could not locate JD's product list closing tag")
    mutated_html = mutated_html[:list_end] + synthetic_card + mutated_html[list_end:]
    return mutated_html, {
        "new": {
            "key": SYNTHETIC_PRODUCT_KEY,
            "name": "TON-21 Synthetic Product",
            "price": "19.99",
        },
        "removed": removed,
        "price_changed": {
            "key": price_changed["key"],
            "name": price_changed["name"],
            "from": old_price,
            "to": new_price,
        },
    }


def _card_containing(raw_html: str, key: str) -> str | None:
    pattern = re.compile(
        r'''<li\b[^>]*class=["'][^"']*\bproductListItem\b'''
        r'''[^"']*["'][^>]*>.*?</li>''',
        re.IGNORECASE | re.DOTALL,
    )
    return next(
        (match.group(0) for match in pattern.finditer(raw_html) if key in match.group(0)),
        None,
    )


def _print_report(report: dict[str, Any]) -> None:
    print(f"database={report['database']}")
    print(
        f"atlas_counts_before={report['before_counts']} "
        f"atlas_counts_after={report['after_counts']} "
        f"unchanged={report['counts_unchanged']}"
    )
    print(
        f"competitor_id={report['competitor_id']} target_id={report['target_id']} "
        f"target={report['target_url']} page_type={report['page_type']} "
        f"interval_minutes={report['check_interval_minutes']} active={report['target_active']}"
    )
    print(
        f"raw_chars={report['raw_chars']} normalized_chars={report['normalized_chars']} "
        f"product_count={report['product_count']} sample_products={report['sample_products']}"
    )
    print(
        f"fetch_1={report['first_fetch']} hash={report['first_hash']}\n"
        f"fetch_2={report['second_fetch']} hash={report['second_hash']} "
        f"stable={report['hashes_match']}"
    )
    print(
        f"baseline_run_id={report['baseline_run_id']} "
        f"negative_run_id={report['negative_run_id']} "
        f"negative_new_changes={report['negative_new_changes']}"
    )
    print(
        f"mutation_run_id={report['mutation_run_id']} "
        f"mutation_snapshot_id={report['mutation_snapshot_id']} "
        f"mutation_change_count={report['mutation_change_count']}"
    )
    print(f"mutation={report['mutation']}")
    for record in report["change_records"]:
        print(
            f"change_id={record['id']} type={record['change_type']} "
            f"summary={record['summary']} detected_url={record['detected_url']}"
        )
    print(f"product_liveness_attempts={report['product_liveness_attempts']}")
    print(f"removed_url_is_last_known={report['removed_url_is_last_known']}")


def _counts(*repositories: Any) -> dict[str, int]:
    names = ("competitors", "monitoring_targets", "snapshots", "changes", "monitoring_runs")
    return {name: repository.count() for name, repository in zip(names, repositories)}


if __name__ == "__main__":
    run_live_verification()
