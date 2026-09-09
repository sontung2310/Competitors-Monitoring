"""Deterministic URL canonicalization, filtering, and scope normalization."""

from __future__ import annotations

import re
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


# These are semantic path patterns, not a list of competitor URLs. They define
# the kinds of site sections that are valid Layer 2-level discovery targets.
#
# Matching is deliberately high precision: the final path segment must equal
# one of these known variants. A blog post such as ``/website-design-review``
# must not become a reviews index merely because a keyword appears in its slug.
INDEX_TYPE_VARIANTS: dict[str, frozenset[str]] = {
    "BLOG": frozenset(
        {
            "article",
            "articles",
            "blog",
            "blogs",
            "blog-posts",
            "insight",
            "insights",
            "post",
            "posts",
        }
    ),
    "NEWS": frozenset({"news", "news-posts", "updates"}),
    "PRESS": frozenset({"press", "press-release", "press-releases"}),
    "CASE_STUDIES": frozenset(
        {"case-study", "case-studies", "case-study-archive", "casestudy"}
    ),
    "TESTIMONIALS": frozenset(
        {"testimonial", "testimonials", "client-testimonials"}
    ),
    "REVIEWS": frozenset(
        {
            "review",
            "reviews",
            "reviews-page",
            "client-reviews",
            "marketing-reviews",
            "lyfe-marketing-reviews",
        }
    ),
    "SUCCESS_STORIES": frozenset(
        {"success-story", "success-stories", "small-business-success-stories"}
    ),
    "ABOUT": frozenset({"about", "about-us", "about-lyfe-marketing"}),
    "CAREERS": frozenset(
        {
            "career",
            "careers",
            "career-opportunities",
            "jobs",
            "join-us",
        }
    ),
    "TEAM": frozenset({"leadership", "people", "team", "team-members"}),
    "CONTACT": frozenset({"contact", "contact-us"}),
    "INDUSTRIES": frozenset({"industry", "industries"}),
    "WORK": frozenset({"work", "showcase"}),
    "PORTFOLIO": frozenset(
        {"portfolio", "portfolio-posts", "website-portfolio"}
    ),
    "RESULTS": frozenset({"result", "results"}),
    "RESOURCES": frozenset({"resource", "resources"}),
    "SERVICES": frozenset({"main-services", "service", "services"}),
    "CALCULATOR": frozenset({"calculator", "roi-cal-page"}),
    "PRICING": frozenset({"pricing", "plans"}),
}

INDEX_TYPE_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(rf"^(?:{'|'.join(sorted(variants, key=len, reverse=True))})$")
    for variants in INDEX_TYPE_VARIANTS.values()
)

INDEX_PATH_ALIASES = {"service": "services", "result": "results"}

# A path under one of these roots describes an independently meaningful item.
# It is deliberately an allowlist: arbitrary deep paths do not become targets.
ITEM_TYPE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^(?:item|items|product|products)$"),
    re.compile(r"^(?:package|packages)$"),
    re.compile(r"^(?:solution|solutions)$"),
)

# A singular product URL with both a human slug and a SKU is an item/detail
# page, not a Layer 2 section. Keep the broader item-root patterns above for
# normalization and classification, but exclude this precise leaf shape from
# discovery promotion. The aggregate ``/sale`` listing target is not matched.
ITEM_TYPE_EXCLUSION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^/product/[^/]+/[^/]+/?$", flags=re.IGNORECASE),
)

# Backwards-compatible segment constants for callers that used the original
# normalization module, while the regex patterns above remain authoritative.
INDEX_PATH_SEGMENTS = frozenset(
    segment
    for variants in INDEX_TYPE_VARIANTS.values()
    for segment in variants
)
ITEM_PATH_SEGMENTS = frozenset(
    {
        "item",
        "items",
        "product",
        "products",
        "package",
        "packages",
        "solution",
        "solutions",
    }
)

TRACKING_QUERY_PREFIXES = ("utm_",)
TRACKING_QUERY_KEYS = frozenset({"fbclid", "gclid", "mc_cid", "mc_eid"})
PAGINATION_QUERY_KEYS = frozenset(
    {"page", "paged", "page_num", "pagenum", "offset", "start", "from", "to"}
)
NON_HTML_EXTENSIONS = frozenset(
    {
        ".7z",
        ".avif",
        ".bmp",
        ".css",
        ".csv",
        ".doc",
        ".docx",
        ".gif",
        ".ico",
        ".jpeg",
        ".jpg",
        ".js",
        ".json",
        ".m4a",
        ".mov",
        ".mp3",
        ".mp4",
        ".mpeg",
        ".pdf",
        ".png",
        ".svg",
        ".tar",
        ".txt",
        ".webm",
        ".webp",
        ".woff",
        ".woff2",
        ".xls",
        ".xlsx",
        ".xml",
        ".zip",
    }
)
SYSTEM_PATH_SEGMENTS = frozenset(
    {"wp-admin", "wp-json", "feed", "tag", "tags", "category", "categories"}
)
TAXONOMY_SEGMENT_PATTERN = re.compile(
    r"(?:^|[-_])(?:tag|tags|category|categories|catagory|catagories)(?:$|[-_])"
)

DiscoveryScope = Literal["INDEX", "ITEM", "SECTION", "UNMATCHED"]


def canonicalize_raw_url(url: str) -> str:
    """Normalize URL spelling without collapsing page-specific path segments."""

    parts = _split_http_url(url)
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    if path != "/":
        path = path.rstrip("/")
    query = _clean_query(parts.query)
    return urlunsplit((parts.scheme.lower(), _normalized_netloc(parts), path, query, ""))


def normalize_url(url: str, page_type: str | None = None) -> str:
    """Collapse explicit index paths while preserving explicit item paths.

    Unknown dynamic trailing segments are still collapsed for compatibility
    with the original normalizer. Callers must use ``discovery_scope`` on the
    raw URL to mark an otherwise-unmatched deep path as DISCARDED.
    """

    canonical = canonicalize_raw_url(url)
    parts = urlsplit(canonical)
    segments = [segment for segment in parts.path.split("/") if segment]

    index_position = _index_position(segments, page_type)
    if index_position is not None:
        segments = segments[: index_position + 1]
    elif segments and not _is_item_style(segments) and _is_dynamic_segment(segments[-1]):
        segments = segments[:-1]

    if segments and segments[0].lower() in INDEX_PATH_ALIASES:
        segments[0] = INDEX_PATH_ALIASES[segments[0].lower()]
    normalized_path = "/" + "/".join(segments) if segments else "/"
    return urlunsplit((parts.scheme, parts.netloc, normalized_path, parts.query, ""))


def discovery_scope(url: str, page_type: str | None = None) -> DiscoveryScope:
    """Return the URL's deterministic Layer 2 discovery scope."""

    canonical = canonicalize_raw_url(url)
    segments = [segment for segment in urlsplit(canonical).path.split("/") if segment]
    if not segments:
        return "SECTION"
    if _index_match_position(segments) is not None:
        return "INDEX"
    if _matches_pattern(segments[0], ITEM_TYPE_PATTERNS):
        return "ITEM"
    if len(segments) == 1:
        return "SECTION"
    return "UNMATCHED"


def is_structural_path(url: str, page_type: str | None = None) -> bool:
    """Whether a URL matches an explicit index/item pattern."""

    canonical = canonicalize_raw_url(url)
    segments = [segment for segment in urlsplit(canonical).path.split("/") if segment]
    if not segments:
        return True
    return _index_match_position(segments) is not None or _matches_pattern(
        segments[0], ITEM_TYPE_PATTERNS
    )


def is_item_type_excluded(url: str) -> bool:
    """Return whether a URL is a known item/detail leaf excluded from discovery."""

    canonical = canonicalize_raw_url(url)
    path = urlsplit(canonical).path
    return any(pattern.fullmatch(path) for pattern in ITEM_TYPE_EXCLUSION_PATTERNS)


def is_same_site(base_url: str, candidate_url: str) -> bool:
    """Compare hostnames while treating a leading ``www.`` as equivalent."""

    base_host = (urlsplit(base_url).hostname or "").lower().removeprefix("www.")
    candidate_host = (urlsplit(candidate_url).hostname or "").lower().removeprefix("www.")
    return bool(base_host and base_host == candidate_host)


def is_html_candidate_url(url: str) -> bool:
    """Return whether a canonical URL can represent an HTML page."""

    path = urlsplit(url).path.lower()
    return not any(path.endswith(extension) for extension in NON_HTML_EXTENSIONS)


def is_system_path(url: str, page_type: str | None = None) -> bool:
    """Reject CMS/system paths unless their classified type is meaningful.

    Index normalization runs before this check, so ``/blog/category/foo``
    becomes ``/blog`` and remains valid. A direct ``/category/foo`` path is
    rejected unless a caller has already supplied an appropriate page type.
    """

    segments = [segment.lower() for segment in urlsplit(url).path.split("/") if segment]
    system_segments = set(segments) & SYSTEM_PATH_SEGMENTS
    has_taxonomy_segment = any(
        TAXONOMY_SEGMENT_PATTERN.search(segment) for segment in segments
    )
    if not system_segments and not has_taxonomy_segment:
        return False
    if page_type and page_type.upper() in {"BLOG", "NEWS", "PRESS"}:
        return False
    return True


def _split_http_url(url: str):
    if not isinstance(url, str) or not url.strip():
        raise ValueError("URL must be a non-empty string")
    parts = urlsplit(url.strip())
    if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
        raise ValueError(f"URL must be an absolute HTTP(S) URL: {url!r}")
    return parts


def _normalized_netloc(parts) -> str:
    hostname = (parts.hostname or "").lower()
    try:
        port = parts.port
    except ValueError as exc:
        raise ValueError(f"invalid URL port: {parts.geturl()!r}") from exc
    if port is None or (parts.scheme.lower() == "http" and port == 80) or (
        parts.scheme.lower() == "https" and port == 443
    ):
        return hostname
    return f"{hostname}:{port}"


def _clean_query(query: str) -> str:
    values = [
        (key, value)
        for key, value in parse_qsl(query, keep_blank_values=True)
        if key.lower() not in PAGINATION_QUERY_KEYS
        and key.lower() not in TRACKING_QUERY_KEYS
        and not any(key.lower().startswith(prefix) for prefix in TRACKING_QUERY_PREFIXES)
    ]
    return urlencode(sorted(values))


def _index_position(segments: list[str], page_type: str | None) -> int | None:
    if not segments:
        return None
    index = _index_match_position(segments)
    if index is None:
        return None
    return index if index < len(segments) - 1 else None


def _index_match_position(segments: list[str]) -> int | None:
    for index, segment in enumerate(segments):
        if not _matches_pattern(segment, INDEX_TYPE_PATTERNS):
            continue
        if index == 0 or (index == 1 and _is_locale_segment(segments[0])):
            return index
    return None


def _is_locale_segment(segment: str) -> bool:
    return re.fullmatch(r"[a-z]{2,3}(?:-[a-z]{2})?", segment, flags=re.IGNORECASE) is not None


def _matches_pattern(segment: str, patterns: tuple[re.Pattern[str], ...]) -> bool:
    value = segment.lower()
    return any(pattern.fullmatch(value) for pattern in patterns)


def _is_item_style(segments: list[str]) -> bool:
    return bool(segments and _matches_pattern(segments[0], ITEM_TYPE_PATTERNS))


def _is_dynamic_segment(segment: str) -> bool:
    if re.fullmatch(r"\d+", segment):
        return True
    if re.fullmatch(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
        segment,
        flags=re.IGNORECASE,
    ):
        return True
    if re.fullmatch(r"\d{4}[-_]?\d{2}[-_]?\d{2}(?:[-_T]?\d{2,6})?", segment):
        return True
    if re.fullmatch(r"[0-9a-f]{8,64}", segment, flags=re.IGNORECASE):
        return True
    return bool(
        len(segment) >= 12
        and re.fullmatch(r"[a-z0-9]+", segment, flags=re.IGNORECASE)
        and re.search(r"[a-z]", segment, flags=re.IGNORECASE)
        and re.search(r"\d", segment)
    )
