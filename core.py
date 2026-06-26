"""Shared types and helpers for feedmint's build script and source parsers.

Lives apart from build.py so custom parsers in parsers/ can import the Item
model and date helper without a circular import back through build.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from dateutil import parser as dateparser


@dataclass(slots=True)
class Item:
    """One feed entry. `link` doubles as the RSS guid."""

    title: str
    link: str
    date: datetime | None = None


class BuildError(RuntimeError):
    """Raised on any condition that must fail the run (e.g. zero items)."""


def parse_date(raw: str, fmt: str | None = None) -> datetime | None:
    """Parse a date string to a timezone-aware datetime, or None.

    RSS pubDate must be tz-aware; assume UTC when the source omits a zone.
    """
    if not raw:
        return None
    try:
        dt = datetime.strptime(raw, fmt) if fmt else dateparser.parse(raw)
    except (ValueError, OverflowError, TypeError):
        return None
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
