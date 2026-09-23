from __future__ import annotations

import unittest
from datetime import datetime, timezone

from backend.flask.change_detection.rm_repository import RmChangeRepository
from tests.test_poc_backend import _Collection


NOW = datetime(2026, 9, 17, 6, 0, tzinfo=timezone.utc)


class _Database:
    def __init__(self):
        self.collections = {}

    def __getitem__(self, name):
        return self.collections.setdefault(name, _Collection())


class RmChangeRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.repo = RmChangeRepository.from_database(_Database())
        self.target_id = "6aab00000000000000000001"
        self.previous_snapshot = {
            "monitoring_target_id": self.target_id,
            "captured_at": "2026-01-01T00:00:00+00:00",
        }
        self.current_snapshot = {
            "monitoring_target_id": self.target_id,
            "captured_at": "2026-01-02T00:00:00+00:00",
        }

    def _create(self, **overrides):
        kwargs = dict(
            monitoring_target_id=self.target_id,
            previous_snapshot_id=self.previous_snapshot,
            current_snapshot_id=self.current_snapshot,
            detected_at=NOW,
            change_type="PAGE_UPDATE",
            summary="a change happened",
            status="NEW",
        )
        kwargs.update(overrides)
        return self.repo.create(**kwargs)

    def test_create_stores_the_dynamodb_reference_pair_not_a_scalar_id(self):
        created = self._create()
        self.assertEqual(created["previous_snapshot"], self.previous_snapshot)
        self.assertEqual(created["current_snapshot"], self.current_snapshot)
        self.assertNotIn("previous_snapshot_id", created)
        self.assertNotIn("current_snapshot_id", created)

    def test_monitoring_target_id_round_trips_as_a_plain_string(self):
        created = self._create()
        self.assertEqual(created["monitoring_target_id"], self.target_id)

    def test_create_rejects_a_non_mapping_snapshot_reference(self):
        with self.assertRaises(ValueError):
            self._create(previous_snapshot_id="not-a-mapping")

    def test_create_rejects_a_reference_missing_captured_at(self):
        with self.assertRaises(ValueError):
            self._create(
                previous_snapshot_id={"monitoring_target_id": self.target_id}
            )

    def test_get_returns_the_created_document(self):
        created = self._create()
        fetched = self.repo.get(created["id"])
        self.assertEqual(fetched["id"], created["id"])
        self.assertEqual(fetched["previous_snapshot"], self.previous_snapshot)

    def test_list_for_target_finds_it_by_the_plain_string_id(self):
        created = self._create()
        rows = self.repo.list_for_target(self.target_id)
        self.assertEqual([row["id"] for row in rows], [created["id"]])

    def test_delete_by_id_removes_the_document(self):
        created = self._create()
        self.assertTrue(self.repo.delete_by_id(created["id"]))
        self.assertIsNone(self.repo.get(created["id"]))

    def test_collection_name_is_the_new_rm_collection(self):
        self.assertEqual(RmChangeRepository.collection_name, "competitors_changes")


if __name__ == "__main__":
    unittest.main()
