"""External source adapters used by Layer 1 discovery.

The adapters are deliberately small and injectable. They know how to collect
URLs from external systems, but do not know anything about MongoDB or the
application's persistence model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Mapping, Protocol, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from .normalization import (
    canonicalize_raw_url,
    discovery_scope,
    is_html_candidate_url,
    is_same_site,
    is_structural_path,
    extract_meta_description,
    extract_page_title,
    normalize_url,
)


class DiscoveryFetchError(RuntimeError):
    """Raised when a source cannot be fetched at all."""


@dataclass(frozen=True)
class FetchResponse:
    """Minimal response shape required by the discovery adapters."""

    url: str
    status: int
    text: str
    headers: Mapping[str, str]


class Fetcher(Protocol):
    def fetch(self, url: str) -> FetchResponse:
        """Fetch a URL and return decoded text."""


@dataclass(frozen=True)
class SourceStats:
    """Counts emitted by one source during its most recent discovery run."""

    source: str
    raw_count: int
    normalized_count: int
    sampled_count: int = 0


@dataclass(frozen=True)
class DiscoveredURL:
    """A raw URL and the source that produced it."""

    raw_url: str
    source: str
    title: str | None = None
    force_discarded: bool = False
    priority: int = 3


class HttpFetcher:
    """Simple HTTP fetcher for static discovery resources."""

    def __init__(self, *, timeout_seconds: float = 10.0, user_agent: str = "CompetitorsMonitoring/1.0"):
        self.timeout_seconds = timeout_seconds
        self.user_agent = user_agent

    def fetch(self, url: str) -> FetchResponse:
        request = Request(
            url,
            headers={"User-Agent": self.user_agent, "Accept": "text/html, application/xml, text/plain"},
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                body = response.read()
                charset = response.headers.get_content_charset() or "utf-8"
                return FetchResponse(
                    url=response.geturl(),
                    status=getattr(response, "status", 200),
                    text=body.decode(charset, errors="replace"),
                    headers=dict(response.headers.items()),
                )
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            return FetchResponse(
                url=url,
                status=exc.code,
                text=body,
                headers=dict(exc.headers.items()) if exc.headers else {},
            )
        except (URLError, TimeoutError, OSError) as exc:
            raise DiscoveryFetchError(f"could not fetch {url!r}: {exc}") from exc


class RobotsTxtSource:
    """Fetch robots.txt and expose sitemap declarations."""

    def __init__(self, fetcher: Fetcher):
        self.fetcher = fetcher
        self.last_stats = SourceStats("ROBOTS", 0, 0)

    def sitemap_urls(self, website_url: str) -> tuple[str, ...]:
        response = self.fetcher.fetch(_root_resource_url(website_url, "robots.txt"))
        if response.status >= 400:
            self.last_stats = SourceStats("ROBOTS", 0, 0)
            return ()
        sitemap_urls = parse_robots_sitemaps(response.text, website_url)
        self.last_stats = SourceStats("ROBOTS", 0, 0)
        return sitemap_urls


def parse_robots_sitemaps(text: str, website_url: str) -> tuple[str, ...]:
    """Extract absolute sitemap URLs from robots.txt declarations."""

    sitemap_urls: list[str] = []
    for line in text.splitlines():
        name, separator, value = line.partition(":")
        if separator and name.strip().lower() == "sitemap" and value.strip():
            try:
                sitemap_urls.append(canonicalize_raw_url(urljoin(website_url, value.strip())))
            except ValueError:
                continue
    return _dedupe_strings(sitemap_urls)


class SitemapSource:
    """Collect section-level URLs from common sitemaps and declarations.

    Sitemap XML can enumerate thousands of leaf pages. The source always
    normalizes URLs before returning them, keeps explicit item paths, and
    retains only a deterministic sample of unmatched raw locations from large
    sub-sitemaps. The sample is chosen before URL normalization; every emitted
    normalized candidate is classified by the discovery service and any
    inferred index parent is checked by its liveness gate before suggestion.
    """

    def __init__(
        self,
        fetcher: Fetcher,
        *,
        max_sitemaps: int = 50,
        max_depth: int = 2,
        large_sitemap_threshold: int = 50,
        sample_urls_per_large_sitemap: int = 5,
    ):
        if large_sitemap_threshold < 1 or sample_urls_per_large_sitemap < 1:
            raise ValueError("sitemap sampling settings must be positive")
        self.fetcher = fetcher
        self.max_sitemaps = max_sitemaps
        self.max_depth = max_depth
        self.large_sitemap_threshold = large_sitemap_threshold
        self.sample_urls_per_large_sitemap = sample_urls_per_large_sitemap
        self.last_stats = SourceStats("SITEMAP", 0, 0)

    def discover(
        self,
        website_url: str,
        declared_sitemaps: Sequence[str] = (),
    ) -> tuple[DiscoveredURL, ...]:
        queue = [
            (_root_resource_url(website_url, "sitemap.xml"), 0),
            (_root_resource_url(website_url, "sitemap_index.xml"), 0),
            *((sitemap_url, 0) for sitemap_url in declared_sitemaps),
        ]
        seen_sitemaps: set[str] = set()
        candidates: list[DiscoveredURL] = []
        raw_urls: set[str] = set()
        sampled_count = 0
        while queue and len(seen_sitemaps) < self.max_sitemaps:
            sitemap_url, depth = queue.pop(0)
            try:
                sitemap_key = canonicalize_raw_url(sitemap_url)
            except ValueError:
                continue
            if sitemap_key in seen_sitemaps:
                continue
            seen_sitemaps.add(sitemap_key)
            if _is_non_content_sitemap(sitemap_key):
                continue
            try:
                response = self.fetcher.fetch(sitemap_key)
            except DiscoveryFetchError:
                continue
            if response.status >= 400:
                continue
            kind, locations = parse_sitemap(response.text)
            if kind == "sitemapindex" and depth < self.max_depth:
                queue.extend(
                    (urljoin(response.url, location), depth + 1)
                    for location in locations
                )
                continue
            sitemap_candidates, sitemap_raw_urls, sitemap_sampled_count = (
                self._normalize_sitemap_locations(website_url, response.url, locations)
            )
            candidates.extend(sitemap_candidates)
            raw_urls.update(sitemap_raw_urls)
            sampled_count += sitemap_sampled_count
        normalized_candidates = dedupe_discovered_urls(candidates)
        self.last_stats = SourceStats(
            "SITEMAP",
            raw_count=len(raw_urls),
            normalized_count=len(normalized_candidates),
            sampled_count=sampled_count,
        )
        return tuple(normalized_candidates)

    def _normalize_sitemap_locations(
        self,
        website_url: str,
        response_url: str,
        locations: Sequence[str],
    ) -> tuple[list[DiscoveredURL], set[str], int]:
        structural_urls: dict[str, str] = {}
        unmatched_urls: dict[str, str] = {}
        raw_urls: set[str] = set()
        for location in locations:
            try:
                raw_url = canonicalize_raw_url(urljoin(response_url, location))
            except ValueError:
                continue
            if not is_same_site(website_url, raw_url):
                continue
            raw_urls.add(raw_url)
            if not is_html_candidate_url(raw_url):
                continue
            target = (
                unmatched_urls
                if discovery_scope(raw_url) == "UNMATCHED"
                or not is_structural_path(raw_url)
                else structural_urls
            )
            target.setdefault(raw_url, raw_url)

        # Sampling happens on raw sitemap locations, before normalization. Every
        # candidate emitted below is therefore normalized and classified by the
        # service; no normalized candidate is discarded merely because it fell
        # outside the sample.
        sampled_raw_urls = list(unmatched_urls.values())
        sampled_count = 0
        if len(locations) > self.large_sitemap_threshold:
            sampled_raw_urls = _evenly_sample(
                sampled_raw_urls,
                self.sample_urls_per_large_sitemap,
            )
            sampled_count = len(sampled_raw_urls)

        candidates: list[DiscoveredURL] = []
        for raw_url in (*structural_urls.values(), *sampled_raw_urls):
            try:
                normalized_url = normalize_url(raw_url)
            except ValueError:
                continue
            candidates.append(
                DiscoveredURL(
                    raw_url=normalized_url,
                    source="SITEMAP",
                    force_discarded=(
                        discovery_scope(raw_url) == "UNMATCHED"
                    ),
                    priority=1,
                )
            )
        return candidates, raw_urls, sampled_count


def parse_sitemap(text: str) -> tuple[str, tuple[str, ...]]:
    """Return sitemap kind and its ``loc`` values, tolerating XML namespaces."""

    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError:
        return "invalid", ()
    kind = _local_name(root.tag)
    if kind not in {"urlset", "sitemapindex"}:
        return "invalid", ()
    locations = tuple(
        element.text.strip()
        for element in root.iter()
        if _local_name(element.tag) == "loc" and element.text and element.text.strip()
    )
    return kind, locations


class InternalLinkSource:
    """Collect same-site links from the homepage at depth 1.

    Links in navigation/header/footer are returned before body links. No child
    pages are fetched by this source, keeping Layer 1 discovery shallow.
    """

    def __init__(self, fetcher: Fetcher):
        self.fetcher = fetcher
        self.last_stats = SourceStats("LINKS", 0, 0)
        self.last_homepage_metadata: dict[str, str | None] = {
            "title": None,
            "meta_description": None,
        }

    def discover(self, website_url: str) -> tuple[DiscoveredURL, ...]:
        homepage = _root_resource_url(website_url, "")
        self.last_homepage_metadata = {"title": None, "meta_description": None}
        try:
            response = self.fetcher.fetch(homepage)
        except DiscoveryFetchError:
            self.last_stats = SourceStats("LINKS", 0, 0)
            return ()
        if response.status >= 400:
            self.last_stats = SourceStats("LINKS", 0, 0)
            return ()

        self.last_homepage_metadata = {
            "title": extract_page_title(response.text),
            "meta_description": extract_meta_description(response.text),
        }

        parser = _LinkParser()
        parser.feed(response.text)
        candidates: list[DiscoveredURL] = []
        canonical_homepage = canonicalize_raw_url(response.url)
        for href, title, priority in parser.links:
            try:
                candidate_url = canonicalize_raw_url(urljoin(response.url, href))
            except ValueError:
                continue
            if (
                is_same_site(website_url, candidate_url)
                and candidate_url != canonical_homepage
                and is_html_candidate_url(candidate_url)
            ):
                candidates.append(
                    DiscoveredURL(
                        candidate_url,
                        "LINKS",
                        title or None,
                        priority=priority,
                    )
                )
        normalized_candidates = dedupe_discovered_urls(candidates)
        normalized_candidates.sort(key=lambda candidate: candidate.priority)
        normalized_urls = set()
        for candidate in normalized_candidates:
            try:
                normalized_urls.add(normalize_url(candidate.raw_url))
            except ValueError:
                continue
        self.last_stats = SourceStats(
            "LINKS",
            raw_count=len(normalized_candidates),
            normalized_count=len(normalized_urls),
        )
        return tuple(normalized_candidates)


def dedupe_discovered_urls(candidates: Sequence[DiscoveredURL]) -> list[DiscoveredURL]:
    """Merge duplicate raw URLs while keeping useful title/source metadata."""

    by_url: dict[str, DiscoveredURL] = {}
    for candidate in candidates:
        try:
            key = canonicalize_raw_url(candidate.raw_url)
        except ValueError:
            continue
        current = by_url.get(key)
        if current is None:
            by_url[key] = DiscoveredURL(
                key,
                candidate.source,
                candidate.title,
                candidate.force_discarded,
                candidate.priority,
            )
            continue
        preferred_source = min(
            (current.source, candidate.source),
            key=lambda source: _SOURCE_PRIORITY.get(source, 99),
        )
        preferred_candidate = min(
            (current, candidate),
            key=lambda item: (
                item.force_discarded,
                _SOURCE_PRIORITY.get(item.source, 99),
                item.priority,
            ),
        )
        by_url[key] = DiscoveredURL(
            raw_url=key,
            source=preferred_source,
            title=current.title or candidate.title,
            force_discarded=preferred_candidate.force_discarded,
            priority=preferred_candidate.priority,
        )
    return list(by_url.values())


_SOURCE_PRIORITY = {"ROBOTS": 0, "SITEMAP": 1, "LINKS": 2}


class _LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links: list[tuple[str, str, int]] = []
        self._stack: list[str] = []
        self._href: str | None = None
        self._text: list[str] = []
        self._priority = 3

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        self._stack.append(tag)
        if tag != "a":
            return
        attributes = dict(attrs)
        href = attributes.get("href")
        if href:
            self._href = href
            self._text = []
            self._priority = self._context_priority()

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "a" and self._href is not None:
            self.links.append(
                (
                    self._href,
                    " ".join("".join(self._text).split()),
                    self._priority,
                )
            )
            self._href = None
            self._text = []
        for index in range(len(self._stack) - 1, -1, -1):
            if self._stack[index] == tag:
                del self._stack[index:]
                break

    def _context_priority(self) -> int:
        if "nav" in self._stack:
            return 0
        if "header" in self._stack:
            return 1
        if "footer" in self._stack:
            return 2
        return 3


def _root_resource_url(website_url: str, resource: str) -> str:
    parts = urlsplit(website_url)
    if parts.scheme.lower() not in {"http", "https"} or not parts.netloc:
        raise ValueError(f"website_url must be an absolute HTTP(S) URL: {website_url!r}")
    path = "/" if not resource else f"/{resource.lstrip('/')}"
    return urlunsplit((parts.scheme.lower(), parts.netloc, path, "", ""))


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _dedupe_strings(values: Sequence[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return tuple(result)


def _is_non_content_sitemap(sitemap_url: str) -> bool:
    """Skip CMS taxonomy, asset, and implementation-detail sitemap families."""

    filename = urlsplit(sitemap_url).path.rsplit("/", 1)[-1].lower()
    ignored_family_tokens = (
        "author",
        "category",
        "post_tag",
        "portfolio_category",
        "testimonial_category",
        "clients-sitemap",
        "employees-sitemap",
        "animated-columns",
        "edge-sitemap",
        "tab_slider",
        "video-showcase",
    )
    return any(token in filename for token in ignored_family_tokens)


def _evenly_sample(values: Sequence[str], limit: int) -> list[str]:
    """Take a deterministic spread of raw entries from a large sitemap."""

    if len(values) <= limit:
        return list(values)
    if limit == 1:
        return [values[0]]
    positions = [round(index * (len(values) - 1) / (limit - 1)) for index in range(limit)]
    return [values[position] for position in positions]
