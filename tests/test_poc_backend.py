from __future__ import annotations

import unittest
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone

from backend.flask.companies.repository import CompanyRepository
from backend.flask.companies.service import CompanyService
from backend.flask.competitors.repository import CompetitorRepository
from backend.flask.discovery.repository import DiscoveryRunRepository
from backend.flask.website_monitoring.service import FetchResult, hash_content
from backend.flask.website_monitoring.simulated_persistence import (
    SimulationPersistenceService,
)

try:
    from bson import ObjectId
except ImportError:
    ObjectId = None


@dataclass
class _InsertResult:
    inserted_id: object


@dataclass
class _WriteResult:
    matched_count: int = 1


class _Cursor(list):
    def sort(self, fields):
        for field, direction in reversed(fields):
            super().sort(
                key=lambda document: document.get(field),
                reverse=direction < 0,
            )
        return self


class _Collection:
    def __init__(self):
        self.documents = []
        self.indexes = []
        self.next_id = 1

    def create_index(self, keys, **options):
        self.indexes.append((keys, options))
        return options.get("name")

    def insert_one(self, document):
        stored = deepcopy(document)
        raw_id = f"{self.next_id:024x}"
        stored["_id"] = ObjectId(raw_id) if ObjectId else raw_id
        self.next_id += 1
        self.documents.append(stored)
        return _InsertResult(stored["_id"])

    def find_one(self, query):
        return next(
            (deepcopy(document) for document in self.documents if _matches(document, query)),
            None,
        )

    def find(self, query):
        return _Cursor(
            deepcopy(document)
            for document in self.documents
            if _matches(document, query)
        )

    def update_one(self, query, update):
        for document in self.documents:
            if _matches(document, query):
                for key, value in update.get("$set", {}).items():
                    document[key] = deepcopy(value)
                for key in update.get("$unset", {}):
                    document.pop(key, None)
                return _WriteResult()
        return _WriteResult(matched_count=0)


def _matches(document, query):
    for field, expected in query.items():
        actual = document.get(field)
        if isinstance(expected, dict):
            if "$ne" in expected and actual == expected["$ne"]:
                return False
            if "$in" in expected and actual not in expected["$in"]:
                return False
            continue
        if actual != expected:
            return False
    return True


class _Database:
    def __init__(self):
        self.collections = {}

    def __getitem__(self, name):
        return self.collections.setdefault(name, _Collection())


class CompanyAndScopingTests(unittest.TestCase):
    def test_demo_companies_are_idempotently_seeded(self):
        database = _Database()
        service = CompanyService(CompanyRepository.from_database(database))

        first = service.ensure_demo_companies()
        second = service.ensure_demo_companies()

        self.assertEqual([company["name"] for company in first], [
            "Marketing Eye",
            "The Athletes Foot",
        ])
        self.assertEqual([company["id"] for company in first], [
            company["id"] for company in second
        ])
        self.assertEqual(len(service.list_companies()), 2)

    def test_migration_assigns_only_known_competitor_hosts(self):
        database = _Database()
        competitors = CompetitorRepository.from_database(database)
        marketing_eye_id = "a" * 24
        jd_id = "b" * 24
        lyfe = competitors.create(
            user_id="legacy-user",
            name="Lyfe Marketing",
            website_url="https://www.lyfemarketing.com/",
        )
        jd = competitors.create(
            user_id="legacy-user",
            name="JD Sports AU",
            website_url="https://www.jd-sports.com.au/",
        )
        brown_bag = competitors.create(
            user_id="legacy-user",
            name="Brown Bag Marketing",
            website_url="https://brownbagmarketing.com/",
        )

        competitors.migrate_legacy_user_ids({
            "lyfemarketing.com": marketing_eye_id,
            "jd-sports.com.au": jd_id,
        })

        self.assertEqual(competitors.get(lyfe["id"], company_id=marketing_eye_id)["company_id"], marketing_eye_id)
        self.assertEqual(competitors.get(jd["id"], company_id=jd_id)["company_id"], jd_id)
        unmapped = competitors.get(brown_bag["id"])
        self.assertNotIn("company_id", unmapped)
        self.assertNotIn("user_id", unmapped)
        self.assertEqual(len(competitors.list_for_company(marketing_eye_id)), 1)

    def test_discovery_run_repository_tracks_terminal_status(self):
        database = _Database()
        repository = DiscoveryRunRepository.from_database(database)
        repository.ensure_indexes()

        running = repository.start(
            "run-1",
            competitor_id="c" * 24,
            company_id="a" * 24,
        )
        self.assertEqual(running["status"], "RUNNING")
        self.assertEqual(repository.get("run-1")["status"], "RUNNING")

        finished = repository.succeed(
            "run-1",
            candidate_count=0,
            summary={"suggested_count": 0},
        )
        self.assertEqual(finished["status"], "SUCCESS")
        self.assertEqual(finished["candidate_count"], 0)
        self.assertEqual(repository.get("run-1")["summary"]["suggested_count"], 0)

    def test_migration_does_not_clear_explicit_company_assignments(self):
        database = _Database()
        competitors = CompetitorRepository.from_database(database)
        assigned = competitors.create(
            company_id="c" * 24,
            name="Assigned competitor",
            website_url="https://new.example.com/",
        )

        competitors.migrate_legacy_user_ids({
            "lyfemarketing.com": "a" * 24,
        })

        refreshed = competitors.get(assigned["id"], company_id="c" * 24)
        self.assertIsNotNone(refreshed)
        self.assertEqual(refreshed["company_id"], "c" * 24)


class _TargetRepository:
    def __init__(self):
        self.target = {
            "id": "t" * 24,
            "competitor_id": "c" * 24,
            "url": "https://example.com/blog",
            "page_type": "BLOG",
            "active": True,
            "discovery_status": "ACTIVE",
        }

    def get(self, target_id):
        return self.target if target_id == self.target["id"] else None


class _SnapshotRepository:
    def __init__(self):
        self.real = {
            "id": "r" * 24,
            "content": "<html><main><h1>Real baseline</h1></main></html>",
            "content_hash": hash_content("<html><main><h1>Real baseline</h1></main></html>"),
            "is_simulated": False,
        }
        self.calls = []

    def list_for_target(self, target_id, *, include_simulated=True):
        self.calls.append(include_simulated)
        return [self.real]


class _SnapshotService:
    def __init__(self):
        self.calls = []

    def create_snapshot(self, target_id, content, **kwargs):
        self.calls.append((target_id, content, kwargs))
        return {
            "id": "s" * 24,
            "monitoring_target_id": target_id,
            "content": content,
            "content_hash": hash_content(content),
            "is_simulated": kwargs["is_simulated"],
        }


class _ChangeService:
    def __init__(self):
        self.calls = []

    def create_change(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return {
            "id": "h" * 24,
            "monitoring_target_id": args[0],
            "current_snapshot_id": kwargs["current_snapshot"]["id"]
            if "current_snapshot" in kwargs else "s" * 24,
            "change_type": kwargs["change_type"],
            "summary": kwargs["summary"],
            "is_simulated": kwargs["is_simulated"],
        }


class _Provider:
    def generate(self, prompt, *, instructions, response_format=None):
        return "<article><h2>A simulated article</h2><p>New copy.</p></article>"


class SimulationPersistenceTests(unittest.TestCase):
    def test_blog_simulation_writes_tagged_records_after_real_history_lookup(self):
        snapshots = _SnapshotRepository()
        snapshot_service = _SnapshotService()
        changes = _ChangeService()
        service = SimulationPersistenceService(
            _TargetRepository(),
            snapshots,
            snapshot_service,
            changes,
            provider_factory=_Provider,
            fetcher=lambda url: FetchResult(
                "<html><main><h1>Real baseline</h1></main></html>",
                "HTTP",
                200,
            ),
        )

        result = service.simulate_and_persist_change("t" * 24)

        self.assertEqual(snapshots.calls, [False])
        self.assertTrue(snapshot_service.calls[0][2]["is_simulated"])
        self.assertTrue(changes.calls[0][1]["is_simulated"])
        self.assertEqual(result["previous_snapshot"]["id"], "r" * 24)
        self.assertTrue(result["snapshot"]["is_simulated"])
        self.assertTrue(result["change"]["is_simulated"])


if __name__ == "__main__":
    unittest.main()
