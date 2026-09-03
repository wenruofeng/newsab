from __future__ import annotations

from datetime import date

import pytest

from newsab_publish.seo import render_robots, render_sitemap


def test_sitemap_is_deterministic_and_includes_real_locale_alternates(catalog_factory, metadata):
    zh = catalog_factory(0, locale="zh-CN")
    en = catalog_factory(0, locale="en")
    first = render_sitemap(
        [zh, en], metadata=metadata, base_url="https://news-ab.example", build_date=date(2026, 8, 25)
    )
    second = render_sitemap(
        [en, zh], metadata=metadata, base_url="https://news-ab.example/", build_date=date(2026, 8, 25)
    )
    assert first == second
    assert '<loc>https://news-ab.example/en/</loc>' in first
    assert f'<loc>https://news-ab.example/zh-CN/topics/{zh.topic_id}/</loc>' in first
    assert 'hreflang="en"' in first
    assert 'hreflang="zh-CN"' in first
    assert "2026-08-25" in first


def test_sitemap_only_advertises_topic_locales_that_exist(catalog_factory, metadata):
    zh = catalog_factory(1, locale="zh-CN")
    rendered = render_sitemap(
        [zh], metadata=metadata, base_url="https://news-ab.example", build_date=date(2026, 8, 25)
    )
    topic_entry = rendered.split(f'<loc>https://news-ab.example{zh.page_url}</loc>', 1)[1].split("</url>", 1)[0]
    assert f'href="https://news-ab.example{zh.page_url}"' in topic_entry
    assert f'/en/topics/{zh.topic_id}/' not in topic_entry


def test_robots_points_to_absolute_sitemap_and_origin_is_validated():
    assert render_robots(base_url="https://news-ab.example/") == (
        "User-agent: *\nAllow: /\n\nSitemap: https://news-ab.example/sitemap.xml\n"
    )
    with pytest.raises(ValueError, match="absolute HTTP"):
        render_robots(base_url="/local")
    with pytest.raises(ValueError, match="must not contain a path"):
        render_robots(base_url="https://news-ab.example/site")
