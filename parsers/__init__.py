"""Per-source custom parsers for pages that don't fit the generic CSS model.

A source in sources.yml opts in with `parser: <name>`; build.py then imports
parsers/<name>.py and calls:

    parse(html: str, base_url: str, source: dict) -> list[core.Item]

Use this escape hatch only when the generic `selectors:` path can't express a
site's shape (e.g. no per-item container, no permalinks, fields concatenated).
"""
