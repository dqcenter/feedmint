"""Custom parser for the Superhuman AI newsletter (Zain Kahn, on beehiiv).

The publication exposes no usable RSS — the native beehiiv feed 404s and the
custom-domain /feed, /rss.xml, /feed.xml paths all 403. The archive at /archive
lists recent issues as /p/<slug> links, but it shows no dates and mangles the
visible titles (title + subtitle + byline run together).

Each *issue* page, however, server-renders clean metadata in its <head> — an
`og:title` and a JSON-LD `datePublished` — both fetchable without JS. So we take
the /p/ links from the (static) archive HTML, then statically fetch each issue
page and read its title + publish date from the head.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin

import httpx
from selectolax.parser import HTMLParser

from core import Item, parse_date

_USER_AGENT = "feedmint/1.0 (+https://github.com/dqcenter/feedmint; RSS minter for pages without feeds)"
_DATE_RE = re.compile(r'"datePublished"\s*:\s*"([^"]+)"')


def parse(html: str, base_url: str, source: dict) -> list[Item]:
    tree = HTMLParser(html)

    # Unique /p/ issue links, in document order.
    seen: set[str] = set()
    links: list[str] = []
    for a in tree.css('a[href^="/p/"]'):
        href = a.attributes.get("href", "")
        if href and href not in seen:
            seen.add(href)
            links.append(urljoin(base_url, href))

    items: list[Item] = []
    with httpx.Client(
        headers={"User-Agent": _USER_AGENT}, timeout=30.0, follow_redirects=True
    ) as client:
        for url in links:
            try:
                resp = client.get(url)
                resp.raise_for_status()
            except httpx.HTTPError:
                continue  # skip one bad issue; the zero-items rule guards the rest

            post = HTMLParser(resp.text)
            meta = post.css_first('meta[property="og:title"]')
            title = ((meta.attributes.get("content") if meta else None) or "").strip()
            if not title:
                continue

            m = _DATE_RE.search(resp.text)
            date = parse_date(m.group(1)) if m else None
            items.append(Item(title=title, link=url, date=date))

    return items
