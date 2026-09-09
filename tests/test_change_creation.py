"""Unit coverage for change/event creation and narrative enrichment."""

from __future__ import annotations

import unittest
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone

from backend.flask.change_detection.repository import ChangeRepository
from backend.flask.change_detection.service import (
    DEFAULT_CHANGE_STATUS,
    ChangeError,
    ChangeService,
    create_change,
    derive_change_type,
)
from backend.flask.website_monitoring.service import hash_content, normalize_content

try:
    from bson import ObjectId
except ImportError:
    ObjectId = None


@dataclass
class _InsertResult:
    inserted_id: object


class _Cursor(list):
    def sort(self, fields):
        for field, direction in reversed(fields):
            super().sort(
                key=lambda document: document.get(field),
                reverse=direction < 0,
            )
        return self


class _FakeCollection:
    def __init__(self):
        self.documents = []
        self.indexes = []
        self._next_id = 1

    def create_index(self, keys, **options):
        self.indexes.append((keys, options))
        return options.get("name")

    def insert_one(self, document):
        stored = deepcopy(document)
        raw_id = f"{self._next_id:024x}"
        stored["_id"] = ObjectId(raw_id) if ObjectId else raw_id
        self._next_id += 1
        self.documents.append(stored)
        return _InsertResult(stored["_id"])

    def find_one(self, query):
        for document in self.documents:
            if _matches(document, query):
                return deepcopy(document)
        return None

    def find(self, query):
        return _Cursor(
            deepcopy(document)
            for document in self.documents
            if _matches(document, query)
        )


def _matches(document, query):
    return all(document.get(field) == value for field, value in query.items())


class _TargetRepository:
    def __init__(self, target_id, page_type):
        self.target_id = target_id
        self.page_type = page_type
        self.get_calls = []

    def get(self, target_id, *, competitor_id=None):
        self.get_calls.append(target_id)
        if target_id != self.target_id:
            return None
        return {
            "id": str(target_id),
            "url": "https://example.com/blog",
            "page_type": self.page_type,
        }


class _NarrativeProvider:
    def __init__(self, output="A new article was added to the monitored page."):
        self.output = output
        self.calls = []

    def generate(self, prompt, *, instructions, response_format=None):
        self.calls.append(
            {
                "prompt": prompt,
                "instructions": instructions,
                "response_format": response_format,
            }
        )
        return self.output


class _FailingNarrativeProvider:
    def generate(self, prompt, *, instructions, response_format=None):
        raise TimeoutError("forced narrative timeout")


class ChangeCreationTests(unittest.TestCase):
    def setUp(self):
        self.collection = _FakeCollection()
        self.repository = ChangeRepository(self.collection)
        self.target_id = (
            ObjectId("000000000000000000000001")
            if ObjectId
            else "000000000000000000000001"
        )
        self.target_repository = _TargetRepository(self.target_id, "BLOG")
        self.narrative_provider = _NarrativeProvider()
        self.service = ChangeService(
            self.repository,
            self.target_repository,
            narrative_provider_factory=lambda: self.narrative_provider,
        )
        self.detected_at = datetime(
            2026,
            9,
            4,
            11,
            30,
            tzinfo=timezone.utc,
        )

    def _snapshot(self, snapshot_id, content):
        normalized = normalize_content(content)
        return {
            "id": snapshot_id,
            "content_hash": hash_content(normalized),
            "content": normalized,
        }

    def test_repository_defines_target_history_index(self):
        self.repository.ensure_indexes()

        self.assertEqual(
            self.collection.indexes,
            [
                (
                    [("monitoring_target_id", 1), ("detected_at", -1)],
                    {"name": "ix_changes_target_detected_at"},
                )
            ],
        )

    def test_equal_hashes_are_rejected_before_change_creation(self):
        previous = self._snapshot(
            "000000000000000000000002",
            "<main>Unchanged blog content</main>",
        )
        current = dict(previous, id="000000000000000000000003")

        with self.assertRaisesRegex(ChangeError, "different content_hash"):
            self.service.create_change(self.target_id, previous, current)

        self.assertEqual(self.collection.documents, [])
        self.assertEqual(self.target_repository.get_calls, [])

    def test_blog_change_is_persisted_with_new_blog_and_deterministic_summary(self):
        previous = self._snapshot(
            "000000000000000000000002",
            "<main>Old blog announcement</main>\n",
        )
        current = self._snapshot(
            "000000000000000000000003",
            "<main>New blog announcement</main>\n",
        )

        change = self.service.create_change(
            self.target_id,
            previous,
            current,
            detected_at=self.detected_at,
        )

        self.assertEqual(change["monitoring_target_id"], str(self.target_id))
        self.assertEqual(change["previous_snapshot_id"], previous["id"])
        self.assertEqual(change["current_snapshot_id"], current["id"])
        self.assertEqual(change["change_type"], "NEW_BLOG")
        self.assertEqual(change["status"], DEFAULT_CHANGE_STATUS)
        self.assertRegex(
            change["summary"],
            r"^NEW_BLOG: 1 line\(s\) added, 1 line\(s\) removed",
        )
        self.assertIn("characters added", change["summary"])
        self.assertEqual(
            change["narrative_summary"],
            "A new article was added to the monitored page.",
        )
        self.assertIn("https://example.com/blog", self.narrative_provider.calls[0]["prompt"])
        self.assertIn("<main>Old blog announcement</main>", self.narrative_provider.calls[0]["prompt"])

    def test_product_change_does_not_call_narrative_provider(self):
        self.target_repository.page_type = "PRODUCT_LISTING"
        previous = self._snapshot(
            "000000000000000000000012",
            '[{"key":"/product/old","name":"Old","price":"10.00"}]',
        )
        current = self._snapshot(
            "000000000000000000000013",
            '[{"key":"/product/new","name":"New","price":"12.00"}]',
        )

        change = self.service.create_change(
            self.target_id,
            previous,
            current,
            change_type="NEW_PRODUCT",
            summary="NEW_PRODUCT: New (12.00) at /product/new",
        )

        self.assertIsNone(change["narrative_summary"])
        self.assertEqual(self.narrative_provider.calls, [])

    def test_narrative_failure_keeps_change_and_mechanical_summary(self):
        service = ChangeService(
            self.repository,
            self.target_repository,
            narrative_provider_factory=_FailingNarrativeProvider,
        )
        previous = self._snapshot(
            "000000000000000000000014",
            "<main>Old page copy</main>",
        )
        current = self._snapshot(
            "000000000000000000000015",
            "<main>New page copy</main>",
        )

        change = service.create_change(self.target_id, previous, current)

        self.assertIsNone(change["narrative_summary"])
        self.assertRegex(change["summary"], r"^NEW_BLOG: 1 line\(s\) added")
        self.assertEqual(len(self.repository.list_for_target(self.target_id)), 1)

    def test_pricing_change_maps_to_price_change(self):
        self.target_repository.page_type = "PRICING"
        previous = self._snapshot(
            "000000000000000000000004",
            "<main><p>Price: $99</p></main>",
        )
        current = self._snapshot(
            "000000000000000000000005",
            "<main><p>Price: $79</p></main>",
        )

        change = create_change(
            self.target_id,
            previous,
            current,
            change_repository=self.repository,
            monitoring_target_repository=self.target_repository,
            detected_at=self.detected_at,
        )

        self.assertEqual(change["change_type"], "PRICE_CHANGE")
        self.assertEqual(change["status"], "NEW")

    def test_other_supported_page_types_use_page_update_fallback(self):
        self.target_repository.page_type = "SERVICES"
        previous = self._snapshot(
            "000000000000000000000006",
            "<main><h1>Old services</h1></main>",
        )
        current = self._snapshot(
            "000000000000000000000007",
            "<main><h1>New services</h1></main>",
        )

        change = self.service.create_change(self.target_id, previous, current)

        self.assertEqual(change["change_type"], "PAGE_UPDATE")

    def test_processor_event_type_and_summary_are_persisted_without_page_type_remapping(self):
        self.target_repository.page_type = "PRODUCT_LISTING"
        previous = self._snapshot(
            "000000000000000000000010",
            '[{"key":"/product/old","name":"Old","price":"10.00"}]',
        )
        current = self._snapshot(
            "000000000000000000000011",
            '[{"key":"/product/new","name":"New","price":"12.00"}]',
        )

        change = self.service.create_change(
            self.target_id,
            previous,
            current,
            detected_at=self.detected_at,
            change_type="PRODUCT_REMOVED",
            summary="PRODUCT_REMOVED: Old (10.00) at /product/old",
        )

        self.assertEqual(change["change_type"], "PRODUCT_REMOVED")
        self.assertEqual(
            change["summary"],
            "PRODUCT_REMOVED: Old (10.00) at /product/old",
        )
        self.assertEqual(derive_change_type("PRODUCT_LISTING"), "PAGE_UPDATE")

    def test_change_service_can_load_metadata_only_snapshots_through_injected_reader(self):
        self.target_repository.page_type = "TESTIMONIALS"
        contents = {
            "000000000000000000000008": "<main>Old testimonial</main>",
            "000000000000000000000009": "<main>New testimonial</main>",
        }
        previous = {
            "id": "000000000000000000000008",
            "content_hash": hash_content(normalize_content(contents["000000000000000000000008"])),
            "storage_path": "snapshots/target/old.txt.gz",
        }
        current = {
            "id": "000000000000000000000009",
            "content_hash": hash_content(normalize_content(contents["000000000000000000000009"])),
            "storage_path": "snapshots/target/new.txt.gz",
        }
        service = ChangeService(
            self.repository,
            self.target_repository,
            snapshot_content_loader=lambda snapshot: contents[snapshot["id"]],
            narrative_provider_factory=lambda: self.narrative_provider,
        )

        change = service.create_change(self.target_id, previous, current)

        self.assertEqual(change["change_type"], "PAGE_UPDATE")
        self.assertEqual(len(self.repository.list_for_target(self.target_id)), 1)

    def test_only_justified_real_page_types_have_special_mappings(self):
        self.assertEqual(derive_change_type("BLOG"), "NEW_BLOG")
        self.assertEqual(derive_change_type("PRICING"), "PRICE_CHANGE")
        self.assertEqual(derive_change_type("PRODUCTS"), "PAGE_UPDATE")
        self.assertEqual(derive_change_type("CAMPAIGN"), "PAGE_UPDATE")


if __name__ == "__main__":
    unittest.main()
