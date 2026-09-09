"""Small JSON client for the frozen Flask API contract.

Views use this module for every backend read and write. It deliberately has no
knowledge of Django templates or persistence, so the frontend cannot bypass
the Flask service/repository boundary.
"""

from __future__ import annotations

import json
import socket
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen


@dataclass
class APIClientError(RuntimeError):
    """An API failure retaining the backend's exact error message."""

    message: str
    status_code: int | None = None
    code: str = "api_error"

    def __str__(self) -> str:
        return self.message


class APIClient:
    """HTTP client for company-scoped CompetitorScope operations."""

    def __init__(self, base_url: str, *, timeout: float = 60.0) -> None:
        self.base_url = base_url.rstrip("/") + "/"
        self.timeout = timeout

    def get_companies(self) -> list[dict[str, Any]]:
        return self._request("GET", "companies")

    def list_competitors(self, company_id: str) -> list[dict[str, Any]]:
        return self._request("GET", "competitors", params={"company_id": company_id, "active": "true"})

    def get_competitor(self, competitor_id: str, company_id: str) -> dict[str, Any]:
        return self._request("GET", f"competitors/{competitor_id}", params={"company_id": company_id})

    def create_competitor(
        self,
        *,
        company_id: str,
        name: str,
        website_url: str,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "competitors",
            body={"company_id": company_id, "name": name, "website_url": website_url},
        )

    def update_competitor(
        self,
        competitor_id: str,
        company_id: str,
        *,
        name: str,
        website_url: str,
    ) -> dict[str, Any]:
        return self._request(
            "PATCH",
            f"competitors/{competitor_id}",
            params={"company_id": company_id},
            body={"name": name, "website_url": website_url},
        )

    def delete_competitor(self, competitor_id: str, company_id: str) -> None:
        self._request("DELETE", f"competitors/{competitor_id}", params={"company_id": company_id})

    def list_candidates(
        self,
        competitor_id: str,
        company_id: str,
        *,
        status: str = "ALL",
    ) -> list[dict[str, Any]]:
        return self._request(
            "GET",
            f"competitors/{competitor_id}/candidates",
            params={"company_id": company_id, "status": status},
        )

    def activate_candidate(self, candidate_id: str, company_id: str) -> dict[str, Any]:
        return self._request("POST", f"candidates/{candidate_id}/activate", params={"company_id": company_id})

    def discard_candidate(self, candidate_id: str, company_id: str) -> dict[str, Any]:
        return self._request("POST", f"candidates/{candidate_id}/discard", params={"company_id": company_id})

    def edit_candidate(self, candidate_id: str, company_id: str, url: str) -> dict[str, Any]:
        return self._request(
            "PATCH",
            f"candidates/{candidate_id}",
            params={"company_id": company_id},
            body={"url": url},
        )

    def delete_candidate(self, candidate_id: str, company_id: str) -> None:
        self._request("DELETE", f"candidates/{candidate_id}", params={"company_id": company_id})

    def discover(
        self,
        competitor_id: str,
        company_id: str,
        *,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"company_id": company_id}
        if run_id:
            params["run_id"] = run_id
        return self._request("POST", f"competitors/{competitor_id}/discover", params=params)

    def get_discovery_run(self, run_id: str, company_id: str) -> dict[str, Any]:
        return self._request(
            "GET",
            f"discovery-runs/{run_id}",
            params={"company_id": company_id},
        )

    def list_targets(self, company_id: str, competitor_id: str) -> list[dict[str, Any]]:
        return self._request(
            "GET",
            "monitoring-targets",
            params={"company_id": company_id, "competitor_id": competitor_id},
        )

    def add_manual_target(
        self,
        *,
        company_id: str,
        competitor_id: str,
        url: str,
        page_type: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "company_id": company_id,
            "competitor_id": competitor_id,
            "url": url,
        }
        if page_type:
            body["page_type"] = page_type
        return self._request("POST", "monitoring-targets", body=body)

    def update_target(
        self,
        target_id: str,
        company_id: str,
        *,
        active: bool | None = None,
        check_interval_minutes: int | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if active is not None:
            body["active"] = active
        if check_interval_minutes is not None:
            body["check_interval_minutes"] = check_interval_minutes
        return self._request(
            "PATCH",
            f"monitoring-targets/{target_id}",
            params={"company_id": company_id},
            body=body,
        )

    def delete_target(self, target_id: str, company_id: str) -> None:
        self._request("DELETE", f"monitoring-targets/{target_id}", params={"company_id": company_id})

    def simulate(
        self,
        target_id: str,
        company_id: str,
        *,
        mutation_type: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"company_id": company_id}
        if mutation_type:
            body["mutation_type"] = mutation_type
        return self._request("POST", f"monitoring-targets/{target_id}/simulate", body=body)

    def list_changes(
        self,
        company_id: str,
        *,
        competitor_id: str | None = None,
        target_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"company_id": company_id, "limit": limit}
        if competitor_id:
            params["competitor_id"] = competitor_id
        if target_id:
            params["target_id"] = target_id
        return self._request("GET", "changes", params=params)

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        body: Mapping[str, Any] | None = None,
    ) -> Any:
        url = urljoin(self.base_url, path.lstrip("/"))
        if params:
            url = f"{url}?{urlencode({key: value for key, value in params.items() if value is not None})}"
        encoded_body = None
        headers = {"Accept": "application/json"}
        if body is not None:
            encoded_body = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(url, data=encoded_body, headers=headers, method=method)

        try:
            with urlopen(request, timeout=self.timeout) as response:
                status_code = int(response.getcode())
                raw_body = response.read()
        except HTTPError as exc:
            status_code = int(exc.code)
            raw_body = exc.read()
            payload = _decode_json(raw_body)
            raise _error_from_payload(payload, status_code) from exc
        except (URLError, TimeoutError, OSError) as exc:
            reason = getattr(exc, "reason", None)
            timed_out = (
                isinstance(exc, (TimeoutError, socket.timeout))
                or isinstance(reason, (TimeoutError, socket.timeout))
                or "timed out" in str(exc).lower()
            )
            raise APIClientError(
                f"the monitoring API could not be reached: {exc}",
                code="backend_timeout" if timed_out else "backend_unavailable",
            ) from exc

        if not 200 <= status_code < 300:
            raise _error_from_payload(_decode_json(raw_body), status_code)
        if status_code == 204 or not raw_body:
            return None
        try:
            return json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise APIClientError(
                "the monitoring API returned an invalid JSON response",
                status_code=status_code,
                code="invalid_response",
            ) from exc


def _decode_json(raw_body: bytes) -> Any:
    try:
        return json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def _error_from_payload(payload: Any, status_code: int) -> APIClientError:
    error = payload.get("error") if isinstance(payload, Mapping) else None
    if isinstance(error, Mapping):
        message = error.get("message")
        code = error.get("code")
        if isinstance(message, str) and message.strip():
            return APIClientError(message, status_code=status_code, code=str(code or "api_error"))
    return APIClientError(
        f"the monitoring API returned HTTP {status_code}",
        status_code=status_code,
        code="api_error",
    )
