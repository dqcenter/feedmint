# feedmint

> Mint RSS feeds for sites that have a news/changelog page but no feed.

feedmint is a **serverless feed factory**: a public GitHub repo whose scheduled
Actions scrape "page, but no RSS" sites, regenerate a static RSS 2.0 file per
source, and commit it. Downstream readers just subscribe to the raw file URL —
exactly like any other feed. There is **no server to run**; GitHub provides the
cron, the scraping runners, and the hosting.

```
sources.yml ──▶ GitHub Action (daily cron, one job per source)
                   │  static tier:   httpx + selectolax
                   │  dynamic tier:  Playwright (headless Chromium)
                   ▼
              build RSS 2.0  ──▶  commit only if the file changed
                   ▼
       feeds/<slug>.xml  ──▶  served raw to any reader
```

## Subscribing to a feed

Feeds are served straight from the repo over `raw.githubusercontent.com` — no
auth, no API:

```
https://raw.githubusercontent.com/dqcenter/feedmint/main/feeds/<slug>.xml
```

For example, the Antigravity feed is at
`https://raw.githubusercontent.com/dqcenter/feedmint/main/feeds/antigravity.xml`.

Current feeds:

| slug | source | feed |
|------|--------|------|
| `antigravity` | [Google Antigravity changelog](https://antigravity.google/changelog) | `feeds/antigravity.xml` |
| `superhuman-ai` | [Superhuman AI newsletter](https://www.superhuman.ai/archive) | `feeds/superhuman-ai.xml` |
| `openai-news` | [OpenAI News](https://openai.com/news/) | `feeds/openai-news.xml` |

## Adding a source

Adding a feed is **one entry in `sources.yml`** — no code change for
well-behaved pages. Each entry:

```yaml
sources:
  - slug: example          # output filename: feeds/example.xml
    tier: static           # static (httpx) | dynamic (Playwright, JS pages)
    url: https://example.com/news
    feed:
      title: "Example — News"
      link: https://example.com/news
      description: "Example news, minted by feedmint."
      language: en         # optional, default "en"
    selectors:             # how to find items in the (rendered) HTML
      item: "article"      # one element per entry
      title: "h2"          # title, relative to item
      link: "a"            # optional; falls back to the item's own/first <a>
      date: "time"         # optional; reads a `datetime` attr or the text
    # date_format: "%Y-%m-%d"   # optional strptime; omit to auto-parse
    # wait_for: ".feed"         # dynamic only: await this selector before scraping
```

### Tiers

- **static** — server-rendered / plain HTML. Fast and cheap (`httpx` +
  `selectolax`).
- **dynamic** — JS-hydrated pages. Rendered with Playwright headless Chromium,
  then parsed the same way. Set `wait_for` to a selector that only appears once
  the content has loaded, so we never read an empty shell.

### Custom parsers (when selectors aren't enough)

Some pages don't fit the "one container per entry, with a link inside" model —
no per-item wrapper, no permalinks, or fields mashed together. For those, set
`parser:` instead of `selectors:` and implement the logic in
`parsers/<name>.py`:

```python
# parsers/<name>.py
from core import Item, parse_date

def parse(html: str, base_url: str, source: dict) -> list[Item]:
    ...
    return [Item(title=..., link=..., date=...)]
```

The generic CSS path stays the default; `parser:` is the escape hatch. See
[`parsers/antigravity.py`](parsers/antigravity.py) — the Antigravity changelog
is an alternating version/description grid with no permalinks, so its parser
pairs the columns, splits the `"2.2.1June 25, 2026"` blob, and synthesises a
stable `…/changelog#<version>` guid per entry.

## How it builds

`build.py` does the work for each source:

1. **Fetch** — `static` via httpx, `dynamic` via Playwright.
2. **Extract** — custom `parser:` if set, else the generic `selectors:` path.
3. **Resilience** — a scrape that yields **zero items raises and exits non-zero**,
   leaving the existing `feeds/<slug>.xml` untouched. A broken selector can
   never overwrite a good feed with an empty one; the run just fails loudly.
4. **Idempotency** — the channel `lastBuildDate` is the newest item's date, not
   "now", and the file is only rewritten when its bytes actually change. So a
   run with no new entries is a no-op and consumers' `pubDate`s never churn.

```bash
python build.py                    # build every source
python build.py --source antigravity
python build.py --dry-run          # build in memory, write nothing
```

## Local development

The dynamic tier needs Chromium and its system libraries. To keep your host
clean, develop in the throwaway Docker image (the official Playwright image,
which bundles Chromium + deps):

```bash
docker build -f Dockerfile.dev -t feedmint-dev .
docker run --rm -v "$PWD":/app feedmint-dev python build.py --source antigravity
```

Source is bind-mounted, so edits are live. Prefer a local venv? Then:

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python -m playwright install --with-deps chromium   # needs sudo for the system deps
python build.py
```

## Automation

[`.github/workflows/feeds.yml`](.github/workflows/feeds.yml) runs daily
(06:17 UTC) and on manual `workflow_dispatch`:

- **discover** — reads `sources.yml` and builds the job matrix, so a new source
  needs no workflow edit.
- **build** — one job per source (`fail-fast: false`); installs deps + Chromium,
  runs `build.py --source <slug>`, uploads the feed as an artifact. A failed
  source fails only its own job.
- **commit** — collects the feeds that succeeded and makes a single commit, only
  if something changed. A failed source uploads nothing, so its last-good feed
  stays put.

The Python version is pinned in [`.python-version`](.python-version) (3.13) and
read by `setup-python` in CI.

## Project layout

```
feedmint/
├── sources.yml            # every source; adding a feed = one entry
├── build.py               # fetch → extract → RSS → write-if-changed
├── core.py                # shared Item model + date parsing
├── parsers/               # custom per-source parsers (escape hatch)
│   └── antigravity.py
├── feeds/                 # generated RSS output (served raw)
├── requirements.txt
├── Dockerfile.dev         # throwaway Playwright dev container
├── .python-version        # CI Python (3.13)
└── .github/workflows/feeds.yml
```

## Why a separate public GitHub repo

The whole value of the pattern is that it's **off our own infrastructure**:
GitHub runs the cron, the scrape, and hosts the output XML for free; failures
show up as Action run history; a scraper bug can never touch the downstream
reader. A **public** repo is required so feeds are fetchable without auth and
consumers can "just paste a URL".
