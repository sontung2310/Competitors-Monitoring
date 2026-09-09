from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import Mock

from backend.flask.website_monitoring.content_processing import (
    ProductListingProcessor,
    ProcessResult,
    TextBlobProcessor,
    diff_by_key,
    extract_products,
    resolve_content_processor,
)
from backend.flask.website_monitoring.service import (
    FetchResult,
    MonitoringRunService,
    hash_content,
    normalize_content,
)


class TextBlobProcessorTests(unittest.TestCase):
    def test_unchanged_content_returns_no_event(self):
        content = "<main>Stable page content with enough visible text to monitor.</main>"
        normalized = normalize_content(content)
        processor = TextBlobProcessor(page_type="BLOG")

        result = processor.process(
            content,
            {
                "content": normalized,
                "content_hash": hash_content(normalized),
            },
        )

        self.assertFalse(result.changed)
        self.assertEqual(result.snapshot_content, normalized)
        self.assertEqual(result.change_events, [])

    def test_changed_content_preserves_existing_blog_event_behavior(self):
        previous = "<main>Old page content with enough visible text to monitor.</main>"
        current = "<main>New page content with enough visible text to monitor.</main>"
        normalized_previous = normalize_content(previous)
        processor = TextBlobProcessor(page_type="BLOG")

        result = processor.process(
            current,
            {
                "content": normalized_previous,
                "content_hash": hash_content(normalized_previous),
            },
        )

        self.assertTrue(result.changed)
        self.assertEqual(result.snapshot_content, normalize_content(current))
        self.assertEqual(len(result.change_events), 1)
        self.assertEqual(result.change_events[0]["change_type"], "NEW_BLOG")
        self.assertTrue(result.change_events[0]["summary"].startswith("NEW_BLOG:"))

    def test_product_listing_page_type_resolves_to_structured_processor(self):
        processor = resolve_content_processor("PRODUCT_LISTING")

        self.assertIsInstance(processor, ProductListingProcessor)

    def test_extract_products_uses_url_name_and_current_sale_price(self):
        content = """
        <ul>
          <li class="productListItem">
            <span class="itemContainer" data-productsku="sku-1">
              <a class="itemImage" href="/product/blue-shoe/sku-1/?utm_source=ad">
                <img alt="Blue Shoe" />
              </a>
              <span class="itemInformation">
                <span class="itemTitle">Blue Shoe</span>
                <span class="itemPrice">Was $120.00 Now $80.00 Save 33%</span>
              </span>
            </span>
          </li>
        </ul>
        """

        self.assertEqual(
            extract_products(content),
            [{"key": "/product/blue-shoe/sku-1", "name": "Blue Shoe", "price": "80.00"}],
        )

    def test_diff_by_key_emits_add_remove_and_price_events(self):
        previous = [
            {"key": "/product/keep", "name": "Keep", "price": "10.00"},
            {"key": "/product/remove", "name": "Remove", "price": "20.00"},
        ]
        current = [
            {"key": "/product/keep", "name": "Keep", "price": "12.00"},
            {"key": "/product/new", "name": "New", "price": "30.00"},
        ]

        events = diff_by_key(previous, current)

        self.assertEqual(
            [event["change_type"] for event in events],
            ["NEW_PRODUCT", "PRODUCT_REMOVED", "PRICE_CHANGE"],
        )
        self.assertIn("/product/new", events[0]["summary"])
        self.assertEqual(events[0]["detected_url"], "/product/new")
        self.assertIn("20.00", events[1]["summary"])
        self.assertEqual(events[1]["detected_url"], "/product/remove")
        self.assertIn("10.00 -> 12.00", events[2]["summary"])
        self.assertEqual(events[2]["detected_url"], "/product/keep")

    def test_product_listing_processor_serializes_canonical_list_and_owns_event_types(self):
        previous_content = '[{"key":"/product/old","name":"Old","price":"10.00"}]'
        processor = ProductListingProcessor()

        result = processor.process(
            '<li class="productListItem"><a class="itemImage" href="/product/new/1/">'
            '<span class="itemTitle">New</span><span class="itemPrice">Now $12.00</span>'
            '</a></li>',
            {
                "content": previous_content,
                "content_hash": hash_content(previous_content),
            },
        )

        self.assertTrue(result.changed)
        self.assertEqual(result.change_events[0]["change_type"], "NEW_PRODUCT")
        self.assertEqual(result.change_events[1]["change_type"], "PRODUCT_REMOVED")
        self.assertNotIn("PAGE_UPDATE", [event["change_type"] for event in result.change_events])


class MonitoringProcessorDispatchTests(unittest.TestCase):
    def test_monitor_target_calls_change_creation_once_per_processor_event(self):
        target_id = "target-1"
        target = {
            "id": target_id,
            "url": "https://example.com/blog",
            "page_type": "BLOG",
            "active": True,
            "discovery_status": "ACTIVE",
        }
        target_repository = Mock()
        target_repository.get.return_value = target
        target_repository.update.return_value = target

        run_repository = Mock()
        run_repository.claim.return_value = {"id": "run-1"}
        run_repository.finish.return_value = {"id": "run-1", "status": "SUCCESS"}

        snapshot_repository = Mock()
        snapshot_repository.list_for_target.return_value = []
        snapshot_service = Mock()
        snapshot_service.create_snapshot.return_value = {
            "id": "snapshot-1",
            "monitoring_target_id": target_id,
            "content_hash": "current-hash",
        }
        change_service = Mock()
        change_service.create_change.side_effect = [
            {"id": "change-1"},
            {"id": "change-2"},
        ]
        processor = Mock()
        processor.process.return_value = ProcessResult(
            changed=True,
            snapshot_content="canonical content",
            change_events=[
                {"change_type": "NEW_BLOG", "summary": "first"},
                {"change_type": "NEW_BLOG", "summary": "second"},
            ],
        )
        now = datetime(2026, 9, 6, 0, 0, tzinfo=timezone.utc)

        service = MonitoringRunService(
            target_repository,
            run_repository,
            snapshot_repository,
            snapshot_service,
            change_service,
            fetcher=lambda _url: FetchResult("raw fetched content", "HTTP", 200),
            clock=lambda: now,
            content_processors={"BLOG": processor},
        )

        result = service.monitor_target(target_id)

        processor.process.assert_called_once_with("raw fetched content", None)
        self.assertEqual(change_service.create_change.call_count, 2)
        self.assertEqual(
            change_service.create_change.call_args_list[0].kwargs,
            {"detected_at": now, "change_type": "NEW_BLOG", "summary": "first"},
        )
        self.assertEqual(result["changes"], [{"id": "change-1"}, {"id": "change-2"}])
        self.assertIsNone(result["change"])


if __name__ == "__main__":
    unittest.main()
