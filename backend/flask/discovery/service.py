"""Layer 1 discovery orchestration."""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from typing import Any, Callable, Iterable, Mapping, Optional, Protocol, Sequence
from urllib.parse import urlsplit, urlunsplit

from backend.flask.competitors.repository import CompetitorRepository
from backend.flask.website_monitoring.repository import MonitoringTargetRepository
from backend.flask.website_monitoring.service import (
    FetchResult,
    MonitoringError,
    fetch_page,
)

from .classification import (
    CandidateClassifier,
    CandidateForClassification,
    classify_candidates,
)
from .normalization import (
    canonicalize_raw_url,
    discovery_scope,
    is_html_candidate_url,
    is_same_site,
    is_system_path,
    is_structural_path,
    normalize_url,
)
from .sources import (
    DiscoveredURL,
    DiscoveryFetchError,
    HttpFetcher,
    InternalLinkSource,
    RobotsTxtSource,
    SitemapSource,
)


class DiscoveryError(RuntimeError):
    """Raised when a competitor cannot be discovered."""


logger = logging.getLogger(__name__)

CANDIDATE_REVIEW_STATUSES = frozenset({"SUGGESTED", "DISCARDED"})


class RobotsSource(Protocol):
    def sitemap_urls(self, website_url: str) -> Sequence[str]:
        """Return sitemap declarations from robots.txt."""


class SitemapCollector(Protocol):
    def discover(
        self,
        website_url: str,
        declared_sitemaps: Sequence[str] = (),
    ) -> Sequence[DiscoveredURL]:
        """Collect candidate URLs from sitemaps."""


class WebsiteSource(Protocol):
    def discover(self, website_url: str) -> Sequence[DiscoveredURL]:
        """Collect candidate URLs from a website source."""


LivenessChecker = Callable[[str], FetchResult | bool]


@dataclass(frozen=True)
class _NormalizedCandidate:
    raw_url: str
    url: str
    source: str
    title: str | None = None
    force_discarded: bool = False
    priority: int = 3


@dataclass(frozen=True)
class SourceDiscoverySummary:
    """Raw and normalized counts for one discovery source."""

    raw_count: int
    normalized_count: int
    sampled_count: int = 0
    declared_sitemaps: int = 0


@dataclass(frozen=True)
class DiscoverySummary:
    """Per-run discovery counts exposed for logs and verification."""

    website_url: str
    source_breakdown: dict[str, SourceDiscoverySummary]
    raw_count: int
    normalized_count: int
    suggested_count: int
    discarded_count: int


class DiscoveryService:
    """Coordinate URL collection, normalization, classification, and storage."""

    def __init__(
        self,
        competitor_repository: CompetitorRepository,
        monitoring_target_repository: MonitoringTargetRepository,
        *,
        fallback_classifier: CandidateClassifier,
        robots_source: Optional[RobotsSource] = None,
        sitemap_source: Optional[SitemapCollector] = None,
        link_source: Optional[WebsiteSource] = None,
        liveness_checker: Optional[LivenessChecker] = None,
    ) -> None:
        self.competitor_repository = competitor_repository
        self.monitoring_target_repository = monitoring_target_repository
        self.fallback_classifier = fallback_classifier
        # This is intentionally injected at the service boundary so tests can
        # avoid network access while production uses the Step 1.4 fetch
        # heuristic, including browser fallback.
        self.liveness_checker = liveness_checker or fetch_page
        self.last_summary: DiscoverySummary | None = None
        if any(source is None for source in (robots_source, sitemap_source, link_source)):
            fetcher = HttpFetcher()
        else:
            fetcher = None
        self.robots_source = robots_source or RobotsTxtSource(fetcher or HttpFetcher())
        self.sitemap_source = sitemap_source or SitemapSource(fetcher or HttpFetcher())
        self.link_source = link_source or InternalLinkSource(fetcher or HttpFetcher())

    def list_candidates(
        self,
        competitor_id: Any,
        status: str = "SUGGESTED",
    ) -> list[dict[str, Any]]:
        """List reviewable candidates without exposing repository details."""

        normalized_status = _normalize_candidate_status(status)
        candidates = self.monitoring_target_repository.list_for_competitor(
            competitor_id,
            discovery_status=None
            if normalized_status == "ALL"
            else normalized_status,
        )
        if normalized_status == "ALL":
            return [
                candidate
                for candidate in candidates
                if candidate.get("discovery_status") in CANDIDATE_REVIEW_STATUSES
            ]
        return candidates

    def list_active_targets(
        self,
        competitor_id: Any | None = None,
    ) -> list[dict[str, Any]]:
        """Return only targets eligible for monitoring or scheduling.

        Monitoring and scheduler code must use this method rather than
        querying the shared candidates/targets collection directly.
        """

        return self.monitoring_target_repository.list_active_targets(competitor_id)

    def activate_candidate(self, candidate_id: Any) -> dict[str, Any]:
        """Promote an inactive candidate to an active Layer 2 target.

        Candidate and target are one document in the current schema. Updating
        that document in place preserves its id and makes repeated activation
        safe: no second monitoring-target row can be created.
        """

        candidate = self._get_candidate(candidate_id)
        if candidate.get("discovery_status") == "DISCARDED":
            raise DiscoveryError(
                f"candidate {candidate_id!r} is DISCARDED and cannot be activated"
            )
        if candidate.get("discovery_status") not in {"SUGGESTED", "ACTIVE"}:
            raise DiscoveryError(
                f"candidate {candidate_id!r} has an invalid activation status"
            )
        if candidate.get("active") and candidate.get("discovery_status") == "ACTIVE":
            return candidate

        updated = self.monitoring_target_repository.update(
            candidate_id,
            {
                "active": True,
                "discovery_status": "ACTIVE",
            },
            competitor_id=candidate.get("competitor_id"),
        )
        if updated is None:
            raise DiscoveryError(f"candidate {candidate_id!r} could not be activated")
        return updated

    def add_candidate(self, competitor_id: Any, url: str) -> dict[str, Any]:
        """Add a manual candidate that still requires user activation."""

        competitor = self._get_competitor(competitor_id)
        candidate_url = _candidate_url_for_competitor(url, competitor["website_url"])
        existing = self.monitoring_target_repository.find_by_url(
            competitor_id,
            candidate_url,
        )
        if existing is not None:
            return existing

        return self.monitoring_target_repository.create(
            competitor_id=competitor_id,
            raw_url=candidate_url,
            url=candidate_url,
            page_type="OTHER",
            discovery_source="MANUAL",
            discovery_status="SUGGESTED",
            classification_method="MANUAL",
            active=False,
            check_interval_minutes=MonitoringTargetRepository.DEFAULT_CANDIDATE_CHECK_INTERVAL_MINUTES,
        )

    def edit_candidate(self, candidate_id: Any, new_url: str) -> dict[str, Any]:
        """Change an unactivated candidate's URL while retaining its metadata."""

        candidate = self._get_candidate(candidate_id)
        if _is_activated(candidate):
            raise DiscoveryError(
                f"candidate {candidate_id!r} is already activated and cannot be edited"
            )

        competitor_id = candidate.get("competitor_id")
        competitor = self._get_competitor(competitor_id)
        candidate_url = _candidate_url_for_competitor(new_url, competitor["website_url"])
        existing = self.monitoring_target_repository.find_by_url(
            competitor_id,
            candidate_url,
        )
        if existing is not None and existing.get("id") != candidate.get("id"):
            raise DiscoveryError(
                f"candidate URL {candidate_url!r} already exists for competitor "
                f"{competitor_id!r}"
            )

        updated = self.monitoring_target_repository.update(
            candidate_id,
            {"raw_url": candidate_url, "url": candidate_url},
            competitor_id=competitor_id,
        )
        if updated is None:
            raise DiscoveryError(f"candidate {candidate_id!r} could not be edited")
        return updated

    def remove_candidate(self, candidate_id: Any) -> bool:
        """Hard-delete an unactivated candidate; protect activated targets."""

        candidate = self._get_candidate(candidate_id)
        if _is_activated(candidate):
            raise DiscoveryError(
                f"candidate {candidate_id!r} is activated; deactivate the monitoring "
                "target before removing it"
            )
        removed = self.monitoring_target_repository.delete(
            candidate_id,
            competitor_id=candidate.get("competitor_id"),
        )
        if not removed:
            raise DiscoveryError(f"candidate {candidate_id!r} could not be removed")
        return True

    def _get_candidate(self, candidate_id: Any) -> dict[str, Any]:
        candidate = self.monitoring_target_repository.get(candidate_id)
        if candidate is None:
            raise DiscoveryError(f"candidate {candidate_id!r} was not found")
        return candidate

    def _get_competitor(self, competitor_id: Any) -> dict[str, Any]:
        competitor = self.competitor_repository.get(competitor_id)
        if competitor is None:
            raise DiscoveryError(f"competitor {competitor_id!r} was not found")
        return competitor

    def discover_website(
        self,
        competitor_id: Any,
        *,
        user_id: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Discover, classify, and persist Layer 2 candidates for one competitor."""

        competitor = self.competitor_repository.get(competitor_id, user_id=user_id)
        if competitor is None:
            raise DiscoveryError(f"competitor {competitor_id!r} was not found")
        website_url = competitor["website_url"]

        source_candidates: dict[str, Sequence[DiscoveredURL]] = {}
        declared_sitemaps = self._safe_sitemap_declarations(website_url)
        source_candidates["SITEMAP"] = self._safe_sitemap_discovery(
            website_url,
            declared_sitemaps,
        )
        source_candidates["LINKS"] = self._safe_source_discovery(self.link_source, website_url)

        normalized_by_source = {
            source: _normalize_and_dedupe(candidates, website_url=website_url)
            for source, candidates in source_candidates.items()
        }
        normalized = _normalize_and_dedupe(
            (
                candidate
                for candidates in source_candidates.values()
                for candidate in candidates
            ),
            website_url=website_url,
        )

        normalized = _apply_liveness_gate(normalized, self.liveness_checker)
        classification_inputs = tuple(
            CandidateForClassification(
                raw_url=candidate.raw_url,
                url=candidate.url,
                title=candidate.title,
                sources=(candidate.source,),
                force_discarded=candidate.force_discarded,
            )
            for candidate in normalized
        )
        classifications = classify_candidates(classification_inputs, self.fallback_classifier)

        persisted: list[dict[str, Any]] = []
        for candidate, classification in zip(normalized, classifications):
            persisted.append(
                self.monitoring_target_repository.upsert_discovered_candidate(
                    competitor_id=competitor_id,
                    raw_url=candidate.raw_url,
                    url=candidate.url,
                    page_type=classification.page_type,
                    discovery_source=candidate.source,
                    discovery_status=classification.discovery_status,
                    classification_method=classification.classification_method,
                )
            )
        suggested_count = sum(
            classification.discovery_status == "SUGGESTED"
            for classification in classifications
        )
        discarded_count = sum(
            classification.discovery_status == "DISCARDED"
            for classification in classifications
        )
        source_breakdown: dict[str, SourceDiscoverySummary] = {
            "ROBOTS": SourceDiscoverySummary(
                raw_count=0,
                normalized_count=0,
                sampled_count=0,
                declared_sitemaps=len(declared_sitemaps),
            )
        }
        for source, candidates in source_candidates.items():
            stats = getattr(
                {"SITEMAP": self.sitemap_source, "LINKS": self.link_source}[source],
                "last_stats",
                None,
            )
            source_breakdown[source] = SourceDiscoverySummary(
                raw_count=getattr(stats, "raw_count", len(candidates)),
                normalized_count=len(normalized_by_source[source]),
                sampled_count=getattr(stats, "sampled_count", 0),
            )
        self.last_summary = DiscoverySummary(
            website_url=website_url,
            source_breakdown=source_breakdown,
            raw_count=sum(summary.raw_count for summary in source_breakdown.values()),
            normalized_count=len(normalized),
            suggested_count=suggested_count,
            discarded_count=discarded_count,
        )
        logger.info(
            "Layer 1 discovery summary website=%s raw=%d normalized=%d suggested=%d discarded=%d sources=%s",
            website_url,
            self.last_summary.raw_count,
            self.last_summary.normalized_count,
            self.last_summary.suggested_count,
            self.last_summary.discarded_count,
            {
                source: {
                    "raw": summary.raw_count,
                    "normalized": summary.normalized_count,
                    "sampled": summary.sampled_count,
                    "declared_sitemaps": summary.declared_sitemaps,
                }
                for source, summary in source_breakdown.items()
            },
        )
        return persisted

    def _safe_sitemap_declarations(self, website_url: str) -> Sequence[str]:
        try:
            return self.robots_source.sitemap_urls(website_url)
        except (DiscoveryFetchError, ValueError):
            return ()

    def _safe_sitemap_discovery(
        self,
        website_url: str,
        declared_sitemaps: Sequence[str],
    ) -> Sequence[DiscoveredURL]:
        try:
            return self.sitemap_source.discover(website_url, declared_sitemaps)
        except (DiscoveryFetchError, ValueError):
            return ()

    @staticmethod
    def _safe_source_discovery(
        source: WebsiteSource,
        website_url: str,
    ) -> Sequence[DiscoveredURL]:
        try:
            return source.discover(website_url)
        except (DiscoveryFetchError, ValueError):
            return ()


def _normalize_candidate_status(status: str) -> str:
    if not isinstance(status, str):
        raise DiscoveryError("candidate status must be SUGGESTED, DISCARDED, or ALL")
    normalized = status.upper()
    if normalized != "ALL" and normalized not in CANDIDATE_REVIEW_STATUSES:
        raise DiscoveryError(
            "candidate status must be SUGGESTED, DISCARDED, or ALL"
        )
    return normalized


def _is_activated(candidate: Mapping[str, Any]) -> bool:
    return bool(candidate.get("active")) or candidate.get("discovery_status") == "ACTIVE"


def _candidate_url_for_competitor(url: str, competitor_url: str) -> str:
    try:
        canonical_url = canonicalize_raw_url(url)
    except ValueError as exc:
        raise DiscoveryError(f"candidate URL is invalid: {exc}") from exc
    if not is_same_site(competitor_url, canonical_url):
        raise DiscoveryError("candidate URL must belong to the competitor's website")
    if not is_html_candidate_url(canonical_url):
        raise DiscoveryError("candidate URL must refer to an HTML page")

    normalized_url = normalize_url(canonical_url)
    if is_system_path(normalized_url):
        raise DiscoveryError("candidate URL cannot be a system or taxonomy path")
    return normalized_url


def _normalize_and_dedupe(
    candidates: Iterable[DiscoveredURL],
    *,
    website_url: str | None = None,
) -> list[_NormalizedCandidate]:
    by_url: dict[str, _NormalizedCandidate] = {}
    canonical_site = canonicalize_raw_url(website_url) if website_url is not None else None
    for candidate in candidates:
        try:
            raw_url = canonicalize_raw_url(candidate.raw_url)
            if website_url is not None and not is_same_site(website_url, raw_url):
                continue
            if canonical_site is not None:
                raw_url = _canonicalize_for_site(raw_url, canonical_site)
            if not is_html_candidate_url(raw_url):
                continue
            force_discarded = candidate.force_discarded or discovery_scope(raw_url) == "UNMATCHED"
            if (
                candidate.source == "LINKS"
                and candidate.priority >= 2
                and not is_structural_path(raw_url)
            ):
                force_discarded = True
            url = normalize_url(raw_url)
            if is_system_path(url):
                continue
        except ValueError:
            continue
        current = by_url.get(url)
        if current is None:
            by_url[url] = _NormalizedCandidate(
                raw_url=candidate.raw_url,
                url=url,
                source=candidate.source,
                title=candidate.title,
                force_discarded=force_discarded,
                priority=candidate.priority,
            )
            continue
        preferred_source = min(
            (current.source, candidate.source),
            key=lambda source: {"SITEMAP": 0, "LINKS": 1}.get(source, 99),
        )
        preferred_candidate = min(
            (current, _NormalizedCandidate(
                raw_url=candidate.raw_url,
                url=url,
                source=candidate.source,
                title=candidate.title,
                force_discarded=force_discarded,
                priority=candidate.priority,
            )),
            key=lambda item: (
                item.force_discarded,
                {"SITEMAP": 0, "LINKS": 1}.get(item.source, 99),
                item.priority,
            ),
        )
        by_url[url] = replace(
            current,
            source=preferred_source,
            title=current.title or candidate.title,
            raw_url=preferred_candidate.raw_url,
            force_discarded=preferred_candidate.force_discarded,
            priority=preferred_candidate.priority,
        )
    return list(by_url.values())


def _apply_liveness_gate(
    candidates: Sequence[_NormalizedCandidate],
    liveness_checker: LivenessChecker,
) -> list[_NormalizedCandidate]:
    """Discard unresolved index candidates whose normalized URL is unusable.

    This gate is the final Layer 1 step after URL normalization and before
    Stage 2 classification. It checks every normalized index candidate; source
    provenance may still force a candidate to DISCARDED, but it never bypasses
    the liveness check. The default checker is ``fetch_page`` from the Layer 2
    service, so HTTP-first and injected-browser behavior stay in one place.
    """

    gated: list[_NormalizedCandidate] = []
    for candidate in candidates:
        if discovery_scope(candidate.url) != "INDEX":
            gated.append(candidate)
            continue

        try:
            result = liveness_checker(candidate.url)
        except (MonitoringError, ValueError) as exc:
            logger.info(
                "Layer 1 liveness check failed url=%s error=%s",
                candidate.url,
                exc,
            )
            gated.append(replace(candidate, force_discarded=True))
            continue

        is_live = result if isinstance(result, bool) else isinstance(result, FetchResult)
        if not is_live:
            logger.info(
                "Layer 1 liveness check rejected url=%s",
                candidate.url,
            )
            gated.append(replace(candidate, force_discarded=True))
            continue
        gated.append(candidate)
    return gated


def _canonicalize_for_site(url: str, site_url: str) -> str:
    """Use the configured competitor host for same-site URL deduplication."""

    candidate = urlsplit(url)
    site = urlsplit(site_url)
    return urlunsplit((site.scheme, site.netloc, candidate.path, candidate.query, ""))
