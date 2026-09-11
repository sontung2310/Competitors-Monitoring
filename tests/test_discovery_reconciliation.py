from __future__ import annotations

import unittest

from backend.flask.discovery.classification import DeterministicStubClassifier
from backend.flask.discovery.service import DiscoveryService
from backend.flask.discovery.sources import DiscoveredURL


class _CompetitorRepository:
    def __init__(self) -> None:
        self.competitor = {
            "id": "competitor-1",
            "company_id": "company-1",
            "website_url": "https://example.com/",
            "name": "Example",
        }

    def get(self, competitor_id, *, user_id=None, company_id=None):
        if competitor_id != self.competitor["id"]:
            return None
        if user_id is not None and user_id != "user-1":
            return None
        if company_id is not None and company_id != self.competitor["company_id"]:
            return None
        return dict(self.competitor)

    def update(self, competitor_id, updates=None, *, user_id=None, company_id=None, **fields):
        if self.get(competitor_id, user_id=user_id, company_id=company_id) is None:
            return None
        self.competitor.update({**(updates or {}), **fields})
        return dict(self.competitor)


class _TargetRepository:
    def __init__(self) -> None:
        self.rows = [
            {
                "id": "target-old",
                "competitor_id": "competitor-1",
                "url": "https://example.com/old",
                "raw_url": "https://example.com/old",
                "page_type": "BLOG",
                "discovery_source": "SITEMAP",
                "discovery_status": "ACTIVE",
                "classification_method": "RULE",
                "active": True,
            },
            {
                "id": "target-new",
                "competitor_id": "competitor-1",
                "url": "https://example.com/new",
                "raw_url": "https://example.com/new",
                "page_type": "BLOG",
                "discovery_source": "SITEMAP",
                "discovery_status": "SUGGESTED",
                "classification_method": "RULE",
                "active": False,
            },
        ]

    def list_active_targets(self, competitor_id=None):
        return [
            dict(row)
            for row in self.rows
            if row.get("competitor_id") == competitor_id
            and row.get("active") is True
            and row.get("discovery_status") == "ACTIVE"
        ]

    def find_by_url(self, competitor_id, url):
        return next(
            (
                dict(row)
                for row in self.rows
                if row.get("competitor_id") == competitor_id and row.get("url") == url
            ),
            None,
        )

    def get(self, target_id, *, competitor_id=None):
        return next(
            (
                dict(row)
                for row in self.rows
                if row.get("id") == target_id
                and (competitor_id is None or row.get("competitor_id") == competitor_id)
            ),
            None,
        )

    def upsert_discovered_candidate(self, **candidate):
        existing = self.find_by_url(candidate["competitor_id"], candidate["url"])
        if existing is not None:
            for row in self.rows:
                if row["id"] != existing["id"]:
                    continue
                row.update(
                    {
                        "raw_url": candidate["raw_url"],
                        "discovery_source": candidate["discovery_source"],
                    }
                )
                if not row.get("active") and row.get("discovery_status") != "ACTIVE":
                    row.update(
                        {
                            "page_type": candidate["page_type"],
                            "discovery_status": candidate["discovery_status"],
                            "classification_method": candidate["classification_method"],
                        }
                    )
                return dict(row)

        row = {
            "id": f"target-{len(self.rows) + 1}",
            **candidate,
            "active": False,
        }
        self.rows.append(row)
        return dict(row)

    def update(self, target_id, updates=None, *, competitor_id=None, **fields):
        row = self.get(target_id, competitor_id=competitor_id)
        if row is None:
            return None
        values = {**(updates or {}), **fields}
        for stored in self.rows:
            if stored["id"] == target_id:
                stored.update(values)
                return dict(stored)
        return None

    def delete(self, target_id, *, competitor_id=None):
        before = len(self.rows)
        self.rows = [
            row
            for row in self.rows
            if not (
                row.get("id") == target_id
                and (competitor_id is None or row.get("competitor_id") == competitor_id)
            )
        ]
        return len(self.rows) != before

    def discard_discovered_candidates_by_url_patterns(self, competitor_id, *, url_patterns):
        return 0


class _HistoryRepository:
    def list_for_target(self, target_id):
        return [{"id": "snapshot-1"}] if target_id == "target-old" else []


class _RunRepository:
    def __init__(self) -> None:
        self.runs = {}

    def start(self, run_id, *, competitor_id, company_id=None):
        self.runs[run_id] = {
            "run_id": run_id,
            "competitor_id": competitor_id,
            "company_id": company_id,
            "status": "RUNNING",
        }
        return dict(self.runs[run_id])

    def succeed(self, run_id, *, candidate_count, summary=None):
        self.runs[run_id].update(
            {
                "status": "SUCCESS",
                "candidate_count": candidate_count,
                "summary": summary,
            }
        )
        return dict(self.runs[run_id])

    def fail(self, run_id, error_message):
        self.runs[run_id].update({"status": "FAILED", "error_message": error_message})
        return dict(self.runs[run_id])

    def get(self, run_id):
        run = self.runs.get(run_id)
        return dict(run) if run is not None else None

    def find_latest_successful(self, competitor_id, *, company_id=None):
        runs = [
            run
            for run in self.runs.values()
            if run.get("competitor_id") == competitor_id
            and run.get("company_id") == company_id
            and run.get("status") == "SUCCESS"
        ]
        return dict(runs[-1]) if runs else None


class _RobotsSource:
    def sitemap_urls(self, website_url):
        return ()


class _SitemapSource:
    def discover(self, website_url, declared_sitemaps=()):
        return [DiscoveredURL("https://example.com/new", "SITEMAP")]


class _LinksSource:
    last_homepage_metadata = {}

    def discover(self, website_url):
        return ()


class DiscoveryReconciliationTests(unittest.TestCase):
    def test_reconciliation_activates_new_suggestions_and_deactivates_missing_targets(self):
        competitors = _CompetitorRepository()
        targets = _TargetRepository()
        runs = _RunRepository()
        service = DiscoveryService(
            competitors,
            targets,
            fallback_classifier=DeterministicStubClassifier(
                page_type="BLOG",
                discovery_status="SUGGESTED",
            ),
            robots_source=_RobotsSource(),
            sitemap_source=_SitemapSource(),
            link_source=_LinksSource(),
            liveness_checker=lambda url: True,
            snapshot_repository=_HistoryRepository(),
            change_repository=_HistoryRepository(),
            run_repository=runs,
        )

        result = service.discover_and_reconcile(
            "competitor-1",
            company_id="company-1",
            run_id="reconcile-1",
        )

        self.assertEqual(result.activated_target_ids, ("target-new",))
        self.assertEqual(result.deactivated_target_ids, ("target-old",))
        self.assertEqual(
            [target["url"] for target in result.active_before],
            ["https://example.com/old"],
        )
        self.assertEqual(
            [target["url"] for target in result.active_after],
            ["https://example.com/new"],
        )
        self.assertEqual(targets.get("target-old")["active"], False)
        self.assertEqual(targets.get("target-old")["discovery_status"], "ACTIVE")
        self.assertEqual(runs.get("reconcile-1")["status"], "SUCCESS")
        self.assertEqual(
            service.latest_successful_run("competitor-1", company_id="company-1")[
                "run_id"
            ],
            "reconcile-1",
        )

    def test_reconciliation_does_not_invoke_monitoring(self):
        competitors = _CompetitorRepository()
        targets = _TargetRepository()
        runs = _RunRepository()
        service = DiscoveryService(
            competitors,
            targets,
            fallback_classifier=DeterministicStubClassifier(
                page_type="BLOG",
                discovery_status="SUGGESTED",
            ),
            robots_source=_RobotsSource(),
            sitemap_source=_SitemapSource(),
            link_source=_LinksSource(),
            liveness_checker=lambda url: True,
            snapshot_repository=_HistoryRepository(),
            change_repository=_HistoryRepository(),
            run_repository=runs,
        )

        result = service.discover_and_reconcile(
            "competitor-1",
            company_id="company-1",
            run_id="reconcile-2",
        )

        self.assertEqual(result.discovered_count, 1)
        self.assertEqual(result.suggested_count, 1)
        self.assertNotIn("snapshot", result.as_dict())


if __name__ == "__main__":
    unittest.main()
