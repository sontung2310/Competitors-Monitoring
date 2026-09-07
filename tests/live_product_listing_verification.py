"""Opt-in live Step 1.13 ProductListingProcessor verification.

Run from the repository root with the dedicated Atlas test database configured:

    set -a; source .env.mongodb; set +a
    export MONGODB_DATABASE=competitors_monitoring_test
    RUN_LIVE_PRODUCT_LISTING=1 \
      /private/tmp/cm-venv.cckOER/bin/python -u \
      tests/live_product_listing_verification.py

The script intentionally keeps the JD Sports competitor, target, snapshots,
and change records in the dedicated test database as auditable evidence. It
uses a real HTTP capture for the baseline, then injects that captured HTML and
one deterministic mutation through the real monitoring orchestration. No LLM
or synthetic product fixture is used.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.flask.change_detection.repository import ChangeRepository
from backend.flask.competitors.repository import CompetitorRepository
from backend.flask.database.connection import MongoSettings, connect_database
from backend.flask.discovery.classification import DeterministicStubClassifier
from backend.flask.discovery.service import DiscoveryService
from backend.flask.snapshot.repository import SnapshotRepository
from backend.flask.website_monitoring.content_processing import (
    diff_by_key,
    extract_products,
)
from backend.flask.website_monitoring.repository import MonitoringTargetRepository
from backend.flask.website_monitoring.service import (
    FetchResult,
    MonitoringRunService,
    fetch_page,
    hash_content,
    normalize_content,
)


TEST_DATABASE = "competitors_monitoring_test"
USER_ID = "live-verification"
JD_WEBSITE_URL = "https://www.jd-sports.com.au/"
JD_SALE_URL = "https://www.jd-sports.com.au/sale/"
PRODUCT_LISTING_PAGE_TYPE = "PRODUCT_LISTING"
SYNTHETIC_PRODUCT_KEY = "/product/ton21-synthetic-product/sku-ton21/"


def run_live_verification() -> dict[str, Any]:
    """Run live extraction, stability, persistence, and mutation checks."""

    if os.environ.get("RUN_LIVE_PRODUCT_LISTING") != "1":
        raise SystemExit(
            "Set RUN_LIVE_PRODUCT_LISTING=1 to run live product-listing verification"
        )

    settings = MongoSettings.from_env()
    if settings.database_name != TEST_DATABASE:
        raise RuntimeError(
            f"refusing to write outside the dedicated test database {TEST_DATABASE!r}; "
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
        competitors.ensure_indexes()
        targets.ensure_indexes()
        snapshots.ensure_indexes()
        changes.ensure_indexes()

        competitor = _get_or_create_competitor(competitors)
        discovery = DiscoveryService(
            competitors,
            targets,
            fallback_classifier=DeterministicStubClassifier(),
        )
        target = discovery.add_manual_target(
            competitor["id"],
            JD_SALE_URL,
            page_type=PRODUCT_LISTING_PAGE_TYPE,
        )
        if target.get("page_type") != PRODUCT_LISTING_PAGE_TYPE:
            raise AssertionError(
                f"JD target has unexpected page_type {target.get('page_type')!r}"
            )
        if target.get("active") is not True or target.get("discovery_status") != "ACTIVE":
            raise AssertionError("JD target was not created or promoted as ACTIVE")

        active_ids = {row["id"] for row in discovery.list_active_targets(competitor["id"])}
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

        monitoring_baseline = MonitoringRunService.from_database(
            database,
            fetcher=lambda _url: FetchResult(
                first_fetch.content,
                first_fetch.fetch_method,
                first_fetch.http_status,
            ),
        )
        baseline_run = monitoring_baseline.monitor_target(target["id"])
        if baseline_run["run"]["status"] != "SUCCESS":
            raise AssertionError("JD baseline monitoring run did not succeed")

        # A second pass over exactly the same captured live HTML proves the
        # negative case through monitor_target and the persisted event path.
        changes_before_negative = changes.list_for_target(target["id"])
        negative_run = monitoring_baseline.monitor_target(target["id"])
        changes_after_negative = changes.list_for_target(target["id"])
        if negative_run["run"]["status"] != "SUCCESS":
            raise AssertionError("JD unchanged monitoring run did not succeed")
        if len(changes_after_negative) != len(changes_before_negative):
            raise AssertionError("unchanged JD content created a change record")

        monitoring_mutation = MonitoringRunService.from_database(
            database,
            fetcher=lambda _url: FetchResult(
                mutated_html,
                first_fetch.fetch_method,
                first_fetch.http_status,
            ),
        )
        changes_before_mutation = changes.list_for_target(target["id"])
        mutation_run = monitoring_mutation.monitor_target(target["id"])
        changes_after_mutation = changes.list_for_target(target["id"])
        new_change_records = _new_records(
            changes_before_mutation,
            changes_after_mutation,
        )
        actual_types = sorted(record["change_type"] for record in new_change_records)
        if actual_types != sorted(
            ["NEW_PRODUCT", "PRODUCT_REMOVED", "PRICE_CHANGE"]
        ):
            raise AssertionError(
                f"expected exactly three persisted product events, got {actual_types}"
            )
        if mutation_run["run"]["status"] != "SUCCESS":
            raise AssertionError("JD mutation monitoring run did not succeed")

        report = {
            "database": database.name,
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
            "baseline_run_id": baseline_run["run"]["id"],
            "negative_run_id": negative_run["run"]["id"],
            "negative_new_changes": len(changes_after_negative)
            - len(changes_before_negative),
            "mutation_run_id": mutation_run["run"]["id"],
            "mutation_snapshot_id": mutation_run["snapshot"]["id"],
            "mutation_change_count": len(new_change_records),
            "mutation": mutation,
            "change_records": [
                {
                    "id": record["id"],
                    "change_type": record["change_type"],
                    "summary": record["summary"],
                }
                for record in sorted(
                    new_change_records,
                    key=lambda record: record["change_type"],
                )
            ],
        }
        _print_report(report)
        return report
    finally:
        client.close()


def _get_or_create_competitor(repository: CompetitorRepository) -> dict[str, Any]:
    for competitor in repository.list_for_user(USER_ID):
        if competitor.get("website_url") == JD_WEBSITE_URL:
            return competitor
    return repository.create(
        user_id=USER_ID,
        name="JD Sports AU",
        website_url=JD_WEBSITE_URL,
    )


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


def _new_records(
    before: list[dict[str, Any]],
    after: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    before_ids = {record["id"] for record in before}
    return [record for record in after if record["id"] not in before_ids]


def _print_report(report: dict[str, Any]) -> None:
    print(f"database={report['database']}")
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
            f"summary={record['summary']}"
        )


if __name__ == "__main__":
    run_live_verification()
