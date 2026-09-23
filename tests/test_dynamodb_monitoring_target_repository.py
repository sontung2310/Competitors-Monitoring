from __future__ import annotations

import unittest
from datetime import datetime, timezone

from backend.flask.website_monitoring.dynamodb_repository import (
    DynamoDBMonitoringTargetRepository,
)
from tests.fake_dynamodb import FakeDynamoDBTable


NOW = datetime(2026, 9, 17, 6, 0, tzinfo=timezone.utc)


class DynamoDBMonitoringTargetRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.table = FakeDynamoDBTable(("_id",), gsi_key_fields={"gsi_competitor_id": "competitor_id"})
        self.repo = DynamoDBMonitoringTargetRepository(self.table)

    def test_create_never_stores_active_and_forces_suggested_status(self):
        target = self.repo.create(
            competitor_id="competitor-1",
            url="https://example.com/blog",
            page_type="BLOG",
            check_interval_minutes=60,
            discovery_source="SITEMAP",
            classification_method="RULE",
            active=True,  # accepted for interface parity, must be ignored
            discovery_status="ACTIVE",  # also ignored
            now=NOW,
        )
        self.assertEqual(target["discovery_status"], "SUGGESTED")
        self.assertNotIn("active", target)
        self.assertIsInstance(target["check_interval_minutes"], int)

    def test_get_round_trips_create_exactly(self):
        created = self.repo.create(
            competitor_id="competitor-1",
            url="https://example.com/blog",
            page_type="BLOG",
            check_interval_minutes=60,
            now=NOW,
        )
        fetched = self.repo.get(created["id"])
        self.assertEqual(fetched, created)

    def test_get_scoped_to_wrong_competitor_returns_none(self):
        created = self.repo.create(
            competitor_id="competitor-1",
            url="https://example.com/blog",
            page_type="BLOG",
            check_interval_minutes=60,
            now=NOW,
        )
        self.assertIsNone(self.repo.get(created["id"], competitor_id="competitor-2"))

    def test_list_for_competitor_uses_the_gsi(self):
        self.repo.create(
            competitor_id="competitor-1", url="https://a.example.com", page_type="BLOG",
            check_interval_minutes=60, now=NOW,
        )
        self.repo.create(
            competitor_id="competitor-2", url="https://b.example.com", page_type="BLOG",
            check_interval_minutes=60, now=NOW,
        )
        rows = self.repo.list_for_competitor("competitor-1")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["competitor_id"], "competitor-1")

    def test_list_for_competitor_with_incompatible_filters_returns_empty(self):
        self.repo.create(
            competitor_id="competitor-1", url="https://a.example.com", page_type="BLOG",
            check_interval_minutes=60, now=NOW,
        )
        self.assertEqual(self.repo.list_for_competitor("competitor-1", active=False), [])
        self.assertEqual(
            self.repo.list_for_competitor("competitor-1", discovery_status="ACTIVE"), []
        )

    def test_list_active_targets_without_competitor_id_scans_whole_table(self):
        self.repo.create(
            competitor_id="competitor-1", url="https://a.example.com", page_type="BLOG",
            check_interval_minutes=60, now=NOW,
        )
        self.repo.create(
            competitor_id="competitor-2", url="https://b.example.com", page_type="BLOG",
            check_interval_minutes=60, now=NOW,
        )
        rows = self.repo.list_active_targets()
        self.assertEqual(len(rows), 2)

    def test_upsert_discovered_candidate_never_persists_discarded(self):
        result = self.repo.upsert_discovered_candidate(
            competitor_id="competitor-1",
            raw_url="https://example.com/careers",
            url="https://example.com/careers",
            page_type="OTHER",
            discovery_source="LINKS",
            discovery_status="DISCARDED",
            classification_method="RULE",
        )
        self.assertEqual(result["discovery_status"], "DISCARDED")
        self.assertEqual(self.table.items, [])

    def test_upsert_discovered_candidate_creates_suggested_row(self):
        result = self.repo.upsert_discovered_candidate(
            competitor_id="competitor-1",
            raw_url="https://example.com/blog",
            url="https://example.com/blog",
            page_type="BLOG",
            discovery_source="SITEMAP",
            discovery_status="SUGGESTED",
            classification_method="RULE",
        )
        self.assertEqual(result["discovery_status"], "SUGGESTED")
        self.assertEqual(len(self.table.items), 1)

    def test_upsert_discovered_candidate_refreshes_existing_row_metadata(self):
        first = self.repo.upsert_discovered_candidate(
            competitor_id="competitor-1", raw_url="https://example.com/blog",
            url="https://example.com/blog", page_type="BLOG",
            discovery_source="SITEMAP", discovery_status="SUGGESTED",
            classification_method="RULE",
        )
        second = self.repo.upsert_discovered_candidate(
            competitor_id="competitor-1", raw_url="https://example.com/blog/",
            url="https://example.com/blog", page_type="BLOG",
            discovery_source="SITEMAP", discovery_status="SUGGESTED",
            classification_method="LLM",
        )
        self.assertEqual(second["id"], first["id"])
        self.assertEqual(second["classification_method"], "LLM")
        self.assertEqual(len(self.table.items), 1)

    def test_last_checked_at_round_trips_as_a_real_datetime_not_a_string(self):
        # SchedulerService._is_due() requires a real datetime; DynamoDB has no
        # native datetime type, so this specifically guards the ISO-string
        # round-trip in _to_dict()/_from_iso().
        created = self.repo.create(
            competitor_id="competitor-1", url="https://example.com/blog",
            page_type="BLOG", check_interval_minutes=60, now=NOW,
        )
        updated = self.repo.update(created["id"], {"last_checked_at": NOW})
        self.assertIsInstance(updated["last_checked_at"], datetime)
        self.assertEqual(updated["last_checked_at"], NOW)
        fetched = self.repo.get(created["id"])
        self.assertIsInstance(fetched["last_checked_at"], datetime)
        self.assertIsInstance(fetched["created_at"], datetime)

    def test_update_rejects_lifecycle_fields(self):
        created = self.repo.create(
            competitor_id="competitor-1", url="https://example.com/blog",
            page_type="BLOG", check_interval_minutes=60, now=NOW,
        )
        with self.assertRaises(ValueError):
            self.repo.update(created["id"], {"active": True})
        with self.assertRaises(ValueError):
            self.repo.update(created["id"], {"discovery_status": "ACTIVE"})

    def test_update_writes_ordinary_metadata_field(self):
        created = self.repo.create(
            competitor_id="competitor-1", url="https://example.com/blog",
            page_type="BLOG", check_interval_minutes=60, now=NOW,
        )
        updated = self.repo.update(created["id"], {"last_checked_at": NOW})
        self.assertIsNotNone(updated["last_checked_at"])

    def test_mark_activated_is_a_no_op_when_interval_already_set(self):
        created = self.repo.create(
            competitor_id="competitor-1", url="https://example.com/blog",
            page_type="BLOG", check_interval_minutes=60, now=NOW,
        )
        result = self.repo.mark_activated(created["id"], check_interval_minutes=60)
        self.assertEqual(result, created)

    def test_mark_activated_backfills_missing_interval(self):
        created = self.repo.create(
            competitor_id="competitor-1", url="https://example.com/blog",
            page_type="BLOG", check_interval_minutes=60, now=NOW,
        )
        result = self.repo.mark_activated(created["id"], check_interval_minutes=30)
        self.assertEqual(result["check_interval_minutes"], 30)

    def test_mark_discarded_deletes_the_row(self):
        created = self.repo.create(
            competitor_id="competitor-1", url="https://example.com/blog",
            page_type="BLOG", check_interval_minutes=60, now=NOW,
        )
        result = self.repo.mark_discarded(created["id"])
        self.assertEqual(result["discovery_status"], "DISCARDED")
        self.assertIsNone(self.repo.get(created["id"]))

    def test_delete_removes_the_row(self):
        created = self.repo.create(
            competitor_id="competitor-1", url="https://example.com/blog",
            page_type="BLOG", check_interval_minutes=60, now=NOW,
        )
        self.assertTrue(self.repo.delete(created["id"]))
        self.assertIsNone(self.repo.get(created["id"]))

    def test_discard_discovered_candidates_by_url_patterns_is_a_no_op(self):
        self.assertEqual(
            self.repo.discard_discovered_candidates_by_url_patterns(
                "competitor-1", url_patterns=("/careers",)
            ),
            0,
        )


if __name__ == "__main__":
    unittest.main()
