from __future__ import annotations

from newsab_publish.fallback import render_locale_fallback
from newsab_publish.site_strings import site_strings


def test_whole_page_fallback_keeps_site_and_content_languages_separate(catalog_factory):
    record = catalog_factory(0, locale="en")
    rendered = render_locale_fallback(
        record,
        site_locale="zh-CN",
        actual_locale_urls={"en": record.page_url},
    )
    assert '<html lang="zh-CN" dir="ltr">' in rendered
    assert f'<link rel="canonical" href="{record.page_url}">' in rendered
    assert f'src="{record.page_url}" lang="en"' in rendered
    # Assert the notice the site dictionary actually holds: this test is about locale
    # separation, and must not break every time the user polishes the copy.
    notice = dict(site_strings("zh-CN"))["fallback_notice"].format(
        site_locale="zh-CN", content_locale="en"
    )
    assert notice in rendered
    assert "noindex,follow" in rendered
    assert 'hreflang="zh-CN"' not in rendered
    # Topic prose is one intact nested document, never copied field by field into chrome.
    assert record.brief.text not in rendered



def test_root_redirect_is_a_blank_sheet_that_picks_the_browser_language():
    """The old root page painted a bare "News A/B" link for one frame before its meta
    refresh replaced it.  Now the body shows nothing, the script
    walks navigator.languages against the locale list, and no-JS still gets the default."""
    from newsab_publish.fallback import render_root_redirect

    page = render_root_redirect(["zh-CN", "en", "ja"], default_locale="en")
    body = page.split("<body>", 1)[1].split("</body>", 1)[0]
    # nothing visible: the one link is clipped away for assistive tech only
    assert "clip:rect(0 0 0 0)" in body and body.count("<a ") == 1
    assert "html{background:#FBFAF7}" in page
    assert "@media (prefers-color-scheme:dark){html{background:#171B20}}" in page
    # every locale is offered to the script and to crawlers; the default wins otherwise
    assert 'var L=["zh-CN", "en", "ja"],D="en"' in page.replace('", "', '", "')
    assert "navigator.languages" in page and "location.replace(" in page
    assert ".split('-')[0]" in page  # zh-Hans-CN / zh-TW fall to zh-CN by primary subtag
    assert '<meta http-equiv="refresh" content="0;url=/en/">' in page
    assert '<link rel="canonical" href="/en/">' in page
    assert 'hreflang="x-default" href="/en/"' in page
    for locale in ("zh-CN", "en", "ja"):
        assert f'hreflang="{locale}" href="/{locale}/"' in page
    assert '<meta name="robots" content="noindex">' in page
    import pytest

    with pytest.raises(ValueError):
        render_root_redirect(["zh-CN", "en"], default_locale="fr")
