from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone

from backend.flask.companies.repository import CompanyRepository
from backend.flask.companies.service import CompanyService
from backend.flask.competitors.repository import CompetitorRepository
from backend.flask.competitors.service import CompetitorService
from backend.flask.scheduler.sqs_handler import (
    MessageValidationError,
    handle_message,
    parse_message,
)


NOW = datetime(2026, 9, 11, 6, 0, tzinfo=timezone.utc)


class _CompanyService:
    def __init__(self):
        self.calls = []

    def find_or_create_by_domain(self, domain):
        self.calls.append(domain)
        return {"id": "company-1", "website_url": domain}


class _CompetitorService:
    def __init__(self):
        self.calls = []
        self.rows = {}

    def find_or_create_competitor(self, *, company_id, name, website_url):
        key = (company_id, website_url)
        self.calls.append({"company_id": company_id, "name": name, "website_url": website_url})
        if key not in self.rows:
            self.rows[key] = {
                "id": "competitor-1",
                "company_id": company_id,
                "name": name,
                "website_url": website_url,
            }
        return dict(self.rows[key])


class _DiscoveryService:
    def __init__(self, latest=None):
        self.latest = latest
        self.latest_calls = []
        self.reconciliation_calls = []

    def latest_successful_run(self, competitor_id, *, company_id):
        self.latest_calls.append((competitor_id, company_id))
        return self.latest

    def discover_and_reconcile(self, competitor_id, *, company_id):
        self.reconciliation_calls.append((competitor_id, company_id))
        self.latest = {
            "run_id": "run-1",
            "finished_at": NOW,
            "status": "SUCCESS",
        }
        return {
            "run_id": "run-1",
            "competitor_id": competitor_id,
            "activated_target_ids": [],
            "deactivated_target_ids": [],
        }


def _message(host="DEV"):
    return {
        "strategy_id": 1,
        "company_domain_id": "Tenant.Example.",
        "company_url": "HTTPS://Example.COM/p3-test///",
        "host": host,
    }


class ParseMessageTests(unittest.TestCase):
    def test_parse_message_normalizes_supported_fields(self):
        parsed = parse_message(json.dumps(_message()))

        self.assertEqual(
            parsed,
            {
                "strategy_id": 1,
                "company_domain_id": "tenant.example",
                "company_url": "https://example.com/p3-test",
                "host": "dev",
            },
        )

    def test_parse_message_accepts_mapping_for_direct_callers(self):
        parsed = parse_message({**_message(), "strategy_id": "1"})
        self.assertEqual(parsed["strategy_id"], 1)

    def test_parse_message_rejects_malformed_values(self):
        invalid_messages = (
            {**_message(), "strategy_id": 2},
            {**_message(), "company_domain_id": "not a domain"},
            {**_message(), "company_url": "ftp://example.com"},
            {**_message(), "host": ""},
        )
        for invalid in invalid_messages:
            with self.subTest(invalid=invalid):
                with self.assertRaises(MessageValidationError):
                    parse_message(invalid)

        with self.assertRaises(MessageValidationError):
            parse_message("not-json")


class HandleMessageTests(unittest.TestCase):
    def setUp(self):
        self.companies = _CompanyService()
        self.competitors = _CompetitorService()
        self.discovery = _DiscoveryService()
        self.services = {
            "companies": self.companies,
            "competitors": self.competitors,
            "discovery": self.discovery,
        }

    def test_stale_existing_competitor_reconciles_at_thirty_day_boundary(self):
        self.discovery.latest = {
            "run_id": "old-run",
            "finished_at": NOW - timedelta(days=30),
            "status": "SUCCESS",
        }

        result = handle_message(_message(), self.services, clock=lambda: NOW)

        self.assertEqual(result["action"], "reconciled")
        self.assertEqual(len(self.competitors.calls), 1)
        self.assertEqual(self.discovery.reconciliation_calls, [("competitor-1", "company-1")])

    def test_fresh_existing_competitor_skips_discovery_and_reconciliation(self):
        self.discovery.latest = {
            "run_id": "fresh-run",
            "finished_at": NOW - timedelta(days=29, seconds=1),
            "status": "SUCCESS",
        }

        result = handle_message(_message(host="prod"), self.services, clock=lambda: NOW)

        self.assertEqual(result["action"], "skipped_fresh")
        self.assertEqual(self.discovery.reconciliation_calls, [])
        self.assertEqual(self.companies.calls, ["tenant.example"])

    def test_identical_message_is_idempotent_without_snapshot_or_monitoring_calls(self):
        first = handle_message(_message(), self.services, clock=lambda: NOW)
        second = handle_message(_message(), self.services, clock=lambda: NOW)

        self.assertEqual(first["action"], "reconciled")
        self.assertEqual(second["action"], "skipped_fresh")
        self.assertEqual(len(self.companies.calls), 2)
        self.assertEqual(len(self.competitors.rows), 1)
        self.assertEqual(len(self.competitors.calls), 2)
        self.assertEqual(len(self.discovery.reconciliation_calls), 1)
        self.assertEqual(first["competitor"], second["competitor"])


class RealServiceFindOrCreateTests(unittest.TestCase):
    def test_company_and_competitor_find_or_create_are_sequentially_idempotent(self):
        class _Database:
            def __init__(self):
                self.collections = {}

            def __getitem__(self, name):
                from tests.test_poc_backend import _Collection

                return self.collections.setdefault(name, _Collection())

        database = _Database()
        companies = CompanyService(CompanyRepository.from_database(database))
        competitors = CompetitorService(CompetitorRepository.from_database(database))

        company_one = companies.find_or_create_by_domain("SQS-Test.Example")
        company_two = companies.find_or_create_by_domain("sqs-test.example")
        competitor_one = competitors.find_or_create_competitor(
            company_id=company_one["id"],
            name="Example",
            website_url="https://example.com/",
        )
        competitor_two = competitors.find_or_create_competitor(
            company_id=company_one["id"],
            name="Different Name",
            website_url="https://example.com/",
        )

        self.assertEqual(company_one["id"], company_two["id"])
        self.assertEqual(competitor_one["id"], competitor_two["id"])
        self.assertEqual(
            len(competitors.repository.list_for_company(company_one["id"])),
            1,
        )


if __name__ == "__main__":
    unittest.main()
