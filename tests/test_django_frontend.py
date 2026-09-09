from __future__ import annotations

import os
import sys
from pathlib import Path


FRONTEND_DIR = Path(__file__).resolve().parents[1] / "frontend" / "django"
if str(FRONTEND_DIR) not in sys.path:
    sys.path.insert(0, str(FRONTEND_DIR))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from django.test import SimpleTestCase

from monitoring import views
from monitoring.api_client import APIClientError


COMPANY = {
    "id": "company-marketing-eye",
    "name": "Marketing Eye",
    "website_url": "https://marketingeye.com.au",
}
COMPETITOR = {
    "id": "competitor-lyfe",
    "company_id": COMPANY["id"],
    "name": "Lyfe Marketing",
    "website_url": "https://www.lyfemarketing.com/",
    "active": True,
}
TARGET = {
    "id": "target-blog",
    "competitor_id": COMPETITOR["id"],
    "url": "https://www.lyfemarketing.com/blog",
    "page_type": "BLOG",
    "discovery_status": "ACTIVE",
    "classification_method": "RULE",
    "active": True,
    "check_interval_minutes": 720,
}
CANDIDATE = {
    "id": "candidate-pricing",
    "competitor_id": COMPETITOR["id"],
    "url": "https://www.lyfemarketing.com/pricing",
    "page_type": "PRICING",
    "discovery_status": "SUGGESTED",
    "classification_method": "RULE",
    "active": False,
    "check_interval_minutes": 1440,
}


class FakeAPIClient:
    def __init__(self) -> None:
        self.manual_error = False
        self.discovery_timeout = False
        self.discovery_run = None
        self.last_run_id = None
        self.discovery_add_candidate = False
        self.companies = [COMPANY]
        self.competitors = [COMPETITOR]
        self.targets = [TARGET, CANDIDATE]
        self.changes = [
            {
                "id": "change-simulated",
                "monitoring_target_id": TARGET["id"],
                "change_type": "NEW_BLOG",
                "summary": "NEW_BLOG: a simulated article was added.",
                "narrative_summary": "Lyfe Marketing published a new article in its blog feed.",
                "detected_at": "2026-09-08T01:02:03Z",
                "status": "NEW",
                "is_simulated": True,
            }
        ]

    def get_companies(self):
        return self.companies

    def list_competitors(self, company_id):
        assert company_id == COMPANY["id"]
        return self.competitors

    def get_competitor(self, competitor_id, company_id):
        assert competitor_id == COMPETITOR["id"]
        assert company_id == COMPANY["id"]
        return COMPETITOR

    def list_candidates(self, competitor_id, company_id, *, status="ALL"):
        assert status == "ALL"
        return [
            candidate
            for candidate in self.targets
            if candidate.get("discovery_status") in {"SUGGESTED", "DISCARDED"}
        ]

    def list_targets(self, company_id, competitor_id):
        assert company_id == COMPANY["id"]
        assert competitor_id == COMPETITOR["id"]
        return self.targets

    def list_changes(self, company_id, *, competitor_id=None, target_id=None, limit=50):
        assert company_id == COMPANY["id"]
        return self.changes

    def add_manual_target(self, **kwargs):
        if self.manual_error:
            raise APIClientError(
                "manual target URL 'https://www.lyfemarketing.com/dead-page' failed liveness checks after 3 attempts; target was not created",
                status_code=400,
                code="validation_error",
            )
        return TARGET

    def discover(self, competitor_id, company_id, *, run_id=None):
        assert competitor_id == COMPETITOR["id"]
        assert company_id == COMPANY["id"]
        self.last_run_id = run_id
        self.discovery_run = {
            "run_id": run_id,
            "competitor_id": competitor_id,
            "company_id": company_id,
            "status": "RUNNING" if self.discovery_timeout else "SUCCESS",
            "candidate_count": 0 if self.discovery_timeout else 1,
            "error_message": None,
        }
        if self.discovery_timeout:
            raise APIClientError(
                "the monitoring API could not be reached: timed out",
                code="backend_timeout",
            )
        if self.discovery_add_candidate:
            new_candidate = {**CANDIDATE, "id": "candidate-about", "url": "https://www.lyfemarketing.com/about"}
            self.targets.append(new_candidate)
        return {"candidates": [CANDIDATE], "summary": None}

    def get_discovery_run(self, run_id, company_id):
        assert run_id == self.last_run_id
        assert company_id == COMPANY["id"]
        return self.discovery_run


class DjangoFrontendViewTests(SimpleTestCase):
    def setUp(self):
        self.client_data = FakeAPIClient()
        self.get_client = views.get_api_client
        views.get_api_client = lambda: self.client_data

    def tearDown(self):
        views.get_api_client = self.get_client

    def test_dashboard_renders_live_company_and_competitor_data(self):
        response = self.client.get("/?company_id=company-marketing-eye")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Marketing Eye")
        self.assertContains(response, "Lyfe Marketing")
        self.assertContains(response, "https://www.lyfemarketing.com/")
        self.assertNotContains(response, "JD Sports AU")

    def test_detail_renders_candidate_and_simulated_marker_from_api_flag(self):
        response = self.client.get("/competitors/competitor-lyfe/?company_id=company-marketing-eye")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "https://www.lyfemarketing.com/pricing")
        self.assertContains(response, "Activate")
        self.assertNotContains(response, "The Athletes Foot")

        response = self.client.get("/changes/?company_id=company-marketing-eye")
        self.assertContains(response, "🧪 SIMULATED")
        self.assertContains(response, "Lyfe Marketing published a new article in its blog feed.")
        self.assertContains(response, "NEW_BLOG: a simulated article was added.")
        self.assertContains(response, "change-narrative")
        self.assertContains(response, "change-mechanical")

    def test_manual_target_error_uses_exact_backend_message(self):
        self.client_data.manual_error = True
        response = self.client.post(
            "/competitors/competitor-lyfe/targets/add/",
            {
                "company_id": COMPANY["id"],
                "url": "https://www.lyfemarketing.com/dead-page",
                "page_type": "",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertContains(
            response,
            "manual target URL &#x27;https://www.lyfemarketing.com/dead-page&#x27; failed liveness checks after 3 attempts; target was not created",
            status_code=400,
        )

    def test_discovery_timeout_uses_friendly_polling_state(self):
        self.client_data.discovery_timeout = True
        response = self.client.post(
            "/competitors/competitor-lyfe/discover/",
            {"company_id": COMPANY["id"]},
        )

        self.assertEqual(response.status_code, 202)
        self.assertContains(response, "Discovery is still working", status_code=202)
        self.assertContains(response, "This can take a few minutes for larger sites.", status_code=202)
        self.assertContains(response, "data-auto-refresh", status_code=202)
        self.assertContains(response, "discovery_pending=1", status_code=202)
        self.assertContains(response, "discovery_run_id=", status_code=202)
        self.assertNotContains(response, "the monitoring API could not be reached: timed out", status_code=202)

    def test_discovery_poll_resolves_zero_new_candidates_from_success_status(self):
        self.client_data.discovery_timeout = True
        pending = self.client.post(
            "/competitors/competitor-lyfe/discover/",
            {"company_id": COMPANY["id"]},
        )
        self.assertEqual(pending.status_code, 202)
        poll_url = views._detail_url(
            COMPETITOR["id"],
            COMPANY["id"],
            discovery_pending=True,
            discovery_run_id=self.client_data.last_run_id,
        )

        self.client_data.discovery_run["status"] = "SUCCESS"
        self.client_data.discovery_run["candidate_count"] = 0
        resolved = self.client.get(poll_url)

        self.assertEqual(resolved.status_code, 200)
        self.assertContains(resolved, "Discovery finished")
        self.assertNotContains(resolved, "Discovery is still working")
        self.assertContains(resolved, "candidate-pricing")

    def test_discovery_success_path_still_renders_new_candidate_results(self):
        self.client_data.discovery_add_candidate = True
        response = self.client.post(
            "/competitors/competitor-lyfe/discover/",
            {"company_id": COMPANY["id"]},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Discovery complete")
        self.assertContains(response, "https://www.lyfemarketing.com/about")
