"""Custom parser for the Google Antigravity changelog.

Why this needs a custom parser (the generic CSS model can't express it):

    section.special-grid > div.grid-body
        div.section-row-wrapper
            div.version          "2.3.1July 16, 2026"   (version + date, one blob)
            div.description       -> h3.heading-7        (the entry title)
        div.section-row-wrapper
            div.version          ...                    (next entry)
            div.description       ...
        ...

Each entry lives in a div.section-row-wrapper (version + description pair), but
the page still has no permalinks and the "2.3.1July 16, 2026" blob concatenates
version and date. So we:
  - iterate one wrapper per entry,
  - split the "2.3.1July 16, 2026" blob into version + date,
  - synthesize a stable unique guid: <slug>-<version>.

(Older snapshots exposed the version/description divs as *alternating siblings*
directly under div.grid-body with no wrapper; the site added the wrapper around
2026-07. We fall back to the sibling-zip layout if no wrappers are present.)
"""

from __future__ import annotations

import hashlib
import re

from selectolax.parser import HTMLParser

from core import Item, parse_date

# Leading run of digits/dots = version; the remainder is the date text.
_VERSION_RE = re.compile(r"^\s*([0-9][0-9.]*)\s*(.+\S)\s*$", re.S)


def parse(html: str, base_url: str, source: dict) -> list[Item]:
    tree = HTMLParser(html)

    # Current layout: one div.section-row-wrapper per entry, each holding a
    # div.version + div.description. Fall back to the older alternating-sibling
    # layout (version/description divs directly under grid-body) if no wrappers.
    wrappers = tree.css("div.section-row-wrapper")
    if wrappers:
        pairs = [
            (w.css_first("div.version"), w.css_first("div.description"))
            for w in wrappers
        ]
    else:
        versions = tree.css("div.grid-body > div.version")
        descriptions = tree.css("div.grid-body > div.description")
        pairs = list(zip(versions, descriptions))

    items: list[Item] = []
    for vnode, dnode in pairs:
        if not vnode or not dnode:
            continue
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

        # No per-entry permalink exists; version is the per-entry anchor. Keep
        # the #-anchored URL as the link (deep-links into the changelog), but use
        # an opaque, fragment-free guid so readers that strip #fragments when
        # deduping don't collapse every entry into one.
        #
        # Version alone is NOT unique: the page carries several version tracks
        # (separate grid-body sections), so the same version string can appear
        # more than once (e.g. two distinct 2.0.1 entries). Fold a stable hash
        # of the title into the guid so those don't collide and drop an entry.
        link = f"{base_url}#{version}" if version else base_url
        if version:
            tag = hashlib.sha1(title.encode("utf-8")).hexdigest()[:8]
            guid = f"{source['slug']}-{version}-{tag}"
        else:
            guid = None
        items.append(Item(title=title, link=link, date=date, guid=guid, summary=summary))

    return items
