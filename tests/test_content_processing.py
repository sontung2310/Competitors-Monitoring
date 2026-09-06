from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import Mock

from backend.flask.website_monitoring.content_processing import (
    ProcessResult,
    TextBlobProcessor,
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

    def test_unmapped_page_type_defaults_to_text_blob(self):
        processor = resolve_content_processor("PRODUCT_LISTING")

        self.assertIsInstance(processor, TextBlobProcessor)


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
        self.assertEqual(result["changes"], [{"id": "change-1"}, {"id": "change-2"}])
        self.assertIsNone(result["change"])


if __name__ == "__main__":
    unittest.main()
