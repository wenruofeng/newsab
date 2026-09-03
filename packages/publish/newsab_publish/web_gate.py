"""Browser-level M2 acceptance gate for the generated static site.

This is a verification command, not part of the deterministic bundle fingerprint.  It
serves an already-built closed directory on loopback and checks the same bytes at the
desktop/mobile, keyboard/touch and reduced-motion boundaries the implementation claims.

**Every failure in a run is reported, not just the first.**  A whole-tree run
costs minutes, so fail-fast made each round surface exactly one defect: an `/ar/` RTL
assertion hid an unrelated `/ru/` card overflow, and the two had to be found serially at
full price each.  Checks are grouped into named *steps*; a failed assertion ends its own
step — the rest of that step would be reading a page already known to be wrong — and the
run carries on with the next step, page and viewport.
"""

from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit
from typing import Callable, Iterator, Optional

from newsab_schema.io import ArtifactError

from . import chrome, gate_selection
from .page_semantics import check_page_semantics
from .static_server import temporary_server
from .themes import load_theme_registry


#: Per-action browser timeout.  Every wait below is a condition, not a sleep, so this is
#: only ever paid by a page that is actually broken.
_TIMEOUT_MS = 3000

#: How many failures a run prints in full before it just counts the rest.
_MAX_REPORTED = 60


class _StepFailed(Exception):
    """One failed assertion.  It ends its own step and nothing else."""


class Gate:
    """Collects the failures of one run so a single round reports all of them."""

    def __init__(self) -> None:
        self.failures: list[str] = []

    def fail(self, message: str) -> None:
        self.failures.append(message)

    def extend(self, messages: list[str]) -> None:
        self.failures.extend(messages)

    @contextmanager
    def step(self, label: str) -> Iterator[None]:
        """Run one group of related assertions, absorbing its first failure.

        A browser timeout or a missing element raises out of Playwright rather than out of
        :func:`_assert`; that is a gate failure too, not a crash of the run, so it is
        recorded under the step's own label and the next step still runs.
        """
        try:
            yield
        except _StepFailed as exc:
            self.failures.append(str(exc))
        except Exception as exc:  # noqa: BLE001 - a broken page must not end the run
            self.failures.append(f"{label}: {type(exc).__name__}: {exc}")

    def raise_if_failed(self) -> None:
        if not self.failures:
            return
        shown = self.failures[:_MAX_REPORTED]
        rest = len(self.failures) - len(shown)
        body = "\n".join(f"  - {item}" for item in shown)
        tail = f"\n  … and {rest} more" if rest else ""
        raise ArtifactError(f"web gate found {len(self.failures)} failure(s):\n{body}{tail}")


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise _StepFailed(message)


def _sequence(
    gate: Gate, page, steps: list[tuple[str, Callable[[], None]]]
) -> None:
    """Run named steps in order, clearing overlays left behind by a failed one.

    Steps share one live page, so a step that fails halfway can leave a modal or a pinned
    tooltip open and turn every later click into a spurious failure.  Recovery runs only
    after an actual failure, so a green page behaves exactly as it did before.
    """
    for label, action in steps:
        before = len(gate.failures)
        with gate.step(label):
            action()
        if len(gate.failures) > before:
            _dismiss_overlays(page)


def _dismiss_overlays(page) -> None:
    try:
        page.evaluate(
            """() => {
              for (const node of document.querySelectorAll('.modal:not([hidden])'))
                node.hidden = true;
              const tip = document.getElementById('floattip');
              if (tip) tip.hidden = true;
              document.body.classList.remove('suggest-open');
            }"""
        )
    except Exception:  # noqa: BLE001 - best effort only; the failure is already recorded
        pass


def _topic_paths(root: Path) -> list[str]:
    found = []
    for path in sorted(root.glob("*/topics/*/index.html")):
        text = path.read_text(encoding="utf-8")
        if "data-site-locale=" in text:
            found.append("/" + path.relative_to(root).parent.as_posix() + "/")
    if not found:
        raise ArtifactError("web gate found no M2 topic pages")
    return found


def _home_paths(root: Path) -> list[str]:
    found = [
        "/" + path.relative_to(root).parent.as_posix() + "/"
        for path in sorted(root.glob("*/index.html"))
        if '<link rel="canonical"' in path.read_text(encoding="utf-8")
    ]
    # A candidate review directory carries only topic pages; a production tree (marked
    # by its sitemap) must never pass the gate with zero home pages checked.
    if not found and (root / "sitemap.xml").is_file():
        raise ArtifactError("web gate found no home pages with a canonical link")
    return found


def _local_path(url: str) -> str:
    """A released page names assets under the site origin; a candidate names them root-relative.

    The gate reads both trees, so it resolves either shape to a path inside the root it
    was given rather than assuming one of them.
    """
    if url.startswith("http://") or url.startswith("https://"):
        return urlsplit(url).path
    return url


def _check_chrome(gate: Gate, root: Path, topic_paths: list[str], overlay: dict[str, bytes]) -> None:
    """A content document must state its theme and link chrome, and carry none of it.

    This is the byte-level half of the contract revision: if a page still inlines its own
    stylesheet or script, the user's approval is again bound to the site's typography
    and every chrome change costs a full re-review.
    """
    for url in topic_paths:
        with gate.step(f"{url}: chrome links"):
            text = (root / url.strip("/") / "index.html").read_text(encoding="utf-8")
            _assert(
                f'<link rel="stylesheet" href="{chrome.STYLESHEET_URL}">' in text,
                f"{url}: page does not link the site chrome stylesheet",
            )
            _assert(
                f'<script src="{chrome.SCRIPT_URL}" defer></script>' in text,
                f"{url}: page does not link the site chrome script",
            )
            _assert("<style>" not in text, f"{url}: content document still inlines a stylesheet")
            _assert(
                "fonts.googleapis.com" not in text,
                f"{url}: content document still loads fonts of its own",
            )
            _assert(
                re.search(r'data-theme-token="[a-z][a-z0-9-]*"', text) is not None,
                f"{url}: page does not state a theme token",
            )
    for relative in (chrome.STYLESHEET_PATH, chrome.SCRIPT_PATH):
        with gate.step("chrome assets"):
            _assert(
                (root / relative).is_file() or relative in overlay,
                f"chrome asset is neither deployed nor supplied: {relative}",
            )


def _check_static(gate: Gate, root: Path, topic_paths: list[str], overlay: dict[str, bytes]) -> None:
    # A candidate bundle states root-relative URLs; the crawler metadata only becomes a
    # released fact once the site build resolves it, so the released-tree assertions
    # apply to a production tree (the one with a sitemap).
    released = (root / "sitemap.xml").is_file()
    for url in topic_paths:
        page_path = root / url.strip("/") / "index.html"
        text = page_path.read_text(encoding="utf-8")
        with gate.step(f"{url}: page metadata"):
            _assert('<link rel="canonical"' in text, f"{url}: canonical link is missing")
            _assert(
                len(re.findall(r'<link rel="canonical"', text)) == 1,
                f"{url}: page states more than one canonical link",
            )
            _assert('<link rel="alternate"' in text, f"{url}: alternate links are missing")
            _assert('property="og:image"' in text, f"{url}: og:image is missing")
            _assert('data-share-angle=' in text, f"{url}: angle share controls are missing")
        question_ids = re.findall(r'data-share-angle="([^"]+)"', text)
        share_dir = page_path.parent / "share"
        share_files = sorted(share_dir.glob("angle-*.svg")) if share_dir.is_dir() else []
        with gate.step(f"{url}: share cards"):
            # A bundle minted since publish-0.8.0 ships no SVG cards; one minted
            # earlier ships exactly one per rendered angle.  Both shapes stand in the same
            # production tree, so the assertion follows what the bundle ships: none at all,
            # or exact coverage — never a partial set, which would mean a broken render.
            expected_names = {f"angle-{question_id}.svg" for question_id in question_ids}
            found_names = {path.name for path in share_files}
            _assert(
                not found_names or found_names == expected_names,
                f"{url}: share cards do not exactly cover the rendered angles",
            )
            for share_file in share_files:
                try:
                    root_node = ET.parse(share_file).getroot()
                except ET.ParseError as exc:
                    raise _StepFailed(f"{share_file}: invalid SVG: {exc}") from exc
                _assert(
                    root_node.attrib.get("width") == "1200"
                    and root_node.attrib.get("height") == "630",
                    f"{share_file}: wrong dimensions",
                )
        landing_urls = re.findall(r'data-share-landing="([^"]+)"', text)
        with gate.step(f"{url}: share landings"):
            _assert(len(landing_urls) == len(question_ids), f"{url}: share landing count differs")
            for question_id, landing_url in zip(question_ids, landing_urls):
                landing = root / _local_path(landing_url).lstrip("/")
                _assert(landing.is_file(), f"{url}: share landing is missing: {landing_url}")
                landing_text = landing.read_text(encoding="utf-8")
                _assert('property="og:image"' in landing_text, f"{landing_url}: og:image missing")
                for landing_asset in re.findall(
                    r'<meta property="og:image" content="([^"]+)"', landing_text
                ):
                    _assert(
                        not (released and _local_path(landing_asset).endswith(".svg")),
                        f"{landing_url}: og:image is an SVG no social platform will render",
                    )
                _assert(
                    f"#angle-{question_id}" in landing_text,
                    f"{landing_url}: landing does not route to its fragment",
                )
        with gate.step(f"{url}: share assets"):
            for asset_url in re.findall(r'<meta property="og:image" content="([^"]+)"', text):
                local = _local_path(asset_url).split("#", 1)[0]
                target = root / local.lstrip("/")
                # The site's PNG card is chrome: a candidate names it before any chrome is
                # deployed beside it, so the overlay answers for it there.
                _assert(
                    target.is_file() or local.lstrip("/") in overlay,
                    f"{url}: share asset is missing: {asset_url}",
                )
                # No platform renders SVG as a card image, so a page that offers one is a
                # page whose share card silently does not exist.
                _assert(
                    not (released and local.endswith(".svg")),
                    f"{url}: og:image is an SVG no social platform will render: {asset_url}",
                )
        with gate.step(f"{url}: data islands"):
            # A page that externalizes its data islands must ship every referenced
            # content-addressed asset, its bytes must match the hash in its own filename,
            # and the per-language overlay must ride inline in the page.
            island_refs = re.findall(r'data-src="([^"]+)"', text)
            if island_refs:
                _assert(
                    'id="lang-overlay"' in text,
                    f"{url}: externalized islands without an inline language overlay",
                )
            for asset_url in island_refs:
                target = root / asset_url.lstrip("/")
                _assert(target.is_file(), f"{url}: data island asset is missing: {asset_url}")
                claimed = target.name.rsplit(".", 2)[-2]
                actual = hashlib.sha256(target.read_bytes()).hexdigest()[:16]
                _assert(
                    actual == claimed,
                    f"{url}: data island bytes do not match their content-hash name: {asset_url}",
                )


def _shipped_locales(topic_paths: list[str]) -> dict[str, set[str]]:
    """Which languages of each topic this tree actually holds — the locale set a page's
    ``hreflang`` alternates must name, no more and no fewer.

    Derived from the tree rather than from the site metadata on purpose: the gate reads a
    released tree *and* a candidate bundle, and the invariant a reader can check is that
    every page the tree ships is reachable from every other language of the same page.
    A published tree once shipped with no English at all and nothing said so.
    """
    shipped: dict[str, set[str]] = {}
    for url in topic_paths:
        parts = url.strip("/").split("/")
        shipped.setdefault(parts[-1], set()).add(parts[0])
    return shipped


def _check_semantics(
    root: Path,
    topic_paths: list[str],
    gate: Optional[Gate] = None,
    *,
    only: Optional[set[str]] = None,
    on_pass: Optional[Callable[[str], None]] = None,
) -> int:
    """Read the render the way a reader does — see :mod:`.page_semantics`.

    With no ``gate`` this raises on the first bad page, which is what a unit test wants; a
    run passes its collector so one round names every bad page.  ``only`` narrows which
    pages are read — the cross-page ``hreflang`` invariant is still derived from the whole
    tree, so a narrowed run asks the same question of the pages it does read.
    """
    shipped = _shipped_locales(topic_paths)
    checked = 0
    for url in topic_paths:
        if only is not None and url not in only:
            continue
        parts = url.strip("/").split("/")
        text = (root / url.strip("/") / "index.html").read_text(encoding="utf-8")
        locale = re.search(r'data-site-locale="([^"]+)"', text)
        if gate is None:
            check_page_semantics(
                text,
                label=url,
                root=root,
                page_locale=locale.group(1) if locale else parts[0],
                expected_locales=shipped[parts[-1]],
            )
        else:
            before = len(gate.failures)
            with gate.step(f"{url}: page semantics"):
                check_page_semantics(
                    text,
                    label=url,
                    root=root,
                    page_locale=locale.group(1) if locale else parts[0],
                    expected_locales=shipped[parts[-1]],
                )
            if on_pass is not None and len(gate.failures) == before:
                on_pass(url)
        checked += 1
    return checked


def semantics_locales(topic_paths: list[str]) -> dict[str, set[str]]:
    """The locale set each page's ``hreflang`` block is checked against."""
    shipped = _shipped_locales(topic_paths)
    return {url: shipped[url.strip("/").split("/")[-1]] for url in topic_paths}


#: The share of a card's width the paragraph under it must cover to count as *under* it.
_COLUMN_OVERLAP = 0.6

#: The rendered geometry of one angle's cards and the paragraphs beneath them.  DOM order
#: is checked statically; this asks the browser whether the two columns actually line up,
#: which is the thing the reviewer sees at touchpoint two.
_COLUMN_GEOMETRY = """(() => {
  const panel = document.querySelector('[data-kindpanel]:not([hidden])');
  const angle = panel && panel.querySelector('.angle');
  if (!angle) return null;
  const duo = angle.querySelector(':scope > .duo');
  const comm = angle.querySelector(':scope > .comm:not(.joint)');
  if (!duo || !comm) return null;
  const cards = Array.from(duo.children).filter(n => n.classList.contains('acard'));
  const paras = Array.from(comm.children).filter(n => n.tagName === 'P');
  if (!cards.length || cards.length !== paras.length) return {mismatch: true};
  const side = n => n.classList.contains('a') ? 'a'
                  : (n.classList.contains('b') ? 'b' : '?');
  return cards.map((card, i) => {
    const c = card.getBoundingClientRect();
    const p = paras[i].getBoundingClientRect();
    const mark = paras[i].querySelector('.cmark');
    return {
      card: side(card),
      para: mark ? side(mark) : '?',
      overlap: Math.min(c.right, p.right) - Math.max(c.left, p.left),
      width: Math.min(c.width, p.width),
    };
  });
})()"""

#: One round trip for the whole desktop relation row instead of three ``bounding_box``
#: calls.  Every extra call is a driver round trip paid once per page per viewport.
_RELATION_GEOMETRY = """(() => {
  const duo = document.querySelector('[data-kindpanel]:not([hidden]) .duo');
  if (!duo) return null;
  const cards = duo.querySelectorAll('.acard');
  const rel = duo.querySelector('.rel');
  const box = n => { if (!n) return null; const r = n.getBoundingClientRect();
                     return {x: r.x, y: r.y, width: r.width, height: r.height}; };
  const leads = rel && rel.querySelector('.rel-leads');
  return {
    first: box(cards[0]), second: box(cards[1]), rel: box(rel),
    leads: box(leads),
    transform: leads ? getComputedStyle(leads).transform : null,
  };
})()"""

#: A touch target must reach 44px; the *visible* box must not, or a row of badges becomes
#: a fence of mismatched slabs.  Measure the reach the page actually offers — the control
#: plus the hit area its ``::after`` carries — for every control in one round trip.
_TOUCH_REACH = """(selectors) => {
  const out = {};
  for (const selector of selectors) {
    const node = document.querySelector(selector);
    if (!node) continue;
    const box = node.getBoundingClientRect();
    const after = getComputedStyle(node, '::after');
    const w = parseFloat(after.width) || 0, h = parseFloat(after.height) || 0;
    out[selector] = {width: Math.max(box.width, w), height: Math.max(box.height, h)};
  }
  return out;
}"""

_TOUCH_SELECTORS = (
    ".site-tools .theme-fab",
    "[data-kindpanel]:not([hidden]) .angle-share",
    "[data-kindpanel]:not([hidden]) .acard .iconbtn",
    ".helpbtn",
    ".apx-toggle",
    ".story-tabs button",
    ".site-tools .home-link",
    ".langmenu>button",
)

#: Site-level controls belong in one row of one shape, the shape has to actually be one
#: shape, they must stay out of the title, and the bar must scroll away with the page.
_TOOLBAR_STATE = """(() => {
  const bar = document.querySelector('.site-tools[data-toolbar]');
  if (!bar) return {bars: document.querySelectorAll('.site-tools[data-toolbar]').length};
  const nodes = document.querySelectorAll(
    '.site-tools .home-link,.langmenu>button,.site-tools .theme-fab');
  const boxes = Array.from(nodes, node => {
    const box = node.getBoundingClientRect();
    return {w: Math.round(box.width), h: Math.round(box.height), y: Math.round(box.top)};
  });
  const title = document.querySelector('header.head h1');
  let collision = null;
  if (title) {
    const t = title.getBoundingClientRect();
    for (const node of bar.querySelectorAll('.home-link,.langmenu>button,.theme-fab')) {
      const c = node.getBoundingClientRect();
      if (c.right > t.left && c.left < t.right && c.bottom > t.top && c.top < t.bottom) {
        collision = {control: [c.left, c.top, c.right, c.bottom],
                     title: [t.left, t.top, t.right, t.bottom]};
        break;
      }
    }
  }
  const tabs = document.querySelector('.story-tabs');
  return {
    bars: document.querySelectorAll('.site-tools[data-toolbar]').length,
    boxes: boxes,
    collision: collision,
    position: getComputedStyle(bar).position,
    tabOverflow: tabs ? tabs.scrollWidth - tabs.clientWidth : 0,
    scrollBehavior: getComputedStyle(document.documentElement).scrollBehavior,
  };
})()"""

#: Every dot must resolve to itself at its own visual centre; inflated overlapping hit
#: circles made most taps open a neighbouring article.
_TIMELINE_DOTS = """(() => {
  const svg = document.querySelector('#tl-canvas svg');
  if (!svg) return null;
  const rect = svg.getBoundingClientRect();
  const view = svg.viewBox.baseVal;
  let bad = 0, total = 0;
  for (const dot of svg.querySelectorAll('.dot-hit')) {
    const cx = rect.left + parseFloat(dot.getAttribute('cx')) * rect.width / view.width;
    const cy = rect.top + parseFloat(dot.getAttribute('cy')) * rect.height / view.height;
    if (cx < 0 || cy < 0 || cx > innerWidth || cy > innerHeight) continue;
    total++;
    const hit = document.elementFromPoint(cx, cy);
    const target = hit && hit.closest && hit.closest('[data-article]');
    if (!target || target.getAttribute('data-article') !== dot.getAttribute('data-article')) bad++;
  }
  return {bad: bad, total: total};
})()"""

#: The chrome layer carries the trust that used to sit in the reviewed bytes: prove it
#: actually loaded, that it resolves the page's declared theme token, and that it hides
#: neither side of the comparison.
_CHROME_STATE = """(() => {
  const root = document.documentElement;
  const styles = getComputedStyle(root);
  const panel = document.querySelector('[data-kindpanel]:not([hidden])');
  const cards = panel ? panel.querySelectorAll('.acard') : [];
  let shown = 0;
  for (const card of cards) {
    const box = card.getBoundingClientRect();
    const cs = getComputedStyle(card);
    if (box.width > 0 && box.height > 0 && cs.visibility !== 'hidden'
        && cs.display !== 'none' && parseFloat(cs.opacity) > 0.05) shown++;
  }
  return {
    token: root.getAttribute('data-theme-token'),
    accent: styles.getPropertyValue('--accent').trim(),
    paper: getComputedStyle(document.body).backgroundColor,
    js: root.classList.contains('js'),
    cards: cards.length,
    shown: shown,
  };
})()"""

_ISLAND_HYDRATION = """(() => {
  try {
    const node = document.getElementById('sentence-index');
    const data = JSON.parse(node.textContent);
    const keys = Object.keys(data);
    if (!keys.length) return 'empty';
    if (!data[keys[0]].source) return 'unhydrated';
    const search = JSON.parse(
      document.getElementById('report-search-index').textContent);
    if (!Array.isArray(search) || !search.length) return 'search-empty';
    if (!search[0].source || !(search[0].meta || []).length)
      return 'search-unhydrated';
    return 'ok';
  } catch (e) { return 'error:' + e; }
})()"""

#: Record, for every focus move, whether focus was still inside the top modal.  The
#: Python loop asked the browser after each of eight Tab presses — sixteen driver round
#: trips to learn what one listener and one read answer, and this also catches a focus
#: that escapes and returns between two presses.
_FOCUS_TRAP_ARM = """() => {
  window.__newsabTrap = [];
  document.addEventListener('focusin', () => {
    const modal = document.querySelector('.modal:not([hidden])');
    window.__newsabTrap.push(!!(modal && modal.contains(document.activeElement)));
  }, true);
}"""

_FOCUS_TRAP_READ = """() => {
  const modal = document.querySelector('.modal:not([hidden])');
  return {seen: window.__newsabTrap || [],
          inside: !!(modal && modal.contains(document.activeElement))};
}"""

_SHARE_STUB = (
    "navigator.share=(data)=>{window.__newsabShared=data;return Promise.resolve()}"
)

#: The page's own readiness marker: the chrome script adds ``js`` to the root element as
#: soon as it runs, which is exactly what the fixed 250ms pause used to wait out.
_READY_SELECTOR = "html.js"


def _visit(page, errors: list[str], url: str, *, islands: bool, reset: bool = True) -> None:
    """Navigate and wait for the page's own readiness markers, never for a clock."""
    if reset:
        errors.clear()
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_selector(_READY_SELECTOR, state="attached")
    if islands:
        # Script startup is asynchronous when islands are externalized; every
        # interaction below relies on the wired listeners, so wait for the loader's own
        # ready marker.
        page.wait_for_selector('html[data-islands="ready"]', state="attached")


def _check_topic_desktop(
    gate: Gate,
    page,
    errors: list[str],
    origin: str,
    page_url: str,
    islands: bool,
    shot_root: Optional[Path],
) -> int:
    written = 0
    _visit(page, errors, origin + page_url, islands=islands)

    def load() -> None:
        _assert(not errors, f"{page_url}: JavaScript errors: {errors}")

    def hydration() -> None:
        if not islands:
            return
        hydrated = page.evaluate(_ISLAND_HYDRATION)
        _assert(
            hydrated == "ok",
            f"{page_url}: externalized data islands did not hydrate: {hydrated}",
        )
        # The fetched record must actually reach a reader: a quote chip opens our own
        # source record with the verbatim sentence and its outlet.  Chips sit inside
        # whichever panel or modal holds their quote, so the click goes through the page's
        # own delegated handler directly.
        opened = page.evaluate(
            "(() => { const chip = document.querySelector('[data-sid]');"
            " if (!chip) return false; chip.click(); return true; })()"
        )
        _assert(opened, f"{page_url}: page has no sentence chip to verify")
        modal = page.locator("#srcmodal:not([hidden])")
        modal.wait_for(state="attached")
        _assert(
            modal.count() == 1,
            f"{page_url}: sentence chip did not open the source record",
        )
        _assert(
            bool(modal.locator(".modal-quote").inner_text().strip()),
            f"{page_url}: source record shows no verbatim sentence",
        )
        _assert(
            bool(modal.locator(".modal-meta").inner_text().strip()),
            f"{page_url}: source record shows no outlet name",
        )
        page.keyboard.press("Escape")
        page.locator(".modal:not([hidden])").first.wait_for(state="detached")
        _assert(
            page.locator(".modal:not([hidden])").count() == 0,
            f"{page_url}: Escape did not close the source record",
        )

    def chrome_layer() -> None:
        state = page.evaluate(_CHROME_STATE)
        _assert(
            bool(state["accent"]),
            f"{page_url}: chrome stylesheet did not resolve --accent",
        )
        _assert(
            state["paper"] not in ("rgba(0, 0, 0, 0)", "transparent"),
            f"{page_url}: chrome stylesheet did not paint the page",
        )
        _assert(state["js"], f"{page_url}: chrome script did not run")
        _assert(
            state["cards"] >= 2 and state["shown"] == state["cards"],
            f"{page_url}: chrome hides part of the approved comparison: {state}",
        )

    def relation() -> None:
        geometry = page.evaluate(_RELATION_GEOMETRY)
        _assert(
            bool(geometry)
            and geometry["first"]
            and geometry["second"]
            and geometry["rel"],
            f"{page_url}: desktop relation geometry missing",
        )
        left, right, rel = geometry["first"], geometry["second"], geometry["rel"]
        _assert(
            left["x"] < rel["x"] < right["x"],
            f"{page_url}: desktop relation is not horizontal",
        )

    def columns() -> None:
        # The writer's two paragraphs must land in the two columns their own cards
        # occupy.  Source order is checked statically; this is the rendered fact the
        # reviewer reads off the page.
        measured = page.evaluate(_COLUMN_GEOMETRY)
        if measured is None:
            return
        _assert(
            isinstance(measured, list),
            f"{page_url}: an angle has one explanation per card no more: {measured}",
        )
        for position, column in enumerate(measured):
            _assert(
                column["card"] == column["para"],
                f"{page_url}: explanation column {position} belongs to side "
                f"{column['para']} but sits under the {column['card']} card",
            )
            _assert(
                column["overlap"] >= _COLUMN_OVERLAP * column["width"],
                f"{page_url}: the {column['card']} explanation is not under "
                f"the {column['card']} card: {column}",
            )

    def storyline_keyboard() -> None:
        active = page.locator('[data-kindtab][aria-selected="true"]')
        before = active.get_attribute("data-kindtab")
        active.focus()
        page.keyboard.press("ArrowRight")
        after = page.locator('[data-kindtab][aria-selected="true"]').get_attribute(
            "data-kindtab"
        )
        _assert(before != after, f"{page_url}: storyline ArrowRight did not select a tab")
        _assert(
            page.locator('[data-kindtab][tabindex="0"]').count() == 1,
            f"{page_url}: storyline does not use roving tabindex",
        )

    def reveal_populated_panel() -> None:
        populated = page.locator("[data-kindpanel]:has(.duo)").first
        if populated.is_hidden():
            populated_kind = populated.get_attribute("data-kindpanel")
            page.locator(f'[data-kindtab="{populated_kind}"]').click()

    def evidence_modal() -> None:
        evidence = page.locator(
            "[data-kindpanel]:not([hidden]) .acard .iconbtn[data-open]"
        ).first
        evidence.focus()
        evidence.press("Enter")
        dialog = page.locator('.modal:not([hidden]) [role="dialog"]').last
        dialog.wait_for(state="attached")
        _assert(dialog.count() == 1, f"{page_url}: evidence modal did not open")
        _assert(
            bool(
                dialog.get_attribute("aria-labelledby") or dialog.get_attribute("aria-label")
            ),
            f"{page_url}: visible dialog has no accessible name",
        )
        page.evaluate(_FOCUS_TRAP_ARM)
        for _ in range(8):
            page.keyboard.press("Tab")
        trap = page.evaluate(_FOCUS_TRAP_READ)
        _assert(
            trap["inside"] and all(trap["seen"]),
            f"{page_url}: Tab escaped the top modal",
        )
        page.keyboard.press("Escape")
        page.locator(".modal:not([hidden])").first.wait_for(state="detached")
        _assert(
            page.locator(".modal:not([hidden])").count() == 0,
            f"{page_url}: Escape did not close modal",
        )

    def share_controls() -> None:
        share = page.locator("[data-kindpanel]:not([hidden]) [data-share-angle]").first
        expected_fragment = share.get_attribute("data-share-angle")
        expected_landing = share.get_attribute("data-share-landing")
        expected_share_url = share.get_attribute("data-share-url")
        _assert(
            bool(expected_share_url)
            and expected_share_url.endswith(f"#angle-{expected_fragment}"),
            f"{page_url}: share button copy link is not its angle fragment",
        )
        share.click()
        shared = page.evaluate("window.__newsabShared")
        _assert(
            shared and shared["url"].endswith(expected_landing),
            f"{page_url}: native share data does not use its card landing",
        )

    def tooltip_pinning() -> None:
        tipped = page.locator("[data-kindpanel]:not([hidden]) .relmark[data-tip]").first
        tip = page.locator("#floattip")
        tipped.click()
        tip.wait_for(state="visible")
        _assert(tip.is_visible(), f"{page_url}: tapped tooltip did not pin")
        tipped.click()
        tip.wait_for(state="hidden")
        _assert(not tip.is_visible(), f"{page_url}: second tooltip tap did not close")
        tipped.click()
        tip.wait_for(state="visible")
        _assert(tip.is_visible(), f"{page_url}: tooltip did not re-pin")
        page.locator("h1").first.click()
        tip.wait_for(state="hidden")
        _assert(
            not tip.is_visible(),
            f"{page_url}: tapping elsewhere did not dismiss the tooltip",
        )

    def featured_angle() -> None:
        featured = page.locator("[data-angle]").first
        if not featured.count():
            return
        featured.click()
        page.wait_for_function(
            "() => document.querySelectorAll('[data-kindtab][tabindex=\"0\"]').length === 1"
        )
        roving = page.evaluate(
            "(() => {const on=document.querySelectorAll('[data-kindtab][tabindex=\"0\"]');"
            "return on.length===1 && on[0].getAttribute('aria-selected')==='true';})()"
        )
        _assert(roving, f"{page_url}: story tab roving tabindex desynced after gotoAngle")

    def hidden_angle_routing() -> None:
        hidden_angle = page.locator("[data-kindpanel][hidden] .angle").first
        if not hidden_angle.count():
            return
        fragment = hidden_angle.get_attribute("id")
        _visit(page, errors, origin + page_url + "#" + fragment, islands=islands, reset=False)
        page.locator("#" + fragment).wait_for(state="visible")
        _assert(
            not page.locator("#" + fragment)
            .locator("xpath=ancestor::*[@data-kindpanel][1]")
            .is_hidden(),
            f"{page_url}: direct angle fragment stayed in a hidden panel",
        )
        # A same-page hash navigation to an angle inside a hidden panel must both reveal
        # the panel and actually scroll to the angle.
        _visit(page, errors, origin + page_url, islands=islands, reset=False)
        page.evaluate(f"location.hash = '#{fragment}'")
        page.locator("#" + fragment).wait_for(state="visible")
        _assert(
            not page.locator("#" + fragment)
            .locator("xpath=ancestor::*[@data-kindpanel][1]")
            .is_hidden(),
            f"{page_url}: hashchange left the angle in a hidden panel",
        )
        page.wait_for_function("() => window.scrollY > 0")
        scrolled = page.evaluate("window.scrollY")
        _assert(scrolled > 0, f"{page_url}: hashchange to a hidden angle did not scroll")

    def no_errors() -> None:
        _assert(not errors, f"{page_url}: JavaScript errors during interactions: {errors}")

    _sequence(
        gate,
        page,
        [
            (f"{page_url}: load", load),
            (f"{page_url}: data island hydration", hydration),
            (f"{page_url}: chrome layer", chrome_layer),
            (f"{page_url}: desktop relation", relation),
            (f"{page_url}: explanation columns", columns),
            (f"{page_url}: storyline keyboard", storyline_keyboard),
            (f"{page_url}: populated panel", reveal_populated_panel),
            (f"{page_url}: evidence modal", evidence_modal),
            (f"{page_url}: share controls", share_controls),
            (f"{page_url}: tooltip pinning", tooltip_pinning),
            (f"{page_url}: featured angle", featured_angle),
            (f"{page_url}: hidden angle routing", hidden_angle_routing),
        ],
    )
    if shot_root:
        with gate.step(f"{page_url}: desktop screenshot"):
            stem = page_url.strip("/").replace("/", "-")
            page.screenshot(path=str(shot_root / f"{stem}-desktop.png"), full_page=True)
            written += 1
    with gate.step(f"{page_url}: desktop script errors"):
        no_errors()
    return written


def _check_topic_mobile(
    gate: Gate,
    page,
    errors: list[str],
    origin: str,
    page_url: str,
    islands: bool,
    shot_root: Optional[Path],
) -> int:
    written = 0
    _visit(page, errors, origin + page_url, islands=islands)

    def page_width() -> None:
        overflow = page.evaluate(
            "document.documentElement.scrollWidth-document.documentElement.clientWidth"
        )
        _assert(overflow <= 1, f"{page_url}: mobile page overflows by {overflow}px")

    def relation() -> None:
        geometry = page.evaluate(_RELATION_GEOMETRY)
        _assert(
            bool(geometry) and geometry["first"] and geometry["second"] and geometry["rel"],
            f"{page_url}: mobile relation geometry missing",
        )
        first, second, rel = geometry["first"], geometry["second"], geometry["rel"]
        _assert(
            first["y"] < rel["y"] < second["y"],
            f"{page_url}: mobile relation is not vertical",
        )
        _assert(
            geometry["transform"] not in (None, "none"),
            f"{page_url}: mobile connector was not rotated",
        )
        # The stacked connector is drawn rotated, so its own width becomes its vertical
        # extent.  Anything wider than the row prints over the card above, which paints
        # under it — the bug is invisible below the lower card and obvious above the upper
        # one, so measure rather than eyeball it.
        leads = geometry["leads"]
        _assert(
            bool(leads)
            and leads["y"] >= rel["y"] - 0.5
            and leads["y"] + leads["height"] <= rel["y"] + rel["height"] + 0.5,
            f"{page_url}: mobile connector overflows its row: {leads} vs {rel}",
        )

    def touch_targets() -> None:
        reaches = page.evaluate(_TOUCH_REACH, list(_TOUCH_SELECTORS))
        for selector, reach in reaches.items():
            _assert(
                reach["width"] >= 43.5 and reach["height"] >= 43.5,
                f"{page_url}: mobile target below 44px: {selector} {reach}",
            )
            # An invisible hit area that escapes its control swallows taps meant for
            # whatever is under it — the failure mode of a ``::after`` whose containing
            # block turned out to be the viewport.
            _assert(
                reach["width"] <= 176 and reach["height"] <= 176,
                f"{page_url}: mobile hit area escaped its control: {selector} {reach}",
            )

    def toolbar() -> None:
        state = page.evaluate(_TOOLBAR_STATE)
        _assert(state["bars"] == 1, f"{page_url}: site toolbar was not assembled")
        boxes = state["boxes"]
        _assert(len(boxes) == 3, f"{page_url}: expected three site controls, got {boxes}")
        _assert(
            len({(item["w"], item["h"]) for item in boxes}) == 1,
            f"{page_url}: site controls are not one shape: {boxes}",
        )
        _assert(
            max(item["y"] for item in boxes) - min(item["y"] for item in boxes) <= 1,
            f"{page_url}: site controls are not on one line: {boxes}",
        )
        # They sit in the page's own corners rather than in the reading column, which only
        # works while the page still leaves them room.
        _assert(
            state["collision"] is None,
            f"{page_url}: a site control overlaps the title: {state['collision']}",
        )
        # It stays at the top of the page and scrolls away; only back-to-top follows.
        _assert(
            state["position"] == "absolute",
            f"{page_url}: the site bar follows the viewport instead of the page",
        )
        # Three tabs that scroll sideways inside a page that does not is a scrollbar
        # nobody asked for.
        _assert(
            state["tabOverflow"] <= 1,
            f"{page_url}: storyline tabs scroll sideways by {state['tabOverflow']}px",
        )
        _assert(
            state["scrollBehavior"] == "auto",
            f"{page_url}: reduced motion keeps smooth scrolling",
        )

    def timeline() -> None:
        dot = page.locator(".dot-hit").first
        _assert(dot.get_attribute("tabindex") == "0", f"{page_url}: timeline dot not focusable")
        _assert(
            page.locator("#tl-canvas[data-m2-nearest]").count() == 1,
            f"{page_url}: timeline lacks nearest-dot tap delegation",
        )
        page.locator("#tl-canvas").scroll_into_view_if_needed()
        mis = page.evaluate(_TIMELINE_DOTS)
        _assert(
            bool(mis) and mis["total"] > 0 and mis["bad"] == 0,
            f"{page_url}: timeline dots mis-resolve at their own centre: {mis}",
        )

    _sequence(
        gate,
        page,
        [
            (f"{page_url}: mobile width", page_width),
            (f"{page_url}: mobile relation", relation),
            (f"{page_url}: mobile touch targets", touch_targets),
            (f"{page_url}: mobile toolbar", toolbar),
            (f"{page_url}: mobile timeline", timeline),
        ],
    )
    if shot_root:
        with gate.step(f"{page_url}: mobile screenshot"):
            stem = page_url.strip("/").replace("/", "-")
            page.screenshot(path=str(shot_root / f"{stem}-mobile.png"), full_page=True)
            written += 1
    with gate.step(f"{page_url}: mobile script errors"):
        _assert(not errors, f"{page_url}: mobile JavaScript errors: {errors}")
    return written


#: The suggestion modal's own geometry, ordering and fail-closed form discovery.
_SUGGESTION_POSITIONS = """() => {
  const plus = document.getElementById('suggestbtn').getBoundingClientRect();
  const about = document.getElementById('aboutbtn').getBoundingClientRect();
  const rtl = getComputedStyle(document.documentElement).direction === 'rtl';
  return {plus: plus.left, about: about.left, rtl: rtl,
          drop: Math.abs(plus.top - about.top)};
}"""

_SUGGESTION_CARD = """node => {
  const r = node.getBoundingClientRect();
  return {left: r.left, right: r.right, top: r.top, bottom: r.bottom,
          width: r.width, scrollWidth: node.scrollWidth};
}"""

#: A card that cannot shrink to its column does not always widen the page — on a fixed
#: desktop track it keeps the card's border where the grid put it and paints its rows out
#: past it instead, which no page-level width check can see.  Measure containment on the
#: card itself, at both column counts.
_CARD_SPILL = """() => {
  const out = [];
  for (const card of document.querySelectorAll('.tcard')) {
    const box = card.getBoundingClientRect();
    for (const el of card.querySelectorAll('*')) {
      const r = el.getBoundingClientRect();
      if (!r.width) continue;
      const over = Math.max(r.right - box.right, box.left - r.left);
      if (over > 1) out.push({
        card: (card.querySelector('.tt') || {}).textContent || '',
        el: el.className || el.tagName,
        over: Math.round(over)});
    }
    if (out.length >= 5) break;
  }
  return {spill: out.slice(0, 5),
          over: document.documentElement.scrollWidth - document.documentElement.clientWidth};
}"""


def _check_home_mobile(
    gate: Gate, page, origin: str, home_url: str, shot_root: Optional[Path]
) -> int:
    written = 0
    page.goto(origin + home_url, wait_until="domcontentloaded")

    def canonical_and_width() -> None:
        _assert(
            page.locator('link[rel="canonical"]').count() == 1, f"{home_url}: home canonical"
        )
        overflow = page.evaluate(
            "document.documentElement.scrollWidth-document.documentElement.clientWidth"
        )
        _assert(overflow <= 1, f"{home_url}: mobile home overflows by {overflow}px")

    def suggestion_order() -> None:
        # The "+" sits immediately before "?" in *reading* order, and that row mirrors
        # with the document's direction (home.py's `[dir="rtl"]` block), so on an RTL
        # homepage "before" is physically to the right.  Asserting a hardcoded left-of
        # failed `/ar/` for being correct.
        positions = page.evaluate(_SUGGESTION_POSITIONS)
        ordered = (
            positions["about"] < positions["plus"]
            if positions["rtl"]
            else positions["plus"] < positions["about"]
        )
        _assert(
            ordered,
            f"{home_url}: suggestion control is not before About in reading "
            f"order: {positions}",
        )
        # Ordering along one axis only means anything while both controls share the other.
        _assert(
            positions["drop"] <= 1,
            f"{home_url}: suggestion control and About are not on one line: {positions}",
        )

    def suggestion_modal() -> None:
        nonlocal written
        page.locator("#suggestbtn").click()
        page.locator("#suggest-modal:not([hidden])").wait_for()
        _assert(
            page.locator("body.suggest-open").count() == 1,
            f"{home_url}: suggestion modal does not lock background scroll",
        )
        _assert(
            page.locator(".suggest-x").evaluate("node => node === document.activeElement"),
            f"{home_url}: suggestion modal does not move focus to Close",
        )
        card = page.locator("#suggest-modal > .suggest-card").evaluate(_SUGGESTION_CARD)
        _assert(
            card["left"] >= 0
            and card["right"] <= 390
            and card["top"] >= 0
            and card["bottom"] <= 844
            and card["scrollWidth"] <= card["width"] + 1,
            f"{home_url}: mobile suggestion modal escapes the viewport: {card}",
        )
        if shot_root:
            stem = home_url.strip("/").replace("/", "-") or "root"
            page.screenshot(
                path=str(shot_root / f"{stem}-home-suggestion-mobile.png"), full_page=False
            )
            written += 1
        page.locator("[data-show-suggestion]").click()
        page.locator("[data-suggestion-formbox]:not([hidden])").wait_for()
        _assert(
            page.locator("[data-suggestion-form]").is_hidden(),
            f"{home_url}: failed intake config opened an unprotected form",
        )
        page.keyboard.press("Escape")
        page.locator("#suggest-modal").wait_for(state="hidden")
        _assert(
            page.locator("#suggest-modal").is_hidden(),
            f"{home_url}: Escape does not close suggestion modal",
        )

    steps = [(f"{home_url}: home canonical and width", canonical_and_width)]
    # The suggestion control is official-site furniture, not generic toolkit furniture.
    # When this homepage carries it, exercise the actual dialog rather than only accepting
    # inert markup: ordering, focus, scroll lock, viewport fit and fail-closed form
    # discovery are all browser behaviours.
    if page.locator("#suggestbtn").count():
        steps.append((f"{home_url}: suggestion control order", suggestion_order))
        steps.append((f"{home_url}: suggestion modal", suggestion_modal))
    _sequence(gate, page, steps)
    return written


def _check_home_widths(gate: Gate, page, origin: str, home_url: str, widths: tuple[int, ...]) -> None:
    for width in widths:
        with gate.step(f"{home_url} at {width}px: card containment"):
            page.set_viewport_size({"width": width, "height": 900})
            page.goto(origin + home_url, wait_until="domcontentloaded")
            measured = page.evaluate(_CARD_SPILL)
            _assert(
                not measured["spill"],
                f"{home_url} at {width}px: card content escapes its own card: "
                f"{measured['spill']}",
            )
            _assert(
                measured["over"] <= 1,
                f"{home_url} at {width}px: home overflows by {measured['over']}px",
            )


def _open(browser, *, share_stub: bool, fonts_offline: bool, **context_kwargs):
    """One reused context per viewport profile.

    Creating a context per page cost a fresh profile, service worker and network stack for
    every one of ~200 page visits; the pages are independent documents on the same origin,
    so one context per profile is the same isolation at a fraction of the setup.
    """
    context = browser.new_context(**context_kwargs)
    if share_stub:
        context.add_init_script(_SHARE_STUB)
    if fonts_offline:
        context.route("https://fonts.googleapis.com/**", lambda route: route.abort())
        context.route("https://fonts.gstatic.com/**", lambda route: route.abort())
    context.route("https://intake.news-ab.com/**", lambda route: route.abort())
    page = context.new_page()
    page.set_default_timeout(_TIMEOUT_MS)
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    return context, page, errors


def _run_pages(
    origin: str,
    root: Path,
    topic_urls: list[str],
    home_urls: list[str],
    shot_root: Optional[Path],
) -> tuple[dict[str, list[str]], int]:
    """Open one browser and check the pages this shard was handed.

    Failures come back grouped by page so the caller can record exactly the pages that
    passed — a page with one bad step must not have its bytes cached as proved.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise ArtifactError("web gate requires the Python playwright package") from exc

    failures: dict[str, list[str]] = {}
    written = 0
    with sync_playwright() as manager:
        browser = manager.chromium.launch(headless=True)
        try:
            if topic_urls:
                desktop_ctx, desktop, desktop_errors = _open(
                    browser,
                    share_stub=True,
                    fonts_offline=True,
                    viewport={"width": 1440, "height": 900},
                    reduced_motion="no-preference",
                )
                mobile_ctx, mobile, mobile_errors = _open(
                    browser,
                    share_stub=True,
                    fonts_offline=True,
                    viewport={"width": 390, "height": 844},
                    is_mobile=True,
                    has_touch=True,
                    reduced_motion="reduce",
                )
                try:
                    for page_url in topic_urls:
                        gate = Gate()
                        islands = 'data-src="' in (
                            root / page_url.strip("/") / "index.html"
                        ).read_text(encoding="utf-8")
                        written += _check_topic_desktop(
                            gate, desktop, desktop_errors, origin, page_url, islands, shot_root
                        )
                        written += _check_topic_mobile(
                            gate, mobile, mobile_errors, origin, page_url, islands, shot_root
                        )
                        failures[page_url] = gate.failures
                finally:
                    desktop_ctx.close()
                    mobile_ctx.close()

            if home_urls:
                # The home profiles deliberately keep web fonts loading: the `/ru/`
                # card overflow is a line-breaking fact of the real typeface, and a run
                # with fallback metrics would not have caught it.
                home_ctx, home_page, _ = _open(
                    browser,
                    share_stub=False,
                    fonts_offline=False,
                    viewport={"width": 390, "height": 844},
                    has_touch=True,
                )
                wide_ctx, wide_page, _ = _open(
                    browser,
                    share_stub=False,
                    fonts_offline=False,
                    viewport={"width": 768, "height": 900},
                )
                try:
                    for home_url in home_urls:
                        gate = Gate()
                        written += _check_home_mobile(
                            gate, home_page, origin, home_url, shot_root
                        )
                        _check_home_widths(gate, wide_page, origin, home_url, (768, 1440))
                        failures[home_url] = gate.failures
                finally:
                    home_ctx.close()
                    wide_ctx.close()
        finally:
            browser.close()
    return failures, written


def _shards(topic_urls: list[str], home_urls: list[str], workers: int) -> list[dict]:
    """Deal both page lists round-robin so every worker gets a similar amount of work."""
    buckets: list[dict] = [{"topics": [], "homes": []} for _ in range(workers)]
    for index, url in enumerate(topic_urls):
        buckets[index % workers]["topics"].append(url)
    for index, url in enumerate(home_urls):
        buckets[index % workers]["homes"].append(url)
    return [bucket for bucket in buckets if bucket["topics"] or bucket["homes"]]


def run_web_gate(
    public_root: str | Path,
    *,
    screenshots: str | Path | None = None,
    full: bool = False,
    workers: Optional[int] = None,
    use_cache: bool = True,
    per_stratum: int = 1,
) -> dict[str, object]:
    """Check a built tree in a real browser, doing as little of it twice as is sound.

    See :mod:`.gate_selection` for what "sound" means here: new bytes are always checked
    in full, unchanged bytes under unchanged chrome are skipped, and bytes that only went
    stale because the chrome moved are sampled across typography strata and page shapes.
    ``full=True`` checks everything, which is what a release gate wants.
    """
    root = Path(public_root).resolve()
    if not root.is_dir():
        raise ArtifactError(f"web gate public root does not exist: {root}")
    topic_paths = _topic_paths(root)
    home_paths = _home_paths(root)
    overlay = chrome.chrome_assets(load_theme_registry())
    gate = Gate()
    _check_chrome(gate, root, topic_paths, overlay)
    _check_static(gate, root, topic_paths, overlay)

    gate_fp = gate_selection.gate_fingerprint()
    chrome_fp = gate_selection.chrome_fingerprint(root, overlay)
    cache = gate_selection.VerifiedCache(enabled=use_cache)

    # The semantic pass reads no browser but parses every page, which is the whole static
    # cost of a full run.  It is a pure function of the page's bytes and the locale set
    # its alternates are checked against, so it caches on exactly those.
    expected = semantics_locales(topic_paths)
    semantic_keys = {
        key.url: key
        for key in gate_selection.build_keys(root, topic_paths, "semantics")
    }
    semantic_cache_keys = {
        url: gate_selection.PageKey(
            url=key.url,
            suite="semantics",
            page_sha=key.page_sha + ":" + ",".join(sorted(expected[url])),
            stratum=key.stratum,
            shape=key.shape,
        )
        for url, key in semantic_keys.items()
    }
    # No chrome in this key: the semantic pass never loads a stylesheet or a script, so a
    # chrome revision leaves its verdicts standing.  Keying it on chrome would put the
    # whole static cost back on exactly the runs the sampling above exists to make cheap.
    semantics_todo = {
        url
        for url, key in semantic_cache_keys.items()
        if full or not cache.holds(key.cache_key(gate_fp, ""))
    }
    _check_semantics(
        root,
        topic_paths,
        gate,
        only=semantics_todo,
        on_pass=lambda url: cache.record(
            semantic_cache_keys[url].cache_key(gate_fp, ""), semantic_cache_keys[url]
        ),
    )

    topic_keys = gate_selection.build_keys(root, topic_paths, "topic")
    home_keys = gate_selection.build_keys(root, home_paths, "home")
    topic_plan = gate_selection.plan(
        topic_keys, cache, gate=gate_fp, chrome=chrome_fp, full=full, per_stratum=per_stratum
    )
    home_plan = gate_selection.plan(
        home_keys, cache, gate=gate_fp, chrome=chrome_fp, full=full, per_stratum=per_stratum
    )

    shot_root: Optional[Path] = Path(screenshots) if screenshots else None
    if shot_root:
        shot_root.mkdir(parents=True, exist_ok=True)

    topic_urls, home_urls = topic_plan.urls, home_plan.urls
    worker_count = min(
        gate_selection.default_workers(workers), max(1, len(topic_urls) + len(home_urls))
    )
    screenshots_written = 0
    per_page: dict[str, list[str]] = {}
    if topic_urls or home_urls:
        with temporary_server(root, overlay) as origin:
            if worker_count == 1:
                per_page, screenshots_written = _run_pages(
                    origin, root, topic_urls, home_urls, shot_root
                )
            else:
                import concurrent.futures

                shards = _shards(topic_urls, home_urls, worker_count)
                # Threads, not processes.  Every shard drives its own Chromium, which is
                # where the work actually happens, so the Python side is almost pure
                # waiting and the GIL is not the limit.  Processes would have to pickle
                # the payload and re-import ``__main__`` under spawn/forkserver, which
                # breaks any caller that is not a file on disk — a REPL, ``python -``, a
                # notebook.  Playwright's sync API is per-thread, and `_run_pages` opens
                # its own instance, so each thread is fully independent.
                with concurrent.futures.ThreadPoolExecutor(
                    max_workers=len(shards), thread_name_prefix="web-gate"
                ) as pool:
                    futures = [
                        pool.submit(
                            _run_pages,
                            origin,
                            root,
                            shard["topics"],
                            shard["homes"],
                            shot_root,
                        )
                        for shard in shards
                    ]
                    for future in futures:
                        found, written = future.result()
                        per_page.update(found)
                        screenshots_written += written

    for key in topic_plan.run + home_plan.run:
        found = per_page.get(key.url, [])
        gate.extend(found)
        if not found:
            cache.record(key.cache_key(gate_fp, chrome_fp), key)
    cache.save()

    summary: dict[str, object] = {
        "topic_pages": len(topic_paths),
        "home_pages": len(home_paths),
        "checked_topic_pages": len(topic_plan.run),
        "checked_home_pages": len(home_plan.run),
        "cached_pages": len(topic_plan.cached) + len(home_plan.cached),
        "sampled_out_pages": len(topic_plan.sampled_out) + len(home_plan.sampled_out),
        "workers": worker_count,
        "screenshots": screenshots_written,
    }
    stale = topic_plan.sampled_out + home_plan.sampled_out
    if stale:
        # Say it out loud rather than letting a green run imply full coverage.
        summary["stale_strata"] = sorted({f"{key.stratum}" for key in stale})
        summary["note"] = (
            f"{len(stale)} page(s) keep a verdict taken under an older chrome or gate; "
            "run with --full before a release"
        )
    gate.raise_if_failed()
    return summary
