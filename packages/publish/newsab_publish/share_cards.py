"""Deterministic, public-safe per-angle share landings derived from pinned page facts.

A landing page gives one angle a fragment-independent URL: the share button hands it to
the system share sheet, a crawler reads its ``og:title`` / ``og:description`` for the
angle's facts, and a person who follows it is routed straight to the angle on the page.

Until ``publish-0.7.0`` this module also drew one SVG card per angle and locale and the
landing's ``og:image`` named it.  Those cards are retired: no social platform renders an
SVG as a card image, so the release had long pointed every crawler at the site's
PNG card anyway, and the SVGs were bytes nobody ever saw.  The landing now names that
PNG directly (root-relative, like every other asset a content document names; the
release makes it absolute).  Historical bundles keep their SVGs on disk under the
never-delete rule, and their records still pin them (``ShareAsset.url``).
"""

from __future__ import annotations

import html
from pathlib import Path
from typing import Iterable

from newsab_editorial.render.common import group_text
from newsab_editorial.render.strings import s, t
from newsab_schema.locales import direction as locale_direction
from newsab_schema.models.publication import ShareAsset

from .identity import site_identity
from .social_card import ASSET_URL as SHARE_IMAGE_URL
from .social_card import HEIGHT, WIDTH


def _escape(value: object) -> str:
    # html.escape covers markup, but XML 1.0 also forbids C0 controls (except tab,
    # newline, carriage return) and lone surrogates; one such character would make the
    # whole SVG unparseable for every crawler.
    text = str(value)
    cleaned = "".join(
        char
        for char in text
        if (char >= " " or char in "\t\n\r")
        and char != "\x7f"
        and not "\ud800" <= char <= "\udfff"
    )
    return html.escape(cleaned, quote=True)


def _answer(angle, side, locale: str) -> str:
    # One wording for both shapes of silence, exactly as the answer card says it.
    if side.is_silent_side:
        return s("silent_answer", locale)
    if angle.shared_answer_label is not None:
        return t(angle.shared_answer_label, locale)
    return t(side.answer_label, locale) if side.answer_label else "—"


def render_share_landing(
    resolved,
    angle,
    locale: str,
    *,
    image_url: str,
    landing_url: str,
    alternate_urls: dict[str, str],
) -> bytes:
    """Give social crawlers a fragment-independent URL for one angle's card."""
    identity = site_identity()
    page = resolved.page
    groups = {group.group_id: group for group in resolved.manifest.groups}
    question_text = page.lexicon.questions.get(angle.question_id) or angle.question_display
    question = t(question_text, locale)

    def _side_label(group_id: str) -> str:
        group = groups[group_id]
        fallback = group.short_label if group.short_label else group.label
        return group_text(page.lexicon, "group_short_labels", group_id, fallback, locale)

    side_phrases = [
        f"{_side_label(side.group_id)}: {_answer(angle, side, locale)} "
        f"({side.badge.numerator}/{side.badge.denominator})"
        for side in angle.sides
    ]
    description = f"{question} — {' · '.join(side_phrases)}"
    fragment_url = f"/{locale}/topics/{page.topic_id}/#angle-{angle.question_id}"
    alternates = "".join(
        f'<link rel="alternate" hreflang="{_escape(item_locale)}" href="{_escape(url)}">'
        for item_locale, url in sorted(alternate_urls.items())
    )
    payload = (
        '<!doctype html>\n'
        f'<html lang="{_escape(locale)}" dir="{_escape(locale_direction(locale))}">'
        '<head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<link rel="canonical" href="{_escape(fragment_url)}">{alternates}'
        f'<meta http-equiv="refresh" content="0;url={_escape(fragment_url)}">'
        '<meta property="og:type" content="article">'
        f'<meta property="og:title" content="{_escape(t(page.title, locale))}">'
        f'<meta property="og:description" content="{_escape(description)}">'
        f'<meta property="og:url" content="{_escape(landing_url)}">'
        f'<meta property="og:image" content="{_escape(image_url)}">'
        '<meta property="og:image:type" content="image/png">'
        f'<meta property="og:image:width" content="{WIDTH}"><meta property="og:image:height" content="{HEIGHT}">'
        f'<title>{_escape(question)} · {_escape(identity.site_name)}</title><style>'
        ':root{font:18px/1.6 system-ui;color:#18201d;background:#f7f5ef}main{width:min(42rem,calc(100% - 2rem));margin:4rem auto}'
        'a{display:inline-flex;min-height:44px;align-items:center;color:inherit}</style></head>'
        f'<body><main><h1>{_escape(t(page.title, locale))}</h1><p><strong>Q:</strong> {_escape(question)}</p>'
        f'<p>{_escape(" · ".join(side_phrases))}</p><a href="{_escape(fragment_url)}">{_escape(identity.site_name)} →</a>'
        '</main></body></html>\n'
    )
    return payload.encode("utf-8")


def render_share_assets(
    resolved,
    locales: Iterable[str],
    output_root: Path,
    *,
    write_file,
    digest,
) -> list[ShareAsset]:
    """Write one landing page per angle and locale; return the records that pin them."""
    assets: list[ShareAsset] = []
    locales = tuple(locales)
    for locale in locales:
        for angle in resolved.page.angles:
            landing_relative = (
                f"{locale}/topics/{resolved.page.topic_id}/share/"
                f"angle-{angle.question_id}.html"
            )
            landing_url = f"/{landing_relative}"
            landing_alternates = {
                item_locale: (
                    f"/{item_locale}/topics/{resolved.page.topic_id}/share/"
                    f"angle-{angle.question_id}.html"
                )
                for item_locale in locales
            }
            landing_payload = render_share_landing(
                resolved,
                angle,
                locale,
                image_url=SHARE_IMAGE_URL,
                landing_url=landing_url,
                alternate_urls=landing_alternates,
            )
            write_file(output_root, landing_relative, landing_payload)
            assets.append(
                ShareAsset(
                    locale=locale,
                    question_id=angle.question_id,
                    landing_url=landing_url,
                    landing_sha256=digest(landing_payload),
                )
            )
    return assets
