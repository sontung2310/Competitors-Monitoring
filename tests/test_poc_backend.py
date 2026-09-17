from __future__ import annotations

import unittest
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from backend.flask.companies.repository import CompanyRepository
from backend.flask.companies.service import CompanyService
from backend.flask.competitors.repository import CompetitorRepository
from backend.flask.discovery.repository import (
    DiscoveryRunAlreadyRunningError,
    DiscoveryRunRepository,
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


@dataclass
class _DeleteResult:
    deleted_count: int = 1


class _DuplicateKeyError(RuntimeError):
    code = 11000


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

    def delete_one(self, query):
        for index, document in enumerate(self.documents):
            if _matches(document, query):
                del self.documents[index]
                return _DeleteResult(deleted_count=1)
        return _DeleteResult(deleted_count=0)

    def count_documents(self, query):
        return sum(1 for document in self.documents if _matches(document, query))


class _RunningUniqueCollection(_Collection):
    def insert_one(self, document):
        if document.get("status") == "RUNNING" and any(
            existing.get("competitor_id") == document.get("competitor_id")
            and existing.get("status") == "RUNNING"
            for existing in self.documents
        ):
            raise _DuplicateKeyError("duplicate running competitor")
        return super().insert_one(document)


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


class _RunningUniqueDatabase(_Database):
    def __getitem__(self, name):
        default = _RunningUniqueCollection() if name == "discovery_runs" else _Collection()
        return self.collections.setdefault(name, default)


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

    def test_discovery_run_repository_returns_latest_successful_run(self):
        database = _Database()
        repository = DiscoveryRunRepository.from_database(database)
        repository.ensure_indexes()
        started_at = datetime(2026, 9, 1, tzinfo=timezone.utc)

        repository.start(
            "run-old",
            competitor_id="c" * 24,
            company_id="a" * 24,
            started_at=started_at,
        )
        repository.succeed(
            "run-old",
            candidate_count=1,
            finished_at=datetime(2026, 9, 1, 0, 5, tzinfo=timezone.utc),
        )
        repository.start(
            "run-failed",
            competitor_id="c" * 24,
            company_id="a" * 24,
            started_at=datetime(2026, 9, 2, tzinfo=timezone.utc),
        )
        repository.fail("run-failed", "source unavailable")
        repository.start(
            "run-new",
            competitor_id="c" * 24,
            company_id="a" * 24,
            started_at=datetime(2026, 9, 3, tzinfo=timezone.utc),
        )
        repository.succeed(
            "run-new",
            candidate_count=2,
            finished_at=datetime(2026, 9, 3, 0, 7, tzinfo=timezone.utc),
        )

        latest = repository.find_latest_successful(
            "c" * 24,
            company_id="a" * 24,
        )

        self.assertEqual(latest["run_id"], "run-new")
        self.assertEqual(
            latest["finished_at"],
            datetime(2026, 9, 3, 0, 7, tzinfo=timezone.utc),
        )
        self.assertIsNone(
            repository.find_latest_successful(
                "c" * 24,
                company_id="b" * 24,
            )
        )

    def test_discovery_run_repository_serializes_concurrent_run_as_retryable_conflict(self):
        database = _RunningUniqueDatabase()
        repository = DiscoveryRunRepository.from_database(database)
        repository.ensure_indexes()

        repository.start("run-1", competitor_id="c" * 24)
        with self.assertRaises(DiscoveryRunAlreadyRunningError):
            repository.start("run-2", competitor_id="c" * 24)

        repository.succeed("run-1", candidate_count=0)
        resumed = repository.start("run-2", competitor_id="c" * 24)
        self.assertEqual(resumed["run_id"], "run-2")

    def test_stale_discovery_run_is_failed_then_replaced(self):
        database = _RunningUniqueDatabase()
        repository = DiscoveryRunRepository.from_database(database)
        repository.ensure_indexes()
        now = datetime(2026, 9, 4, 12, tzinfo=timezone.utc)

        stale = repository.start(
            "run-stale",
            competitor_id="c" * 24,
            started_at=now - timedelta(minutes=31),
        )
        replacement = repository.start(
            "run-replacement",
            competitor_id="c" * 24,
            started_at=now,
        )

        self.assertEqual(repository.get(stale["run_id"])["status"], "FAILED")
        self.assertEqual(replacement["run_id"], "run-replacement")

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

if __name__ == "__main__":
    unittest.main()
