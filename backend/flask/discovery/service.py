"""Layer 1 discovery orchestration."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, replace
from typing import Any, Callable, Iterable, Mapping, Optional, Protocol, Sequence
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from backend.flask.competitors.repository import CompetitorRepository
from backend.flask.website_monitoring.repository import MonitoringTargetRepository
from backend.flask.website_monitoring.service import (
    FetchResult,
    MonitoringError,
    fetch_page,
)
from backend.flask.website_monitoring.intervals import default_check_interval_minutes
from backend.flask.discovery.repository import DiscoveryRunAlreadyRunningError

from .audit import (
    DiscoveryAuditClassifier,
    DiscoveryAuditConfigurationError,
    DiscoveryAuditResult,
    NoopDiscoveryAudit,
    OpenAIDiscoveryAudit,
    SuggestedCandidateForAudit,
)
from .classification import (
    CandidateClassifier,
    CandidateForClassification,
    DeterministicStubClassifier,
    OpenAIClassifier,
    OpenAIClassifierConfigurationError,
    classify_by_rules,
    classify_candidates,
    resolve_classifier_batch_size,
)
from .normalization import (
    ITEM_TYPE_EXCLUSION_PATTERNS,
    canonicalize_raw_url,
    discovery_scope,
    is_html_candidate_url,
    is_item_type_excluded,
    is_same_site,
    is_system_path,
    is_structural_path,
    extract_meta_description,
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

    status_code = 400
    code = "validation_error"


class DiscoveryNotFoundError(DiscoveryError):
    """Raised when a candidate or competitor is absent."""

    status_code = 404
    code = "not_found"


class DiscoveryConflictError(DiscoveryError):
    """Raised when a candidate action conflicts with its current state."""

    status_code = 409
    code = "conflict"


logger = logging.getLogger(__name__)

CANDIDATE_REVIEW_STATUSES = frozenset({"SUGGESTED", "DISCARDED"})
DEFAULT_LIVENESS_ATTEMPTS = 3
DEFAULT_LIVENESS_BACKOFF_SECONDS = 0.25


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


class TargetHistoryRepository(Protocol):
    """Repository boundary for target-linked snapshot or change history."""

    def list_for_target(self, monitoring_target_id: Any) -> list[Mapping[str, Any]]:
        """Return persisted history rows linked to one monitoring target."""


class DiscoveryRunTracker(Protocol):
    """Repository boundary for the status of an HTTP-triggered discovery run."""

    def start(
        self,
        run_id: str,
        *,
        competitor_id: Any,
        company_id: Any = None,
    ) -> Mapping[str, Any]:
        """Persist a RUNNING discovery record before source collection begins."""

    def succeed(
        self,
        run_id: str,
        *,
        candidate_count: int,
        summary: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any] | None:
        """Transition a discovery run to SUCCESS."""

    def fail(self, run_id: str, error_message: str) -> Mapping[str, Any] | None:
        """Transition a discovery run to FAILED."""

    def get(self, run_id: str) -> Mapping[str, Any] | None:
        """Read one discovery run by its public run identifier."""

    def find_latest_successful(
        self,
        competitor_id: Any,
        *,
        company_id: Any = None,
    ) -> Mapping[str, Any] | None:
        """Return the latest successful run for one scoped competitor."""


@dataclass(frozen=True)
class _NormalizedCandidate:
    raw_url: str
    url: str
    source: str
    title: str | None = None
    meta_description: str | None = None
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


@dataclass(frozen=True)
class DiscoveryReconciliationResult:
    """The state transition produced by one automatic discovery pass.

    This result deliberately contains no monitoring snapshots.  SQS-triggered
    discovery and target reconciliation must finish independently of the
    per-target monitoring scheduler so a long discovery does not also have to
    wait for every active page fetch.
    """

    run_id: str
    competitor_id: Any
    active_before: tuple[Mapping[str, Any], ...]
    active_after: tuple[Mapping[str, Any], ...]
    activated_target_ids: tuple[Any, ...]
    deactivated_target_ids: tuple[Any, ...]
    suggested_count: int
    discovered_count: int

    def as_dict(self) -> dict[str, Any]:
        """Return a defensive, JSON-friendly summary for callers."""

        return {
            "run_id": self.run_id,
            "competitor_id": self.competitor_id,
            "active_before": [dict(target) for target in self.active_before],
            "active_after": [dict(target) for target in self.active_after],
            "activated_target_ids": list(self.activated_target_ids),
            "deactivated_target_ids": list(self.deactivated_target_ids),
            "suggested_count": self.suggested_count,
            "discovered_count": self.discovered_count,
        }


class DiscoveryService:
    """Coordinate URL collection, normalization, classification, and storage."""

    def __init__(
        self,
        competitor_repository: CompetitorRepository,
        monitoring_target_repository: MonitoringTargetRepository,
        *,
        fallback_classifier: CandidateClassifier | None = None,
        audit_classifier: DiscoveryAuditClassifier | None = None,
        robots_source: Optional[RobotsSource] = None,
        sitemap_source: Optional[SitemapCollector] = None,
        link_source: Optional[WebsiteSource] = None,
        snapshot_repository: Optional[TargetHistoryRepository] = None,
        change_repository: Optional[TargetHistoryRepository] = None,
        liveness_checker: Optional[LivenessChecker] = None,
        liveness_attempts: int = DEFAULT_LIVENESS_ATTEMPTS,
        liveness_backoff_seconds: float = DEFAULT_LIVENESS_BACKOFF_SECONDS,
        liveness_sleep: Optional[Callable[[float], None]] = None,
        classifier_batch_size: int | None = None,
        run_repository: Optional[DiscoveryRunTracker] = None,
    ) -> None:
        if (
            isinstance(liveness_attempts, bool)
            or not isinstance(liveness_attempts, int)
            or liveness_attempts < 2
        ):
            raise ValueError("liveness_attempts must be at least 2")
        if (
            isinstance(liveness_backoff_seconds, bool)
            or not isinstance(liveness_backoff_seconds, (int, float))
            or liveness_backoff_seconds < 0
        ):
            raise ValueError("liveness_backoff_seconds cannot be negative")
        self.competitor_repository = competitor_repository
        self.monitoring_target_repository = monitoring_target_repository
        self.fallback_classifier = fallback_classifier or _default_classifier()
        # Direct service consumers default to a safe no-op. The Flask
        # application factory explicitly wires the configured OpenAI auditor;
        # this keeps unit/in-process callers from making accidental provider
        # calls merely by constructing the service.
        self.audit_classifier = audit_classifier or NoopDiscoveryAudit()
        self.classifier_batch_size = resolve_classifier_batch_size(classifier_batch_size)
        # This is intentionally injected at the service boundary so tests can
        # avoid network access while production uses the Step 1.4 fetch
        # heuristic, including browser fallback.
        self.liveness_checker = liveness_checker or fetch_page
        self.liveness_attempts = liveness_attempts
        self.liveness_backoff_seconds = liveness_backoff_seconds
        self.liveness_sleep = liveness_sleep or time.sleep
        self.last_summary: DiscoverySummary | None = None
        self.last_discovered_suggested_urls: frozenset[str] = frozenset()
        self.last_audit_result: DiscoveryAuditResult | None = None
        self.last_audit_error: str | None = None
        if any(source is None for source in (robots_source, sitemap_source, link_source)):
            fetcher = HttpFetcher()
        else:
            fetcher = None
        self.robots_source = robots_source or RobotsTxtSource(fetcher or HttpFetcher())
        self.sitemap_source = sitemap_source or SitemapSource(fetcher or HttpFetcher())
        self.link_source = link_source or InternalLinkSource(fetcher or HttpFetcher())
        self.snapshot_repository = snapshot_repository
        self.change_repository = change_repository
        self.run_repository = run_repository

    def list_candidates(
        self,
        competitor_id: Any,
        status: str = "SUGGESTED",
        *,
        company_id: Any = None,
    ) -> list[dict[str, Any]]:
        """List reviewable candidates without exposing repository details."""

        normalized_status = _normalize_candidate_status(status)
        if company_id is not None:
            self._get_competitor(competitor_id, company_id=company_id)
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
        *,
        company_id: Any = None,
    ) -> list[dict[str, Any]]:
        """Return only targets eligible for monitoring or scheduling.

        Monitoring and scheduler code must use this method rather than
        querying the shared candidates/targets collection directly.
        """

        if company_id is None:
            return self.monitoring_target_repository.list_active_targets(competitor_id)
        competitors = self.competitor_repository.list_for_company(company_id)
        competitor_ids = {competitor.get("id") for competitor in competitors}
        if competitor_id is not None:
            if str(competitor_id) not in {str(value) for value in competitor_ids}:
                return []
            return self.monitoring_target_repository.list_active_targets(competitor_id)
        rows: list[dict[str, Any]] = []
        for scoped_competitor_id in competitor_ids:
            rows.extend(self.monitoring_target_repository.list_active_targets(scoped_competitor_id))
        return rows

    def activate_candidate(self, candidate_id: Any, *, company_id: Any = None) -> dict[str, Any]:
        """Promote an inactive candidate to an active Layer 2 target.

        Candidate and target are one document in the current schema. Updating
        that document in place preserves its id and makes repeated activation
        safe: no second monitoring-target row can be created.
        """

        candidate = self._get_candidate(candidate_id, company_id=company_id)
        if candidate.get("discovery_status") == "DISCARDED":
            raise DiscoveryConflictError(
                f"candidate {candidate_id!r} is DISCARDED and cannot be activated"
            )
        if candidate.get("discovery_status") not in {"SUGGESTED", "ACTIVE"}:
            raise DiscoveryConflictError(
                f"candidate {candidate_id!r} has an invalid activation status"
            )
        if candidate.get("active") and candidate.get("discovery_status") == "ACTIVE":
            return candidate

        check_interval_minutes = None
        if not _has_positive_interval(candidate.get("check_interval_minutes")):
            check_interval_minutes = default_check_interval_minutes(candidate.get("page_type"))

        updated = self.monitoring_target_repository.mark_activated(
            candidate_id,
            competitor_id=candidate.get("competitor_id"),
            check_interval_minutes=check_interval_minutes,
        )
        if updated is None:
            raise DiscoveryError(f"candidate {candidate_id!r} could not be activated")
        return updated

    def add_candidate(
        self,
        competitor_id: Any,
        url: str,
        *,
        company_id: Any = None,
    ) -> dict[str, Any]:
        """Add a manual candidate that still requires user activation."""

        competitor = self._get_competitor(competitor_id, company_id=company_id)
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
            check_interval_minutes=default_check_interval_minutes("OTHER"),
        )

    def add_manual_target(
        self,
        competitor_id: Any,
        url: str,
        page_type: str | None = None,
        *,
        company_id: Any = None,
    ) -> dict[str, Any]:
        """Create an already-active user-selected Layer 2 target.

        This intentionally bypasses the SUGGESTED review state.  If no page
        type is supplied, the existing deterministic URL classifier is used;
        an unmatched URL receives ``OTHER``.  The liveness gate is reused with
        its bounded retries, but manual creation requires a confirmed LIVE
        result because an inconclusive check must not create a target that is
        immediately unusable.

        An exact normalized URL duplicate is never inserted twice.  An
        existing ACTIVE row is returned unchanged.  A SUGGESTED or DISCARDED
        row is promoted in place after liveness succeeds, because the explicit
        manual request is a user decision to monitor that page.
        """

        competitor = self._get_competitor(competitor_id, company_id=company_id)
        try:
            canonical_url = canonicalize_raw_url(url)
        except (TypeError, ValueError) as exc:
            raise DiscoveryError(f"manual target URL is invalid: {exc}") from exc
        normalized_url = _candidate_url_for_competitor(
            canonical_url,
            competitor["website_url"],
        )
        existing = self.monitoring_target_repository.find_by_url(
            competitor_id,
            normalized_url,
        )
        if existing is not None and _is_active_target(existing):
            return existing

        try:
            liveness = _confirm_liveness(
                normalized_url,
                self.liveness_checker,
                attempts=self.liveness_attempts,
                backoff_seconds=self.liveness_backoff_seconds,
                sleep=self.liveness_sleep,
            )
        except Exception as exc:
            raise DiscoveryError(
                f"manual target URL {normalized_url!r} liveness check failed; "
                "target was not created"
            ) from exc
        if liveness == "DEAD":
            raise DiscoveryError(
                f"manual target URL {normalized_url!r} failed liveness checks "
                f"after {self.liveness_attempts} attempts; target was not created"
            )
        if liveness != "LIVE":
            raise DiscoveryError(
                f"manual target URL {normalized_url!r} could not be confirmed live "
                f"after {self.liveness_attempts} attempts; retry later"
            )

        resolved_page_type = _resolve_manual_page_type(normalized_url, page_type)
        updates = {
            "raw_url": canonical_url,
            "url": normalized_url,
            "page_type": resolved_page_type,
            "discovery_source": "MANUAL",
            "discovery_status": "ACTIVE",
            "classification_method": "MANUAL",
            "active": True,
            "check_interval_minutes": default_check_interval_minutes(
                resolved_page_type
            ),
        }
        if existing is not None:
            updated = self.monitoring_target_repository.update(
                existing["id"],
                updates,
                competitor_id=competitor_id,
            )
            if updated is None:
                raise DiscoveryError(
                    f"existing target {existing['id']!r} could not be promoted"
                )
            return updated

        return self.monitoring_target_repository.create(
            competitor_id=competitor_id,
            **updates,
        )

    def edit_candidate(
        self,
        candidate_id: Any,
        new_url: str,
        *,
        company_id: Any = None,
    ) -> dict[str, Any]:
        """Change an unactivated candidate's URL while retaining its metadata."""

        candidate = self._get_candidate(candidate_id, company_id=company_id)
        if _is_activated(candidate):
            raise DiscoveryConflictError(
                f"candidate {candidate_id!r} is already activated and cannot be edited"
            )

        competitor_id = candidate.get("competitor_id")
        competitor = self._get_competitor(competitor_id, company_id=company_id)
        candidate_url = _candidate_url_for_competitor(new_url, competitor["website_url"])
        existing = self.monitoring_target_repository.find_by_url(
            competitor_id,
            candidate_url,
        )
        if existing is not None and existing.get("id") != candidate.get("id"):
            raise DiscoveryConflictError(
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

    def discard_candidate(self, candidate_id: Any, *, company_id: Any = None) -> dict[str, Any]:
        """Mark an unactivated candidate DISCARDED without deleting its row."""

        candidate = self._get_candidate(candidate_id, company_id=company_id)
        if _is_activated(candidate):
            raise DiscoveryConflictError(
                f"candidate {candidate_id!r} is already activated and cannot be discarded"
            )
        if candidate.get("discovery_status") == "DISCARDED":
            return candidate
        updated = self.monitoring_target_repository.mark_discarded(
            candidate_id,
            competitor_id=candidate.get("competitor_id"),
        )
        if updated is None:
            raise DiscoveryError(f"candidate {candidate_id!r} could not be discarded")
        return updated

    def remove_candidate(self, candidate_id: Any, *, company_id: Any = None) -> bool:
        """Delete an unactivated/historyless target or deactivate its history.

        Candidates and active targets share one collection. An ACTIVE row with
        snapshot or change history is retained and marked ``active=False`` so
        those history records continue to reference an existing target. Its
        ``discovery_status`` remains ``ACTIVE``; the strict active-target
        repository filter excludes it from monitoring and scheduling. ACTIVE
        rows with no history are safe to hard-delete.
        """

        candidate = self._get_candidate(candidate_id, company_id=company_id)
        if _is_activated(candidate):
            if self.snapshot_repository is None or self.change_repository is None:
                raise DiscoveryError(
                    "snapshot and change history repositories are required before "
                    f"removing activated target {candidate_id!r}"
                )
            try:
                has_history = bool(
                    self.snapshot_repository.list_for_target(candidate_id)
                    or self.change_repository.list_for_target(candidate_id)
                )
            except Exception as exc:
                raise DiscoveryError(
                    f"could not inspect history for activated target {candidate_id!r}; "
                    "nothing was removed"
                ) from exc
            if has_history:
                updated = self.monitoring_target_repository.update(
                    candidate_id,
                    {"active": False},
                    competitor_id=candidate.get("competitor_id"),
                )
                if updated is None:
                    raise DiscoveryError(
                        f"activated target {candidate_id!r} could not be deactivated"
                    )
                return True

        removed = self.monitoring_target_repository.delete(
            candidate_id,
            competitor_id=candidate.get("competitor_id"),
        )
        if not removed:
            raise DiscoveryError(f"candidate {candidate_id!r} could not be removed")
        return True

    def _get_candidate(self, candidate_id: Any, *, company_id: Any = None) -> dict[str, Any]:
        candidate = self.monitoring_target_repository.get(candidate_id)
        if candidate is None:
            raise DiscoveryNotFoundError(f"candidate {candidate_id!r} was not found")
        if company_id is not None:
            self._get_competitor(candidate.get("competitor_id"), company_id=company_id)
        return candidate

    def _get_competitor(self, competitor_id: Any, *, company_id: Any = None) -> dict[str, Any]:
        competitor = self.competitor_repository.get(
            competitor_id,
            company_id=company_id,
        ) if company_id is not None else self.competitor_repository.get(competitor_id)
        if competitor is None:
            raise DiscoveryNotFoundError(f"competitor {competitor_id!r} was not found")
        return competitor

    def discover_website(
        self,
        competitor_id: Any,
        *,
        user_id: Optional[str] = None,
        company_id: Any = None,
        run_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Discover candidates and track an HTTP-triggered run when requested.

        The discovery work remains synchronous inside Flask.  ``run_id`` is
        optional so existing internal callers keep their original behavior;
        the HTTP trigger supplies it so a client that times out can poll the
        persisted lifecycle independently of candidate row counts.
        """

        if run_id is None or self.run_repository is None:
            return self._discover_website_impl(
                competitor_id,
                user_id=user_id,
                company_id=company_id,
            )

        if company_id is not None:
            competitor = self.competitor_repository.get(
                competitor_id,
                company_id=company_id,
            )
        else:
            competitor = self.competitor_repository.get(competitor_id, user_id=user_id)
        if competitor is None:
            raise DiscoveryNotFoundError(f"competitor {competitor_id!r} was not found")

        self.run_repository.start(
            run_id,
            competitor_id=competitor_id,
            company_id=company_id,
        )
        try:
            persisted = self._discover_website_impl(
                competitor_id,
                user_id=user_id,
                company_id=company_id,
            )
        except Exception as exc:
            try:
                self.run_repository.fail(run_id, str(exc))
            except Exception:
                logger.exception("could not mark discovery run failed run_id=%s", run_id)
            raise

        try:
            self.run_repository.succeed(
                run_id,
                candidate_count=len(persisted),
                summary=_discovery_summary_payload(self.last_summary),
            )
        except Exception as exc:
            try:
                self.run_repository.fail(run_id, str(exc))
            except Exception:
                logger.exception("could not mark discovery run failed run_id=%s", run_id)
            raise
        return persisted

    def latest_successful_run(
        self,
        competitor_id: Any,
        *,
        company_id: Any = None,
    ) -> Mapping[str, Any] | None:
        """Return the latest successful discovery run for one competitor."""

        if self.run_repository is None:
            raise DiscoveryError(
                "discovery run repository is required to query discovery freshness"
            )
        return self.run_repository.find_latest_successful(
            competitor_id,
            company_id=company_id,
        )

    def discover_and_reconcile(
        self,
        competitor_id: Any,
        *,
        user_id: Optional[str] = None,
        company_id: Any = None,
        run_id: str | None = None,
    ) -> DiscoveryReconciliationResult:
        """Run discovery and reconcile the automatically tracked target set.

        This is the production/SQS discovery boundary.  It intentionally does
        not call ``monitor_target`` or create snapshots.  The existing
        scheduler will pick up the resulting active targets on its next
        cadence, keeping the SQS message's processing window limited to
        discovery and state reconciliation.
        """

        if self.run_repository is None:
            raise DiscoveryError(
                "discovery run repository is required for automatic reconciliation"
            )
        if company_id is None and user_id is not None:
            competitor = self.competitor_repository.get(
                competitor_id,
                user_id=user_id,
            )
            if competitor is None:
                raise DiscoveryNotFoundError(
                    f"competitor {competitor_id!r} was not found"
                )
        else:
            self._get_competitor(competitor_id, company_id=company_id)
        active_before = tuple(
            dict(target)
            for target in self.monitoring_target_repository.list_active_targets(
                competitor_id
            )
        )
        resolved_run_id = run_id or uuid4().hex
        try:
            self.run_repository.start(
                resolved_run_id,
                competitor_id=competitor_id,
                company_id=company_id,
            )
        except DiscoveryRunAlreadyRunningError as exc:
            raise DiscoveryConflictError(
                f"discovery is already running for competitor {competitor_id!r}"
            ) from exc

        activated_target_ids: list[Any] = []
        deactivated_target_ids: list[Any] = []
        try:
            persisted = self._discover_website_impl(
                competitor_id,
                user_id=user_id,
                company_id=company_id,
            )
            persisted_by_url = {
                candidate.get("url"): candidate
                for candidate in persisted
                if isinstance(candidate.get("url"), str)
            }
            suggested_urls = set(self.last_discovered_suggested_urls)
            # The second-pass audit may discard a first-pass suggestion.  Its
            # persisted state is the final decision used by reconciliation.
            # The discard set is fully materialized before mutating
            # suggested_urls: passing a generator that still iterates
            # suggested_urls straight into its own difference_update() raises
            # "Set changed size during iteration" once anything is actually
            # removed.
            discarded_suggested_urls = {
                url
                for url in suggested_urls
                if persisted_by_url.get(url, {}).get("discovery_status")
                == "DISCARDED"
            }
            suggested_urls.difference_update(discarded_suggested_urls)

            for candidate in persisted:
                if (
                    candidate.get("url") in suggested_urls
                    and candidate.get("active") is not True
                    and candidate.get("discovery_status") in {"SUGGESTED", "ACTIVE"}
                ):
                    activated = self.activate_candidate(
                        candidate["id"],
                        company_id=company_id,
                    )
                    activated_target_ids.append(activated["id"])

            for target in active_before:
                if target.get("url") in suggested_urls:
                    continue
                self.remove_candidate(target["id"], company_id=company_id)
                deactivated_target_ids.append(target["id"])

            active_after = tuple(
                dict(target)
                for target in self.monitoring_target_repository.list_active_targets(
                    competitor_id
                )
            )
            self.run_repository.succeed(
                resolved_run_id,
                candidate_count=len(persisted),
                summary=_discovery_summary_payload(self.last_summary),
            )
        except Exception as exc:
            try:
                self.run_repository.fail(resolved_run_id, str(exc))
            except Exception:
                logger.exception(
                    "could not mark reconciliation run failed run_id=%s",
                    resolved_run_id,
                )
            raise

        return DiscoveryReconciliationResult(
            run_id=resolved_run_id,
            competitor_id=competitor_id,
            active_before=active_before,
            active_after=active_after,
            activated_target_ids=tuple(activated_target_ids),
            deactivated_target_ids=tuple(deactivated_target_ids),
            suggested_count=len(suggested_urls),
            discovered_count=len(persisted),
        )

    def get_discovery_run(
        self,
        run_id: str,
        *,
        company_id: Any = None,
    ) -> dict[str, Any]:
        """Read one discovery lifecycle record, enforcing company scope."""

        if self.run_repository is None:
            raise DiscoveryNotFoundError(f"discovery run {run_id!r} was not found")
        record = self.run_repository.get(run_id)
        if record is None:
            raise DiscoveryNotFoundError(f"discovery run {run_id!r} was not found")
        if company_id is not None:
            self._get_competitor(record.get("competitor_id"), company_id=company_id)
        return dict(record)

    def _discover_website_impl(
        self,
        competitor_id: Any,
        *,
        user_id: Optional[str] = None,
        company_id: Any = None,
    ) -> list[dict[str, Any]]:
        """Discover, classify, and persist Layer 2 candidates for one competitor."""

        self.last_discovered_suggested_urls = frozenset()

        if company_id is not None:
            competitor = self.competitor_repository.get(
                competitor_id,
                company_id=company_id,
            )
        else:
            competitor = self.competitor_repository.get(competitor_id, user_id=user_id)
        if competitor is None:
            raise DiscoveryNotFoundError(f"competitor {competitor_id!r} was not found")
        website_url = competitor["website_url"]

        source_candidates: dict[str, Sequence[DiscoveredURL]] = {}
        declared_sitemaps = self._safe_sitemap_declarations(website_url)
        source_candidates["SITEMAP"] = self._safe_sitemap_discovery(
            website_url,
            declared_sitemaps,
        )
        source_candidates["LINKS"] = self._safe_source_discovery(self.link_source, website_url)
        homepage_metadata = getattr(self.link_source, "last_homepage_metadata", {})
        if not isinstance(homepage_metadata, Mapping):
            homepage_metadata = {}

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

        fetched_meta_descriptions: dict[str, str | None] = {}

        def liveness_checker(url: str) -> FetchResult | bool:
            result = self.liveness_checker(url)
            if isinstance(result, FetchResult):
                fetched_meta_descriptions[url] = extract_meta_description(result.content)
            return result

        normalized = [
            replace(
                candidate,
                meta_description=fetched_meta_descriptions.get(candidate.url),
            )
            for candidate in _apply_liveness_gate(
                normalized,
                liveness_checker,
                attempts=self.liveness_attempts,
                backoff_seconds=self.liveness_backoff_seconds,
                sleep=self.liveness_sleep,
            )
            if not is_item_type_excluded(candidate.url)
        ]
        classification_inputs = tuple(
            CandidateForClassification(
                raw_url=candidate.raw_url,
                url=candidate.url,
                title=candidate.title,
                meta_description=candidate.meta_description,
                sources=(candidate.source,),
                force_discarded=candidate.force_discarded,
            )
            for candidate in normalized
        )
        classifications = classify_candidates(
            classification_inputs,
            self.fallback_classifier,
            batch_size=self.classifier_batch_size,
        )
        self.last_discovered_suggested_urls = frozenset(
            candidate.url
            for candidate, classification in zip(normalized, classifications)
            if classification.discovery_status == "SUGGESTED"
        )

        persisted: list[dict[str, Any]] = []
        audit_candidates: list[SuggestedCandidateForAudit] = []
        audit_rows_by_url: dict[str, dict[str, Any]] = {}
        for candidate, classification in zip(normalized, classifications):
            persisted_candidate = self.monitoring_target_repository.upsert_discovered_candidate(
                competitor_id=competitor_id,
                raw_url=candidate.raw_url,
                url=candidate.url,
                page_type=classification.page_type,
                discovery_source=candidate.source,
                discovery_status=classification.discovery_status,
                classification_method=classification.classification_method,
            )
            persisted.append(persisted_candidate)
            if (
                classification.discovery_status == "SUGGESTED"
                and not _is_activated(persisted_candidate)
            ):
                audit_candidates.append(
                    SuggestedCandidateForAudit(
                        url=candidate.url,
                        page_type=classification.page_type,
                        title=candidate.title,
                        meta_description=candidate.meta_description,
                    )
                )
                audit_rows_by_url.setdefault(candidate.url, persisted_candidate)
        self._reconcile_excluded_candidates(competitor_id)
        audited_updates = self._run_second_pass_audit(
            competitor_id,
            audit_candidates,
            audit_rows_by_url,
            homepage_title=homepage_metadata.get("title"),
            homepage_meta_description=homepage_metadata.get("meta_description"),
            user_id=user_id,
            company_id=company_id,
        )
        for index, candidate in enumerate(persisted):
            updated = audited_updates.get(candidate.get("id"))
            if updated is not None:
                persisted[index] = updated

        suggested_count = sum(
            candidate.get("discovery_status") == "SUGGESTED"
            for candidate in persisted
        )
        discarded_count = sum(
            candidate.get("discovery_status") == "DISCARDED"
            for candidate in persisted
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

    def _run_second_pass_audit(
        self,
        competitor_id: Any,
        candidates: Sequence[SuggestedCandidateForAudit],
        rows_by_url: Mapping[str, Mapping[str, Any]],
        *,
        homepage_title: str | None,
        homepage_meta_description: str | None,
        user_id: str | None,
        company_id: Any,
    ) -> dict[Any, dict[str, Any]]:
        """Audit pass-one suggestions and apply only safe narrowing actions.

        ``rows_by_url`` is built exclusively from pass-one rows whose status is
        SUGGESTED and which are not activated. The method has no promotion or
        creation operation: a provider can only identify one of those rows for
        the existing ``discard_candidate`` transition.
        """

        self.last_audit_result = None
        self.last_audit_error = None
        if isinstance(self.audit_classifier, NoopDiscoveryAudit):
            self.last_audit_error = "audit provider is not configured"
            return {}
        try:
            result = self.audit_classifier.audit(
                candidates,
                homepage_title=homepage_title,
                homepage_meta_description=homepage_meta_description,
            )
            if not isinstance(result, DiscoveryAuditResult):
                raise TypeError("audit classifier returned an invalid result")
        except Exception as exc:
            self.last_audit_error = str(exc)
            logger.warning(
                "discovery second-pass audit failed competitor=%s; preserving "
                "first-pass results: %s",
                competitor_id,
                exc,
            )
            return {}

        self.last_audit_result = result
        updated_rows: dict[Any, dict[str, Any]] = {}
        seen_urls: set[str] = set()
        for flag in result.flagged_redundant:
            if flag.url in seen_urls:
                continue
            seen_urls.add(flag.url)
            if not _is_high_confidence_redundancy(flag.reason):
                logger.warning(
                    "discovery audit ignored low-confidence redundancy "
                    "competitor=%s url=%s reason=%s",
                    competitor_id,
                    flag.url,
                    flag.reason,
                )
                continue
            row = rows_by_url.get(flag.url)
            if row is None:
                logger.warning(
                    "discovery audit ignored unknown/non-suggested URL competitor=%s url=%s",
                    competitor_id,
                    flag.url,
                )
                continue
            if not _has_structural_redundancy(flag.url, rows_by_url):
                logger.warning(
                    "discovery audit ignored structurally unproven redundancy "
                    "competitor=%s url=%s",
                    competitor_id,
                    flag.url,
                )
                continue
            try:
                updated_rows[row["id"]] = self.discard_candidate(
                    row["id"],
                    company_id=company_id,
                )
            except Exception as exc:
                logger.warning(
                    "discovery audit could not discard flagged candidate=%s: %s",
                    row.get("id"),
                    exc,
                )

        gap_flags = [
            {"page_type": flag.page_type, "reason": flag.reason}
            for flag in result.flagged_missing_categories
        ]
        self._persist_discovery_gap_flags(
            competitor_id,
            gap_flags,
            user_id=user_id,
            company_id=company_id,
        )
        return updated_rows

    def _persist_discovery_gap_flags(
        self,
        competitor_id: Any,
        flags: Sequence[Mapping[str, str]],
        *,
        user_id: str | None,
        company_id: Any,
    ) -> None:
        """Persist successful audit gap findings without blocking discovery."""

        scope: dict[str, Any] = {}
        if company_id is not None:
            scope["company_id"] = company_id
        elif user_id is not None:
            scope["user_id"] = user_id
        try:
            updated = self.competitor_repository.update(
                competitor_id,
                {"discovery_gap_flags": [dict(flag) for flag in flags]},
                **scope,
            )
            if updated is None:
                raise DiscoveryError("competitor record was not found")
        except Exception as exc:
            logger.warning(
                "could not persist discovery gap flags competitor=%s: %s",
                competitor_id,
                exc,
            )

    def _reconcile_excluded_candidates(self, competitor_id: Any) -> None:
        """Repair old discovery rows that now match an item/detail exclusion.

        Discovery sources can change between runs, so an old candidate is not
        guaranteed to be emitted again. Newly learned exclusion patterns must
        therefore also be applied to existing, unactivated discovery rows;
        active targets and user-created manual rows remain untouched.
        """

        self.monitoring_target_repository.discard_discovered_candidates_by_url_patterns(
            competitor_id,
            url_patterns=tuple(
                pattern.pattern.removeprefix("^")
                for pattern in ITEM_TYPE_EXCLUSION_PATTERNS
            )
        )

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


def _default_classifier() -> CandidateClassifier:
    """Use configured OpenAI classification without making configuration fatal.

    Discovery remains usable in environments without an API key. Runtime
    provider failures are handled by ``classify_candidates``; configuration
    failures at startup use the same deterministic discarded fallback.
    """

    try:
        return OpenAIClassifier.from_env()
    except OpenAIClassifierConfigurationError as exc:
        logger.warning(
            "OpenAI candidate classifier is unavailable; using deterministic "
            "discarded fallback: %s",
            exc,
        )
        return DeterministicStubClassifier()


def _default_discovery_audit() -> DiscoveryAuditClassifier:
    """Use the configured holistic audit without making startup fatal."""

    try:
        return OpenAIDiscoveryAudit.from_env()
    except DiscoveryAuditConfigurationError as exc:
        logger.warning(
            "OpenAI discovery audit is unavailable; using a no-op audit: %s",
            exc,
        )
        return NoopDiscoveryAudit()


def configured_discovery_audit() -> DiscoveryAuditClassifier:
    """Return the production-configured auditor or its safe no-op fallback."""

    return _default_discovery_audit()


def _discovery_summary_payload(summary: DiscoverySummary | None) -> dict[str, Any] | None:
    """Convert the in-process summary into a compact persisted API shape."""

    if summary is None:
        return None
    return {
        "website_url": summary.website_url,
        "raw_count": summary.raw_count,
        "normalized_count": summary.normalized_count,
        "suggested_count": summary.suggested_count,
        "discarded_count": summary.discarded_count,
        "source_breakdown": {
            source: {
                "raw_count": details.raw_count,
                "normalized_count": details.normalized_count,
                "sampled_count": details.sampled_count,
                "declared_sitemaps": details.declared_sitemaps,
            }
            for source, details in summary.source_breakdown.items()
        },
    }


def _is_activated(candidate: Mapping[str, Any]) -> bool:
    return bool(candidate.get("active")) or candidate.get("discovery_status") == "ACTIVE"


def _is_active_target(candidate: Mapping[str, Any]) -> bool:
    """Return whether a row is a valid, already-active target."""

    return (
        candidate.get("active") is True
        and candidate.get("discovery_status") == "ACTIVE"
    )


_REDUNDANCY_HEDGE_TERMS = (
    "likely",
    "possibly",
    "could be",
    "might be",
    "may be",
    "appears to",
    "unless",
)


def _is_high_confidence_redundancy(reason: str) -> bool:
    """Reject speculative model flags before they can narrow production data."""

    normalized = reason.casefold()
    return not any(term in normalized for term in _REDUNDANCY_HEDGE_TERMS)


def _has_structural_redundancy(
    url: str,
    rows_by_url: Mapping[str, Mapping[str, Any]],
) -> bool:
    """Require an obvious URL relationship before auto-discarding a row.

    A flat, descriptive page such as ``/pittsburgh-seo-company`` is not
    automatically redundant with ``/services`` just because both were typed
    SERVICES. Nested section/filter variants such as ``/men/sale`` versus
    ``/sale`` are structurally comparable and can be narrowed when the audit
    also supplies a high-confidence reason.
    """

    candidate = urlsplit(url)
    candidate_path = [part for part in candidate.path.split("/") if part]
    for other_url in rows_by_url:
        if other_url == url:
            continue
        other = urlsplit(other_url)
        if candidate.netloc != other.netloc:
            continue
        if candidate.path == other.path and candidate.query != other.query:
            return True
        other_path = [part for part in other.path.split("/") if part]
        if not candidate_path or not other_path or len(candidate_path) == len(other_path):
            continue
        shorter, longer = (
            (candidate_path, other_path)
            if len(candidate_path) < len(other_path)
            else (other_path, candidate_path)
        )
        if longer[: len(shorter)] == shorter or longer[-len(shorter) :] == shorter:
            return True
    return False


def _candidate_url_for_competitor(url: str, competitor_url: str) -> str:
    try:
        canonical_url = canonicalize_raw_url(url)
    except (TypeError, ValueError) as exc:
        raise DiscoveryError(f"candidate URL is invalid: {exc}") from exc
    if not is_same_site(competitor_url, canonical_url):
        raise DiscoveryError("candidate URL must belong to the competitor's website")
    if not is_html_candidate_url(canonical_url):
        raise DiscoveryError("candidate URL must refer to an HTML page")

    normalized_url = normalize_url(canonical_url)
    if is_system_path(normalized_url):
        raise DiscoveryError("candidate URL cannot be a system or taxonomy path")
    return normalized_url


def _has_positive_interval(value: Any) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and value > 0
    )


def _resolve_manual_page_type(url: str, page_type: str | None) -> str:
    """Resolve an explicit or rule-derived page type for a manual target."""

    if page_type is not None:
        if not isinstance(page_type, str) or not page_type.strip():
            raise DiscoveryError("manual target page_type must be a non-empty string")
        return page_type.strip().upper()

    rule_result = classify_by_rules(
        CandidateForClassification(raw_url=url, url=url)
    )
    return rule_result.page_type if rule_result is not None else "OTHER"


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
            force_discarded = (
                candidate.force_discarded
                or discovery_scope(raw_url) == "UNMATCHED"
                or is_item_type_excluded(raw_url)
            )
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
    *,
    attempts: int = DEFAULT_LIVENESS_ATTEMPTS,
    backoff_seconds: float = DEFAULT_LIVENESS_BACKOFF_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
) -> list[_NormalizedCandidate]:
    """Discard index candidates only after repeated confirmation of a dead URL.

    This gate is the final Layer 1 step after URL normalization and before
    Stage 2 classification. It checks every normalized index candidate; source
    provenance may still force a candidate to DISCARDED, but it never bypasses
    the liveness check. The default checker is ``fetch_page`` from the Layer 2
    service, so HTTP-first and injected-browser behavior stay in one place.

    Only repeated HTTP 404/410 results are considered confirmation that the
    normalized page is dead. Transport errors, missing browser fallback,
    anti-bot responses such as 403/429, server errors, and other unusable
    results are inconclusive and leave the candidate eligible for suggestion.
    """

    gated: list[_NormalizedCandidate] = []
    for candidate in candidates:
        if discovery_scope(candidate.url) != "INDEX":
            gated.append(candidate)
            continue

        decision = _confirm_liveness(
            candidate.url,
            liveness_checker,
            attempts=attempts,
            backoff_seconds=backoff_seconds,
            sleep=sleep,
        )
        if decision == "DEAD":
            gated.append(replace(candidate, force_discarded=True))
        else:
            gated.append(candidate)
    return gated


def _confirm_liveness(
    url: str,
    liveness_checker: LivenessChecker,
    *,
    attempts: int,
    backoff_seconds: float,
    sleep: Callable[[float], None],
) -> str:
    """Return LIVE, DEAD, or INCONCLUSIVE after bounded liveness attempts."""

    permanent_failures = 0
    for attempt in range(1, attempts + 1):
        try:
            result = liveness_checker(url)
        except (MonitoringError, ValueError) as exc:
            status = getattr(exc, "http_status", None)
            is_permanent = _is_confirmable_dead_status(status)
            permanent_failures += is_permanent
            logger.info(
                "Layer 1 liveness attempt=%d/%d url=%s status=%s "
                "failure=%s",
                attempt,
                attempts,
                url,
                status,
                exc,
            )
        else:
            is_live = (
                result
                if isinstance(result, bool)
                else isinstance(result, FetchResult)
            )
            if is_live:
                if attempt > 1:
                    logger.info(
                        "Layer 1 liveness recovered url=%s attempt=%d/%d",
                        url,
                        attempt,
                        attempts,
                    )
                return "LIVE"
            logger.info(
                "Layer 1 liveness attempt=%d/%d url=%s returned an "
                "inconclusive unusable result",
                attempt,
                attempts,
            )

        if attempt < attempts:
            sleep(backoff_seconds)

    if permanent_failures == attempts:
        logger.info(
            "Layer 1 liveness confirmed dead url=%s attempts=%d",
            url,
            attempts,
        )
        return "DEAD"
    logger.info(
        "Layer 1 liveness inconclusive url=%s attempts=%d; candidate retained",
        url,
        attempts,
    )
    return "INCONCLUSIVE"


def _is_confirmable_dead_status(status: Any) -> bool:
    return isinstance(status, int) and status in {404, 410}


def _canonicalize_for_site(url: str, site_url: str) -> str:
    """Use the configured competitor host for same-site URL deduplication."""

    candidate = urlsplit(url)
    site = urlsplit(site_url)
    return urlunsplit((site.scheme, site.netloc, candidate.path, candidate.query, ""))
