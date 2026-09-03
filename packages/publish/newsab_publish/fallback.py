"""Whole-page locale fallback without field-by-field mixed localization."""

from __future__ import annotations

import html
import json
from typing import Sequence

from newsab_schema import CatalogRecord
from newsab_schema.locales import direction as locale_direction

from .identity import site_identity
from .site_strings import site_strings


def render_locale_fallback(
    record: CatalogRecord,
    *,
    site_locale: str,
    actual_locale_urls: dict[str, str],
) -> str:
    """Keep site chrome in the requested locale and embed one intact topic locale.

    The iframe boundary is deliberate: it gives the complete article its own document
    language and prevents renderer controls from being translated one field at a time.
    Search engines receive the actual topic locale as canonical and only real locale
    bundles as alternates.
    """
    s = dict(site_strings(site_locale))
    identity = site_identity()
    content_locale = record.locale
    notice = s["fallback_notice"].format(
        site_locale=site_locale, content_locale=content_locale
    )
    direct = s["fallback_open"].format(content_locale=content_locale)
    alternates = "".join(
        f'<link rel="alternate" hreflang="{html.escape(locale)}" href="{html.escape(url, quote=True)}">'
        for locale, url in sorted(actual_locale_urls.items())
    )
    language_links = "".join(
        f'<a lang="{html.escape(locale)}" hreflang="{html.escape(locale)}" '
        f'href="{html.escape(url, quote=True)}">{html.escape(locale)}</a>'
        for locale, url in sorted(actual_locale_urls.items())
    )
    return (
        '<!doctype html>\n'
        f'<html lang="{html.escape(site_locale)}" '
        f'dir="{html.escape(locale_direction(site_locale))}"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="robots" content="noindex,follow">'
        f'<link rel="canonical" href="{html.escape(record.page_url, quote=True)}">{alternates}'
        f'<title>{html.escape(record.title.text)} · {html.escape(identity.site_name)}</title><style>'
        ':root{font:16px/1.5 system-ui;color:#18201d;background:#f7f5ef}*{box-sizing:border-box}'
        'body{margin:0}.chrome{display:flex;align-items:center;gap:.75rem;flex-wrap:wrap;padding:max(.75rem,env(safe-area-inset-top)) max(1rem,env(safe-area-inset-right)) .75rem max(1rem,env(safe-area-inset-left));border-bottom:1px solid #d9d8d0;background:white}'
        '.brand{font-weight:750;margin-right:auto}.chrome a{display:inline-flex;align-items:center;min-height:44px;color:inherit}'
        '[dir="rtl"] .brand{margin-right:0;margin-left:auto}'
        '.notice{margin:0;padding:.75rem max(1rem,env(safe-area-inset-right)) .75rem max(1rem,env(safe-area-inset-left));background:#fff5dc;border-bottom:1px solid #e1c77c}'
        'iframe{display:block;width:100%;height:calc(100dvh - 8.5rem);min-height:32rem;border:0;background:#fbfaf7}'
        '@media(max-width:420px){.chrome{gap:.4rem}.notice{font-size:.9rem}iframe{height:calc(100dvh - 10.5rem)}}'
        '</style></head><body>'
        f'<header class="chrome"><a class="brand" href="/{html.escape(site_locale)}/">{html.escape(identity.site_name)}</a>'
        f'<nav aria-label="{html.escape(s["language"], quote=True)}">{language_links}</nav></header>'
        f'<p class="notice">{html.escape(notice)} '
        f'<a href="{html.escape(record.page_url, quote=True)}">{html.escape(direct)}</a></p>'
        f'<iframe src="{html.escape(record.page_url, quote=True)}" lang="{html.escape(content_locale)}" '
        f'title="{html.escape(record.title.text, quote=True)}"></iframe></body></html>\n'
    )


#: The homepage's paper colour in each theme, so the redirect page is the same blank
#: sheet the homepage is about to paint over.  Mirrors ``home._STYLE``'s ``--paper``.
_PAPER_LIGHT = "#FBFAF7"
_PAPER_DARK = "#171B20"


def render_root_redirect(locales: Sequence[str], *, default_locale: str) -> str:
    """The site root: a blank sheet that sends the browser to its own language's homepage.

    A static host answers ``/`` with the same bytes for everyone, so the language choice
    happens in the browser: the script walks ``navigator.languages`` against the site's
    locale list — exact tag first, then primary subtag, so ``zh-Hans-CN`` and ``zh-TW``
    both reach ``zh-CN`` — and ``location.replace`` keeps this page out of history.
    Without JS the meta refresh goes to ``default_locale``.  The body paints nothing but
    the paper colour: the old root page showed a bare link for one frame before the
    homepage replaced it.
    """
    locales = [str(item) for item in locales]
    if default_locale not in locales:
        raise ValueError(f"root redirect default {default_locale!r} is not a site locale")
    identity = site_identity()
    default_url = f"/{default_locale}/"
    alternates = "".join(
        f'<link rel="alternate" hreflang="{html.escape(locale)}" href="/{html.escape(locale)}/">'
        for locale in sorted(locales)
    ) + f'<link rel="alternate" hreflang="x-default" href="{html.escape(default_url)}">'
    script = (
        "(function(){var L=" + json.dumps(locales) + ",D=" + json.dumps(default_locale) + ";"
        "var want=navigator.languages&&navigator.languages.length"
        "?navigator.languages:[navigator.language||''];var pick='';"
        "for(var i=0;i<want.length&&!pick;i++){var w=String(want[i]).toLowerCase(),j;"
        "for(j=0;j<L.length;j++){if(L[j].toLowerCase()===w){pick=L[j];break}}"
        "if(pick)break;var base=w.split('-')[0];"
        "for(j=0;j<L.length;j++){if(L[j].toLowerCase().split('-')[0]===base){pick=L[j];break}}}"
        "location.replace('/'+(pick||D)+'/')})();"
    )
    return (
        f'<!doctype html><html lang="{html.escape(default_locale)}"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="robots" content="noindex">'
        f"<title>{html.escape(identity.site_name)}</title>"
        f'<link rel="canonical" href="{html.escape(default_url)}">{alternates}'
        f"<style>html{{background:{_PAPER_LIGHT}}}"
        f"@media (prefers-color-scheme:dark){{html{{background:{_PAPER_DARK}}}}}"
        "body{margin:0}</style>"
        f"<script>{script}</script>"
        f'<meta http-equiv="refresh" content="0;url={html.escape(default_url)}">'
        '</head><body><a href="' + html.escape(default_url) + '" style="position:absolute;'
        'width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)">'
        f"{html.escape(identity.site_name)}</a></body></html>\n"
    )
