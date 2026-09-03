"""Semantic assertions over a *rendered* reader page.

The gate stack until now checked bytes (page-check), data (schema validators) and
behaviour (the browser gate).  One defect family slips through all three: the page's data
pairs correctly, every mechanical check is green, the judge cannot see it — and the render
is still wrong.  The measured case is a crossed-explanations defect, where the storyline
drew the two answer cards in manifest order while the writer's two paragraphs were emitted
in stored order, so every angle showed each side's explanation under the *other* side's
card.  A reviewer found it by eye at touchpoint two.

So this module reads the render the way a reader does: it parses the emitted document and
asserts the relations a human would notice.

* **pairing** — each side's explanation paragraph sits under its own side's card, in the
  same order, with the silent side's paragraph under the silent side's card;
* **badges** — the ``n/d`` count a card shows is what the page's own annotation record
  says: ``d`` addressed reporting clusters for that side, ``n`` of them carrying the
  answer the card states, and every one of those clusters belonging to that side
  according to the ``cluster-index`` data island;
* **hreflang** — the alternate links name exactly the locales the publication actually
  ships, and each one points at that locale's real page.

Everything here is deterministic and stdlib-only: no model calls, no browser.  The browser
gate calls it once per topic page before it launches Chromium.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable, Iterator, Optional

from newsab_schema.io import ArtifactError

#: HTML elements that never carry children.  ``<use>``/``<path>`` and friends inside the
#: page's inline SVG close themselves, which :class:`HTMLParser` reports separately.
_VOID = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
    "param", "source", "track", "wbr",
}


@dataclass
class Node:
    """One element of a parsed page — enough of a DOM for the questions asked here."""

    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    children: list["Node"] = field(default_factory=list)
    data: list[str] = field(default_factory=list)

    @property
    def classes(self) -> set[str]:
        return set(self.attrs.get("class", "").split())

    def text(self) -> str:
        parts = list(self.data)
        for child in self.children:
            parts.append(child.text())
        return "".join(parts).strip()

    def descendants(self) -> Iterator["Node"]:
        for child in self.children:
            yield child
            yield from child.descendants()

    def find_all(
        self,
        tag: Optional[str] = None,
        *,
        cls: Optional[str] = None,
        attr: Optional[str] = None,
        value: Optional[str] = None,
    ) -> list["Node"]:
        out = []
        for node in self.descendants():
            if tag is not None and node.tag != tag:
                continue
            if cls is not None and cls not in node.classes:
                continue
            if attr is not None:
                if attr not in node.attrs:
                    continue
                if value is not None and node.attrs[attr] != value:
                    continue
            out.append(node)
        return out

    def first(self, tag: Optional[str] = None, **kwargs) -> Optional["Node"]:
        found = self.find_all(tag, **kwargs)
        return found[0] if found else None

    def child_elements(self, *, cls: Optional[str] = None, tag: Optional[str] = None):
        for child in self.children:
            if tag is not None and child.tag != tag:
                continue
            if cls is not None and cls not in child.classes:
                continue
            yield child


class _TreeBuilder(HTMLParser):
    """A forgiving tree builder: a stray end tag is dropped rather than fatal.

    The gate must fail on the *semantics* of a page, never on a parser's opinion of its
    markup, so anything it cannot place is ignored instead of raised.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("#document")
        self._stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = Node(tag, {key: (value or "") for key, value in attrs})
        self._stack[-1].children.append(node)
        if tag not in _VOID:
            self._stack.append(node)

    def handle_startendtag(self, tag, attrs):
        node = Node(tag, {key: (value or "") for key, value in attrs})
        self._stack[-1].children.append(node)

    def handle_endtag(self, tag):
        for depth in range(len(self._stack) - 1, 0, -1):
            if self._stack[depth].tag == tag:
                del self._stack[depth:]
                return

    def handle_data(self, data):
        self._stack[-1].data.append(data)


def parse_document(html_text: str) -> Node:
    builder = _TreeBuilder()
    builder.feed(html_text)
    builder.close()
    return builder.root


def _fail(message: str) -> None:
    raise ArtifactError(message)


def _assert(condition: bool, message: str) -> None:
    if not condition:
        _fail(message)


def _side_class(node: Node) -> Optional[str]:
    """The side a coloured element belongs to: the ``a``/``b`` token the theme paints."""
    for token in ("a", "b"):
        if token in node.classes:
            return token
    return None


def _element_by_id(doc: Node, element_id: str) -> Optional[Node]:
    return doc.first(attr="id", value=element_id)


# --------------------------------------------------------------------------------------
# 1. the writer's explanations sit under their own cards
# --------------------------------------------------------------------------------------


def _angle_cards(angle: Node) -> list[Node]:
    duo = angle.first(cls="duo")
    if duo is None:
        return []
    return list(duo.child_elements(cls="acard"))


def check_explanation_pairing(doc: Node, label: str) -> int:
    """Each angle's two paragraphs must be in the same side order as its two cards."""
    checked = 0
    for angle in doc.find_all(cls="angle"):
        angle_id = angle.attrs.get("id", "?")
        cards = _angle_cards(angle)
        if not cards:
            continue
        comm = next(angle.child_elements(cls="comm"), None)
        if comm is None or "joint" in comm.classes:
            # A joint commentary is one paragraph for both sides by editorial choice.
            continue
        paragraphs = list(comm.child_elements(tag="p"))
        card_sides = [_side_class(card) for card in cards]
        mark_sides = []
        for paragraph in paragraphs:
            mark = paragraph.first(cls="cmark")
            mark_sides.append(_side_class(mark) if mark is not None else None)
        _assert(
            None not in card_sides and None not in mark_sides,
            f"{label}: {angle_id}: a card or an explanation carries no side colour "
            f"(cards={card_sides}, explanations={mark_sides})",
        )
        _assert(
            mark_sides == card_sides,
            f"{label}: {angle_id}: explanations are not under their own cards — cards "
            f"are drawn {card_sides} but the paragraphs below them are {mark_sides}",
        )
        card_silence = ["silent" in card.classes for card in cards]
        para_silence = ["silent" in p.classes for p in paragraphs]
        _assert(
            card_silence == para_silence,
            f"{label}: {angle_id}: the silent side's explanation is not under the silent "
            f"side's card (cards={card_silence}, explanations={para_silence})",
        )
        checked += 1
    return checked


# --------------------------------------------------------------------------------------
# 2. the count on a card is what the page's own record says
# --------------------------------------------------------------------------------------


def load_island(doc: Node, island_id: str, root: Optional[Path]) -> Optional[object]:
    """A data island's payload, inline or fetched from its content-addressed asset."""
    node = _element_by_id(doc, island_id)
    if node is None:
        return None
    source = node.attrs.get("data-src")
    if source:
        if root is None:
            return None
        target = root / source.split("?", 1)[0].lstrip("/")
        if not target.is_file():
            return None
        return json.loads(target.read_text(encoding="utf-8"))
    text = node.text()
    return json.loads(text) if text else None


def _addressed_rows(table: Node) -> list[Node]:
    rows = []
    for row in table.find_all("tr"):
        if "unaddressed" in row.classes:
            continue
        if row.find_all("th"):  # the header row
            continue
        rows.append(row)
    return rows


def _leading_shares(doc: Node, question_id: str, side: str) -> Optional[set[str]]:
    """The counts the answer-share chart marks as this side's leading answer.

    The chart is drawn from the analyze finding's category counts, the card's badge from
    the writer's page model, and the chart marks the leading bar per side — so the card's
    numerator has to be one of them.  A tie leaves more than one; anything else means the
    two halves of the page disagree about what this side mostly said.
    """
    block = _element_by_id(doc, f"q-{question_id}")
    if block is None:
        return None
    half = "bf-left" if side == "a" else "bf-right"
    leads: set[str] = set()
    for row in block.find_all(cls="axis3"):
        if "rates" in row.classes:  # the addressed/total row, not an answer share
            continue
        cell = row.first(cls=half)
        if cell is None:
            continue
        bar = cell.first(cls="bar")
        if bar is None or "lead" not in bar.classes:
            continue
        count = cell.first(cls="bn")
        if count is not None:
            leads.add(count.text().split("·")[0].strip())
    return leads or None


def check_badge_counts(doc: Node, label: str, cluster_index: Optional[dict]) -> int:
    """A card's ``n/d`` badge, re-derived from the annotation table it is drawn from.

    The badge comes from the writer's page model and the table from the analyze finding,
    so the two are independent enough for the comparison to mean something: a side whose
    numbers belong to the other side fails here, and so does a page whose annotation
    record lists another group's reporting clusters.
    """
    checked = 0
    for angle in doc.find_all(cls="angle"):
        angle_id = angle.attrs.get("id", "?")
        question_id = angle_id[len("angle-"):] if angle_id.startswith("angle-") else ""
        cards = _angle_cards(angle)
        if not (cards and question_id):
            continue
        annotations = _element_by_id(doc, f"ann-{question_id}")
        if annotations is None:
            continue
        tabs = annotations.first(cls="tabs")
        if tabs is None:
            continue
        by_side = {}
        for button in tabs.find_all("button", attr="data-tab"):
            side = _side_class(button)
            if side:
                by_side[side] = button.attrs["data-tab"]
        for card in cards:
            side = _side_class(card)
            counter = card.first(cls="count")
            if side is None or counter is None:
                continue
            shown = counter.text()
            _assert(
                "/" in shown,
                f"{label}: {angle_id}: the {side} card's badge is not a count: {shown!r}",
            )
            numerator, denominator = (part.strip() for part in shown.split("/", 1))
            group_id = by_side.get(side)
            _assert(
                group_id is not None,
                f"{label}: {angle_id}: no annotation tab for the {side} side",
            )
            panel = annotations.first(attr="data-panel", value=group_id)
            _assert(
                panel is not None,
                f"{label}: {angle_id}: no annotation panel for {group_id}",
            )
            table = panel.first("table", cls="ann")
            if table is None:
                continue
            rows = _addressed_rows(table)
            # Two badge shapes reach a reader, and they read their denominator
            # differently.  A speaking card counts one category out of the reports that
            # answered, so its denominator *is* the answered count.  An attention gap's
            # quiet side is badged `addressed` — "1 of 11" means one report out of the
            # side's whole readable universe — so there the answered count is the
            # numerator.  Comparing the table against the denominator either way would
            # refuse every silent block on sight (qa-0.5.0 made these reachable).
            silent = "silent" in card.classes
            expected = numerator if silent else denominator
            _assert(
                str(len(rows)) == expected,
                f"{label}: {angle_id}: the {group_id} card claims {expected} reports "
                f"answered the question, its annotation table lists {len(rows)}",
            )
            if cluster_index is not None:
                for row in rows:
                    chip = row.first(attr="data-cluster")
                    if chip is None:
                        continue
                    cluster_id = chip.attrs["data-cluster"]
                    entry = cluster_index.get(cluster_id)
                    _assert(
                        entry is not None,
                        f"{label}: {angle_id}: annotation row cites {cluster_id}, which "
                        "the cluster-index data island does not contain",
                    )
                    _assert(
                        entry.get("group") == group_id,
                        f"{label}: {angle_id}: the {group_id} side's annotation table "
                        f"lists {cluster_id}, which the data island assigns to "
                        f"{entry.get('group')!r}",
                    )
            # A silent block states no answer at all, so it makes no claim the answer
            # shares could contradict: its numerator is "how many reports touched the
            # question", not "how many gave this answer".  Only a speaking card is
            # checked against the leading share.
            leads = None if silent else _leading_shares(doc, question_id, side)
            if leads is not None:
                _assert(
                    numerator in leads,
                    f"{label}: {angle_id}: the {group_id} card claims {numerator} of "
                    f"them gave the answer it states, while the answer shares below it "
                    f"put this side's leading answer at {sorted(leads)}",
                )
            checked += 1
    return checked


# --------------------------------------------------------------------------------------
# 3. the alternates name the locales the publication actually ships
# --------------------------------------------------------------------------------------


def check_hreflang(
    doc: Node,
    label: str,
    *,
    page_locale: str,
    expected_locales: Iterable[str],
) -> int:
    expected = set(expected_locales)
    alternates: dict[str, str] = {}
    for link in doc.find_all("link", attr="rel", value="alternate"):
        locale = link.attrs.get("hreflang")
        if not locale or locale == "x-default":
            continue
        _assert(
            locale not in alternates,
            f"{label}: hreflang {locale!r} is declared twice",
        )
        alternates[locale] = link.attrs.get("href", "")
    _assert(
        set(alternates) == expected,
        f"{label}: hreflang alternates {sorted(alternates)} do not match the locales "
        f"this publication ships {sorted(expected)}",
    )
    _assert(
        page_locale in alternates,
        f"{label}: the page declares locale {page_locale!r} but does not link itself "
        f"among its alternates {sorted(alternates)}",
    )
    for locale, href in alternates.items():
        _assert(
            bool(href),
            f"{label}: the {locale!r} alternate has no href",
        )
        _assert(
            f"/{locale}/" in href,
            f"{label}: the {locale!r} alternate points at {href!r}, which is not that "
            "locale's page",
        )
    return len(alternates)


# --------------------------------------------------------------------------------------
# the whole page
# --------------------------------------------------------------------------------------


def check_page_semantics(
    html_text: str,
    *,
    label: str,
    root: Optional[Path] = None,
    page_locale: Optional[str] = None,
    expected_locales: Optional[Iterable[str]] = None,
) -> dict[str, int]:
    """Run every semantic assertion over one rendered page's markup."""
    doc = parse_document(html_text)
    cluster_index = load_island(doc, "cluster-index", root)
    if not isinstance(cluster_index, dict):
        cluster_index = None
    result = {
        "angles_paired": check_explanation_pairing(doc, label),
        "badges_checked": check_badge_counts(doc, label, cluster_index),
        "alternates": 0,
    }
    if page_locale and expected_locales is not None:
        result["alternates"] = check_hreflang(
            doc, label, page_locale=page_locale, expected_locales=expected_locales
        )
    return result
