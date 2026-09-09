from __future__ import annotations

import unittest
from datetime import datetime, timezone

from backend.flask.app import create_app
from backend.flask.change_detection.service import ChangeService
from backend.flask.errors import NotFoundError


NOW = datetime(2026, 9, 8, 1, 2, 3, tzinfo=timezone.utc)


def _competitor():
    return {
        "id": "c" * 24,
        "name": "Example",
        "website_url": "https://example.com",
        "active": True,
        "created_at": NOW,
        "updated_at": NOW,
    }


def _candidate():
    return {
        "id": "a" * 24,
        "competitor_id": "c" * 24,
        "raw_url": "https://example.com/blog/post",
        "url": "https://example.com/blog",
        "page_type": "BLOG",
        "discovery_status": "SUGGESTED",
        "classification_method": "RULE",
        "active": False,
        "check_interval_minutes": 180,
        "created_at": NOW,
        "updated_at": NOW,
    }


class _CompetitorService:
    def __init__(self):
        self.item = _competitor()

    def list_competitors(self, *, active=None):
        return [self.item] if active is None or active == self.item["active"] else []

    def get_competitor(self, competitor_id):
        if competitor_id != self.item["id"]:
            raise NotFoundError("competitor was not found")
        return self.item

    def create_competitor(self, **fields):
        self.item = {**self.item, **fields, "id": "d" * 24}
        return self.item

    def update_competitor(self, competitor_id, updates):
        self.get_competitor(competitor_id)
        self.item.update(updates)
        return self.item

    def delete_competitor(self, competitor_id):
        self.get_competitor(competitor_id)
        self.item = {**self.item, "active": False}


class _DiscoveryService:
    def __init__(self):
        self.item = _candidate()
        self.removed = False
        self.runs = {}

    def list_candidates(self, competitor_id, status="SUGGESTED"):
        if status == "ALL" or self.item["discovery_status"] == status:
            return [] if self.removed else [self.item]
        return []

    def add_candidate(self, competitor_id, url):
        return self.item

    def activate_candidate(self, candidate_id):
        self.item.update(active=True, discovery_status="ACTIVE")
        return self.item

    def edit_candidate(self, candidate_id, new_url):
        self.item.update(raw_url=new_url, url=new_url)
        return self.item

    def discard_candidate(self, candidate_id):
        self.item.update(active=False, discovery_status="DISCARDED")
        return self.item

    def remove_candidate(self, candidate_id):
        self.removed = True

    def discover_website(self, competitor_id, **kwargs):
        run_id = kwargs.get("run_id")
        if run_id:
            self.runs[run_id] = {
                "run_id": run_id,
                "competitor_id": competitor_id,
                "status": "SUCCESS",
                "candidate_count": 1,
            }
        return [self.item]

    def get_discovery_run(self, run_id, **kwargs):
        run = self.runs.get(run_id)
        if run is None:
            raise NotFoundError("discovery run was not found")
        return run


class _TargetService:
    def __init__(self, discovery):
        self.discovery = discovery
        self.target = None

    def list_targets(self, *, competitor_id=None):
        return [self.target] if self.target is not None else []

    def get_target(self, target_id):
        if self.target is not None and self.target["id"] == target_id:
            return self.target
        return None

    def add_manual_target(self, competitor_id, url, page_type=None):
        self.target = {
            "id": "b" * 24,
            "competitor_id": competitor_id,
            "raw_url": url,
            "url": url,
            "page_type": page_type or "OTHER",
            "discovery_status": "ACTIVE",
            "classification_method": "MANUAL",
            "active": True,
            "check_interval_minutes": 1440,
            "last_checked_at": None,
            "last_changed_at": None,
            "created_at": NOW,
            "updated_at": NOW,
        }
        return self.target

    def update_target(self, target_id, updates):
        if self.target is None or self.target["id"] != target_id:
            raise NotFoundError("monitoring target was not found")
        self.target.update(updates)
        return self.target

    def remove_target(self, target_id):
        if self.target is None or self.target["id"] != target_id:
            raise NotFoundError("monitoring target was not found")
        self.target = None


class _ChangeService:
    def __init__(self):
        self.item = {
            "id": "e" * 24,
            "monitoring_target_id": "b" * 24,
            "change_type": "PAGE_UPDATE",
            "summary": "PAGE_UPDATE: one paragraph changed.",
            "detected_at": NOW,
            "status": "NEW",
            "previous_snapshot_id": "f" * 24,
            "current_snapshot_id": "1" * 24,
        }

    def list_changes(self, **kwargs):
        return [self.item]

    def get_change(self, change_id):
        if change_id != self.item["id"]:
            return None
        return self.item


def _services():
    competitors = _CompetitorService()
    discovery = _DiscoveryService()
    targets = _TargetService(discovery)
    return {
        "competitors": competitors,
        "discovery": discovery,
        "targets": targets,
        "changes": _ChangeService(),
    }


class HTTPAPITests(unittest.TestCase):
    def setUp(self):
        self.app = create_app(services=_services(), testing=True)
        self.client = self.app.test_client()

    def test_competitor_crud_and_nested_error_shape(self):
        response = self.client.get("/api/competitors")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json[0]["id"], "c" * 24)
        self.assertEqual(response.json[0]["created_at"], "2026-09-08T01:02:03Z")

        response = self.client.post(
            "/api/competitors",
            json={"name": "New", "website_url": "https://new.example"},
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json["name"], "New")

        response = self.client.patch(
            "/api/competitors/" + "d" * 24,
            json={"active": False},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json["active"])

        response = self.client.post("/api/competitors", json={"name": "missing"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json, {
            "error": {"code": "validation_error", "message": "website_url must be a non-empty string"}
        })

        response = self.client.get("/api/competitors/not-a-real-id")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json["error"]["code"], "not_found")

    def test_candidate_review_and_monitoring_target_routes(self):
        competitor_id = "c" * 24
        response = self.client.get(f"/api/competitors/{competitor_id}/candidates")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json[0]["discovery_status"], "SUGGESTED")

        response = self.client.post(
            f"/api/competitors/{competitor_id}/candidates",
            json={"url": "https://example.com/about"},
        )
        self.assertEqual(response.status_code, 201)

        candidate_id = "a" * 24
        response = self.client.post(f"/api/candidates/{candidate_id}/activate")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json["active"])

        response = self.client.patch(
            f"/api/candidates/{candidate_id}",
            json={"url": "https://example.com/blog"},
        )
        self.assertEqual(response.status_code, 200)

        response = self.client.post(
            "/api/monitoring-targets",
            json={"competitor_id": competitor_id, "url": "https://example.com/pricing"},
        )
        self.assertEqual(response.status_code, 201)
        target_id = response.json["id"]
        self.assertEqual(response.json["discovery_status"], "ACTIVE")

        response = self.client.patch(
            f"/api/monitoring-targets/{target_id}",
            json={"active": False, "check_interval_minutes": 360},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json["active"])
        self.assertEqual(response.json["check_interval_minutes"], 360)

        response = self.client.delete(f"/api/candidates/{candidate_id}")
        self.assertEqual(response.status_code, 204)
        response = self.client.delete(f"/api/monitoring-targets/{target_id}")
        self.assertEqual(response.status_code, 204)

    def test_discard_preserves_candidate_for_review(self):
        client = create_app(services=_services(), testing=True).test_client()
        response = client.post("/api/candidates/" + "a" * 24 + "/discard")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["discovery_status"], "DISCARDED")
        self.assertFalse(response.json["active"])

    def test_changes_feed_and_full_record(self):
        response = self.client.get("/api/changes?limit=10")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json[0]["change_type"], "PAGE_UPDATE")
        self.assertEqual(response.json[0]["detected_at"], "2026-09-08T01:02:03Z")

        response = self.client.get("/api/changes/" + "e" * 24)
        self.assertEqual(response.status_code, 200)
        self.assertIn("previous_snapshot_id", response.json)

        response = self.client.get("/api/changes/" + "0" * 24)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json["error"]["code"], "not_found")

        response = self.client.get("/api/changes?limit=not-an-int")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json["error"]["code"], "validation_error")

    def test_discovery_trigger_and_run_status_route(self):
        competitor_id = "c" * 24
        response = self.client.post(
            f"/api/competitors/{competitor_id}/discover?run_id=run-1"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["competitor_id"], competitor_id)

        response = self.client.get("/api/discovery-runs/run-1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["status"], "SUCCESS")

        response = self.client.get("/api/discovery-runs/missing")
        self.assertEqual(response.status_code, 404)

    def test_unexpected_service_error_is_safe_and_consistent(self):
        services = _services()

        class BrokenCompetitorService(_CompetitorService):
            def list_competitors(self, *, active=None):
                raise RuntimeError("database details must not be exposed")

        services["competitors"] = BrokenCompetitorService()
        client = create_app(services=services, testing=True).test_client()
        response = client.get("/api/competitors")
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json, {
            "error": {
                "code": "internal_error",
                "message": "an unexpected server error occurred",
            }
        })


class ChangeFeedServiceTests(unittest.TestCase):
    def test_competitor_scoping_is_resolved_before_repository_query(self):
        class TargetReader:
            def get(self, target_id, *, competitor_id=None):
                return {"id": target_id}

            def list_for_competitor(self, competitor_id):
                return [{"id": "target-1"}, {"id": "target-2"}]

        class ChangeReader:
            def list(self, **kwargs):
                self.kwargs = kwargs
                return []

            def get(self, change_id):
                return None

        repository = ChangeReader()
        service = ChangeService(repository, TargetReader())
        self.assertEqual(service.list_changes(competitor_id="competitor-1"), [])
        self.assertEqual(repository.kwargs["monitoring_target_ids"], ["target-1", "target-2"])


if __name__ == "__main__":
    unittest.main()
