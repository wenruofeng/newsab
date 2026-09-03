"""The site's target language set, defined once and read by every layer that needs it.

The "multi-country" language set is fixed at exactly
nine: the languages ringed around the ``A / B`` lockup on the home page (``home.py``'s
halo). English is not special among them — it just happens to sit at the top of the
ring — and the halo *is* the site's public commitment to that set, so this module is
named after it.

Before this module existed, the same nine-language fact was typed out independently in
three places (the halo layout table, ``m2.py``'s locale-switcher endonym table, and
site-locale validation), and they could silently drift apart.  Everything downstream —
``newsab_publish.site_strings.SITE_LOCALES`` validation, the eventual dev-serve locale
selector, and ``newsab_editorial.render.m2``'s endonym table — reads the set from
here instead.

``SITE_LOCALES`` itself (which locales are actually *live* on the site right now) stays a
strict subset of this set and is not defined here: it is a publish-layer decision
(``newsab_publish.site_strings.SITE_LOCALES``), not a schema-layer fact, and this module
must not assume every halo locale is live.
"""

from __future__ import annotations

from typing import Literal, NamedTuple

Direction = Literal["ltr", "rtl"]


class HaloLocale(NamedTuple):
    """One language in the halo's nine.

    ``locale`` is the canonical BCP-47 site-locale code (Chinese is ``zh-CN``, never the
    halo's own script variant).  ``display_lang`` is the ``lang=`` attribute the halo ring
    itself renders with — for Chinese this is ``zh-Hans`` (the script the ring's word is
    set in), matching every other entry everywhere else.  ``halo_word`` is "news"
    translated, the word the ring actually shows; ``endonym`` is the language's own name
    for itself, for locale switchers ("Русский", not "Russian").
    """

    locale: str
    display_lang: str
    direction: Direction
    halo_word: str
    endonym: str


#: Order matches the ring: top arch first, then the left flank top-to-bottom, then the
#: right flank top-to-bottom — the same order ``home.py`` lays the ring out in.
HALO_LOCALES: tuple[HaloLocale, ...] = (
    HaloLocale("zh-CN", "zh-Hans", "ltr", "新闻", "中文（简体）"),
    HaloLocale("en", "en", "ltr", "News", "English"),
    HaloLocale("ru", "ru", "ltr", "Новости", "Русский"),
    HaloLocale("fr", "fr", "ltr", "Actualités", "Français"),
    HaloLocale("ko", "ko", "ltr", "뉴스", "한국어"),
    HaloLocale("hi", "hi", "ltr", "समाचार", "हिन्दी"),
    HaloLocale("es", "es", "ltr", "Noticias", "Español"),
    HaloLocale("ja", "ja", "ltr", "ニュース", "日本語"),
    HaloLocale("ar", "ar", "rtl", "أخبار", "العربية"),
)

#: Just the codes, in the same order — the common case for membership checks.
HALO_LOCALE_CODES: tuple[str, ...] = tuple(entry.locale for entry in HALO_LOCALES)

#: The seven halo locales beyond the two already live on ``SITE_LOCALES`` (every chrome
#: catalog gets exactly these seven added, in halo order).
EXTRA_HALO_LOCALES: tuple[str, ...] = tuple(
    code for code in HALO_LOCALE_CODES if code not in ("en", "zh-CN")
)

_BY_LOCALE: dict[str, HaloLocale] = {entry.locale: entry for entry in HALO_LOCALES}

if len(_BY_LOCALE) != len(HALO_LOCALES):
    raise RuntimeError("HALO_LOCALES repeats a locale code")


def halo_locale(locale: str) -> HaloLocale:
    """Look up one halo locale's record, or fail loudly for a locale outside the nine."""
    try:
        return _BY_LOCALE[locale]
    except KeyError as exc:
        raise ValueError(f"{locale!r} is not one of the halo's nine locales") from exc


def direction(locale: str) -> Direction:
    """The ``dir=`` a page in this locale must carry — ``rtl`` for Arabic, else ``ltr``.

    Lenient on purpose, unlike :func:`halo_locale`: every renderer that emits an
    ``<html dir=...>`` also has plenty of exercise (tests, previews, fixtures) that pass
    a locale outside the halo's nine, and none of that exercise is asserting anything
    about text direction — it should keep working, not start failing loudly because a
    RTL gate learned about a closed set it was never checking membership in.  The one
    locale that actually matters (``ar``) is always in the set, so the closed-set
    enforcement other callers need stays on :func:`halo_locale` and ``SITE_LOCALES``
    validation; this just answers the one yes/no question every page layout needs.
    """
    entry = _BY_LOCALE.get(locale)
    return entry.direction if entry is not None else "ltr"
