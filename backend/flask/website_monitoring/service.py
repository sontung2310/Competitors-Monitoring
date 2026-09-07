"""Layer 2 fetch, comparison, and monitoring-run orchestration.

The low-level fetch/normalize/hash/diff functions remain usable independently,
while :class:`MonitoringRunService` composes them with the repository-backed
snapshot and change services. Concurrency and scheduling remain separate
roadmap concerns.

HTTP usability heuristic
------------------------
An HTTP response is usable when its status is in the 200-399 range, its
Content-Type is HTML/XHTML (or is not supplied), and it contains at least 40
characters of visible text after scripts, styles, templates, noscript blocks,
comments, and explicitly hidden elements are removed. This catches error
pages, empty SPA shells, and non-HTML resources without requiring a browser
for ordinary HTML pages. A response that fails any check is eligible for the
injected browser fallback; transport errors remain errors because there is no
HTTP response to assess.
"""

from __future__ import annotations

import difflib
import hashlib
import html
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from html.parser import HTMLParser
from typing import Any, Callable, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from backend.flask.database.base_repository import utc_now

from .content_processing import (
    ContentProcessor,
    resolve_content_processor,
)
from .repository import (
    DEFAULT_RUN_STALE_AFTER,
    MonitoringRunRepository,
    MonitoringTargetRepository,
    RunAlreadyClaimedError,
)


HTTP_FETCH_METHOD = "HTTP"
BROWSER_FETCH_METHOD = "BROWSER"
MIN_RENDERABLE_TEXT_LENGTH = 40
DEFAULT_HTTP_TIMEOUT_SECONDS = 15


class MonitoringError(RuntimeError):
    """Raised when a monitoring operation cannot produce a valid result."""


class BrowserFetchError(MonitoringError):
    """Raised when browser fallback is required but cannot be completed."""

    def __init__(self, message: str, *, http_status: int | None = None) -> None:
        super().__init__(message)
        self.http_status = http_status


@dataclass(frozen=True)
class HttpResponse:
    """Small fetcher response boundary used by the default and test fetchers."""

    content: str
    http_status: int
    headers: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class FetchResult:
    """Content and provenance returned by :func:`fetch_page`."""

    content: str
    fetch_method: str
    http_status: int | None

    def __iter__(self):
        """Allow backwards-friendly tuple unpacking of the three result fields."""

        yield self.content
        yield self.fetch_method
        yield self.http_status


class PageFetcher(Protocol):
    """Protocol implemented by HTTP and browser fetch adapters."""

    def fetch(self, url: str) -> HttpResponse | FetchResult:
        """Fetch one URL and return its response."""


class HttpPageFetcher:
    """Minimal HTTP adapter for ordinary server-rendered pages."""

    def __init__(
        self,
        *,
        timeout_seconds: float = DEFAULT_HTTP_TIMEOUT_SECONDS,
        user_agent: str = "CompetitorsMonitoring/1.0",
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.user_agent = user_agent

    def fetch(self, url: str) -> HttpResponse:
        _validate_url(url)
        request = Request(
            url,
            headers={
                "Accept": "text/html,application/xhtml+xml",
                "User-Agent": self.user_agent,
            },
            method="GET",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                return HttpResponse(
                    content=_decode_response_body(response),
                    http_status=int(response.getcode()),
                    headers=_response_headers(response),
                )
        except HTTPError as exc:
            # HTTPError is also a file-like response, so preserve its body for
            # the usability check and possible browser fallback.
            try:
                body = exc.read()
            except Exception:
                body = b""
            return HttpResponse(
                content=_decode_bytes(body, _header_charset(exc.headers)),
                http_status=int(exc.code),
                headers=_response_headers(exc),
            )
        except (URLError, TimeoutError, OSError) as exc:
            raise MonitoringError(f"HTTP fetch failed for {url!r}") from exc


class BrowserPageFetcher:
    """Explicit browser adapter boundary.

    The repository has no browser runtime dependency yet. Applications that
    provide one inject an object implementing ``fetch`` (or a callable) into
    :func:`fetch_page`. Keeping this default explicit prevents a silent switch
    to a local-only or fake browser implementation in production.
    """

    def fetch(self, url: str) -> HttpResponse:
        raise BrowserFetchError(
            "browser fallback is required for {!r}, but no browser fetcher is configured".format(
                url
            )
        )


def fetch_page(
    url: str,
    *,
    http_fetcher: PageFetcher | Callable[[str], HttpResponse | FetchResult] | None = None,
    browser_fetcher: PageFetcher | Callable[[str], HttpResponse | FetchResult] | None = None,
) -> FetchResult:
    """Fetch a page over HTTP and use browser rendering only when necessary.

    A browser is not used merely because a page contains JavaScript. The HTTP
    result must first fail the documented usability heuristic. Fetcher
    injection makes the browser boundary deterministic in unit tests and
    allows a later browser adapter to be added without changing this service.
    """

    _validate_url(url)
    resolved_http_fetcher = http_fetcher or HttpPageFetcher()
    http_result = _coerce_response(_call_fetcher(resolved_http_fetcher, url))
    if _is_usable_http_response(http_result):
        return FetchResult(
            content=http_result.content,
            fetch_method=HTTP_FETCH_METHOD,
            http_status=http_result.http_status,
        )

    resolved_browser_fetcher = browser_fetcher or BrowserPageFetcher()
    try:
        browser_result = _coerce_response(
            _call_fetcher(resolved_browser_fetcher, url)
        )
    except BrowserFetchError as exc:
        if exc.http_status is not None:
            raise
        raise BrowserFetchError(
            f"browser fetch failed for {url!r}",
            http_status=http_result.http_status,
        ) from exc
    except Exception as exc:
        raise BrowserFetchError(
            f"browser fetch failed for {url!r}",
            http_status=http_result.http_status,
        ) from exc
    if not _is_usable_http_response(browser_result):
        raise BrowserFetchError(
            f"browser fetch returned an unusable response for {url!r}",
            http_status=browser_result.http_status,
        )
    return FetchResult(
        content=browser_result.content,
        fetch_method=BROWSER_FETCH_METHOD,
        http_status=browser_result.http_status,
    )


def normalize_content(raw_content: str) -> str:
    """Return deterministic canonical HTML suitable for content hashing.

    The normalizer removes non-visible script/style/template/noscript content,
    comments, content with an explicit ``hidden`` attribute, and content with
    inline ``display: none`` or ``visibility: hidden`` declarations. It also
    removes known request/render tokens and cache-busting URL parameters,
    sorts attributes, and collapses text whitespace. Business content,
    meaningful URL parameters, element structure, and non-volatile attributes
    remain in the canonical form, so a real page change still changes the
    result.

    Visibility is intentionally limited to explicit signals present in the
    captured HTML. The parser does not attempt to evaluate external stylesheets
    or infer whether a JavaScript-controlled interactive element will become
    visible after a user action. This prevents static consent, utility, menu,
    and A/B-variant markup from entering the hash without pretending that a
    text normalizer can model every interactive UI state.
    """

    if not isinstance(raw_content, str):
        raise TypeError("raw_content must be a string")
    parser = _CanonicalHTMLParser()
    parser.feed(raw_content)
    parser.close()
    return parser.result()


def hash_content(normalized_content: str) -> str:
    """Return the deterministic SHA-256 digest of canonical content."""

    if not isinstance(normalized_content, str):
        raise TypeError("normalized_content must be a string")
    return hashlib.sha256(normalized_content.encode("utf-8")).hexdigest()


def compare_hashes(previous_hash: str, current_hash: str) -> bool:
    """Return ``True`` when two content hashes represent the same content."""

    return previous_hash == current_hash


def generate_diff(previous_content: str, current_content: str) -> str:
    """Generate a unified text diff for content that has already changed.

    Callers should compare hashes first and skip this function when they match.
    Returning an empty string for identical inputs keeps the function safe for
    defensive use while the service's intended fast path remains hash-first.
    """

    if not isinstance(previous_content, str) or not isinstance(current_content, str):
        raise TypeError("diff inputs must be strings")
    return "".join(
        difflib.unified_diff(
            previous_content.splitlines(keepends=True),
            current_content.splitlines(keepends=True),
            fromfile="previous",
            tofile="current",
        )
    )


class MonitoringRunError(MonitoringError):
    """Raised when a monitoring run cannot be started or finalized safely."""


class AlreadyRunningError(MonitoringRunError):
    """Raised when a non-stale run already owns the requested target."""


class SnapshotCreator(Protocol):
    """Repository-backed snapshot service boundary used by run orchestration."""

    def create_snapshot(
        self,
        target_id: Any,
        content: str,
        *,
        fetch_method: str,
        http_status: int,
        captured_at: datetime,
    ) -> dict[str, Any]:
        """Persist one successful normalized fetch."""


class SnapshotHistoryReader(Protocol):
    """Snapshot repository boundary used to find the previous valid snapshot."""

    def list_for_target(self, monitoring_target_id: Any) -> list[dict[str, Any]]:
        """Return snapshots newest first."""


SnapshotContentLoader = Callable[[Mapping[str, Any]], str]


class ChangeCreator(Protocol):
    """Repository-backed change service boundary used after a hash difference."""

    def create_change(
        self,
        target_id: Any,
        previous_snapshot: Mapping[str, Any],
        current_snapshot: Mapping[str, Any],
        *,
        detected_at: datetime,
    ) -> dict[str, Any]:
        """Persist one change derived from two different snapshots."""


class MonitoringRunService:
    """Run one target check and persist its complete lifecycle."""

    def __init__(
        self,
        target_repository: MonitoringTargetRepository,
        run_repository: MonitoringRunRepository,
        snapshot_repository: SnapshotHistoryReader,
        snapshot_service: SnapshotCreator,
        change_service: ChangeCreator,
        *,
        fetcher: Callable[[str], FetchResult] = fetch_page,
        clock: Callable[[], datetime] = utc_now,
        stale_after: timedelta = DEFAULT_RUN_STALE_AFTER,
        snapshot_content_loader: SnapshotContentLoader | None = None,
        content_processors: Mapping[str, ContentProcessor] | None = None,
    ) -> None:
        self.target_repository = target_repository
        self.run_repository = run_repository
        self.snapshot_repository = snapshot_repository
        self.snapshot_service = snapshot_service
        self.change_service = change_service
        self.fetcher = fetcher
        self.clock = clock
        self.stale_after = stale_after
        self.snapshot_content_loader = snapshot_content_loader
        self.content_processors = dict(content_processors or {})
        if isinstance(run_repository, MonitoringRunRepository):
            # The partial unique index is part of the runtime safety contract,
            # so repository-backed construction makes sure it exists before
            # the first claim attempt.
            run_repository.ensure_indexes()

    @classmethod
    def from_database(
        cls,
        database: Any,
        *,
        storage_root: str | None = None,
        fetcher: Callable[[str], FetchResult] = fetch_page,
        clock: Callable[[], datetime] = utc_now,
        stale_after: timedelta = DEFAULT_RUN_STALE_AFTER,
        content_processors: Mapping[str, ContentProcessor] | None = None,
    ) -> "MonitoringRunService":
        """Build the complete repository-backed monitoring service."""

        # These imports stay local because snapshot.service imports the
        # low-level fetch/normalization functions from this module.
        from backend.flask.change_detection.repository import ChangeRepository
        from backend.flask.change_detection.service import ChangeService
        from backend.flask.snapshot.repository import SnapshotRepository
        from backend.flask.snapshot.service import SnapshotService
        from backend.flask.snapshot.storage import SnapshotStorage

        target_repository = MonitoringTargetRepository.from_database(database)
        run_repository = MonitoringRunRepository.from_database(database)
        snapshot_repository = SnapshotRepository.from_database(database)
        storage = SnapshotStorage(storage_root)
        snapshot_service = SnapshotService(snapshot_repository, storage)
        snapshot_content_loader = lambda snapshot: storage.read_snapshot_bytes(
            snapshot["storage_path"]
        ).decode("utf-8")
        change_service = ChangeService(
            ChangeRepository.from_database(database),
            target_repository,
            snapshot_content_loader=snapshot_content_loader,
        )
        return cls(
            target_repository,
            run_repository,
            snapshot_repository,
            snapshot_service,
            change_service,
            fetcher=fetcher,
            clock=clock,
            stale_after=stale_after,
            snapshot_content_loader=snapshot_content_loader,
            content_processors=content_processors,
        )

    def monitor_target(self, target_id: Any) -> dict[str, Any]:
        """Execute one tracked attempt for an active monitoring target.

        ``last_checked_at`` is written immediately after the RUNNING record is
        created, so it records the last attempt even when fetching fails.
        Fetch failures return a FAILED run result and never reach snapshot or
        change creation. A successful fetch always creates a snapshot; change
        creation is limited to a different previous hash.
        """

        target = self.target_repository.get(target_id)
        if target is None:
            raise MonitoringRunError(f"monitoring target {target_id!r} was not found")
        if not _is_active_monitoring_target(target):
            raise MonitoringRunError(
                f"monitoring target {target_id!r} is not an active target"
            )

        started_at = self.clock()
        try:
            run = self.run_repository.claim(
                monitoring_target_id=target_id,
                started_at=started_at,
                stale_after=self.stale_after,
                now=started_at,
            )
        except RunAlreadyClaimedError as exc:
            raise AlreadyRunningError(str(exc)) from exc
        previous_snapshot: dict[str, Any] | None = None
        current_snapshot: dict[str, Any] | None = None
        change: dict[str, Any] | None = None

        try:
            checked_target = self.target_repository.update(
                target_id,
                {"last_checked_at": started_at},
            )
            if checked_target is None:
                raise MonitoringRunError(
                    f"monitoring target {target_id!r} disappeared before it was checked"
                )

            url = target.get("url")
            if not isinstance(url, str) or not url.strip():
                raise MonitoringRunError(
                    f"monitoring target {target_id!r} has no monitorable URL"
                )

            try:
                fetched = self.fetcher(url)
            except Exception as exc:
                raise MonitoringRunError(
                    f"fetch failed for {url!r}: {_exception_detail(exc)}"
                ) from exc
            _validate_fetch_result(fetched, url)

            snapshots = self.snapshot_repository.list_for_target(target_id)
            previous_snapshot = snapshots[0] if snapshots else None
            previous_snapshot = self._load_previous_snapshot_content(previous_snapshot)
            processor = resolve_content_processor(
                target.get("page_type"),
                self.content_processors,
            )
            process_result = processor.process(fetched.content, previous_snapshot)

            current_snapshot = self.snapshot_service.create_snapshot(
                target_id,
                process_result.snapshot_content,
                fetch_method=fetched.fetch_method,
                http_status=fetched.http_status,
                captured_at=self.clock(),
            )

            changes: list[dict[str, Any]] = []
            if process_result.changed:
                detected_at = self.clock()
                for _event in process_result.change_events:
                    changes.append(
                        self.change_service.create_change(
                            target_id,
                            previous_snapshot,
                            current_snapshot,
                            detected_at=detected_at,
                        )
                    )
                if changes:
                    changed_target = self.target_repository.update(
                        target_id,
                        {"last_changed_at": detected_at},
                    )
                    if changed_target is None:
                        raise MonitoringRunError(
                            f"monitoring target {target_id!r} disappeared while recording its change"
                        )
                change = changes[0] if len(changes) == 1 else None

            finished_at = self.clock()
            completed_run = self.run_repository.finish(
                run["id"],
                status=MonitoringRunRepository.SUCCESS,
                finished_at=finished_at,
            )
            if completed_run is None:
                raise MonitoringRunError(
                    f"monitoring run {run['id']!r} could not be marked SUCCESS"
                )
            return {
                "run": completed_run,
                "previous_snapshot": previous_snapshot,
                "snapshot": current_snapshot,
                "change": change,
                "changes": changes,
            }
        except Exception as exc:
            finished_at = self.clock()
            error_message = _monitoring_error_message(target_id, target, exc)
            failed_run = self.run_repository.finish(
                run["id"],
                status=MonitoringRunRepository.FAILED,
                finished_at=finished_at,
                error_message=error_message,
            )
            if failed_run is None:
                raise MonitoringRunError(
                    f"monitoring run {run['id']!r} failed and could not be finalized"
                ) from exc
            return {
                "run": failed_run,
                "previous_snapshot": previous_snapshot,
                "snapshot": current_snapshot,
                "change": change,
                "changes": [],
            }

    def _load_previous_snapshot_content(
        self,
        snapshot: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if snapshot is None or "content" in snapshot or "normalized_content" in snapshot:
            return snapshot
        if self.snapshot_content_loader is None:
            return snapshot
        loaded = dict(snapshot)
        loaded["content"] = self.snapshot_content_loader(snapshot)
        return loaded


def monitor_target(
    target_id: Any,
    *,
    target_repository: MonitoringTargetRepository,
    run_repository: MonitoringRunRepository,
    snapshot_repository: SnapshotHistoryReader,
    snapshot_service: SnapshotCreator,
    change_service: ChangeCreator,
    fetcher: Callable[[str], FetchResult] = fetch_page,
    clock: Callable[[], datetime] = utc_now,
    stale_after: timedelta = DEFAULT_RUN_STALE_AFTER,
    snapshot_content_loader: SnapshotContentLoader | None = None,
    content_processors: Mapping[str, ContentProcessor] | None = None,
) -> dict[str, Any]:
    """Functional entry point for one repository-backed monitoring attempt."""

    return MonitoringRunService(
        target_repository,
        run_repository,
        snapshot_repository,
        snapshot_service,
        change_service,
        fetcher=fetcher,
        clock=clock,
        stale_after=stale_after,
        snapshot_content_loader=snapshot_content_loader,
        content_processors=content_processors,
    ).monitor_target(target_id)


def _is_active_monitoring_target(target: Mapping[str, Any]) -> bool:
    return target.get("active") is True and target.get("discovery_status") == "ACTIVE"


def _validate_fetch_result(result: Any, url: str) -> None:
    if not isinstance(result, FetchResult):
        raise MonitoringRunError(
            f"fetcher returned an invalid result for {url!r}; expected FetchResult"
        )
    if not isinstance(result.content, str) or not result.content.strip():
        raise MonitoringRunError(f"fetch returned empty content for {url!r}")
    if result.fetch_method not in {HTTP_FETCH_METHOD, BROWSER_FETCH_METHOD}:
        raise MonitoringRunError(
            f"fetch returned invalid fetch_method {result.fetch_method!r} for {url!r}"
        )
    if (
        isinstance(result.http_status, bool)
        or not isinstance(result.http_status, int)
        or not 100 <= result.http_status <= 599
    ):
        raise MonitoringRunError(
            f"fetch returned invalid HTTP status for {url!r}: {result.http_status!r}"
        )


def _snapshot_hash(snapshot: Mapping[str, Any], target_id: Any) -> str:
    value = snapshot.get("content_hash")
    if not isinstance(value, str) or not value.strip():
        raise MonitoringRunError(
            f"previous snapshot for target {target_id!r} has no content_hash"
        )
    return value


def _exception_detail(exc: Exception) -> str:
    message = str(exc).strip()
    if message:
        return f"{exc.__class__.__name__}: {message}"
    return exc.__class__.__name__


def _monitoring_error_message(
    target_id: Any,
    target: Mapping[str, Any],
    exc: Exception,
) -> str:
    url = target.get("url") or "<missing URL>"
    return f"monitoring target {target_id!r} ({url!r}) failed: {_exception_detail(exc)}"


_SKIPPED_CONTENT_TAGS = frozenset({"script", "style", "template", "noscript"})
_VOLATILE_ATTRIBUTE_NAMES = frozenset(
    {
        "nonce",
        "data-nonce",
        "csrf-token",
        "data-csrf-token",
        "data-csrf",
        "data-rendered-at",
        "data-render-time",
        "data-timestamp",
        "data-request-id",
        "data-instance-id",
        "data-widget-instance",
    }
)
_VOLATILE_QUERY_NAMES = frozenset(
    {
        "cachebust",
        "cache_bust",
        "cachebuster",
        "cb",
        "nonce",
        "request_id",
        "requestid",
        "timestamp",
        "ts",
        "instance_id",
        "instanceid",
        "_",
        "mc_cid",
        "mc_eid",
        "fbclid",
        "gclid",
    }
)
_URL_ATTRIBUTES = frozenset({"href", "src", "action", "poster"})
_INSTANCE_ID_ATTRIBUTE_NAMES = frozenset(
    {"id", "name", "data-ad-id", "data-iframe-id", "data-instance-id", "data-widget-id"}
)
_VOID_HTML_TAGS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)
_INSTANCE_ID_VALUE_PATTERN = re.compile(
    r"(?i)^(?:ad|ads|iframe|gpt|googletag|slot|widget|instance)[-_]?(?:[a-z0-9]{4,}|\d{2,})$"
)
_VOLATILE_TOKEN_KEY_PATTERN = re.compile(r"(?i)(?:csrf|nonce)")
_VOLATILE_CLASS_TOKEN_PATTERNS = (
    re.compile(r"(?i)^(?:gf|gform)_browser[_-][a-z0-9_-]+$"),
)
_VOLATILE_PLUGIN_MARKER_PATTERN = re.compile(
    r"(?i)(?:honeypot|akismet|(?:^|[_-])ak(?:[_-]|$))"
)
_VOLATILE_GRAVITY_FIELD_PATTERNS = (
    re.compile(
        r"(?i)^gform_(?:field_values|source_page_number|submit|target_page_number|unique_id)(?:_\d+)?$"
    ),
    re.compile(r"(?i)^is_submit_\d+$"),
    re.compile(r"(?i)^state_\d+$"),
)
_WHITESPACE_PATTERN = re.compile(r"\s+")
_VOID_HTML_TAGS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)


class _CanonicalHTMLParser(HTMLParser):
    """Canonical HTML serializer and visible-text extractor."""

    def __init__(self, *, capture_markup: bool = True) -> None:
        super().__init__(convert_charrefs=True)
        self.capture_markup = capture_markup
        self._parts: list[str] = []
        self._visible_text_parts: list[str] = []
        self._skip_depth = 0
        self._skip_tags: list[str] = []
        self._volatile_skip_tags: list[str] = []
        self._hidden_tags: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized_tag = tag.lower()
        if self._volatile_skip_tags:
            if normalized_tag not in _VOID_HTML_TAGS:
                self._volatile_skip_tags.append(normalized_tag)
            return
        if self._hidden_tags:
            if normalized_tag not in _VOID_HTML_TAGS:
                self._hidden_tags.append(normalized_tag)
            return
        if normalized_tag in _SKIPPED_CONTENT_TAGS:
            self._skip_depth += 1
            self._skip_tags.append(normalized_tag)
            return
        if self._skip_depth:
            return
        if _is_volatile_plugin_element(normalized_tag, attrs):
            if normalized_tag not in _VOID_HTML_TAGS:
                self._volatile_skip_tags.append(normalized_tag)
            return
        if _is_explicitly_hidden(attrs):
            if normalized_tag not in _VOID_HTML_TAGS:
                self._hidden_tags.append(normalized_tag)
            return
        if self.capture_markup:
            self._parts.append(
                _serialize_start_tag(normalized_tag, attrs, self_closing=False)
            )

    def handle_startendtag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        normalized_tag = tag.lower()
        if (
            self._volatile_skip_tags
            or self._hidden_tags
            or self._skip_depth
            or normalized_tag in _SKIPPED_CONTENT_TAGS
            or _is_volatile_plugin_element(normalized_tag, attrs)
            or _is_explicitly_hidden(attrs)
        ):
            return
        if self.capture_markup:
            self._parts.append(
                _serialize_start_tag(normalized_tag, attrs, self_closing=True)
            )

    def handle_endtag(self, tag: str) -> None:
        normalized_tag = tag.lower()
        if self._volatile_skip_tags:
            if normalized_tag == self._volatile_skip_tags[-1]:
                self._volatile_skip_tags.pop()
            return
        if self._hidden_tags:
            if normalized_tag == self._hidden_tags[-1]:
                self._hidden_tags.pop()
            return
        if self._skip_depth:
            if self._skip_tags and normalized_tag == self._skip_tags[-1]:
                self._skip_tags.pop()
                self._skip_depth -= 1
            return
        if self.capture_markup:
            self._parts.append(f"</{normalized_tag}>")

    def handle_data(self, data: str) -> None:
        if self._skip_depth or self._volatile_skip_tags or self._hidden_tags:
            return
        collapsed = _WHITESPACE_PATTERN.sub(" ", data).strip()
        if not collapsed:
            return
        self._visible_text_parts.append(collapsed)
        if self.capture_markup:
            self._parts.append(collapsed)

    def handle_comment(self, data: str) -> None:
        # Comments commonly contain render timestamps and are not visible page
        # content, so they are intentionally excluded from both outputs.
        return

    def handle_decl(self, decl: str) -> None:
        return

    def unknown_decl(self, data: str) -> None:
        return

    def result(self) -> str:
        return "".join(self._parts)

    def visible_text(self) -> str:
        return " ".join(self._visible_text_parts)


def _serialize_start_tag(
    tag: str,
    attrs: list[tuple[str, str | None]],
    *,
    self_closing: bool,
) -> str:
    attribute_values = {name.lower(): value for name, value in attrs if name}
    hidden_input = tag == "input" and attribute_values.get("type", "").lower() == "hidden"
    volatile_gravity_field = _is_volatile_gravity_field(tag, attribute_values)
    hidden_name = attribute_values.get("name", "") or ""
    serialized_attrs: list[str] = []
    for name, value in sorted(
        ((name.lower(), value) for name, value in attrs if name),
        key=lambda item: item[0],
    ):
        if name in _VOLATILE_ATTRIBUTE_NAMES:
            continue
        if hidden_input and name == "value" and _VOLATILE_TOKEN_KEY_PATTERN.search(hidden_name):
            value = "<volatile>"
        elif volatile_gravity_field and name == "value":
            value = "<volatile>"
        elif name in _URL_ATTRIBUTES and value is not None:
            value = _normalize_url_attribute(value)
        elif name in _INSTANCE_ID_ATTRIBUTE_NAMES and value is not None:
            if _is_volatile_instance_value(value):
                value = "<volatile>"
        elif name == "class" and value is not None:
            class_tokens = [
                token
                for token in _WHITESPACE_PATTERN.sub(" ", value).strip().split(" ")
                if token and not _is_volatile_class_token(token)
            ]
            if not class_tokens:
                continue
            value = " ".join(class_tokens)

        if value is None:
            serialized_attrs.append(name)
        else:
            serialized_attrs.append(
                f'{name}="{html.escape(value, quote=True)}"'
            )
    suffix = " />" if self_closing else ">"
    if serialized_attrs:
        return f"<{tag} {' '.join(serialized_attrs)}{suffix}"
    return f"<{tag}{suffix}"


def _is_volatile_plugin_element(
    tag: str,
    attrs: list[tuple[str, str | None]],
) -> bool:
    """Identify whole elements injected by comment-form anti-spam plugins."""

    attributes = {
        name.lower(): value or ""
        for name, value in attrs
        if name
    }
    for name in ("id", "name", "class", "data-prefix"):
        if _VOLATILE_PLUGIN_MARKER_PATTERN.search(attributes.get(name, "")):
            return True
    return False


def _is_volatile_class_token(token: str) -> bool:
    return any(pattern.fullmatch(token) for pattern in _VOLATILE_CLASS_TOKEN_PATTERNS)


def _is_volatile_gravity_field(
    tag: str,
    attributes: Mapping[str, str | None],
) -> bool:
    field_type = attributes.get("type") or ""
    if tag != "input" or field_type.lower() != "hidden":
        return False
    classes = attributes.get("class") or ""
    if "gform_hidden" not in classes.split():
        return False
    field_name = attributes.get("name") or attributes.get("id") or ""
    return any(pattern.fullmatch(field_name) for pattern in _VOLATILE_GRAVITY_FIELD_PATTERNS)


def _normalize_url_attribute(value: str) -> str:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return value
    query_items = []
    for key, item_value in parse_qsl(parsed.query, keep_blank_values=True):
        normalized_key = key.lower()
        if normalized_key.startswith("utm_"):
            continue
        if normalized_key in _VOLATILE_QUERY_NAMES:
            continue
        if _VOLATILE_TOKEN_KEY_PATTERN.search(normalized_key):
            continue
        query_items.append((key, item_value))
    query_items.sort(key=lambda item: (item[0].lower(), item[1]))
    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            urlencode(query_items, doseq=True),
            "",
        )
    )


def _is_volatile_instance_value(value: str) -> bool:
    return bool(_INSTANCE_ID_VALUE_PATTERN.fullmatch(value.strip()))


def _is_explicitly_hidden(attrs: list[tuple[str, str | None]]) -> bool:
    """Return whether HTML explicitly marks an element as not visible.

    This intentionally handles only stable, local signals that can be
    determined without executing CSS or JavaScript: the boolean ``hidden``
    attribute and the final inline values of ``display``/``visibility``.
    Class names and external stylesheets are not interpreted here because
    doing so would require a browser's computed-style engine and would blur
    the boundary between initial page content and post-interaction state.
    """

    attributes = {name.lower(): value for name, value in attrs if name}
    if "hidden" in attributes:
        return True

    style = attributes.get("style")
    if not isinstance(style, str):
        return False

    declarations: dict[str, str] = {}
    for declaration in re.sub(r"/\*.*?\*/", "", style, flags=re.S).split(";"):
        if ":" not in declaration:
            continue
        name, value = declaration.split(":", 1)
        normalized_name = name.strip().lower()
        if normalized_name not in {"display", "visibility"}:
            continue
        declarations[normalized_name] = re.sub(
            r"\s*!important\s*$", "", value.strip().lower()
        )

    return declarations.get("display") == "none" or declarations.get(
        "visibility"
    ) == "hidden"


def _visible_text(content: str) -> str:
    parser = _CanonicalHTMLParser(capture_markup=False)
    parser.feed(content)
    parser.close()
    return parser.visible_text()


def _is_usable_http_response(response: HttpResponse) -> bool:
    if not 200 <= response.http_status < 400:
        return False
    content_type = _header_value(response.headers, "content-type")
    if content_type and not (
        "text/html" in content_type.lower()
        or "application/xhtml+xml" in content_type.lower()
    ):
        return False
    return len(_visible_text(response.content)) >= MIN_RENDERABLE_TEXT_LENGTH


def _call_fetcher(
    fetcher: PageFetcher | Callable[[str], HttpResponse | FetchResult],
    url: str,
) -> HttpResponse | FetchResult:
    method = getattr(fetcher, "fetch", None)
    if callable(method):
        return method(url)
    if callable(fetcher):
        return fetcher(url)
    raise MonitoringError("fetcher must be callable or implement fetch(url)")


def _coerce_response(response: HttpResponse | FetchResult) -> HttpResponse:
    if isinstance(response, HttpResponse):
        if not isinstance(response.content, str):
            raise MonitoringError("HTTP fetcher returned non-text content")
        return response
    if isinstance(response, FetchResult):
        if not isinstance(response.content, str):
            raise MonitoringError("fetcher returned non-text content")
        if response.http_status is None:
            raise MonitoringError("fetcher returned no HTTP status")
        return HttpResponse(
            content=response.content,
            http_status=int(response.http_status),
        )
    raise MonitoringError("fetcher must return HttpResponse or FetchResult")


def _validate_url(url: str) -> None:
    if not isinstance(url, str) or not url.strip():
        raise ValueError("url must be a non-empty string")
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("url must be an absolute HTTP or HTTPS URL")


def _decode_response_body(response: Any) -> str:
    body = response.read()
    return _decode_bytes(body, _header_charset(getattr(response, "headers", None)))


def _decode_bytes(body: Any, charset: str | None) -> str:
    if isinstance(body, str):
        return body
    if not isinstance(body, bytes):
        raise MonitoringError("HTTP response body was not text or bytes")
    return body.decode(charset or "utf-8", errors="replace")


def _header_charset(headers: Any) -> str | None:
    getter = getattr(headers, "get_content_charset", None)
    if callable(getter):
        return getter()
    content_type = _header_value(headers, "content-type")
    if content_type:
        match = re.search(r"charset=\s*[\"']?([^;\"']+)", content_type, re.I)
        if match:
            return match.group(1).strip()
    return None


def _response_headers(response: Any) -> Mapping[str, str]:
    headers = getattr(response, "headers", None)
    if headers is None:
        return {}
    try:
        return {str(key): str(value) for key, value in headers.items()}
    except AttributeError:
        return {}


def _header_value(headers: Any, name: str) -> str | None:
    if headers is None:
        return None
    if hasattr(headers, "get"):
        direct = headers.get(name)
        if direct is not None:
            return str(direct)
        direct = headers.get(name.title())
        if direct is not None:
            return str(direct)
    try:
        for key, value in headers.items():
            if str(key).lower() == name.lower():
                return str(value)
    except AttributeError:
        return None
    return None


__all__ = [
    "BROWSER_FETCH_METHOD",
    "BrowserFetchError",
    "BrowserPageFetcher",
    "DEFAULT_HTTP_TIMEOUT_SECONDS",
    "FetchResult",
    "HTTP_FETCH_METHOD",
    "HttpPageFetcher",
    "HttpResponse",
    "MIN_RENDERABLE_TEXT_LENGTH",
    "MonitoringError",
    "compare_hashes",
    "fetch_page",
    "generate_diff",
    "hash_content",
    "normalize_content",
]
