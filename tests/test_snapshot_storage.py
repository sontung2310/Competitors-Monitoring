"""Unit coverage for snapshot metadata and compressed local storage."""

from __future__ import annotations

import tempfile
import unittest
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from backend.flask.database.base_repository import serialize_document, to_object_id
from backend.flask.snapshot.repository import SnapshotRepository
from backend.flask.snapshot.service import SnapshotService, create_snapshot
from backend.flask.snapshot.storage import SnapshotStorage
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


class SnapshotStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.storage = SnapshotStorage(self.temp_directory.name)
        self.collection = _FakeCollection()
        self.repository = SnapshotRepository(self.collection)
        self.service = SnapshotService(self.repository, self.storage)
        self.target_id = (
            ObjectId("000000000000000000000001")
            if ObjectId
            else "000000000000000000000001"
        )
        self.captured_at = datetime(
            2026,
            9,
            4,
            6,
            30,
            15,
            123456,
            tzinfo=timezone.utc,
        )

    def tearDown(self):
        self.temp_directory.cleanup()

    def test_repository_defines_target_history_index(self):
        self.repository.ensure_indexes()

        self.assertEqual(
            self.collection.indexes,
            [
                (
                    [("monitoring_target_id", 1), ("captured_at", -1)],
                    {"name": "ix_snapshots_target_captured_at"},
                )
            ],
        )

    def test_create_snapshot_stores_normalized_bytes_and_matching_metadata(self):
        raw_content = """
            <html>
              <body>
                <main>
                  <h1>Stable competitor content</h1>
                  <p>Meaningful copy remains in the stored snapshot.</p>
                </main>
                <script>window.renderedAt = 123;</script>
              </body>
            </html>
        """
        normalized = normalize_content(raw_content)
        snapshot = self.service.create_snapshot(
            self.target_id,
            raw_content,
            fetch_method="HTTP",
            http_status=200,
            captured_at=self.captured_at,
        )

        self.assertEqual(
            set(snapshot),
            {
                "id",
                "monitoring_target_id",
                "captured_at",
                "content_hash",
                "content_size",
                "storage_path",
                "fetch_method",
                "http_status",
                "created_at",
                "updated_at",
            },
        )
        self.assertEqual(snapshot["monitoring_target_id"], str(self.target_id))
        self.assertEqual(snapshot["content_hash"], hash_content(normalized))
        self.assertEqual(snapshot["content_size"], len(normalized.encode("utf-8")))
        self.assertEqual(snapshot["fetch_method"], "HTTP")
        self.assertEqual(snapshot["http_status"], 200)
        self.assertFalse(Path(snapshot["storage_path"]).is_absolute())
        self.assertTrue(snapshot["storage_path"].startswith("snapshots/"))
        self.assertEqual(
            self.storage.read_snapshot_bytes(snapshot["storage_path"]),
            normalized.encode("utf-8"),
        )

    def test_two_close_snapshots_have_distinct_files_and_records(self):
        content = "<main><h1>Stable page content for a snapshot</h1></main>"

        first = self.service.create_snapshot(
            self.target_id,
            content,
            captured_at=self.captured_at,
        )
        second = self.service.create_snapshot(
            self.target_id,
            content,
            captured_at=self.captured_at,
        )

        self.assertNotEqual(first["id"], second["id"])
        self.assertNotEqual(first["storage_path"], second["storage_path"])
        self.assertEqual(first["content_hash"], second["content_hash"])
        self.assertEqual(len(self.repository.list_for_target(self.target_id)), 2)
        self.assertTrue(
            self.storage.absolute_path(first["storage_path"]).exists()
        )
        self.assertTrue(
            self.storage.absolute_path(second["storage_path"]).exists()
        )
        self.assertLess(first["storage_path"], second["storage_path"])

    def test_functional_entry_point_uses_injected_repository_and_storage(self):
        content = "<main><p>Manual snapshot content with enough text.</p></main>"

        snapshot = create_snapshot(
            self.target_id,
            content,
            snapshot_repository=self.repository,
            storage=self.storage,
            fetch_method="BROWSER",
            http_status=200,
        )

        self.assertEqual(snapshot["fetch_method"], "BROWSER")
        self.assertEqual(snapshot["http_status"], 200)
        self.assertEqual(len(self.repository.list_for_target(self.target_id)), 1)

    def test_metadata_insert_failure_removes_orphaned_file(self):
        class FailingRepository:
            def create(self, **metadata):
                raise RuntimeError("database unavailable")

        service = SnapshotService(FailingRepository(), self.storage)
        with self.assertRaisesRegex(RuntimeError, "metadata could not be persisted"):
            service.create_snapshot(
                self.target_id,
                "<main>Content that is long enough to be stored.</main>",
            )

        files = list((Path(self.temp_directory.name) / "snapshots").rglob("*.gz"))
        self.assertEqual(files, [])


if __name__ == "__main__":
    unittest.main()
