"""What a web-gate run must actually open a browser for.

The gate used to open two real browser contexts for every page in the tree, every time.
At 99 pages that is a six-minute round whether or not a single byte moved, and it is
O(topics × locales) — unusable at the thousand-topic scale the product is aimed at.

Two facts make almost all of that work redundant.

* **A page's browser behaviour is a function of bytes.**  What Chromium does with
  ``/en/topics/x/`` is decided by that page's own bytes, the chrome stylesheet and script
  served beside it, and the assertions this gate makes.  Hash all three and a page that
  has already passed under exactly that triple has nothing left to prove.  Data islands
  need no separate key: they are content-addressed and their hashes are *in* the page.
* **A chrome change is a global change, and typography is the thing it moves.**  It
  invalidates every page at once, so a byte-level cache buys nothing there.  What matters
  then is coverage of the ways text can break a layout — direction, script, word length —
  and of the page shapes whose code paths differ, not one run per topic per language.

So the run splits its pages three ways:

``new``
    Bytes this cache has never seen pass.  **Always checked in full.**  A candidate bundle
    at touchpoint two is entirely new bytes, so nothing about the publish path relaxes.
``cached``
    Same bytes, same chrome, same gate code.  Skipped.
``stale``
    Bytes that passed before, under a different chrome or a different gate.  These are
    *sampled*: one page per (page shape × typography stratum), with the representative
    rotating on the chrome fingerprint so successive chrome changes land on different
    pages.  Everything not sampled keeps its older verdict, and the run says so out loud.

``--full`` turns all three into "check everything", which is what a release does.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

#: Machine-local, never committed: a cache is not provenance, and keeping it out of git
#: also keeps parallel agent sessions from fighting over one file.  The build machine that
#: holds the artifacts is the only machine that runs the gate anyway.
CACHE_PATH = Path(__file__).resolve().parents[3] / ".newsab" / "web_gate_verified.json"

#: Bump when an entry's meaning changes rather than its contents.
CACHE_VERSION = 1

#: Keep the file bounded; entries are cheap but a year of chrome revisions is not.
_MAX_ENTRIES = 20000

#: Typography strata.  Two locales share a stratum only when the layout risk they carry is
#: the same one: direction, script, and whether the script breaks lines between words.
_LOCALE_STRATA: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("rtl", ("ar", "he", "fa", "ur")),
    ("cjk-unspaced", ("zh-CN", "zh-TW", "zh", "ja")),
    ("hangul", ("ko",)),
    ("indic", ("hi", "bn", "ta", "te", "mr")),
    ("cyrillic-long", ("ru", "uk", "bg", "sr")),
    ("latin", ("en", "es", "fr", "de", "pt", "it", "nl", "id", "vi", "tr", "pl")),
)

_STRATUM_OF = {
    locale: name for name, locales in _LOCALE_STRATA for locale in locales
}


def locale_stratum(locale: str) -> str:
    """The typography class a locale belongs to.

    A language nobody classified gets a stratum of its own rather than being folded into
    the biggest one: an unknown script is exactly the case where sampling must not assume
    another language already covered it.
    """
    return _STRATUM_OF.get(locale, f"unclassified:{locale}")


def page_shape(text: str) -> str:
    """The page features this gate actually branches on.

    Two pages with the same shape take the same path through every assertion below, so
    when only the chrome moved, checking both proves nothing the first did not.  This
    deliberately reads shape, never content: a different topic with the same furniture is
    the same test.
    """
    angles = len(re.findall(r"data-share-angle=", text))
    panels = len(set(re.findall(r'data-kindpanel="([^"]+)"', text)))
    return "|".join(
        (
            "islands" if 'data-src="' in text else "inline",
            f"panels={panels}",
            f"angles={min(angles, 3)}",
            "featured" if "data-angle=" in text else "no-featured",
            "timeline" if "tl-canvas" in text else "no-timeline",
            "tips" if "data-tip=" in text else "no-tips",
        )
    )


def _digest(*parts: bytes) -> str:
    hasher = hashlib.sha256()
    for part in parts:
        hasher.update(part)
        hasher.update(b"\x00")
    return hasher.hexdigest()


def gate_fingerprint() -> str:
    """Everything about *this checkout* that decides what the gate asserts.

    Hashing the source beats a hand-maintained version constant: an assertion edited
    without a bump would otherwise keep skipping the pages it was edited to catch.  The
    browser build is in here too, because layout numbers are its output.
    """
    package = Path(__file__).resolve().parent
    parts: list[bytes] = []
    for path in sorted(package.glob("*.py")):
        parts.append(path.name.encode("utf-8"))
        parts.append(hashlib.sha256(path.read_bytes()).digest())
    try:
        from importlib.metadata import version

        parts.append(version("playwright").encode("utf-8"))
    except Exception:  # noqa: BLE001 - an unpinnable browser just means a coarser key
        parts.append(b"playwright:unknown")
    return _digest(*parts)


def chrome_fingerprint(root: Path, overlay: dict[str, bytes]) -> str:
    """The chrome bytes a browser will actually load from this root.

    The gate serves disk first and falls back to the overlay, so the fingerprint follows
    the same rule — a candidate bundle (chrome supplied in memory) and a production tree
    (chrome deployed on disk) both get the fingerprint of what is really served.
    """
    parts: list[bytes] = []
    for relative in sorted(overlay):
        deployed = root.joinpath(*relative.split("/"))
        payload = deployed.read_bytes() if deployed.is_file() else overlay[relative]
        parts.append(relative.encode("utf-8"))
        parts.append(hashlib.sha256(payload).digest())
    return _digest(*parts)


@dataclass(frozen=True)
class PageKey:
    """One page in one suite, and everything its verdict depends on."""

    url: str
    suite: str
    page_sha: str
    stratum: str
    shape: str

    def cache_key(self, gate: str, chrome: str) -> str:
        return _digest(
            gate.encode("ascii"),
            chrome.encode("ascii"),
            self.suite.encode("ascii"),
            self.page_sha.encode("ascii"),
        )


@dataclass
class Selection:
    """The verdict of the planner: what to run, and what keeps an older verdict."""

    run: list[PageKey] = field(default_factory=list)
    cached: list[PageKey] = field(default_factory=list)
    sampled_out: list[PageKey] = field(default_factory=list)

    @property
    def urls(self) -> list[str]:
        return [key.url for key in self.run]


class VerifiedCache:
    """The machine-local record of which page bytes passed under which chrome and gate."""

    def __init__(self, path: Path = CACHE_PATH, *, enabled: bool = True) -> None:
        self.path = path
        self.enabled = enabled
        self.entries: dict[str, dict] = {}
        if enabled and path.is_file():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                raw = {}
            if raw.get("version") == CACHE_VERSION:
                self.entries = raw.get("entries") or {}

    def holds(self, key: str) -> bool:
        return self.enabled and key in self.entries

    def has_seen_bytes(self, suite: str, page_sha: str) -> bool:
        if not self.enabled:
            return False
        return any(
            entry.get("suite") == suite and entry.get("page_sha") == page_sha
            for entry in self.entries.values()
        )

    def record(self, key: str, page: PageKey) -> None:
        if not self.enabled:
            return
        self.entries[key] = {
            "url": page.url,
            "suite": page.suite,
            "page_sha": page.page_sha,
            "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

    def save(self) -> None:
        if not self.enabled:
            return
        entries = self.entries
        if len(entries) > _MAX_ENTRIES:
            newest = sorted(entries.items(), key=lambda item: item[1].get("at", ""), reverse=True)
            entries = dict(newest[:_MAX_ENTRIES])
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": CACHE_VERSION, "entries": entries}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(tmp, self.path)


def build_keys(root: Path, urls: Iterable[str], suite: str) -> list[PageKey]:
    keys = []
    for url in urls:
        payload = (root / url.strip("/") / "index.html").read_bytes()
        text = payload.decode("utf-8", "replace")
        keys.append(
            PageKey(
                url=url,
                suite=suite,
                page_sha=hashlib.sha256(payload).hexdigest(),
                stratum=locale_stratum(url.strip("/").split("/")[0]),
                shape=page_shape(text),
            )
        )
    return keys


def plan(
    keys: list[PageKey],
    cache: VerifiedCache,
    *,
    gate: str,
    chrome: str,
    full: bool = False,
    per_stratum: int = 1,
) -> Selection:
    """Split the pages into run / cached / sampled-out.

    ``full`` runs everything, which is what a release gate wants.  Otherwise a page whose
    exact bytes have never passed is always run — sampling only ever thins pages a human
    has already seen proved, under a chrome that has since moved.
    """
    selection = Selection()
    if full:
        selection.run = list(keys)
        return selection

    stale: dict[tuple[str, str], list[PageKey]] = {}
    for key in keys:
        if cache.holds(key.cache_key(gate, chrome)):
            selection.cached.append(key)
        elif cache.has_seen_bytes(key.suite, key.page_sha):
            stale.setdefault((key.shape, key.stratum), []).append(key)
        else:
            selection.run.append(key)

    for stratum_key, members in sorted(stale.items()):
        ordered = sorted(members, key=lambda item: item.url)
        # Rotate the representative on the chrome fingerprint so two successive chrome
        # revisions do not keep testing the same page and never the rest of its stratum.
        offset = int(_digest(chrome.encode("ascii"), "".join(stratum_key).encode("utf-8"))[:8], 16)
        take = max(1, min(per_stratum, len(ordered)))
        chosen = {ordered[(offset + step) % len(ordered)].url for step in range(take)}
        for member in ordered:
            (selection.run if member.url in chosen else selection.sampled_out).append(member)
    selection.run.sort(key=lambda item: item.url)
    return selection


def default_workers(requested: Optional[int] = None) -> int:
    if requested:
        return max(1, requested)
    return min(8, max(1, (os.cpu_count() or 2) // 2))
