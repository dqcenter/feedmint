"""Custom parser for the Google Antigravity changelog.

Why this needs a custom parser (the generic CSS model can't express it):

    section.special-grid > div.grid-body
        div.version              "2.2.1June 25, 2026"   (version + date, one <p>)
        div.description          -> h3.heading-7        (the entry title)
        div.version              ...                    (next entry)
        div.description          ...
        ...

Entries are *alternating sibling* divs — there is no per-entry wrapper, and the
page has no permalinks. So we:
  - pair version[i] with description[i] in document order,
  - split the "2.2.1June 25, 2026" blob into version + date,
  - synthesize a stable unique guid: <changelog-url>#<version>.
"""

from __future__ import annotations

import re

from selectolax.parser import HTMLParser

from core import Item, parse_date

# Leading run of digits/dots = version; the remainder is the date text.
_VERSION_RE = re.compile(r"^\s*([0-9][0-9.]*)\s*(.+\S)\s*$", re.S)


def parse(html: str, base_url: str, source: dict) -> list[Item]:
    tree = HTMLParser(html)

    versions = tree.css("div.grid-body > div.version")
    descriptions = tree.css("div.grid-body > div.description")

    items: list[Item] = []
    for vnode, dnode in zip(versions, descriptions):
        title_node = dnode.css_first("h3")
        title = title_node.text(strip=True) if title_node else ""
        if not title:
            continue

        version, date = "", None
        if m := _VERSION_RE.match(vnode.text(strip=True)):
            version, date = m.group(1), parse_date(m.group(2))

        # Lead overview paragraph (separate from the long Improvements/Fixes
        # accordions) makes a clean short summary.
        changes = dnode.css_first("div.changes")
        summary = changes.text(strip=True) if changes else None

        # No per-entry permalink exists; version is the stable per-entry anchor.
        # Keep the #-anchored URL as the link (deep-links into the changelog),
        # but use an opaque, fragment-free guid so readers that strip #fragments
        # when deduping don't collapse every entry into one.
        link = f"{base_url}#{version}" if version else base_url
        guid = f"{source['slug']}-{version}" if version else None
        items.append(Item(title=title, link=link, date=date, guid=guid, summary=summary))

    return items
