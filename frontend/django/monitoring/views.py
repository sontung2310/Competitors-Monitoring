"""Django presentation views for the company-scoped monitoring PoC."""

from __future__ import annotations

from typing import Any, Iterable, Mapping
from urllib.parse import urlencode
from uuid import uuid4

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse

from .api_client import APIClient, APIClientError


def get_api_client() -> APIClient:
    """Build the request-scoped client used by every view."""

    return APIClient(
        settings.FLASK_API_BASE_URL,
        timeout=settings.FLASK_API_TIMEOUT_SECONDS,
    )


def dashboard(request: HttpRequest) -> HttpResponse:
    client = get_api_client()
    try:
        companies, selected_company = _load_company_context(request, client)
        competitors = client.list_competitors(selected_company["id"])
        company_changes = client.list_changes(selected_company["id"], limit=100)
        target_lookup: dict[str, dict[str, Any]] = {}
        cards: list[dict[str, Any]] = []
        for competitor in competitors:
            targets = client.list_targets(selected_company["id"], competitor["id"])
            competitor_changes = client.list_changes(
                selected_company["id"],
                competitor_id=competitor["id"],
                limit=100,
            )
            for target in targets:
                target_lookup[str(target["id"])] = target
            cards.append(
                {
                    "competitor": competitor,
                    "active_targets": sum(
                        target.get("active") is True
                        and target.get("discovery_status") == "ACTIVE"
                        for target in targets
                    ),
                    "recent_changes": len(competitor_changes),
                }
            )
        context = _shell_context(
            companies=companies,
            selected_company=selected_company,
            competitors=competitors,
            nav_changes_count=len(company_changes),
            title=selected_company["name"],
            meta="Competitive monitoring overview",
        )
        context.update(
            {
                "cards": cards,
                "recent_changes": _decorate_changes(company_changes, target_lookup),
                "active_page_count": sum(card["active_targets"] for card in cards),
                "recent_changes_count": len(company_changes),
                "stats": [
                    {"label": "Active pages", "value": sum(card["active_targets"] for card in cards), "icon": "◎", "tone": "neutral"},
                    {"label": "Recent changes", "value": len(company_changes), "icon": "◌", "tone": "favorable"},
                    {"label": "Competitors", "value": len(cards), "icon": "◈", "tone": "neutral"},
                ],
            }
        )
        return render(request, "pages/dashboard.html", context)
    except APIClientError as exc:
        return _error_page(request, str(exc), status_code=502)


def competitor_detail(request: HttpRequest, competitor_id: str) -> HttpResponse:
    client = get_api_client()
    try:
        companies, selected_company = _load_company_context(request, client)
        context = _detail_context(
            request,
            client,
            companies,
            selected_company,
            competitor_id,
        )
        return render(request, "pages/competitor_detail.html", context)
    except APIClientError as exc:
        return _error_page(request, str(exc), status_code=exc.status_code or 502)


def run_discovery(request: HttpRequest, competitor_id: str) -> HttpResponse:
    if request.method != "POST":
        return redirect(_detail_url(competitor_id, request.GET.get("company_id")))
    client = get_api_client()
    run_id = uuid4().hex
    try:
        companies, selected_company = _load_company_context(request, client)
        discovery_result = client.discover(
            competitor_id,
            selected_company["id"],
            run_id=run_id,
        )
        context = _detail_context(
            request,
            client,
            companies,
            selected_company,
            competitor_id,
        )
        context["discovery_result"] = discovery_result
        return render(request, "pages/competitor_detail.html", context)
    except APIClientError as exc:
        if exc.code == "backend_timeout":
            timeout_message = (
                "Discovery is still working — larger sites can take a few minutes. "
                "This page will refresh automatically."
            )
            company_id = request.POST.get("company_id") or request.GET.get("company_id")
            poll_url = _detail_url(
                competitor_id,
                company_id,
                discovery_pending=True,
                discovery_run_id=run_id,
            )
            return _detail_error_response(
                request,
                client,
                competitor_id,
                timeout_message,
                status_code=202,
                extra_context={
                    "page_error": None,
                    "discovery_pending": True,
                    "discovery_complete": False,
                    "discovery_poll_url": poll_url,
                },
            )
        return _detail_error_response(
            request,
            client,
            competitor_id,
            str(exc),
            status_code=exc.status_code or 502,
        )


def activate_candidate(request: HttpRequest, competitor_id: str, candidate_id: str) -> HttpResponse:
    if request.method == "POST":
        client = get_api_client()
        try:
            company_id = _company_id_from_request(request)
            if request.POST.get("status", "SUGGESTED").upper() == "DISCARDED":
                client.add_manual_target(
                    company_id=company_id,
                    competitor_id=competitor_id,
                    url=request.POST.get("url", "").strip(),
                    page_type=request.POST.get("page_type", "").strip().upper() or None,
                )
            else:
                client.activate_candidate(candidate_id, company_id)
            return redirect(_detail_url(competitor_id, company_id, status="ACTIVE"))
        except APIClientError as exc:
            return _detail_error_response(request, client, competitor_id, str(exc), exc.status_code or 502)
    return redirect(_detail_url(competitor_id, request.GET.get("company_id")))


def discard_candidate(request: HttpRequest, competitor_id: str, candidate_id: str) -> HttpResponse:
    if request.method == "POST":
        client = get_api_client()
        try:
            company_id = _company_id_from_request(request)
            client.discard_candidate(candidate_id, company_id)
            return redirect(_detail_url(competitor_id, company_id, status="DISCARDED"))
        except APIClientError as exc:
            return _detail_error_response(request, client, competitor_id, str(exc), exc.status_code or 502)
    return redirect(_detail_url(competitor_id, request.GET.get("company_id")))


def edit_candidate(request: HttpRequest, competitor_id: str, candidate_id: str) -> HttpResponse:
    if request.method == "POST":
        client = get_api_client()
        try:
            company_id = _company_id_from_request(request)
            client.edit_candidate(candidate_id, company_id, request.POST.get("url", "").strip())
            return redirect(_detail_url(competitor_id, company_id, status=request.POST.get("status", "SUGGESTED")))
        except APIClientError as exc:
            return _detail_error_response(request, client, competitor_id, str(exc), exc.status_code or 502)
    return redirect(_detail_url(competitor_id, request.GET.get("company_id")))


def delete_candidate(request: HttpRequest, competitor_id: str, candidate_id: str) -> HttpResponse:
    if request.method == "POST":
        client = get_api_client()
        try:
            company_id = _company_id_from_request(request)
            client.delete_candidate(candidate_id, company_id)
            return redirect(_detail_url(competitor_id, company_id, status="DISCARDED"))
        except APIClientError as exc:
            return _detail_error_response(request, client, competitor_id, str(exc), exc.status_code or 502)
    return redirect(_detail_url(competitor_id, request.GET.get("company_id")))


def add_manual_target(request: HttpRequest, competitor_id: str) -> HttpResponse:
    client = get_api_client()
    if request.method != "POST":
        return redirect(_detail_url(competitor_id, request.GET.get("company_id")))
    try:
        company_id = _company_id_from_request(request)
        client.add_manual_target(
            company_id=company_id,
            competitor_id=competitor_id,
            url=request.POST.get("url", "").strip(),
            page_type=request.POST.get("page_type", "").strip().upper() or None,
        )
        return redirect(_detail_url(competitor_id, company_id, status="ACTIVE"))
    except APIClientError as exc:
        return _detail_error_response(
            request,
            client,
            competitor_id,
            str(exc),
            status_code=exc.status_code or 502,
            extra_context={
                "manual_url": request.POST.get("url", ""),
                "manual_page_type": request.POST.get("page_type", ""),
                "manual_error": str(exc),
            },
        )


def deactivate_target(request: HttpRequest, competitor_id: str, target_id: str) -> HttpResponse:
    if request.method == "POST":
        client = get_api_client()
        try:
            company_id = _company_id_from_request(request)
            client.update_target(target_id, company_id, active=False)
            return redirect(_detail_url(competitor_id, company_id, status="ACTIVE"))
        except APIClientError as exc:
            return _detail_error_response(request, client, competitor_id, str(exc), exc.status_code or 502)
    return redirect(_detail_url(competitor_id, request.GET.get("company_id")))


def delete_target(request: HttpRequest, competitor_id: str, target_id: str) -> HttpResponse:
    if request.method == "POST":
        client = get_api_client()
        try:
            company_id = _company_id_from_request(request)
            client.delete_target(target_id, company_id)
            return redirect(_detail_url(competitor_id, company_id, status="ACTIVE"))
        except APIClientError as exc:
            return _detail_error_response(request, client, competitor_id, str(exc), exc.status_code or 502)
    return redirect(_detail_url(competitor_id, request.GET.get("company_id")))


def simulate_target(request: HttpRequest, competitor_id: str, target_id: str) -> HttpResponse:
    if request.method != "POST":
        return redirect(_detail_url(competitor_id, request.GET.get("company_id"), status="ACTIVE"))
    client = get_api_client()
    try:
        companies, selected_company = _load_company_context(request, client)
        competitor = client.get_competitor(competitor_id, selected_company["id"])
        targets = client.list_targets(selected_company["id"], competitor_id)
        target = next((item for item in targets if str(item.get("id")) == str(target_id)), None)
        if target is None:
            raise APIClientError(f"monitoring target {target_id!r} was not found", status_code=404, code="not_found")
        mutation_type = request.POST.get("mutation_type", "").strip().upper() or None
        result = client.simulate(target_id, selected_company["id"], mutation_type=mutation_type)
        company_changes = client.list_changes(selected_company["id"], limit=100)
        context = _shell_context(
            companies=companies,
            selected_company=selected_company,
            competitors=[competitor],
            nav_changes_count=len(company_changes),
            title="Simulate a Change",
            breadcrumb=f"{competitor['name']} / Tracked pages",
            meta="Generated by the simulation tool — not a real detected change",
        )
        context.update(
            {
                "competitor": competitor,
                "target": target,
                "simulation_result": result,
                "result_changes": result.get("changes", []),
            }
        )
        return render(request, "pages/simulate_result.html", context)
    except APIClientError as exc:
        return _error_page(request, str(exc), status_code=exc.status_code or 502)


def changes_feed(request: HttpRequest) -> HttpResponse:
    client = get_api_client()
    try:
        companies, selected_company = _load_company_context(request, client)
        competitors = client.list_competitors(selected_company["id"])
        company_changes = client.list_changes(selected_company["id"], limit=100)
        target_lookup: dict[str, dict[str, Any]] = {}
        for competitor in competitors:
            for target in client.list_targets(selected_company["id"], competitor["id"]):
                target_lookup[str(target["id"])] = target
        scope = request.GET.get("scope", "ALL").upper()
        if scope not in {"ALL", "REAL", "SIMULATED"}:
            scope = "ALL"
        visible_changes = [
            change
            for change in company_changes
            if scope == "ALL"
            or (scope == "SIMULATED" and change.get("is_simulated") is True)
            or (scope == "REAL" and change.get("is_simulated") is not True)
        ]
        context = _shell_context(
            companies=companies,
            selected_company=selected_company,
            competitors=competitors,
            nav_changes_count=len(company_changes),
            title="Changes",
            meta="Chronological feed for the selected company",
        )
        context.update(
            {
                "changes": _decorate_changes(visible_changes, target_lookup),
                "all_change_count": len(company_changes),
                "real_change_count": sum(change.get("is_simulated") is not True for change in company_changes),
                "simulated_change_count": sum(change.get("is_simulated") is True for change in company_changes),
                "scope": scope,
            }
        )
        return render(request, "pages/changes.html", context)
    except APIClientError as exc:
        return _error_page(request, str(exc), status_code=exc.status_code or 502)


def create_competitor(request: HttpRequest) -> HttpResponse:
    if request.method != "POST":
        return redirect(_dashboard_url(request.GET.get("company_id")))
    client = get_api_client()
    try:
        company_id = _company_id_from_request(request)
        client.create_competitor(
            company_id=company_id,
            name=request.POST.get("name", "").strip(),
            website_url=request.POST.get("website_url", "").strip(),
        )
        return redirect(_dashboard_url(company_id))
    except APIClientError as exc:
        return _error_page(request, str(exc), status_code=exc.status_code or 502)


def update_competitor(request: HttpRequest, competitor_id: str) -> HttpResponse:
    if request.method != "POST":
        return redirect(_detail_url(competitor_id, request.GET.get("company_id")))
    client = get_api_client()
    try:
        company_id = _company_id_from_request(request)
        client.update_competitor(
            competitor_id,
            company_id,
            name=request.POST.get("name", "").strip(),
            website_url=request.POST.get("website_url", "").strip(),
        )
        return redirect(_detail_url(competitor_id, company_id))
    except APIClientError as exc:
        return _detail_error_response(request, client, competitor_id, str(exc), exc.status_code or 502)


def delete_competitor(request: HttpRequest, competitor_id: str) -> HttpResponse:
    if request.method == "POST":
        client = get_api_client()
        try:
            company_id = _company_id_from_request(request)
            client.delete_competitor(competitor_id, company_id)
            return redirect(_dashboard_url(company_id))
        except APIClientError as exc:
            return _detail_error_response(request, client, competitor_id, str(exc), exc.status_code or 502)
    return redirect(_detail_url(competitor_id, request.GET.get("company_id")))


def _load_company_context(request: HttpRequest, client: APIClient) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    companies = client.get_companies()
    if not companies:
        raise APIClientError("no companies are available for this demo", status_code=404, code="not_found")
    requested_id = request.GET.get("company_id") or request.POST.get("company_id")
    selected_company = next(
        (company for company in companies if str(company.get("id")) == str(requested_id)),
        companies[0] if requested_id is None else None,
    )
    if selected_company is None:
        raise APIClientError(f"company {requested_id!r} was not found", status_code=404, code="not_found")
    return companies, selected_company


def _detail_context(
    request: HttpRequest,
    client: APIClient,
    companies: list[dict[str, Any]],
    selected_company: dict[str, Any],
    competitor_id: str,
) -> dict[str, Any]:
    competitor = client.get_competitor(competitor_id, selected_company["id"])
    targets = _sort_review_rows(client.list_targets(selected_company["id"], competitor_id))
    review_candidates = _sort_review_rows(
        [
            *client.list_candidates(competitor_id, selected_company["id"], status="ALL"),
            *_inactive_targets_for_review(targets),
        ]
    )
    status = (request.GET.get("status") or request.POST.get("status") or "SUGGESTED").upper()
    if status not in {"SUGGESTED", "ACTIVE", "DISCARDED"}:
        status = "SUGGESTED"
    candidates = [candidate for candidate in review_candidates if candidate.get("discovery_status") == status]
    total_rows = len(candidates)
    if status == "ACTIVE":
        candidates = [
            target
            for target in targets
            if target.get("active") is True and target.get("discovery_status") == "ACTIVE"
        ]
        total_rows = len(candidates)
    elif len(candidates) > 50:
        # Discovery can return hundreds of candidates. Keep the review screen
        # responsive while retaining the API-backed total in the tab count.
        candidates = candidates[:50]
    pending_requested = request.GET.get("discovery_pending") == "1"
    discovery_run_id = request.GET.get("discovery_run_id")
    discovery_run: dict[str, Any] | None = None
    discovery_status: str | None = None
    discovery_pending = False
    discovery_complete = False
    discovery_error: str | None = None
    if pending_requested and discovery_run_id:
        try:
            discovery_run = client.get_discovery_run(
                discovery_run_id,
                selected_company["id"],
            )
            discovery_status = str(discovery_run.get("status", "")).upper()
        except APIClientError as exc:
            if exc.status_code == 404:
                # The trigger may have timed out immediately after the Flask
                # request began. Keep polling until its RUNNING record becomes
                # visible rather than guessing from candidate rows.
                discovery_status = "RUNNING"
            else:
                discovery_error = str(exc)
        if discovery_status == "RUNNING":
            discovery_pending = True
        elif discovery_status == "SUCCESS":
            discovery_complete = True
        elif discovery_status == "FAILED":
            discovery_error = (
                discovery_run.get("error_message")
                or "Discovery failed without an error message."
            )
    company_changes = client.list_changes(
        selected_company["id"],
        competitor_id=competitor_id,
        limit=100,
    )
    context = _shell_context(
        companies=companies,
        selected_company=selected_company,
        competitors=[competitor],
        nav_changes_count=len(client.list_changes(selected_company["id"], limit=100)),
        title=competitor["name"],
        breadcrumb="Competitors",
        meta=competitor["website_url"],
    )
    context.update(
        {
            "competitor": competitor,
            "targets": targets,
            "rows": candidates,
            "total_rows": total_rows,
            "candidate_total": len(review_candidates),
            "discovery_pending": discovery_pending,
            "discovery_complete": discovery_complete,
            "discovery_poll_url": _detail_url(
                competitor_id,
                selected_company["id"],
                discovery_pending=True,
                discovery_run_id=discovery_run_id,
            ) if discovery_pending and discovery_run_id else None,
            "discovery_run": discovery_run,
            "discovery_status": discovery_status,
            "status": status,
            "suggested_count": sum(candidate.get("discovery_status") == "SUGGESTED" for candidate in review_candidates),
            "active_count": sum(
                target.get("active") is True and target.get("discovery_status") == "ACTIVE"
                for target in targets
            ),
            "discarded_count": sum(candidate.get("discovery_status") == "DISCARDED" for candidate in review_candidates),
            "recent_changes": _decorate_changes(company_changes, {str(target["id"]): target for target in targets}),
            "manual_url": "",
            "manual_page_type": "",
            "manual_error": None,
            "competitor_form_name": competitor["name"],
            "competitor_form_website": competitor["website_url"],
            "page_error": discovery_error,
        }
    )
    return context


def _detail_error_response(
    request: HttpRequest,
    client: APIClient,
    competitor_id: str,
    message: str,
    status_code: int,
    *,
    extra_context: Mapping[str, Any] | None = None,
) -> HttpResponse:
    try:
        companies, selected_company = _load_company_context(request, client)
        context = _detail_context(request, client, companies, selected_company, competitor_id)
    except APIClientError:
        return _error_page(request, message, status_code=status_code)
    context["page_error"] = message
    if extra_context:
        context.update(extra_context)
    return render(request, "pages/competitor_detail.html", context, status=status_code)


def _shell_context(
    *,
    companies: list[dict[str, Any]],
    selected_company: dict[str, Any],
    competitors: Iterable[dict[str, Any]],
    nav_changes_count: int,
    title: str,
    meta: str | None = None,
    breadcrumb: str | None = None,
) -> dict[str, Any]:
    competitor_list = list(competitors)
    return {
        "companies": companies,
        "selected_company": selected_company,
        "competitors": competitor_list,
        "nav_competitor_count": len(competitor_list),
        "nav_changes_count": nav_changes_count,
        "topbar_title": title,
        "topbar_meta": meta,
        "topbar_breadcrumb": breadcrumb,
        "page_error": None,
    }


def _decorate_changes(
    changes: Iterable[Mapping[str, Any]],
    target_lookup: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    decorated: list[dict[str, Any]] = []
    for change in changes:
        item = dict(change)
        target = target_lookup.get(str(change.get("monitoring_target_id")))
        item["target_url"] = target.get("url") if target else None
        decorated.append(item)
    return decorated


def _sort_review_rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Put the most recently changed review row first.

    The API contract guarantees UTC ISO 8601 timestamps, whose string ordering
    is chronological. Missing timestamps stay at the end without preventing
    older rows from rendering.
    """

    return sorted(
        (dict(row) for row in rows),
        key=lambda row: str(row.get("updated_at") or ""),
        reverse=True,
    )


def _inactive_targets_for_review(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Expose deactivated history-bearing targets in the Discarded tab.

    The backend intentionally preserves ``discovery_status=ACTIVE`` when a
    target with history is deactivated, so its foreign-key references remain
    valid. The review UI still needs to offer the same liveness-gated
    reactivation action, so this creates a presentation-only DISCARDED view of
    those inactive rows without changing their stored lifecycle status.
    """

    return [
        {**row, "discovery_status": "DISCARDED"}
        for row in rows
        if row.get("active") is False and row.get("discovery_status") == "ACTIVE"
    ]


def _company_id_from_request(request: HttpRequest) -> str:
    company_id = request.POST.get("company_id") or request.GET.get("company_id")
    if not company_id:
        raise APIClientError("company_id is required for a scoped frontend request", status_code=400, code="validation_error")
    return company_id


def _dashboard_url(company_id: str | None) -> str:
    url = reverse("dashboard")
    return f"{url}?{urlencode({'company_id': company_id})}" if company_id else url


def _detail_url(
    competitor_id: str,
    company_id: str | None,
    *,
    status: str | None = None,
    discovery_pending: bool = False,
    discovery_run_id: str | None = None,
) -> str:
    url = reverse("competitor_detail", args=[competitor_id])
    params = {"company_id": company_id}
    if status:
        params["status"] = status
    if discovery_pending:
        params["discovery_pending"] = "1"
    if discovery_run_id is not None:
        params["discovery_run_id"] = discovery_run_id
    params = {key: value for key, value in params.items() if value is not None}
    return f"{url}?{urlencode(params)}" if params else url


def _error_page(request: HttpRequest, message: str, *, status_code: int) -> HttpResponse:
    return render(
        request,
        "pages/error.html",
        {
            "companies": [],
            "selected_company": None,
            "nav_competitor_count": 0,
            "nav_changes_count": 0,
            "topbar_title": "CompetitorScope",
            "topbar_meta": "Monitoring UI",
            "topbar_breadcrumb": None,
            "page_error": message,
        },
        status=status_code,
    )
