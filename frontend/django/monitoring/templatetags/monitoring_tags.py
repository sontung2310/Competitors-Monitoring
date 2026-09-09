from __future__ import annotations

from datetime import datetime, timezone as dt_timezone

from django import template
from django.utils import timezone


register = template.Library()


@register.filter
def display_time(value: object) -> str:
    """Format the API's UTC ISO timestamp without changing the stored value."""

    if not value:
        return "Not checked yet"
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
    else:
        return str(value)
    if timezone.is_naive(parsed):
        parsed = parsed.replace(tzinfo=dt_timezone.utc)
    local = timezone.localtime(parsed)
    return local.strftime("%-d %b %Y, %H:%M")


@register.filter
def short_url(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return value.removeprefix("https://").removeprefix("http://").rstrip("/")
