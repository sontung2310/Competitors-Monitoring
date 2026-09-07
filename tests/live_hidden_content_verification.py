"""Live verification for hidden-content normalization.

Run from the repository root with:
    python tests/live_hidden_content_verification.py

This reads exact real snapshot files already captured for Lyfe and Brown Bag,
and fetches the current JD Sports /sale/ HTML over the real HTTP path.
"""

from __future__ import annotations

import gzip
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.flask.website_monitoring.service import (  # noqa: E402
    _SKIPPED_CONTENT_TAGS,
    _VOID_HTML_TAGS,
    _is_explicitly_hidden,
    _visible_text,
    fetch_page,
    hash_content,
    normalize_content,
)


HISTORICAL = (
    (
        "Lyfe",
        Path("storage/snapshots/6a9a44efba8f10678b8e30d0/20260904T122050804511Z-000000.txt.gz"),
        "440963ea1f00c46c9315dd4e3d62dcdd5238759fe2d83313e29ee60b553e2042",
    ),
    (
        "Brown Bag",
        Path("storage/snapshots/6a9a4da2345431aa0e799506/20260905T005337903500Z-000000.txt.gz"),
        "c48f0533bc16b24dd9b955e14542501bfb888881c07e138be977ccf22085f6b2",
    ),
)


class _VisibilityAuditParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._skip_tags: list[str] = []
        self._hidden_tags: list[str] = []
        self.all_text: list[str] = []
        self.hidden_text: list[str] = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if self._hidden_tags:
            if tag not in _VOID_HTML_TAGS:
                self._hidden_tags.append(tag)
            return
        if tag in _SKIPPED_CONTENT_TAGS:
            self._skip_tags.append(tag)
            return
        if self._skip_tags:
            return
        if _is_explicitly_hidden(attrs) and tag not in _VOID_HTML_TAGS:
            self._hidden_tags.append(tag)

    def handle_startendtag(self, tag, attrs):
        return

    def handle_endtag(self, tag):
        tag = tag.lower()
        if self._hidden_tags:
            if tag == self._hidden_tags[-1]:
                self._hidden_tags.pop()
            return
        if self._skip_tags and tag == self._skip_tags[-1]:
            self._skip_tags.pop()

    def handle_data(self, data):
        if self._skip_tags:
            return
        text = re.sub(r"\s+", " ", data).strip()
        if not text:
            return
        self.all_text.append(text)
        if self._hidden_tags:
            self.hidden_text.append(text)


def _audit_visibility(html: str) -> _VisibilityAuditParser:
    parser = _VisibilityAuditParser()
    parser.feed(html)
    parser.close()
    return parser


def verify_historical_hashes() -> None:
    for label, path, expected in HISTORICAL:
        content = gzip.open(path, "rb").read().decode("utf-8")
        # Snapshot files contain the exact canonical bytes already persisted by
        # the monitoring pipeline. Re-hashing those bytes is the correct
        # regression check; normalizing a canonical snapshot a second time is
        # not equivalent to reprocessing its original raw HTML.
        actual = hash_content(content)
        print(
            f"{label}: historical_hash={actual} expected={expected} "
            f"match={actual == expected} canonical_bytes={len(content)}"
        )
        if actual != expected:
            raise AssertionError(f"{label}: historical hash changed")


def verify_jd_sports() -> None:
    fetched = fetch_page("https://www.jd-sports.com.au/sale/")
    raw = fetched.content
    audit = _audit_visibility(raw)
    normalized = normalize_content(raw)
    base_hash = hash_content(normalized)

    if "Accept All Cookies" not in raw or "Your Cookie Settings" not in raw:
        raise AssertionError("JD Sports consent markup was not present in the live response")
    if "Accept All Cookies" in normalized or "Your Cookie Settings" in normalized:
        raise AssertionError("hidden JD Sports consent text entered normalized content")

    mutated = raw.replace(
        "Accept All Cookies",
        "Rotating hidden consent text",
        1,
    ).replace(
        "Your Cookie Settings",
        "Rotating hidden settings text",
        1,
    )
    mutated_hash = hash_content(normalize_content(mutated))
    if mutated_hash != base_hash:
        raise AssertionError("mutating hidden consent text changed the normalized hash")

    all_text_chars = len(" ".join(audit.all_text))
    hidden_text_chars = len(" ".join(audit.hidden_text))
    post_visibility_chars = len(_visible_text(raw))
    print(
        "JD Sports: "
        f"http_status={fetched.http_status} "
        f"raw_chars={len(raw)} "
        f"pre_visibility_text_chars={all_text_chars} "
        f"hidden_text_chars={hidden_text_chars} "
        f"post_visibility_text_chars={post_visibility_chars} "
        f"hidden_share={hidden_text_chars / all_text_chars:.1%} "
        f"hash={base_hash} "
        f"hidden_mutation_hash_match={mutated_hash == base_hash}"
    )


if __name__ == "__main__":
    verify_historical_hashes()
    verify_jd_sports()
