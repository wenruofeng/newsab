"""The gate reads the render, not just the bytes.

The defect these checks exist for (crossed explanations) had correct data, a green
page-check and an invisible-to-the-judge symptom: only a human looking at the page saw
that each side's paragraph sat under the other side's card.  Every test here builds a page
in the shape the renderer really emits, breaks exactly one relation, and asserts the gate
names it.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

from newsab_publish.page_semantics import check_page_semantics, parse_document
from newsab_publish.web_gate import _check_semantics
from newsab_schema.io import ArtifactError


REPO_ROOT = Path(__file__).resolve().parents[3]

# The two sides of the fixture topic: cluster ids, their side, and how each cluster was
# categorized.  The card badges below are derived from exactly this table, so a test that
# breaks one number and not the other is breaking a real relation.
CLUSTERS = {
    "a": [("RC-CN-0001", "Answer A"), ("RC-CN-0002", "Answer A"), ("RC-CN-0003", "Answer B")],
    "b": [("RC-US-0001", "Answer B"), ("RC-US-0002", "Answer B"), ("RC-US-0003", "Answer A")],
}
GROUP_OF = {"a": "cn", "b": "us"}
QUESTION_ID = "QST-aabb-river-light-2026-001"


def _cards(order=("a", "b"), silent=(), badges=None, answers=None):
    badges = badges or {"a": "2/3", "b": "2/3"}
    answers = answers or {"a": "Answer A", "b": "Answer B"}
    out = []
    for side in order:
        quiet = " silent" if side in silent else ""
        out.append(
            f'<div class="acard {side}{quiet}">'
            f'<span class="acontrol"><span class="badge count" tabindex="0">{badges[side]}</span>'
            f'<button class="iconbtn" type="button" data-open="ev-1" '
            f'data-open-tab="{GROUP_OF[side]}"></button></span>'
            f'<div class="ahead"><span class="badge gtag {side}">side {side}</span></div>'
            f'<div class="alabel">{answers[side]}</div></div>'
        )
    return out


def _commentary(order=("a", "b"), silent=()):
    columns = []
    for side in order:
        quiet = ' class="silent"' if side in silent else ""
        columns.append(
            f'<p{quiet}><span class="cmark {side}"></span>'
            f"What the {side} side said, and why.</p>"
        )
    return f'<div class="comm">{"".join(columns)}</div>'


def _shares(leads=None, counts=None):
    """The answer-share butterfly: one row per category, the leading bar marked."""
    leads = leads or {"a": "Answer A", "b": "Answer B"}
    counts = counts or {("a", "Answer A"): 2, ("a", "Answer B"): 1,
                        ("b", "Answer A"): 1, ("b", "Answer B"): 2}
    rows = ['<div class="axis3 rates"><span class="bf-left"></span>'
            '<span class="cat"></span><span class="bf-right"></span></div>']
    for category in ("Answer A", "Answer B"):
        top = any(leads[side] == category for side in ("a", "b"))
        cells = {}
        for side, half in (("a", "bf-left"), ("b", "bf-right")):
            count = counts[(side, category)]
            lead = " lead" if leads[side] == category else ""
            bar = f'<span class="bar {side}{lead}" style="width:40%"></span>'
            number = f'<span class="bn">{count} · 50%</span>'
            cells[half] = (number + bar) if half == "bf-left" else (bar + number)
        rows.append(
            f'<div class="axis3{" top" if top else ""}">'
            f'<span class="bf-left">{cells["bf-left"]}</span>'
            f'<span class="cat">{category}</span>'
            f'<span class="bf-right">{cells["bf-right"]}</span></div>'
        )
    return f'<div class="qblock" id="q-{QUESTION_ID}">{"".join(rows)}</div>'


def _annotation_table(side, *, rows=None, unaddressed=1):
    entries = rows if rows is not None else CLUSTERS[side]
    body = [
        '<colgroup><col class="meta"><col class="cat"><col><col class="anchors"></colgroup>'
        "<tr><th>Report</th><th>Category</th><th>Summary</th><th>Quote</th></tr>"
    ]
    for cluster_id, category in entries:
        body.append(
            f'<tr><td class="meta"><button class="clusterid" type="button" '
            f'data-cluster="{cluster_id}">{cluster_id}</button></td>'
            f'<td class="cat"><strong>{category}</strong></td>'
            f"<td>a summary</td><td class=\"anchors\"></td></tr>"
        )
    for index in range(unaddressed):
        body.append(
            f'<tr class="unaddressed"><td class="meta"><button class="clusterid" '
            f'type="button" data-cluster="RC-{side.upper()}-X{index}"></button></td>'
            f'<td colspan="3">not addressed</td></tr>'
        )
    return f'<div class="ann-scroll"><table class="ann">{"".join(body)}</table></div>'


def _annotation_modal(tables=None):
    tables = tables or {"a": _annotation_table("a"), "b": _annotation_table("b")}
    tabs, panels = [], []
    for position, side in enumerate(("a", "b")):
        tabs.append(
            f'<button type="button" class="{side}{" on" if not position else ""}" '
            f'data-tab="{GROUP_OF[side]}">side {side} · 4</button>'
        )
        panels.append(
            f'<div class="tabpanel" data-panel="{GROUP_OF[side]}"'
            f'{"" if not position else " hidden"}>{tables[side]}</div>'
        )
    return (
        f'<div class="modal" id="ann-{QUESTION_ID}" hidden><div class="modal-card wide">'
        f'<div class="tabs">{"".join(tabs)}</div>{"".join(panels)}</div></div>'
    )


def _island(entries=None):
    if entries is None:
        entries = {
            cluster_id: {"articles": ["A"], "group": GROUP_OF[side]}
            for side, rows in CLUSTERS.items()
            for cluster_id, _ in rows
        }
        for side in ("a", "b"):
            entries[f"RC-{side.upper()}-X0"] = {"articles": ["A"], "group": GROUP_OF[side]}
    return (
        '<script type="application/json" id="cluster-index">'
        f"{json.dumps(entries)}</script>"
    )


def page(
    *,
    card_order=("a", "b"),
    comm_order=("a", "b"),
    silent_cards=(),
    silent_comm=(),
    badges=None,
    tables=None,
    island=None,
    shares=None,
    alternates=(("en", "/en/topics/aabb-river-light-2026/"), ("zh-CN", "/zh-CN/topics/aabb-river-light-2026/")),
    locale="en",
) -> str:
    links = "".join(
        f'<link rel="alternate" hreflang="{code}" href="{href}">' for code, href in alternates
    )
    cards = _cards(card_order, silent_cards, badges)
    return (
        f'<html lang="{locale}"><head><meta charset="utf-8">'
        f'<link rel="canonical" href="/{locale}/topics/aabb-river-light-2026/">{links}</head>'
        f'<body data-site-locale="{locale}">'
        f'<div data-kindpanel="divergence">'
        f'<article class="angle" id="angle-{QUESTION_ID}">'
        f"<h2>Q: a question?</h2>"
        f'<div class="duo">{cards[0]}<div class="rel"></div>{cards[1]}</div>'
        f"{_commentary(comm_order, silent_comm)}"
        f'<details class="qdata">{shares if shares is not None else _shares()}</details>'
        f"</article></div>"
        f"{_annotation_modal(tables)}{island if island is not None else _island()}"
        f"</body></html>"
    )


def check(html_text, **kwargs):
    kwargs.setdefault("label", "/en/topics/aabb-river-light-2026/")
    return check_page_semantics(html_text, **kwargs)


# --------------------------------------------------------------------------------------
# the baseline
# --------------------------------------------------------------------------------------


def test_a_well_formed_page_passes_every_semantic_check():
    result = check(page(), page_locale="en", expected_locales={"en", "zh-CN"})
    assert result == {"angles_paired": 1, "badges_checked": 2, "alternates": 2}


def test_the_parser_survives_stray_end_tags_and_self_closing_svg():
    doc = parse_document(
        '<div class="angle"><svg><use href="#i"/></svg></p><span>x</span></div>'
    )
    angle = doc.first(cls="angle")
    assert angle is not None and angle.text() == "x"


# --------------------------------------------------------------------------------------
# 1. explanations under their own cards
# --------------------------------------------------------------------------------------


def test_swapped_explanations_are_caught():
    """Regression: cards in manifest order, paragraphs in stored order.

    The page data pairs correctly and every byte-level check passes; the render is wrong.
    This is the one defect in the cycle that reached the reviewer's eyes.
    """
    with pytest.raises(ArtifactError, match="explanations are not under their own cards"):
        check(page(card_order=("a", "b"), comm_order=("b", "a")))


def test_the_swap_is_caught_on_a_page_from_the_real_renderer():
    """The same swap, on markup the editorial renderer actually emitted.

    A fixture proves the checker reads its own markup; this proves the markup it reads is
    the markup the renderer produces.  ``_commentary`` no longer *can* cross the columns
    (the fix is held by its own unit test in the editorial package), so the crossing is
    reintroduced here the way the broken renderer expressed it: the two side colours on
    the paragraphs, swapped, over a real page.
    """
    for package in ("schema", "editorial"):
        path = str(REPO_ROOT / "packages" / package)
        if path not in sys.path:
            sys.path.insert(0, path)
    tests_dir = str(REPO_ROOT / "packages" / "editorial" / "tests")
    if tests_dir not in sys.path:
        sys.path.insert(0, tests_dir)
    reader_page = pytest.importorskip("test_reader_page")

    good = reader_page.render_page(
        reader_page.page(), reader_page.ARTICLES, reader_page.manifest(), lang="en"
    )
    check(good, label="/en/topics/rendered/")
    assert 'class="cmark a"' in good and 'class="cmark b"' in good

    crossed = good.replace('class="cmark a"', 'class="cmark @"').replace(
        'class="cmark b"', 'class="cmark a"'
    ).replace('class="cmark @"', 'class="cmark b"')
    with pytest.raises(ArtifactError, match="explanations are not under their own cards"):
        check(crossed, label="/en/topics/rendered/")


def test_a_silent_explanation_must_sit_under_the_silent_card():
    with pytest.raises(ArtifactError, match="silent side's explanation"):
        check(page(silent_cards=("a",), silent_comm=("b",)))


def test_a_joint_commentary_is_not_a_pairing_failure():
    html_text = page().replace('<div class="comm">', '<div class="comm joint">')
    assert check(html_text)["angles_paired"] == 0


# --------------------------------------------------------------------------------------
# 2. badge counts against the page's own record and its data island
# --------------------------------------------------------------------------------------


def test_a_denominator_the_annotation_table_does_not_support_is_caught():
    with pytest.raises(ArtifactError, match="claims 9 reports answered the question"):
        check(page(badges={"a": "2/9", "b": "2/3"}))


def test_a_numerator_the_answer_shares_do_not_support_is_caught():
    with pytest.raises(ArtifactError, match="leading answer at"):
        check(page(badges={"a": "3/3", "b": "2/3"}))


def test_an_attention_gaps_silent_side_reads_its_badge_the_other_way_round():
    """A silent block is badged `addressed`: "2 of 9" means two of the side's whole
    readable universe touched the question at all, not two of the reports that answered.

    qa-0.5.0 made attention gaps reachable for the first time, and both assertions
    below would otherwise refuse every silent block on sight — the table check by
    comparing the answered rows against the *universe*, and the answer-share check by
    demanding a leading category from a card that deliberately states no answer.
    """
    # Three addressed rows in the table, a universe of nine: the silent card says 3/9,
    # and the numerator — not the denominator — is what the table has to match.
    assert check(
        page(silent_cards=("a",), silent_comm=("a",), badges={"a": "3/9", "b": "2/3"})
    )

    # The same numbers on a speaking card are still a real defect: it would be claiming
    # nine reports answered while its table shows two.
    with pytest.raises(ArtifactError, match="claims 9 reports answered the question"):
        check(page(badges={"a": "2/9", "b": "2/3"}))


def test_badges_swapped_between_the_two_sides_are_caught():
    """Both cards' numbers moved to the other card — the counting twin of the swap."""
    tables = {
        "a": _annotation_table("a", rows=CLUSTERS["a"][:2]),
        "b": _annotation_table("b"),
    }
    with pytest.raises(ArtifactError, match="answered the question"):
        check(page(badges={"a": "2/3", "b": "2/2"}, tables=tables))


def test_an_annotation_row_from_the_other_side_fails_against_the_data_island():
    tables = {"a": _annotation_table("a", rows=CLUSTERS["b"]), "b": _annotation_table("b")}
    with pytest.raises(ArtifactError, match="which the data island assigns to"):
        check(page(tables=tables))


def test_a_cluster_the_data_island_never_heard_of_is_caught():
    tables = {
        "a": _annotation_table("a", rows=[("RC-CN-9999", "Answer A")] + CLUSTERS["a"][1:]),
        "b": _annotation_table("b"),
    }
    with pytest.raises(ArtifactError, match="cluster-index data island does not contain"):
        check(page(tables=tables))


def test_badges_are_still_checked_when_the_island_is_absent():
    """No island is not a pass: the counting relations that do not need it still run."""
    html_text = page(badges={"a": "2/9", "b": "2/3"}, island="")
    with pytest.raises(ArtifactError, match="answered the question"):
        check(html_text)


def test_an_externalized_island_is_read_from_disk(tmp_path):
    (tmp_path / "topics" / "t" / "data").mkdir(parents=True)
    asset = tmp_path / "topics" / "t" / "data" / "cluster-index.0000000000000000.json"
    asset.write_text(
        json.dumps({cluster_id: {"group": "us"} for cluster_id, _ in CLUSTERS["a"]}),
        encoding="utf-8",
    )
    island = (
        '<script type="application/json" id="cluster-index" '
        'data-src="/topics/t/data/cluster-index.0000000000000000.json"></script>'
    )
    with pytest.raises(ArtifactError, match="which the data island assigns to 'us'"):
        check(page(island=island), root=tmp_path)


# --------------------------------------------------------------------------------------
# 3. hreflang against the locale set actually shipped
# --------------------------------------------------------------------------------------


def test_a_missing_alternate_for_a_shipped_locale_is_caught():
    """Topics have shipped with no English page and nothing said so."""
    html_text = page(alternates=(("zh-CN", "/zh-CN/topics/aabb-river-light-2026/"),), locale="zh-CN")
    with pytest.raises(ArtifactError, match="do not match the locales this publication ships"):
        check(html_text, page_locale="zh-CN", expected_locales={"en", "zh-CN"})


def test_an_alternate_for_a_locale_that_does_not_ship_is_caught():
    extra = (
        ("en", "/en/topics/aabb-river-light-2026/"),
        ("zh-CN", "/zh-CN/topics/aabb-river-light-2026/"),
        ("ja", "/ja/topics/aabb-river-light-2026/"),
    )
    with pytest.raises(ArtifactError, match="do not match the locales"):
        check(page(alternates=extra), page_locale="en", expected_locales={"en", "zh-CN"})


def test_a_duplicated_hreflang_is_caught():
    doubled = (
        ("en", "/en/topics/aabb-river-light-2026/"),
        ("en", "/en/topics/aabb-river-light-2026/"),
        ("zh-CN", "/zh-CN/topics/aabb-river-light-2026/"),
    )
    with pytest.raises(ArtifactError, match="declared twice"):
        check(page(alternates=doubled), page_locale="en", expected_locales={"en", "zh-CN"})


def test_an_alternate_pointing_at_the_wrong_locale_is_caught():
    crossed = (
        ("en", "/zh-CN/topics/aabb-river-light-2026/"),
        ("zh-CN", "/zh-CN/topics/aabb-river-light-2026/"),
    )
    with pytest.raises(ArtifactError, match="is not that locale's page"):
        check(page(alternates=crossed), page_locale="en", expected_locales={"en", "zh-CN"})


def test_a_page_must_link_itself_among_its_alternates():
    html_text = page(alternates=(("en", "/en/topics/aabb-river-light-2026/"),), locale="zh-CN")
    with pytest.raises(ArtifactError, match="does not link itself"):
        check(html_text, page_locale="zh-CN", expected_locales={"en"})


# --------------------------------------------------------------------------------------
# the gate wiring
# --------------------------------------------------------------------------------------


def _write_tree(root: Path, locales=("en", "zh-CN"), **kwargs):
    for locale in locales:
        target = root / locale / "topics" / "aabb-river-light-2026"
        target.mkdir(parents=True)
        (target / "index.html").write_text(page(locale=locale, **kwargs), encoding="utf-8")


def test_the_gate_derives_each_publication_locale_set_from_the_tree(tmp_path):
    _write_tree(tmp_path)
    paths = ["/en/topics/aabb-river-light-2026/", "/zh-CN/topics/aabb-river-light-2026/"]
    assert _check_semantics(tmp_path, paths) == 2


def test_the_gate_fails_a_tree_whose_pages_hide_a_shipped_language(tmp_path):
    _write_tree(tmp_path, alternates=(("en", "/en/topics/aabb-river-light-2026/"),))
    paths = ["/en/topics/aabb-river-light-2026/", "/zh-CN/topics/aabb-river-light-2026/"]
    with pytest.raises(ArtifactError, match="do not match the locales"):
        _check_semantics(tmp_path, paths)


# --------------------------------------------------------------------------------------
# no false positives on a complete synthetic exported tree
# --------------------------------------------------------------------------------------


def test_every_synthetic_publication_page_passes(tmp_path):
    root = tmp_path / "public"
    _write_tree(root)
    pages = sorted(root.glob("*/topics/*/index.html"))
    shipped: dict[str, set[str]] = {}
    for path in pages:
        shipped.setdefault(path.parent.name, set()).add(path.relative_to(root).parts[0])
    for path in pages:
        text = path.read_text(encoding="utf-8")
        locale = re.search(r'data-site-locale="([^"]+)"', text)
        result = check_page_semantics(
            text,
            label="/" + path.relative_to(root).parent.as_posix() + "/",
            root=root,
            page_locale=locale.group(1) if locale else None,
            expected_locales=shipped[path.parent.name],
        )
        assert result["angles_paired"] >= 1
        assert result["badges_checked"] >= 2
        assert result["alternates"] >= 1
