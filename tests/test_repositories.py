from __future__ import annotations

import unittest
import re
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone

from backend.flask.competitors.repository import CompetitorRepository
from backend.flask.change_detection.repository import ChangeRepository
from backend.flask.database.base_repository import to_object_id
from backend.flask.database.connection import MongoConfigurationError, MongoSettings
from backend.flask.discovery.classification import DeterministicStubClassifier
from backend.flask.discovery.service import DiscoveryError, DiscoveryService
from backend.flask.website_monitoring.repository import MonitoringTargetRepository
from backend.flask.snapshot.repository import SnapshotRepository

try:
    from bson import ObjectId
except ImportError:
    ObjectId = None


@dataclass
class _InsertResult:
    inserted_id: str


@dataclass
class _WriteResult:
    matched_count: int = 1
    deleted_count: int = 1


@dataclass
class _UpdateManyResult:
    matched_count: int = 0
    modified_count: int = 0


class _Cursor(list):
    def sort(self, fields):
        for field, direction in reversed(fields):
            super().sort(key=lambda document: document.get(field), reverse=direction < 0)
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
        stored["_id"] = ObjectId(raw_id) if ObjectId else f"id-{self._next_id}"
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

    def update_one(self, query, update):
        for document in self.documents:
            if _matches(document, query):
                document.update(deepcopy(update["$set"]))
                return _WriteResult(matched_count=1)
        return _WriteResult(matched_count=0)

    def update_many(self, query, update):
        matched_count = 0
        modified_count = 0
        for document in self.documents:
            if not _matches(document, query):
                continue
            matched_count += 1
            values = deepcopy(update["$set"])
            if any(document.get(key) != value for key, value in values.items()):
                modified_count += 1
                document.update(values)
        return _UpdateManyResult(matched_count, modified_count)

    def delete_one(self, query):
        for index, document in enumerate(self.documents):
            if _matches(document, query):
                del self.documents[index]
                return _WriteResult(deleted_count=1)
        return _WriteResult(deleted_count=0)


class _FakeDatabase:
    def __init__(self):
        self.collections = {}

    def __getitem__(self, name):
        return self.collections.setdefault(name, _FakeCollection())


def _matches(document, query):
    for field, value in query.items():
        if field == "$or":
            if not any(_matches(document, branch) for branch in value):
                return False
            continue
        actual = document.get(field)
        if isinstance(value, dict):
            if "$exists" in value and ((field in document) != value["$exists"]):
                return False
            if "$ne" in value and actual == value["$ne"]:
                return False
            if "$in" in value and actual not in value["$in"]:
                return False
            if "$regex" in value and re.search(
                value["$regex"], str(actual or ""), flags=re.IGNORECASE
            ) is None:
                return False
            continue
        if actual != value:
            return False
    return True


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        database = _FakeDatabase()
        self.database = database
        self.competitors = CompetitorRepository.from_database(database)
        self.targets = MonitoringTargetRepository.from_database(database)
        self.timestamp = datetime(2026, 9, 3, tzinfo=timezone.utc)

    def test_ensure_indexes_defines_tenant_and_target_indexes(self):
        self.competitors.ensure_indexes()
        self.targets.ensure_indexes()

        competitor_names = {options["name"] for _, options in self.competitors.collection.indexes}
        target_names = {options["name"] for _, options in self.targets.collection.indexes}
        self.assertEqual(
            competitor_names,
            {"uq_competitors_user_website_url", "ix_competitors_user_active"},
        )
        self.assertEqual(
            target_names,
            {
                "uq_monitoring_targets_competitor_url",
                "ix_monitoring_targets_competitor_active",
                "ix_monitoring_targets_competitor_discovery_status",
                "ix_monitoring_targets_scheduler",
            },
        )

    def test_competitor_crud_is_tenant_scoped(self):
        created = self.competitors.create(
            user_id="company-a",
            name="Example",
            website_url="https://example.com",
            now=self.timestamp,
        )

        self.assertTrue(created["id"])
        self.assertEqual(self.competitors.get(created["id"], user_id="company-b"), None)
        self.assertEqual(len(self.competitors.list_for_user("company-a")), 1)

        updated = self.competitors.update(
            created["id"],
            user_id="company-a",
            name="Updated Example",
            active=False,
        )
        self.assertEqual(updated["name"], "Updated Example")
        self.assertFalse(updated["active"])
        self.assertEqual(len(self.competitors.list_for_user("company-a", active=True)), 0)
        self.assertTrue(self.competitors.delete(created["id"], user_id="company-a"))
        self.assertIsNone(self.competitors.get(created["id"], user_id="company-a"))

    def test_monitoring_target_preserves_discovery_metadata(self):
        competitor = self.competitors.create(
            user_id="company-a",
            name="Example",
            website_url="https://example.com",
            now=self.timestamp,
        )
        target = self.targets.create(
            competitor_id=competitor["id"],
            raw_url="https://example.com/blog/123",
            url="https://example.com/blog",
            page_type="BLOG",
            discovery_source="SITEMAP",
            discovery_status="SUGGESTED",
            classification_method="RULE",
            check_interval_minutes=180,
            now=self.timestamp,
        )

        self.assertEqual(target["competitor_id"], competitor["id"])
        self.assertEqual(target["raw_url"], "https://example.com/blog/123")
        self.assertEqual(target["discovery_status"], "SUGGESTED")
        self.assertEqual(
            self.targets.list_for_competitor(
                competitor["id"], discovery_status="SUGGESTED"
            )[0]["id"],
            target["id"],
        )

        updated = self.targets.update(
            target["id"],
            competitor_id=competitor["id"],
            active=True,
            check_interval_minutes=60,
        )
        self.assertEqual(updated["check_interval_minutes"], 60)
        self.assertTrue(updated["active"])

    def test_discovered_candidate_upsert_does_not_regress_an_active_target(self):
        competitor = self.competitors.create(
            user_id="company-a",
            name="Example",
            website_url="https://example.com",
            now=self.timestamp,
        )
        candidate = self.targets.upsert_discovered_candidate(
            competitor_id=competitor["id"],
            raw_url="https://example.com/pages/abc123",
            url="https://example.com/pages",
            page_type="ABOUT",
            discovery_source="LINKS",
            discovery_status="SUGGESTED",
            classification_method="RULE",
            now=self.timestamp,
        )
        self.targets.update(candidate["id"], active=True)

        refreshed = self.targets.upsert_discovered_candidate(
            competitor_id=competitor["id"],
            raw_url="https://example.com/pages/def456",
            url="https://example.com/pages",
            page_type="CAREERS",
            discovery_source="SITEMAP",
            discovery_status="DISCARDED",
            classification_method="LLM",
        )
        self.assertTrue(refreshed["active"])
        self.assertEqual(refreshed["discovery_status"], "SUGGESTED")
        self.assertEqual(refreshed["classification_method"], "RULE")
        self.assertEqual(refreshed["raw_url"], "https://example.com/pages/def456")

    def test_bulk_discard_only_updates_inactive_discovery_item_rows(self):
        competitor = self.competitors.create(
            user_id="company-a",
            name="Example",
            website_url="https://example.com",
            now=self.timestamp,
        )
        old_discovery_row = self.targets.create(
            competitor_id=competitor["id"],
            raw_url="https://example.com/product/blue-shoe/sku-1",
            url="https://example.com/product/blue-shoe/sku-1",
            page_type="PRODUCTS",
            discovery_source="SITEMAP",
            discovery_status="SUGGESTED",
            classification_method="RULE",
            active=False,
            check_interval_minutes=1440,
            now=self.timestamp,
        )
        manual_row = self.targets.create(
            competitor_id=competitor["id"],
            raw_url="https://example.com/product/manual/sku-1",
            url="https://example.com/product/manual/sku-1",
            page_type="OTHER",
            discovery_source="MANUAL",
            discovery_status="SUGGESTED",
            classification_method="MANUAL",
            active=False,
            check_interval_minutes=1440,
            now=self.timestamp,
        )
        active_row = self.targets.create(
            competitor_id=competitor["id"],
            raw_url="https://example.com/product/active/sku-1",
            url="https://example.com/product/active/sku-1",
            page_type="PRODUCTS",
            discovery_source="SITEMAP",
            discovery_status="ACTIVE",
            classification_method="RULE",
            active=True,
            check_interval_minutes=1440,
            now=self.timestamp,
        )

        changed = self.targets.discard_discovered_candidates_by_url_patterns(
            competitor["id"],
            url_patterns=(r"/product/[^/]+/[^/]+/?$",),
        )

        self.assertEqual(changed, 1)
        self.assertEqual(
            self.targets.get(old_discovery_row["id"])["discovery_status"],
            "DISCARDED",
        )
        self.assertEqual(
            self.targets.get(manual_row["id"])["discovery_status"],
            "SUGGESTED",
        )
        self.assertEqual(
            self.targets.get(active_row["id"])["discovery_status"],
            "ACTIVE",
        )

    def test_candidate_review_service_uses_candidate_target_repository(self):
        competitor = self.competitors.create(
            user_id="company-a",
            name="Example",
            website_url="https://example.com",
            now=self.timestamp,
        )
        suggested = self.targets.upsert_discovered_candidate(
            competitor_id=competitor["id"],
            raw_url="https://example.com/blog/post-1",
            url="https://example.com/blog",
            page_type="BLOG",
            discovery_source="SITEMAP",
            discovery_status="SUGGESTED",
            classification_method="RULE",
            now=self.timestamp,
        )
        discarded = self.targets.upsert_discovered_candidate(
            competitor_id=competitor["id"],
            raw_url="https://example.com/opaque",
            url="https://example.com/opaque",
            page_type="OTHER",
            discovery_source="SITEMAP",
            discovery_status="DISCARDED",
            classification_method="LLM",
            now=self.timestamp,
        )
        service = DiscoveryService(
            self.competitors,
            self.targets,
            fallback_classifier=DeterministicStubClassifier(),
            snapshot_repository=SnapshotRepository.from_database(self.database),
            change_repository=ChangeRepository.from_database(self.database),
        )

        self.assertEqual(
            [candidate["id"] for candidate in service.list_candidates(competitor["id"])],
            [suggested["id"]],
        )
        self.assertEqual(
            {candidate["id"] for candidate in service.list_candidates(competitor["id"], "ALL")},
            {suggested["id"], discarded["id"]},
        )

        activated = service.activate_candidate(suggested["id"])
        self.assertTrue(activated["active"])
        self.assertEqual(activated["discovery_status"], "ACTIVE")
        self.assertEqual(len(self.targets.list_for_competitor(competitor["id"])), 2)
        self.assertEqual(service.activate_candidate(suggested["id"])["id"], suggested["id"])
        self.assertEqual(len(self.targets.list_for_competitor(competitor["id"])), 2)

        added = service.add_candidate(competitor["id"], "https://example.com/manual")
        self.assertEqual(added["classification_method"], "MANUAL")
        edited = service.edit_candidate(discarded["id"], "https://example.com/review")
        self.assertEqual(edited["url"], "https://example.com/review")
        self.assertTrue(service.remove_candidate(discarded["id"]))
        with self.assertRaisesRegex(DiscoveryError, "already activated"):
            service.edit_candidate(suggested["id"], "https://example.com/changed")
        self.assertTrue(service.remove_candidate(suggested["id"]))
        self.assertIsNone(self.targets.get(suggested["id"]))
        self.assertIsNotNone(self.targets.get(added["id"]))

    def test_list_active_targets_excludes_candidates_and_malformed_rows(self):
        competitor = self.competitors.create(
            user_id="company-a",
            name="Example",
            website_url="https://example.com",
            now=self.timestamp,
        )
        suggested = self.targets.create(
            competitor_id=competitor["id"],
            url="https://example.com/suggested",
            page_type="OTHER",
            discovery_status="SUGGESTED",
            classification_method="RULE",
            check_interval_minutes=1440,
            active=False,
            now=self.timestamp,
        )
        discarded = self.targets.create(
            competitor_id=competitor["id"],
            url="https://example.com/discarded",
            page_type="OTHER",
            discovery_status="DISCARDED",
            classification_method="LLM",
            check_interval_minutes=1440,
            active=False,
            now=self.timestamp,
        )
        active = self.targets.create(
            competitor_id=competitor["id"],
            url="https://example.com/active",
            page_type="BLOG",
            discovery_status="ACTIVE",
            classification_method="RULE",
            check_interval_minutes=1440,
            active=True,
            now=self.timestamp,
        )
        with self.assertRaisesRegex(ValueError, "DISCARDED"):
            self.targets.create(
                competitor_id=competitor["id"],
                url="https://example.com/invalid",
                page_type="OTHER",
                discovery_status="DISCARDED",
                classification_method="LLM",
                check_interval_minutes=1440,
                active=True,
            )

        malformed_id = ObjectId("000000000000000000000099") if ObjectId else "malformed"
        self.targets.collection.documents.extend(
            (
                {
                    "_id": malformed_id,
                    "competitor_id": to_object_id(competitor["id"]),
                    "url": "https://example.com/malformed-discarded",
                    "active": True,
                    "discovery_status": "DISCARDED",
                },
                {
                    "_id": ObjectId("000000000000000000000098") if ObjectId else "missing-active",
                    "competitor_id": to_object_id(competitor["id"]),
                    "url": "https://example.com/missing-active",
                    "discovery_status": "ACTIVE",
                },
            )
        )
        active_targets = self.targets.list_active_targets(competitor["id"])
        self.assertEqual([target["id"] for target in active_targets], [active["id"]])
        self.assertNotIn(suggested["id"], {target["id"] for target in active_targets})
        self.assertNotIn(discarded["id"], {target["id"] for target in active_targets})

    def test_invalid_persisted_values_are_rejected(self):
        with self.assertRaises(ValueError):
            self.competitors.create(
                user_id="company-a",
                name="",
                website_url="https://example.com",
            )
        with self.assertRaises(ValueError):
            self.targets.create(
                competitor_id="competitor-1",
                url="https://example.com",
                page_type="BLOG",
                check_interval_minutes=0,
            )

    def test_change_repository_backfill_updates_only_nullable_narratives(self):
        repository = ChangeRepository.from_database(self.database)
        change = repository.create(
            monitoring_target_id="1" * 24,
            previous_snapshot_id="2" * 24,
            current_snapshot_id="3" * 24,
            detected_at=self.timestamp,
            change_type="NEW_BLOG",
            summary="NEW_BLOG: one line changed.",
            status="NEW",
            now=self.timestamp,
        )

        self.assertIsNone(change["narrative_summary"])
        self.assertEqual(
            [row["id"] for row in repository.list_needing_narrative_summary()],
            [change["id"]],
        )
        updated = repository.update_narrative_summary(
            change["id"],
            "A new article was added to the blog.",
            now=self.timestamp,
        )
        self.assertEqual(
            updated["narrative_summary"],
            "A new article was added to the blog.",
        )
        self.assertEqual(repository.list_needing_narrative_summary(), [])
        self.assertIsNone(
            repository.update_narrative_summary(
                change["id"],
                "This second update must not overwrite the first.",
                now=self.timestamp,
            )
        )

    def test_change_repository_delete_by_id_removes_only_requested_record(self):
        repository = ChangeRepository.from_database(self.database)
        change = repository.create(
            monitoring_target_id="1" * 24,
            previous_snapshot_id="2" * 24,
            current_snapshot_id="3" * 24,
            detected_at=self.timestamp,
            change_type="NEW_BLOG",
            summary="NEW_BLOG: one line changed.",
            status="NEW",
            now=self.timestamp,
        )

        self.assertTrue(repository.delete_by_id(change["id"]))
        self.assertIsNone(repository.get(change["id"]))
        self.assertFalse(repository.delete_by_id(change["id"]))

    def test_mongo_settings_require_uri_and_support_database_aliases(self):
        with self.assertRaises(MongoConfigurationError):
            MongoSettings.from_env({})

        settings = MongoSettings.from_env(
            {"MONGODB_URI": "mongodb://localhost", "MONGODB_DB_NAME": "monitoring"}
        )
        self.assertEqual(settings.database_name, "monitoring")


if __name__ == "__main__":
    unittest.main()
