"""The privacy and submission notice as release pages, linked from both forms."""

from __future__ import annotations

import re
from datetime import date

import pytest

from newsab_publish.identity import site_identity
from newsab_publish.legal import (
    LEGAL_LOCALES,
    legal_pages,
    markdown_to_html,
    privacy_notice_source,
    privacy_notice_url,
    render_privacy_notice,
)

official = pytest.mark.skipif(
    site_identity().domain_label != "news-ab.com", reason="official identity only"
)


def _shape(html: str) -> dict[str, int]:
    return {tag: html.count(f"<{tag}>") for tag in ("h1", "h2", "h3", "p", "li", "table", "tr")}


def test_markdown_subset_renders_and_escapes():
    html = markdown_to_html(
        "# T <b>\n\nPara **bold** `code` [x](https://e.example/p).\n\n- a\n- b\n\n1. one\n\n| h1 | h2 |\n|---|---|\n| c1 | c2 |\n"
    )
    assert "<h1>T &lt;b&gt;</h1>" in html
    assert "<strong>bold</strong>" in html and "<code>code</code>" in html
    assert '<a href="https://e.example/p" rel="noopener noreferrer">x</a>' in html
    assert "<ul><li>a</li><li>b</li></ul>" in html and "<ol><li>one</li></ol>" in html
    assert "<th>h1</th>" in html and "<td>c2</td>" in html


@official
def test_translation_keeps_the_authoritative_structure():
    """A translated notice must promise exactly what the English one promises."""
    shapes = {locale: _shape(markdown_to_html(privacy_notice_source(locale))) for locale in LEGAL_LOCALES}
    assert shapes["zh-CN"] == shapes["en"]
    for locale in LEGAL_LOCALES:
        source = privacy_notice_source(locale)
        for identifier in ("suggestion-terms-2", "suggestion-privacy-2", "submission-terms-2"):
            assert identifier in source
        assert "https://www.cloudflare.com/privacypolicy/" in source


def test_every_site_locale_reads_a_written_notice():
    assert privacy_notice_url("en") == "/en/legal/privacy/"
    assert privacy_notice_url("zh-CN") == "/zh-CN/legal/privacy/"
    for other in ("ar", "es", "fr", "hi", "ja", "ko", "ru"):
        assert privacy_notice_url(other) == "/en/legal/privacy/"


@official
def test_notice_pages_are_self_contained_and_cross_linked():
    pages = legal_pages()
    assert sorted(pages) == ["en/legal/privacy/index.html", "zh-CN/legal/privacy/index.html"]
    for locale in LEGAL_LOCALES:
        html = render_privacy_notice(locale)
        assert html.startswith("<!doctype html>")
        assert f'<html lang="{locale}"' in html
        assert f'<link rel="canonical" href="/{locale}/legal/privacy/">' in html
        for item in LEGAL_LOCALES:
            assert f'hreflang="{item}" href="/{item}/legal/privacy/"' in html
        assert "<script" not in html and "/assets/" not in html
        assert "https://" not in re.sub(r'href="https://www\.cloudflare\.com/privacypolicy/"', "", html)


@official
def test_both_forms_link_the_notice_in_the_consent_sentence(catalog_factory, metadata):
    from newsab_publish.home import render_home

    others = [item for item in metadata.locales if item not in LEGAL_LOCALES]
    cases = [("zh-CN", "/zh-CN/legal/privacy/")] + [(item, "/en/legal/privacy/") for item in others[:1]]
    for locale, expected in cases:
        rendered = render_home(
            [catalog_factory(0)], locale=locale, metadata=metadata, build_date=date(2026, 9, 2)
        )
        links = re.findall(r'href="(/[^"]+/legal/privacy/)" target="_blank" rel="noopener noreferrer"', rendered)
        assert links == [expected, expected], locale
        labels = re.findall(r'<label class="suggest-consent">.*?</label>', rendered)
        assert len(labels) == 2 and all("{notice}" not in label for label in labels)
        assert 'class="suggest-privacy"' not in rendered
