"""Custom parser for the Google Antigravity blog ("news"), via the homepage.

The /blog index itself does not render its post list in headless Chromium —
no embedded data, no XHR carrying posts, and the sitemap lists only one post
(it appears to be gated by anti-bot or a component that never hydrates headless).

The homepage, however, reliably renders a curated slider of the blog posts with
clean per-card markup:

    a[href^="/blog/"]
        p.item-title                -> title
        div.list-item-metadata
            span.caption            -> date ("May 19, 2026", with year)
            span.caption            -> category

Antigravity is new (launched Nov 2025), so this curated set is effectively the
whole blog. We therefore scrape the homepage (the source `url`) and read those
cards. The /blog/<slug> links are real permalinks, so the default permalink guid
is fine — no opaque guid needed here.

If the homepage ever stops rendering the slider, `wait_for` times out and the
build yields zero items, which fails the run loudly and keeps the last good feed.
"""

from __future__ import annotations

from urllib.parse import urljoin

from selectolax.parser import HTMLParser

from core import Item, parse_date


def parse(html: str, base_url: str, source: dict) -> list[Item]:
    tree = HTMLParser(html)

    seen: set[str] = set()
    items: list[Item] = []
    for a in tree.css('a[href^="/blog/"]'):
        href = a.attributes.get("href", "")
        # Skip the /blog index nav link and any duplicate cards.
        if not href or href.rstrip("/").endswith("/blog") or href in seen:
            continue
        seen.add(href)

        title_node = a.css_first("p.item-title") or a.css_first(".item-title")
        title = title_node.text(strip=True) if title_node else ""
        if not title:
            continue

        date_node = a.css_first("div.list-item-metadata span.caption") or a.css_first(
            ".list-item-metadata .caption"
        )
        date = parse_date(date_node.text(strip=True)) if date_node else None

        items.append(Item(title=title, link=urljoin(base_url, href), date=date))

    return items
