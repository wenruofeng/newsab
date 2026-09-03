#!/usr/bin/env python3
"""Run one scoped search cell through DuckDuckGo's html endpoint, no browser needed.

`search-strategy.md` §1b routes `site:` cells to `https://html.duckduckgo.com/html/`
because it was the one route measured to honour the scope. Opening it in the shared
Playwright browser serialized every parallel collect worker behind one session; this
script walks the same endpoint through `newsab_corpus`'s honest fetcher instead —
product-token identity, robots read, per-host pacing and the browser retry all kept —
so N workers can search N cells at once.

Output is one JSON document on stdout: the resolved result list plus the on-host /
off-host split, because the §1b silent-drop test ("results that do not belong to the
host were never scoped") has to be measurable, not eyeballed. Off-host rows are
reported, never silently dropped.

Exit codes mirror `python -m newsab_corpus fetch`: 0 results parsed · 1 the endpoint
did not yield a readable page · 2 bad usage · 3 the browser retry was needed but no
Chromium is installed.
"""

from __future__ import annotations

import _bootstrap  # noqa: F401

import argparse
import json
import sys
import tempfile
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, quote_plus, urlparse

from newsab_corpus.fetch import BrowserUnavailable, Fetcher

ENDPOINT = "https://html.duckduckgo.com/html/"


class _Results(HTMLParser):
    """The endpoint's result anchors: ``<a class="result__a" href="…">title</a>``."""

    def __init__(self) -> None:
        super().__init__()
        self.results: list[tuple[str, str]] = []
        self._href: str | None = None
        self._title: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        got = dict(attrs)
        if tag == "a" and "result__a" in (got.get("class") or ""):
            self._href = got.get("href") or ""
            self._title = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._title.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href is not None:
            self.results.append((self._href, "".join(self._title).strip()))
            self._href = None


def resolve_result_url(href: str) -> str:
    """Unwrap DDG's ``//duckduckgo.com/l/?uddg=<encoded>`` redirect, if present."""
    parsed = urlparse(href)
    if parsed.path.rstrip("/").endswith("/l"):
        target = parse_qs(parsed.query).get("uddg")
        if target:
            return target[0]
    return href


def on_host(url: str, host: str) -> bool:
    """True when ``url`` is on ``host`` or one of its subdomains."""
    netloc = urlparse(url).netloc.lower().split(":")[0]
    host = host.lower()
    return netloc == host or netloc.endswith("." + host)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("terms", help="the query terms (quote the whole cell)")
    parser.add_argument(
        "--site",
        help="scope to this host with site:; the on/off-host split is judged against it",
    )
    parser.add_argument(
        "--max", type=int, default=30, help="cap the parsed result rows (default 30)"
    )
    args = parser.parse_args()

    query = f"site:{args.site} {args.terms}" if args.site else args.terms
    url = f"{ENDPOINT}?q={quote_plus(query)}"

    fetcher = Fetcher()
    try:
        with tempfile.TemporaryDirectory(prefix="ddg-search-") as scratch:
            outcome = fetcher.fetch(url, out_dir=Path(scratch))
            if not outcome.ok or not outcome.path:
                print(
                    json.dumps(
                        {"query": query, "ok": False, "reason": outcome.reason},
                        ensure_ascii=False,
                    )
                )
                return 1
            markup = Path(outcome.path).read_text(encoding="utf-8", errors="replace")
    except BrowserUnavailable as exc:
        print(str(exc), file=sys.stderr)
        return 3
    finally:
        fetcher.close()

    parser_ = _Results()
    parser_.feed(markup)
    rows = []
    for href, title in parser_.results[: args.max]:
        resolved = resolve_result_url(href)
        row = {"url": resolved, "title": title}
        if args.site:
            row["on_site"] = on_host(resolved, args.site)
        rows.append(row)
    report = {
        "query": query,
        "ok": True,
        "layer": outcome.layer,
        "robots": outcome.robots,
        "results": rows,
    }
    if args.site:
        report["on_site"] = sum(1 for row in rows if row["on_site"])
        report["off_site"] = len(rows) - report["on_site"]
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
