"""Custom parser for the Google Antigravity changelog.

The changelog moved (~2026-10) from antigravity.google/changelog (a JS grid) to
antigravity.google/docs/changelog, a server-rendered Astro docs page — so it is
now a STATIC-tier source. Layout:

    article.release-entry#rel-<product>-<version>      one per release, per product tab
        time.rn-date-text          "November 9, 2026"
        h3.rn-headline             entry title
        div.rn-summary             lead paragraph (short summary)
    article.release-entry.rn-model-row#rel-<product>-model-<name>
        [data-release-key="models/<name>"]
        time[datetime]             ISO date
        h3.rn-headline             model name
        a.rn-model-link            -> blog post

Products: hub, cli, ide, sdk, vscode, jetbrains, visual-studio, xcode, zed, ...
Model-launch cards are repeated in every product tab, so they are deduped by
data-release-key. Version strings repeat across products, so the product is
part of both the title and the guid (the article id is unique page-wide).
"""

from __future__ import annotations

import re

from selectolax.lexbor import LexborHTMLParser as HTMLParser

from core import Item, parse_date

# rel-<product>-<version>  (product may contain hyphens, e.g. visual-studio)
_RELEASE_ID_RE = re.compile(r"^rel-(?P<product>.+?)-(?P<version>v?\d[\w.]*)$")

_PRODUCT_LABELS = {
    "hub": "Hub",
    "cli": "CLI",
    "ide": "IDE",
    "sdk": "SDK",
    "vscode": "VS Code",
    "jetbrains": "JetBrains",
    "visual-studio": "Visual Studio",
    "xcode": "Xcode",
    "zed": "Zed",
    "eclipse": "Eclipse",
}


def _text(node, sel: str) -> str:
    n = node.css_first(sel)
    return n.text(strip=True) if n else ""


def parse(html: str, base_url: str, source: dict) -> list[Item]:
    tree = HTMLParser(html)
    slug = source["slug"]
    items: list[Item] = []
    seen_models: set[str] = set()

    for art in tree.css("article.release-entry"):
        art_id = art.attributes.get("id") or ""
        title = _text(art, "h3.rn-headline")
        if not art_id or not title:
            continue
        summary = _text(art, "div.rn-summary") or None
        time_node = art.css_first("time")
        raw_date = (time_node.attributes.get("datetime") or time_node.text(strip=True)) if time_node else ""
        date = parse_date(raw_date) if raw_date else None

        if "rn-model-row" in (art.attributes.get("class") or ""):
            key = art.attributes.get("data-release-key") or art_id
            if key in seen_models:
                continue
            seen_models.add(key)
            a = art.css_first("a.rn-model-link")
            href = a.attributes.get("href") if a else None
            link = (
                f"https://antigravity.google{href}" if href and href.startswith("/")
                else href or f"{base_url}#{art_id}"
            )
            items.append(Item(
                title=f"Model launch: {title}", link=link, date=date,
                guid=f"{slug}-{key.replace('/', '-')}", summary=summary,
            ))
            continue

        m = _RELEASE_ID_RE.match(art_id)
        if m:
            product = _PRODUCT_LABELS.get(m["product"], m["product"])
            version = m["version"].lstrip("v")
            full_title = f"{product} {version}: {title}"
        else:
            full_title = title
        items.append(Item(
            title=full_title, link=f"{base_url}#{art_id}", date=date,
            guid=f"{slug}-{art_id}", summary=summary,
        ))

    return items
