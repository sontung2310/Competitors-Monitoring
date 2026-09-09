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
    "updated_at": "2026-09-08T01:00:00Z",
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
    "updated_at": "2026-09-08T02:00:00Z",
}


class FakeAPIClient:
    def __init__(self) -> None:
        self.manual_error = False
        self.discovery_timeout = False
        self.discovery_run = None
        self.last_run_id = None
        self.discovery_add_candidate = False
        self.reactivated_calls = []
        self.companies = [COMPANY]
        self.competitors = [COMPETITOR]
        self.targets = [dict(TARGET), dict(CANDIDATE)]
        self.changes = [
            {
                "id": "change-simulated",
                "monitoring_target_id": TARGET["id"],
                "change_type": "NEW_BLOG",
                "summary": "NEW_BLOG: a simulated article was added.",
                "narrative_summary": "Lyfe Marketing published a new article in its blog feed.",
                "detected_url": "https://www.lyfemarketing.com/blog/new-article",
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
        self.reactivated_calls.append(kwargs)
        for target in self.targets:
            if target.get("url") == kwargs.get("url"):
                target.update(
                    active=True,
                    discovery_status="ACTIVE",
                    updated_at="2026-09-09T03:00:00Z",
                )
                return target
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
        self.assertContains(response, 'href="https://www.lyfemarketing.com/blog/new-article"')
        self.assertContains(response, "Detected page")
        self.assertContains(response, "Tracked page:")

    def test_discarded_candidate_can_be_reactivated_through_manual_liveness_path(self):
        discarded = {
            **CANDIDATE,
            "id": "candidate-discarded",
            "url": "https://www.lyfemarketing.com/about",
            "discovery_status": "DISCARDED",
        }
        self.client_data.targets.append(discarded)

        response = self.client.get(
            "/competitors/competitor-lyfe/?company_id=company-marketing-eye&status=DISCARDED"
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Activate anyway")
        self.assertContains(response, 'name="status" value="DISCARDED"')

        response = self.client.post(
            "/competitors/competitor-lyfe/candidates/candidate-discarded/activate/",
            {
                "company_id": COMPANY["id"],
                "status": "DISCARDED",
                "url": discarded["url"],
                "page_type": discarded["page_type"],
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client_data.reactivated_calls[0]["competitor_id"], COMPETITOR["id"])
        self.assertEqual(self.client_data.reactivated_calls[0]["url"], discarded["url"])
        self.assertEqual(self.client_data.targets[-1]["discovery_status"], "ACTIVE")

        active_response = self.client.get(response["Location"])
        self.assertContains(active_response, discarded["url"])

    def test_deactivated_history_target_is_shown_in_discarded_review(self):
        deactivated = {
            **TARGET,
            "id": "target-deactivated",
            "url": "https://www.lyfemarketing.com/deactivated-history",
            "active": False,
            "updated_at": "2026-09-09T04:00:00Z",
        }
        discarded_old = {
            **CANDIDATE,
            "id": "candidate-discarded-old",
            "url": "https://www.lyfemarketing.com/discarded-old",
            "discovery_status": "DISCARDED",
            "updated_at": "2026-09-09T01:00:00Z",
        }
        self.client_data.targets.extend((deactivated, discarded_old))

        response = self.client.get(
            "/competitors/competitor-lyfe/?company_id=company-marketing-eye&status=DISCARDED"
        )

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertLess(content.index(deactivated["url"]), content.index(discarded_old["url"]))
        self.assertContains(response, "Activate anyway")

    def test_discarded_reactivation_preserves_backend_liveness_error(self):
        discarded = {
            **CANDIDATE,
            "id": "candidate-dead",
            "url": "https://www.lyfemarketing.com/dead-page",
            "discovery_status": "DISCARDED",
        }
        self.client_data.targets.append(discarded)
        self.client_data.manual_error = True

        response = self.client.post(
            "/competitors/competitor-lyfe/candidates/candidate-dead/activate/",
            {
                "company_id": COMPANY["id"],
                "status": "DISCARDED",
                "url": discarded["url"],
                "page_type": discarded["page_type"],
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertContains(
            response,
            "manual target URL &#x27;https://www.lyfemarketing.com/dead-page&#x27; failed liveness checks after 3 attempts; target was not created",
            status_code=400,
        )
        self.assertContains(response, "Discarded", status_code=400)

    def test_review_tabs_sort_rows_by_updated_at_descending(self):
        self.client_data.targets = [
            {
                **CANDIDATE,
                "id": "suggested-old",
                "url": "https://www.lyfemarketing.com/suggested-old",
                "updated_at": "2026-09-09T01:00:00Z",
            },
            {
                **CANDIDATE,
                "id": "suggested-new",
                "url": "https://www.lyfemarketing.com/suggested-new",
                "updated_at": "2026-09-09T02:00:00Z",
            },
            {
                **CANDIDATE,
                "id": "discarded-old",
                "url": "https://www.lyfemarketing.com/discarded-old",
                "discovery_status": "DISCARDED",
                "updated_at": "2026-09-09T01:00:00Z",
            },
            {
                **CANDIDATE,
                "id": "discarded-new",
                "url": "https://www.lyfemarketing.com/discarded-new",
                "discovery_status": "DISCARDED",
                "updated_at": "2026-09-09T02:00:00Z",
            },
            {
                **TARGET,
                "id": "active-old",
                "url": "https://www.lyfemarketing.com/active-old",
                "updated_at": "2026-09-09T01:00:00Z",
            },
            {
                **TARGET,
                "id": "active-new",
                "url": "https://www.lyfemarketing.com/active-new",
                "updated_at": "2026-09-09T02:00:00Z",
            },
        ]

        for status, newest, oldest in (
            ("SUGGESTED", "suggested-new", "suggested-old"),
            ("ACTIVE", "active-new", "active-old"),
            ("DISCARDED", "discarded-new", "discarded-old"),
        ):
            response = self.client.get(
                f"/competitors/competitor-lyfe/?company_id={COMPANY['id']}&status={status}"
            )
            content = response.content.decode()
            self.assertLess(content.index(newest), content.index(oldest))

    def test_removed_product_link_has_last_known_warning_treatment(self):
        self.client_data.changes.append(
            {
                "id": "change-removed",
                "monitoring_target_id": TARGET["id"],
                "change_type": "PRODUCT_REMOVED",
                "summary": "PRODUCT_REMOVED: Gone (10.00) at /product/gone",
                "narrative_summary": None,
                "detected_url": "https://www.lyfemarketing.com/product/gone",
                "detected_at": "2026-09-08T02:02:03Z",
                "status": "NEW",
            }
        )

        response = self.client.get("/changes/?company_id=company-marketing-eye")

        self.assertContains(response, "Last known URL — may no longer be available")
        self.assertContains(response, 'href="https://www.lyfemarketing.com/product/gone"')
        self.assertContains(response, "change-detected-link-removed")

    def test_identical_detected_and_tracked_urls_render_one_tracked_link(self):
        self.client_data.changes[0]["detected_url"] = TARGET["url"]
        response = self.client.get("/changes/?company_id=company-marketing-eye")

        self.assertContains(response, "Tracked page:")
        self.assertNotContains(response, "Detected page")
        self.assertContains(response, 'href="https://www.lyfemarketing.com/blog"')
        self.assertEqual(response.content.decode().count("Tracked page:"), 1)

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
