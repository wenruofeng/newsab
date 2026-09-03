"""The static report-search payload never becomes a hidden full-text index."""

from __future__ import annotations

import json
from types import SimpleNamespace

from newsab_editorial.render.common import ICONS
from newsab_editorial.render.islands import merge_search_docs
from newsab_editorial.render.search import report_search_payload, report_search_section
from newsab_editorial.render.script import JS


def _row():
    cluster = SimpleNamespace(
        cluster_id="RC-CN-00000001",
        addressed=True,
        category="policy_shift",
        summary="The report says the quota will tighten.",
        notes="The quota is annual.",
    )
    return SimpleNamespace(
        question_id="QST-example-001",
        text={"en": "What changes?", "zh-CN": "政策有何变化？"},
        groups=[SimpleNamespace(clusters=[cluster])],
    )


def test_search_payload_uses_only_reader_visible_article_and_annotation_fields():
    article = SimpleNamespace(
        article_id="CN_00000001",
        reporting_cluster_id="RC-CN-00000001",
        structured_text="SECRET FULL ARTICLE TEXT",
    )
    article_index = {
        article.article_id: {
            "title": "配额政策调整",
            "source_id": "src-example",
            "date": "2026-07-17",
            "fetched": "2026-07-18",
            "origin": "original",
            "wire_source": None,
            "cluster": article.reporting_cluster_id,
            "topics": [
                {"source_phrase": "配额收紧", "pivot_en": "quota tightening"}
            ],
        }
    }

    payload = report_search_payload([article], article_index, [_row()])

    # The neutral document carries stable ids and English-pivot text only.
    assert payload[0]["title"] == "配额政策调整"
    assert payload[0]["source_id"] == "src-example"
    assert payload[0]["group_id"] == "cn"
    assert payload[0]["question_ids"] == ["QST-example-001"]
    assert payload[0]["answers"] == [
        {
            "category": "policy_shift",
            "texts": [
                "The report says the quota will tighten.",
                "The quota is annual.",
            ],
        }
    ]
    assert "SECRET FULL ARTICLE TEXT" not in json.dumps(payload, ensure_ascii=False)

    # The overlay merge — the reference the page script's hydration mirrors — restores
    # the legacy localized search document.
    overlay = {
        "sources": {"src-example": "示例媒体"},
        "topics": {"quota tightening": "收紧配额"},
        "origins": {"original": "原创报道"},
        "groups": {
            "cn": {"short": "中方", "label": "中文报道", "definition": "中文媒体样本"}
        },
        "questions": {"QST-example-001": "政策有何变化？"},
        "categories": {"policy_shift": "policy shift"},
    }
    merged = merge_search_docs(payload, overlay)
    assert merged[0]["source"] == "示例媒体"
    assert merged[0]["group"] == "中方"
    assert merged[0]["origin"] == "原创报道"
    assert merged[0]["phrases"] == ["配额收紧", "收紧配额", "quota tightening"]
    assert merged[0]["phrase_labels"] == ["收紧配额"]
    assert merged[0]["questions"] == ["政策有何变化？"]
    assert merged[0]["answers"] == [
        "policy shift",
        "The report says the quota will tighten.",
        "The quota is annual.",
    ]
    assert "中文媒体样本" in merged[0]["meta"]
    assert "SECRET FULL ARTICLE TEXT" not in json.dumps(merged, ensure_ascii=False)


def test_search_shell_is_bilingual_accessible_and_debounced():
    zh = report_search_section("zh-CN")
    en = report_search_section("en")

    assert "搜索报道" in zh and "除正文" in zh
    assert "Search" in en and "article text excluded" in en
    assert "输入关键词，定位报道及其原站链接" not in zh
    assert "Start typing to locate a report" not in en
    assert '<use href="#i-search-plain"></use>' in zh
    assert 'type="search"' in zh
    assert 'aria-controls="report-search-results"' in zh
    assert 'aria-live="polite"' in zh
    assert 'data-search-delay="80"' in zh


def test_search_results_keep_two_meta_fields_and_bold_visible_matches():
    assert "[doc.source, doc.date]" in JS
    assert "[doc.source, doc.date, doc.group, doc.origin]" not in JS
    assert "document.createElement('strong')" in JS
    assert "strong.className = 'sr-match'" in JS
    assert "appendSearchHighlighted(title, doc.title, terms)" in JS

    heading_icon = ICONS.split('<symbol id="i-search"', 1)[1].split("</symbol>", 1)[0]
    input_icon = ICONS.split('<symbol id="i-search-plain"', 1)[1].split("</symbol>", 1)[0]
    assert "<rect" in heading_icon and "<circle" in heading_icon
    assert "<rect" not in input_icon and "<circle" in input_icon
