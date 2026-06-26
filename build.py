#!/usr/bin/env python3
"""feedmint — mint RSS 2.0 feeds for sites that have a page but no feed.

Reads sources.yml, scrapes each source with the right tier (static httpx or
dynamic Playwright), extracts items (generic CSS selectors, or a custom
per-source parser), and writes feeds/<slug>.xml.

Resilience rule: a scrape that yields zero items must NOT overwrite
a good feed with an empty one. We raise loudly and leave the existing file
untouched so the GitHub Action fails visibly and the last good feed survives.

Idempotency: the channel lastBuildDate is set to the newest item's date — not
"now" — so a rerun with no new items produces byte-identical XML and git sees
no change (consumers' pubDates don't churn).

Item extraction, per source:
  - default        : generic CSS selectors under `selectors:` (one container
                     per item with title/link/date inside it).
  - `parser: <name>`: delegate to parsers/<name>.py's parse(html, base_url,
                     source) for sites that don't fit the generic shape.

Usage:
    python build.py                 # build every source in sources.yml
    python build.py --source antigravity
    python build.py --dry-run       # build in memory, write nothing
"""

from __future__ import annotations

import argparse
import importlib
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import yaml
from feedgen.feed import FeedGenerator
from selectolax.parser import HTMLParser

from core import BuildError, Item, parse_date

ROOT = Path(__file__).resolve().parent
SOURCES_FILE = ROOT / "sources.yml"
FEEDS_DIR = ROOT / "feeds"
USER_AGENT = (
    "feedmint/1.0 (+https://github.com/feedmint; RSS minter for pages without feeds)"
)
HTTP_TIMEOUT = 30.0
DYNAMIC_TIMEOUT_MS = 30_000


# --------------------------------------------------------------------------- #
# Fetching
# --------------------------------------------------------------------------- #
def fetch_static(url: str) -> str:
    """Fetch plain/SSR HTML with httpx."""
    import httpx

    resp = httpx.get(
        url,
        headers={"User-Agent": USER_AGENT},
        timeout=HTTP_TIMEOUT,
        follow_redirects=True,
    )
    resp.raise_for_status()
    return resp.text


def fetch_dynamic(url: str, wait_for: str | None) -> str:
    """Render a JS page with Playwright headless Chromium, return its HTML.

    Imported lazily so static-only runs don't require Playwright installed.
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(user_agent=USER_AGENT)
            page.goto(url, wait_until="networkidle", timeout=DYNAMIC_TIMEOUT_MS)
            if wait_for:
                page.wait_for_selector(wait_for, timeout=DYNAMIC_TIMEOUT_MS)
            return page.content()
        finally:
            browser.close()


# --------------------------------------------------------------------------- #
# Item extraction
# --------------------------------------------------------------------------- #
def extract_items(html: str, base_url: str, source: dict) -> list[Item]:
    """Dispatch to a custom parser if the source names one, else generic CSS."""
    parser_name = source.get("parser")
    if parser_name:
        mod = importlib.import_module(f"parsers.{parser_name}")
        return mod.parse(html, base_url, source)
    return parse_with_selectors(html, base_url, source["selectors"])


def _text(node) -> str:
    return node.text(strip=True) if node else ""


def parse_with_selectors(html: str, base_url: str, selectors: dict) -> list[Item]:
    """Generic extractor: one container per item, title/link/date inside it."""
    tree = HTMLParser(html)
    item_sel = selectors["item"]
    title_sel = selectors["title"]
    link_sel = selectors.get("link")
    date_sel = selectors.get("date")
    date_fmt = selectors.get("date_format")

    items: list[Item] = []
    for node in tree.css(item_sel):
        title = _text(node.css_first(title_sel))
        if not title:
            continue

        href = None
        if link_sel and (a := node.css_first(link_sel)):
            href = a.attributes.get("href")
        if not href and (a := node.css_first("a")):
            href = a.attributes.get("href")
        if not href and node.tag == "a":
            href = node.attributes.get("href")
        if not href:
            continue
        link = urljoin(base_url, href)

        date = None
        if date_sel and (dnode := node.css_first(date_sel)):
            raw = dnode.attributes.get("datetime") or _text(dnode)
            date = parse_date(raw, date_fmt)

        items.append(Item(title=title, link=link, date=date))
    return items


# --------------------------------------------------------------------------- #
# RSS generation
# --------------------------------------------------------------------------- #
def build_rss(feed_meta: dict, items: list[Item]) -> bytes:
    fg = FeedGenerator()
    fg.title(feed_meta["title"])
    fg.link(href=feed_meta["link"], rel="alternate")
    fg.description(feed_meta["description"])
    fg.language(feed_meta.get("language", "en"))
    fg.generator("feedmint")

    # Stable lastBuildDate = newest item date → byte-identical reruns.
    dated = [i.date for i in items if i.date]
    fg.lastBuildDate(max(dated) if dated else False)

    # feedgen prepends entries, so add oldest-first to keep newest on top.
    epoch = datetime.min.replace(tzinfo=timezone.utc)
    for item in sorted(items, key=lambda i: i.date or epoch):
        fe = fg.add_entry()
        fe.title(item.title)
        if item.summary:
            fe.description(item.summary)
        fe.link(href=item.link)
        # Opaque guid (isPermaLink=false) when the link isn't a reliable
        # permalink; otherwise the link itself is the permalink guid.
        if item.guid:
            fe.guid(item.guid, permalink=False)
        else:
            fe.guid(item.link, permalink=True)
        if item.date:
            fe.pubDate(item.date)

    return fg.rss_str(pretty=True)


# --------------------------------------------------------------------------- #
# Per-source build
# --------------------------------------------------------------------------- #
def build_source(source: dict, *, dry_run: bool = False) -> bool:
    """Build one source. Returns True if the on-disk feed changed."""
    slug = source["slug"]
    tier = source["tier"]
    url = source["url"]
    print(f"[{slug}] {tier} fetch: {url}")

    if tier == "static":
        html = fetch_static(url)
    elif tier == "dynamic":
        html = fetch_dynamic(url, source.get("wait_for"))
    else:
        raise BuildError(f"[{slug}] unknown tier {tier!r} (expected static|dynamic)")

    items = extract_items(html, url, source)
    print(f"[{slug}] parsed {len(items)} item(s)")

    # Resilience: never overwrite a good feed with an empty one.
    if not items:
        raise BuildError(
            f"[{slug}] zero items — refusing to overwrite feeds/{slug}.xml. "
            "Check the selectors/parser against the current page."
        )

    rss = build_rss(source["feed"], items)
    out = FEEDS_DIR / f"{slug}.xml"

    if dry_run:
        print(f"[{slug}] dry-run: would write {len(rss)} bytes to {out}")
        return False

    old = out.read_bytes() if out.exists() else None
    if old == rss:
        print(f"[{slug}] unchanged")
        return False

    FEEDS_DIR.mkdir(parents=True, exist_ok=True)
    out.write_bytes(rss)
    print(f"[{slug}] wrote {out} ({len(rss)} bytes)")
    return True


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def load_sources() -> list[dict]:
    data = yaml.safe_load(SOURCES_FILE.read_text())
    sources = (data or {}).get("sources", [])
    if not sources:
        raise BuildError(f"no sources defined in {SOURCES_FILE}")
    return sources


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Mint RSS feeds from sources.yml")
    ap.add_argument("--source", help="build only this slug (default: all)")
    ap.add_argument("--dry-run", action="store_true", help="build but write nothing")
    args = ap.parse_args(argv)

    sources = load_sources()
    if args.source:
        sources = [s for s in sources if s["slug"] == args.source]
        if not sources:
            print(f"no source with slug {args.source!r}", file=sys.stderr)
            return 2

    failures = 0
    for source in sources:
        try:
            build_source(source, dry_run=args.dry_run)
        except Exception as exc:  # keep going so one bad source doesn't block others
            failures += 1
            print(f"[{source.get('slug', '?')}] FAILED: {exc}", file=sys.stderr)

    if failures:
        print(f"{failures} source(s) failed", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
