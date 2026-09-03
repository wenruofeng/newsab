"""A share landing must always be well-formed and name the one card a crawler can render."""

from __future__ import annotations

import html.parser
from types import SimpleNamespace

from newsab_publish.share_cards import _escape, render_share_assets, render_share_landing
from newsab_publish.social_card import ASSET_URL
from newsab_schema.common import MultiLangText


def test_escape_strips_xml_invalid_control_characters():
    assert _escape("bad\x0bchar") == "badchar"
    assert _escape("keep\ttabs\nand lines") == "keep\ttabs\nand lines"
    assert _escape('<x>&"') == "&lt;x&gt;&amp;&quot;"
    hostile = "</title><script>alert(1)</script>\x00\x1f"
    assert "<script>" not in _escape(hostile)


def _Text(text: str) -> MultiLangText:
    return MultiLangText(values={"en": text})


def _resolved(question_ids=("QST-aabb-market-meal-2024-001",)):
    page = SimpleNamespace(
        topic_id="aabb-market-meal-2024",
        title=_Text("Two markets, one meal"),
        lexicon=SimpleNamespace(questions={}, group_short_labels={}, group_labels={}, group_definitions={}),
        angles=[
            SimpleNamespace(
                question_id=qid,
                question_display=_Text("Who pays?"),
                shared_answer_label=None,
                sides=[
                    SimpleNamespace(
                        group_id="A",
                        is_silent_side=False,
                        answer_label=_Text("the state"),
                        badge=SimpleNamespace(numerator=3, denominator=4),
                    ),
                    SimpleNamespace(
                        group_id="B",
                        is_silent_side=True,
                        answer_label=None,
                        badge=SimpleNamespace(numerator=0, denominator=5),
                    ),
                ],
            )
            for qid in question_ids
        ],
    )
    groups = [
        SimpleNamespace(group_id="A", label=_Text("Country A"), short_label=None),
        SimpleNamespace(group_id="B", label=_Text("Country B"), short_label=None),
    ]
    return SimpleNamespace(page=page, manifest=SimpleNamespace(groups=groups))


class _Meta(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.meta = {}

    def handle_starttag(self, tag, attrs):
        if tag == "meta":
            found = dict(attrs)
            if "property" in found:
                self.meta[found["property"]] = found.get("content")


def test_landing_names_the_site_png_card_and_routes_to_its_fragment():
    resolved = _resolved()
    angle = resolved.page.angles[0]
    landing_url = "/en/topics/aabb-market-meal-2024/share/angle-QST-aabb-market-meal-2024-001.html"
    payload = render_share_landing(
        resolved,
        angle,
        "en",
        image_url=ASSET_URL,
        landing_url=landing_url,
        alternate_urls={"en": landing_url},
    ).decode("utf-8")
    parser = _Meta()
    parser.feed(payload)
    assert parser.meta["og:image"] == ASSET_URL
    assert parser.meta["og:image:type"] == "image/png"
    assert parser.meta["og:url"] == landing_url
    assert "angle-QST-aabb-market-meal-2024-001.svg" not in payload
    assert "#angle-QST-aabb-market-meal-2024-001" in payload
    # The per-angle facts travel as text, which every platform renders.
    assert "Who pays?" in parser.meta["og:description"]
    assert "3/4" in parser.meta["og:description"]


def test_render_share_assets_writes_landings_only(tmp_path):
    written = {}

    def write_file(root, relative, payload):
        written[relative] = payload

    assets = render_share_assets(
        _resolved(),
        ("en", "zh-CN"),
        tmp_path,
        write_file=write_file,
        digest=lambda payload: "sha256:" + "0" * 64,
    )
    assert sorted(written) == [
        "en/topics/aabb-market-meal-2024/share/angle-QST-aabb-market-meal-2024-001.html",
        "zh-CN/topics/aabb-market-meal-2024/share/angle-QST-aabb-market-meal-2024-001.html",
    ]
    assert not any(name.endswith(".svg") for name in written)
    assert [(asset.locale, asset.url, asset.sha256) for asset in assets] == [
        ("en", None, None),
        ("zh-CN", None, None),
    ]
    assert all(asset.landing_url.endswith(".html") for asset in assets)
