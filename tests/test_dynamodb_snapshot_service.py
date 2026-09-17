from __future__ import annotations

import unittest
from datetime import datetime, timezone

from backend.flask.snapshot.dynamodb_service import DynamoDBSnapshotService, SNAPSHOT_TTL
from tests.fake_dynamodb import FakeDynamoDBTable


NOW = datetime(2026, 9, 17, 6, 0, tzinfo=timezone.utc)


class DynamoDBSnapshotServiceTests(unittest.TestCase):
    def setUp(self):
        self.table = FakeDynamoDBTable(("monitoring_target_id", "captured_at"))
        self.service = DynamoDBSnapshotService(self.table)

    def test_create_snapshot_stores_content_directly_in_the_item(self):
        snapshot = self.service.create_snapshot(
            "target-1",
            "<html>hello</html>",
            fetch_method="HTTP",
            http_status=200,
            captured_at=NOW,
        )
        self.assertEqual(snapshot["normalized_content"], "<html>hello</html>")
        self.assertIsInstance(snapshot["content_size"], int)
        self.assertIsInstance(snapshot["http_status"], int)
        self.assertNotIn("storage_path", snapshot)
        self.assertNotIn("expires_at", snapshot)

    def test_create_snapshot_sets_a_thirty_day_ttl(self):
        self.service.create_snapshot(
            "target-1", "<html>hello</html>", captured_at=NOW,
        )
        stored = self.table.items[0]
        expected_expiry = int((NOW + SNAPSHOT_TTL).timestamp())
        self.assertEqual(int(stored["expires_at"]), expected_expiry)

    def test_create_snapshot_requires_timezone_aware_captured_at(self):
        with self.assertRaises(ValueError):
            self.service.create_snapshot(
                "target-1", "<html>hello</html>", captured_at=datetime(2026, 1, 1)
            )

    def test_list_for_target_returns_newest_first(self):
        self.service.create_snapshot(
            "target-1", "<html>v1</html>",
            captured_at=NOW.replace(hour=1),
        )
        self.service.create_snapshot(
            "target-1", "<html>v2</html>",
            captured_at=NOW.replace(hour=2),
        )
        self.service.create_snapshot(
            "target-2", "<html>other</html>",
            captured_at=NOW.replace(hour=1),
        )
        history = self.service.list_for_target("target-1")
        self.assertEqual(len(history), 2)
        self.assertEqual(
            [snap["normalized_content"] for snap in history],
            ["<html>v2</html>", "<html>v1</html>"],
        )

    def test_get_fetches_one_snapshot_by_its_real_key(self):
        created = self.service.create_snapshot(
            "target-1", "<html>hello</html>", captured_at=NOW,
        )
        fetched = self.service.get("target-1", created["captured_at"])
        self.assertEqual(fetched["normalized_content"], "<html>hello</html>")
        self.assertIsNone(self.service.get("target-1", "1970-01-01T00:00:00+00:00"))

    def test_content_hash_matches_normalized_content_hashing(self):
        from backend.flask.website_monitoring.service import hash_content, normalize_content

        raw = "<html><body>Hello   World</body></html>"
        snapshot = self.service.create_snapshot("target-1", raw, captured_at=NOW)
        self.assertEqual(
            snapshot["content_hash"],
            hash_content(normalize_content(raw)),
        )


if __name__ == "__main__":
    unittest.main()
