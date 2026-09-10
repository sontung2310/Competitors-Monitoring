"""Change creation from already-different snapshots.

Hash comparison and the mechanical diff remain deterministic and upstream in
the monitoring engine. This service defensively rejects equal hashes so an
accidental call cannot create a false change record. Eligible blog and generic
page changes may also receive an optional LLM narrative; its failure never
prevents the mechanical change record from being persisted.

BLOG and PRICING receive special whole-page event types here. Production
PRODUCTS targets are routed through ``ProductListingProcessor``, which emits
the structured NEW_PRODUCT, PRODUCT_REMOVED, and PRICE_CHANGE events; this
module's direct ``derive_change_type("PRODUCTS")`` fallback remains
PAGE_UPDATE. NEWS, SERVICES, and PRESS use the generic PAGE_UPDATE mapping.

The default change status is ``NEW``. It means the change was detected and has
not yet been reviewed by a future presentation layer. A later frontend can add
reviewed/read states without changing the persistence contract or conflating
detection with user acknowledgement.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Mapping, Optional, Protocol
from urllib.parse import urljoin, urlsplit

from backend.flask.database.base_repository import utc_now
from backend.flask.llm_provider import OpenAIProvider
from backend.flask.website_monitoring.service import (
    compare_hashes,
    generate_diff,
)

from .repository import ChangeRepository


logger = logging.getLogger(__name__)


class ChangeError(RuntimeError):
    """Raised when a change cannot be created safely."""

    status_code = 400
    code = "validation_error"


class ChangeNotFoundError(ChangeError):
    """Raised when a requested target used to scope changes is absent."""

    status_code = 404
    code = "not_found"


class MonitoringTargetReader(Protocol):
    """Repository boundary used to resolve a target's page type."""

    def get(self, target_id: Any, *, competitor_id: Any | None = None) -> Optional[dict[str, Any]]:
        """Return target metadata."""


SnapshotContentLoader = Callable[[Mapping[str, Any]], str]

CHANGE_TYPE_BY_PAGE_TYPE = {
    "BLOG": "NEW_BLOG",
    "PRICING": "PRICE_CHANGE",
}
NARRATIVE_CHANGE_TYPES = frozenset({"NEW_BLOG", "PAGE_UPDATE"})
PROCESSOR_CHANGE_TYPES = frozenset(
    {"NEW_PRODUCT", "PRODUCT_REMOVED", "PRICE_CHANGE"}
)
DEFAULT_CHANGE_TYPE = "PAGE_UPDATE"
DEFAULT_CHANGE_STATUS = "NEW"
NARRATIVE_RESPONSE_FORMAT = {
    "type": "json_schema",
    "name": "change_narrative_and_detected_url",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "narrative_summary": {"type": "string"},
            "detected_url": {"type": ["string", "null"]},
        },
        "required": ["narrative_summary", "detected_url"],
    },
}
NARRATIVE_SUMMARY_INSTRUCTIONS = """You write concise plain-language summaries for a competitor monitoring feed.
Describe only observable changes in the supplied page diff. Do not speculate about
reasons, intent, or business impact. Do not mention line counts, the diff, or these
instructions. Return a JSON object with exactly these fields:
- narrative_summary: one or two sentences of narrative text, with no markdown heading or preamble.
- detected_url: the specific new post URL only when the supplied diff contains enough
  evidence to identify one; otherwise null. Copy the URL exactly from the diff and
  never invent or guess one. For PAGE_UPDATE, return null when the change is a
  wording or layout edit without a specific new post.
"""


@dataclass(frozen=True)
class NarrativeSummaryResult:
    """Structured output from the single narrative-and-URL LLM call."""

    narrative_summary: str
    detected_url: str | None


DetectedURLLivenessChecker = Callable[[str], Any]


class ChangeService:
    """Generate a deterministic diff, classify it, and persist one record."""

    def __init__(
        self,
        change_repository: ChangeRepository,
        monitoring_target_repository: MonitoringTargetReader,
        *,
        snapshot_content_loader: Optional[SnapshotContentLoader] = None,
        competitor_repository: Any | None = None,
        narrative_provider_factory: Callable[[], Any] = OpenAIProvider.from_env,
        detected_url_liveness_checker: DetectedURLLivenessChecker | None = None,
    ) -> None:
        self.change_repository = change_repository
        self.monitoring_target_repository = monitoring_target_repository
        self.snapshot_content_loader = snapshot_content_loader
        self.competitor_repository = competitor_repository
        self.narrative_provider_factory = narrative_provider_factory
        self.detected_url_liveness_checker = detected_url_liveness_checker

    @classmethod
    def from_database(
        cls,
        database: Any,
        monitoring_target_repository: MonitoringTargetReader,
        *,
        snapshot_content_loader: Optional[SnapshotContentLoader] = None,
        competitor_repository: Any | None = None,
        narrative_provider_factory: Callable[[], Any] = OpenAIProvider.from_env,
        detected_url_liveness_checker: DetectedURLLivenessChecker | None = None,
    ) -> "ChangeService":
        """Build a service with a repository backed by a database handle."""

        return cls(
            ChangeRepository.from_database(database),
            monitoring_target_repository,
            snapshot_content_loader=snapshot_content_loader,
            competitor_repository=competitor_repository,
            narrative_provider_factory=narrative_provider_factory,
            detected_url_liveness_checker=detected_url_liveness_checker,
        )

    def create_change(
        self,
        target_id: Any,
        previous_snapshot: Mapping[str, Any],
        current_snapshot: Mapping[str, Any],
        *,
        detected_at: Optional[datetime] = None,
        change_type: Optional[str] = None,
        summary: Optional[str] = None,
        narrative_provider: Any | None = None,
        detected_url: str | None = None,
    ) -> dict[str, Any]:
        """Persist a change from two snapshots whose hashes differ.

        Snapshot records may include their loaded content under ``content`` or
        ``normalized_content``. For metadata-only records, callers inject a
        ``snapshot_content_loader`` that reads the content through the snapshot
        storage layer; this service never touches the filesystem directly.
        """

        _require_snapshot_mapping(previous_snapshot, "previous_snapshot")
        _require_snapshot_mapping(current_snapshot, "current_snapshot")
        previous_hash = _snapshot_hash(previous_snapshot, "previous_snapshot")
        current_hash = _snapshot_hash(current_snapshot, "current_snapshot")
        if compare_hashes(previous_hash, current_hash):
            raise ChangeError(
                "create_change requires snapshots with different content_hash values"
            )

        target = self.monitoring_target_repository.get(target_id)
        if target is None:
            raise ChangeError(f"monitoring target {target_id!r} was not found")
        page_type = target.get("page_type")
        if not isinstance(page_type, str) or not page_type.strip():
            raise ChangeError(f"monitoring target {target_id!r} has no page_type")

        previous_content = self._load_content(previous_snapshot, "previous_snapshot")
        current_content = self._load_content(current_snapshot, "current_snapshot")
        diff = generate_diff(
            _diff_text(previous_content),
            _diff_text(current_content),
        )
        if not diff:
            raise ChangeError(
                "snapshot hashes differ but generate_diff returned no content"
            )

        if change_type is None:
            resolved_change_type = derive_change_type(page_type)
        else:
            if not isinstance(change_type, str) or not change_type.strip():
                raise ChangeError("change_type override must be a non-empty string")
            resolved_change_type = change_type.strip().upper()
        if summary is None:
            resolved_summary = summarize_diff(resolved_change_type, diff)
        else:
            if not isinstance(summary, str) or not summary.strip():
                raise ChangeError("summary override must be a non-empty string")
            resolved_summary = summary.strip()
        target_url = _target_url(target)
        narrative_summary = None
        resolved_detected_url = None
        if resolved_change_type in NARRATIVE_CHANGE_TYPES:
            # The target URL is the safe, deterministic fallback. A specific URL
            # is accepted only after same-domain and liveness validation.
            resolved_detected_url = target_url
            try:
                provider = (
                    narrative_provider
                    if narrative_provider is not None
                    else self.narrative_provider_factory()
                )
                narrative_result = generate_narrative_summary_with_url(
                    change_type=resolved_change_type,
                    diff=diff,
                    target_url=target_url,
                    page_type=page_type,
                    provider=provider,
                )
                narrative_summary = narrative_result.narrative_summary
                resolved_detected_url = resolve_blog_detected_url(
                    narrative_result.detected_url,
                    target_url,
                    liveness_checker=self.detected_url_liveness_checker,
                )
            except Exception as exc:
                # Narrative text enriches a change but must never make change
                # detection unavailable. The deterministic mechanical summary
                # remains the complete fallback display value.
                logger.warning(
                    "narrative summary generation failed for %s target %r; "
                    "persisting the mechanical summary only: %s",
                    resolved_change_type,
                    target_id,
                    exc,
                )
        elif resolved_change_type in PROCESSOR_CHANGE_TYPES:
            # ProductListingProcessor already extracted this URL. It is not an
            # LLM-derived value and PRODUCT_REMOVED deliberately skips every
            # liveness check so its last-known 404 remains informative.
            resolved_detected_url = resolve_product_detected_url(
                change_type=resolved_change_type,
                detected_url=detected_url,
                summary=resolved_summary,
                target_url=target_url,
            )
        return self.change_repository.create(
            monitoring_target_id=target_id,
            previous_snapshot_id=_snapshot_id(previous_snapshot, "previous_snapshot"),
            current_snapshot_id=_snapshot_id(current_snapshot, "current_snapshot"),
            detected_at=detected_at or utc_now(),
            change_type=resolved_change_type,
            summary=resolved_summary,
            narrative_summary=narrative_summary,
            detected_url=resolved_detected_url,
            status=DEFAULT_CHANGE_STATUS,
        )

    def _load_content(
        self,
        snapshot: Mapping[str, Any],
        label: str,
    ) -> str:
        if self.snapshot_content_loader is not None:
            content = self.snapshot_content_loader(snapshot)
        else:
            content = snapshot.get("content")
            if content is None:
                content = snapshot.get("normalized_content")
        if not isinstance(content, str):
            raise ChangeError(
                f"{label} content is unavailable; inject a snapshot_content_loader"
            )
        return content

    def get_change(
        self,
        change_id: Any,
        *,
        company_id: Any | None = None,
    ) -> dict[str, Any] | None:
        """Return one persisted change for the read-only changes endpoint."""

        change = self.change_repository.get(change_id)
        if change is None or company_id is None:
            return change
        self._require_company_repository()
        target = self.monitoring_target_repository.get(change.get("monitoring_target_id"))
        if target is None:
            return None
        competitor = self.competitor_repository.get(
            target.get("competitor_id"),
            company_id=company_id,
        )
        return change if competitor is not None else None

    def list_changes(
        self,
        *,
        competitor_id: Any | None = None,
        target_id: Any | None = None,
        company_id: Any | None = None,
        since: datetime | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Read a bounded latest-change feed without bypassing repositories."""

        target_ids: list[Any] | None = None
        if company_id is not None:
            self._require_company_repository()
            scoped_competitors = self.competitor_repository.list_for_company(company_id)
            scoped_competitor_ids = [competitor["id"] for competitor in scoped_competitors]
            if competitor_id is not None and str(competitor_id) not in {
                str(value) for value in scoped_competitor_ids
            }:
                return []
            if target_id is not None:
                target = self.monitoring_target_repository.get(target_id)
                if target is None or str(target.get("competitor_id")) not in {
                    str(value) for value in scoped_competitor_ids
                }:
                    return []
            if competitor_id is None:
                target_ids = []
                for scoped_competitor_id in scoped_competitor_ids:
                    target_ids.extend(
                        target["id"]
                        for target in self.monitoring_target_repository.list_for_competitor(
                            scoped_competitor_id
                        )
                    )
        if target_id is not None:
            target = self.monitoring_target_repository.get(target_id)
            if target is None:
                raise ChangeNotFoundError(f"monitoring target {target_id!r} was not found")
            target_ids = [target_id]

        if competitor_id is not None:
            list_for_competitor = getattr(
                self.monitoring_target_repository,
                "list_for_competitor",
                None,
            )
            if not callable(list_for_competitor):
                raise ChangeError("target repository cannot scope changes by competitor")
            competitor_targets = list_for_competitor(competitor_id)
            competitor_target_ids = [target["id"] for target in competitor_targets]
            if target_ids is None:
                target_ids = competitor_target_ids
            else:
                allowed_ids = set(competitor_target_ids)
                target_ids = [value for value in target_ids if value in allowed_ids]

        return self.change_repository.list(
            monitoring_target_ids=target_ids,
            since=since,
            limit=limit,
        )

    def _require_company_repository(self) -> None:
        if self.competitor_repository is None:
            raise ChangeError("company-scoped changes require a competitor repository")


def create_change(
    target_id: Any,
    previous_snapshot: Mapping[str, Any],
    current_snapshot: Mapping[str, Any],
    *,
    change_repository: ChangeRepository,
    monitoring_target_repository: MonitoringTargetReader,
    snapshot_content_loader: Optional[SnapshotContentLoader] = None,
    detected_at: Optional[datetime] = None,
    change_type: Optional[str] = None,
    summary: Optional[str] = None,
    narrative_provider: Any | None = None,
    detected_url: str | None = None,
    narrative_provider_factory: Callable[[], Any] = OpenAIProvider.from_env,
    detected_url_liveness_checker: DetectedURLLivenessChecker | None = None,
) -> dict[str, Any]:
    """Functional entry point for repository-backed change creation."""

    return ChangeService(
        change_repository,
        monitoring_target_repository,
        snapshot_content_loader=snapshot_content_loader,
        narrative_provider_factory=narrative_provider_factory,
        detected_url_liveness_checker=detected_url_liveness_checker,
    ).create_change(
        target_id,
        previous_snapshot,
        current_snapshot,
        detected_at=detected_at,
        change_type=change_type,
        summary=summary,
        narrative_provider=narrative_provider,
        detected_url=detected_url,
    )


def derive_change_type(page_type: str) -> str:
    """Map supported page types to event types with a safe update fallback."""

    if not isinstance(page_type, str) or not page_type.strip():
        raise ValueError("page_type must be a non-empty string")
    return CHANGE_TYPE_BY_PAGE_TYPE.get(page_type.strip().upper(), DEFAULT_CHANGE_TYPE)


def summarize_diff(change_type: str, diff: str) -> str:
    """Return a short deterministic summary based on unified-diff statistics."""

    added_lines = 0
    removed_lines = 0
    added_characters = 0
    removed_characters = 0
    for line in diff.splitlines(keepends=True):
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            added_lines += 1
            added_characters += len(line[1:])
        elif line.startswith("-"):
            removed_lines += 1
            removed_characters += len(line[1:])
    return (
        f"{change_type}: {added_lines} line(s) added, {removed_lines} line(s) removed "
        f"({added_characters} characters added, {removed_characters} removed)."
    )


def generate_narrative_summary(
    *,
    change_type: str,
    diff: str,
    target_url: str,
    page_type: str,
    provider: Any,
) -> str:
    """Ask the shared LLM provider to describe one eligible page change.

    This compatibility wrapper preserves the original text-only helper API;
    the underlying call also returns the optional detected URL.
    """

    return generate_narrative_summary_with_url(
        change_type=change_type,
        diff=diff,
        target_url=target_url,
        page_type=page_type,
        provider=provider,
    ).narrative_summary


def generate_narrative_summary_with_url(
    *,
    change_type: str,
    diff: str,
    target_url: str,
    page_type: str,
    provider: Any,
) -> NarrativeSummaryResult:
    """Make one structured narrative call and return its optional URL.

    Real providers implement ``generate_json`` and therefore receive strict
    JSON-schema output. A small text-only compatibility path remains for older
    injected test doubles; it treats their plain string as the narrative and
    safely supplies no candidate URL.
    """

    if change_type not in NARRATIVE_CHANGE_TYPES:
        raise ValueError(f"narrative summaries are not supported for {change_type!r}")
    if not isinstance(diff, str) or not diff.strip():
        raise ValueError("narrative summary diff must be non-empty")
    if not isinstance(target_url, str) or not target_url.strip():
        raise ValueError("narrative summary target_url must be non-empty")
    if not isinstance(page_type, str) or not page_type.strip():
        raise ValueError("narrative summary page_type must be non-empty")
    if provider is None or not any(
        callable(getattr(provider, method, None))
        for method in ("generate", "generate_json")
    ):
        raise ValueError(
            "narrative summary provider must implement generate or generate_json"
        )

    prompt = (
        "Target URL: "
        f"{target_url.strip()}\n"
        f"Page type: {page_type.strip().upper()}\n\n"
        "Describe what changed in this page:\n"
        "<page-diff>\n"
        f"{diff}\n"
        "</page-diff>"
    )
    generate_json = getattr(provider, "generate_json", None)
    if callable(generate_json):
        payload = generate_json(
            prompt,
            instructions=NARRATIVE_SUMMARY_INSTRUCTIONS,
            response_format=NARRATIVE_RESPONSE_FORMAT,
        )
        return _parse_narrative_result(payload)

    # Compatibility for the pre-structured provider doubles used by older
    # callers. This is still one provider call and cannot produce a URL unless
    # a future double implements the structured method above.
    output = provider.generate(
        prompt,
        instructions=NARRATIVE_SUMMARY_INSTRUCTIONS,
        response_format=NARRATIVE_RESPONSE_FORMAT,
    )
    if not isinstance(output, str) or not output.strip():
        raise ValueError("narrative summary provider returned empty output")
    try:
        payload = json.loads(output)
    except (TypeError, json.JSONDecodeError):
        return NarrativeSummaryResult(output.strip(), None)
    return _parse_narrative_result(payload)


def resolve_blog_detected_url(
    candidate: Any,
    target_url: str,
    *,
    liveness_checker: DetectedURLLivenessChecker | None = None,
) -> str:
    """Return a validated blog URL, or the monitored target URL as fallback."""

    fallback = _require_http_url(target_url, "target_url")
    if not isinstance(candidate, str) or not candidate.strip():
        return fallback
    try:
        resolved = _require_http_url(
            urljoin(fallback, candidate.strip()),
            "detected_url",
        )
    except ValueError:
        return fallback
    if not _same_domain(resolved, fallback):
        logger.warning(
            "rejecting detected URL from a different domain: %s (target %s)",
            resolved,
            fallback,
        )
        return fallback

    checker = liveness_checker or _default_detected_url_liveness_checker
    try:
        result = checker(resolved)
    except Exception as exc:
        logger.warning("detected URL liveness check failed for %s: %s", resolved, exc)
        return fallback
    if not _is_usable_liveness_result(result):
        logger.warning("detected URL failed liveness validation: %s", resolved)
        return fallback
    return resolved


def resolve_product_detected_url(
    *,
    change_type: str,
    detected_url: Any,
    summary: str,
    target_url: str,
) -> str:
    """Resolve a structured product path into the absolute last-known URL.

    No network request is made here. In particular, a removed product's 404 is
    the expected evidence and must not cause this URL to be replaced.
    """

    fallback_candidate = _product_url_from_summary(summary)
    candidate = (
        detected_url
        if isinstance(detected_url, str) and detected_url.strip()
        else fallback_candidate
    )
    if not isinstance(candidate, str) or not candidate.strip():
        if change_type == "PRODUCT_REMOVED":
            raise ChangeError("product removal has no last-known product URL")
        # Legacy PRICING targets can derive PRICE_CHANGE without structured
        # product-card data. Keep those links useful while structured product
        # events always provide their exact extracted path above.
        candidate = _require_http_url(target_url, "target_url")
    return _require_http_url(
        urljoin(_require_http_url(target_url, "target_url"), candidate.strip()),
        "detected_url",
    )


def _parse_narrative_result(payload: Any) -> NarrativeSummaryResult:
    if not isinstance(payload, Mapping):
        raise ValueError("narrative summary provider returned a non-object")
    narrative = payload.get("narrative_summary")
    if not isinstance(narrative, str) or not narrative.strip():
        raise ValueError("narrative summary provider returned empty narrative_summary")
    detected_url = payload.get("detected_url")
    if detected_url is not None and not isinstance(detected_url, str):
        # Treat malformed optional output as an extraction failure while still
        # preserving the useful narrative text.
        detected_url = None
    return NarrativeSummaryResult(
        narrative.strip(), detected_url.strip() if detected_url else None
    )


def _default_detected_url_liveness_checker(url: str) -> Any:
    # Keep this import local to avoid coupling module initialization to the
    # content-processor import cycle.
    from backend.flask.website_monitoring.service import fetch_page

    return fetch_page(url)


def _is_usable_liveness_result(result: Any) -> bool:
    if isinstance(result, bool):
        return result
    if result is None:
        return False
    # fetch_page returns only after the existing status/content-type/visible
    # text heuristic succeeds. Accept that successful result directly.
    from backend.flask.website_monitoring.service import (
        FetchResult,
        HttpResponse,
        _is_usable_http_response,
    )

    if isinstance(result, FetchResult):
        return True
    if isinstance(result, HttpResponse):
        return _is_usable_http_response(result)
    return bool(result)


def _same_domain(candidate_url: str, target_url: str) -> bool:
    candidate_host = (urlsplit(candidate_url).hostname or "").lower().removeprefix("www.")
    target_host = (urlsplit(target_url).hostname or "").lower().removeprefix("www.")
    return bool(candidate_host) and candidate_host == target_host


def _require_http_url(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty URL")
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{field} must be an absolute HTTP or HTTPS URL")
    return value.strip()


def _product_url_from_summary(summary: str) -> str | None:
    if not isinstance(summary, str):
        return None
    # NEW_PRODUCT / PRODUCT_REMOVED end after the path. PRICE_CHANGE adds a
    # colon and the old/new prices after it.
    match = re.search(r"\bat\s+(\S+?)(?::\s+\S+\s+->|$)", summary)
    return match.group(1) if match else None


def _diff_text(content: str) -> str:
    """Give line-oriented diffs a terminator without changing page content."""

    return content if content.endswith("\n") else f"{content}\n"


def _require_snapshot_mapping(snapshot: Any, label: str) -> None:
    if not isinstance(snapshot, Mapping):
        raise TypeError(f"{label} must be a mapping")


def _snapshot_hash(snapshot: Mapping[str, Any], label: str) -> str:
    value = snapshot.get("content_hash")
    if not isinstance(value, str) or not value.strip():
        raise ChangeError(f"{label} has no content_hash")
    return value


def _snapshot_id(snapshot: Mapping[str, Any], label: str) -> Any:
    value = snapshot.get("id", snapshot.get("_id"))
    if value is None:
        raise ChangeError(f"{label} has no id")
    return value


def _target_url(target: Mapping[str, Any]) -> str:
    value = target.get("url")
    if not isinstance(value, str) or not value.strip():
        raise ChangeError("monitoring target has no url")
    return value.strip()
