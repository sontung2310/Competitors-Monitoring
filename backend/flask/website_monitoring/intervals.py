"""Shared default monitoring intervals for website page types."""

from __future__ import annotations

from typing import Final


# These defaults are applied only when a target/candidate is first created and
# do not override an interval explicitly configured by a user.
DEFAULT_CHECK_INTERVAL_MINUTES: Final = 1440
PAGE_TYPE_CHECK_INTERVAL_MINUTES: dict[str, int] = {
    "BLOG": 180,
    "NEWS": 180,
    "PRESS": 180,
    "PRICING": 360,
}


def default_check_interval_minutes(page_type: str | None) -> int:
    """Return the shared interval default for a page type.

    The specification gives BLOG (3 hours) and PRICING (6 hours) as examples.
    Other website page types use a conservative daily default until a user
    chooses a more frequent interval.
    """

    normalized = page_type.strip().upper() if isinstance(page_type, str) else ""
    return PAGE_TYPE_CHECK_INTERVAL_MINUTES.get(
        normalized,
        DEFAULT_CHECK_INTERVAL_MINUTES,
    )
