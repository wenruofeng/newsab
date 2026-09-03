"""``HALO_LOCALES`` is the site's single source of its nine target languages.

Everything that used to type this list out independently — the home page's halo layout,
``m2.py``'s locale-switcher endonym table, and (eventually) the dev-serve locale
selector — now reads it from here, so this module's own shape is what keeps them from
drifting apart again.
"""

from __future__ import annotations

import pytest

from newsab_schema import HALO_LOCALE_CODES, HALO_LOCALES, HaloLocale, direction, halo_locale


def test_halo_locales_is_exactly_the_planned_nine():
    # Exactly the planned nine: "不多不少" — not one more, not one less.
    assert HALO_LOCALE_CODES == ("zh-CN", "en", "ru", "fr", "ko", "hi", "es", "ja", "ar")
    assert len(HALO_LOCALES) == 9


def test_every_entry_is_well_formed():
    for entry in HALO_LOCALES:
        assert isinstance(entry, HaloLocale)
        assert entry.direction in ("ltr", "rtl")
        assert entry.halo_word.strip()
        assert entry.endonym.strip()
        assert entry.display_lang.strip()
    # Only Arabic is right-to-left; the plan's D6 puts it alone in the second rollout
    # batch precisely because it is the one RTL entry.
    assert [entry.locale for entry in HALO_LOCALES if entry.direction == "rtl"] == ["ar"]


def test_chinese_is_canonical_site_locale_but_keeps_its_halo_script_variant():
    zh = halo_locale("zh-CN")
    assert zh.locale == "zh-CN"
    assert zh.display_lang == "zh-Hans"


def test_halo_locale_looks_up_by_canonical_code_and_refuses_unknown_ones():
    assert halo_locale("en").halo_word == "News"
    with pytest.raises(ValueError, match="not one of the halo's nine"):
        halo_locale("de")


def test_no_duplicate_locale_codes():
    assert len(set(HALO_LOCALE_CODES)) == len(HALO_LOCALE_CODES)


def test_direction_is_rtl_only_for_arabic():
    assert direction("ar") == "rtl"
    for code in HALO_LOCALE_CODES:
        if code != "ar":
            assert direction(code) == "ltr"


def test_direction_falls_back_to_ltr_outside_the_halo_unlike_halo_locale():
    # Unlike halo_locale (closed-set, fails loudly), direction() is the one lenient
    # lookup every page-layout call site needs — see its own docstring for why.
    assert direction("de") == "ltr"
    assert direction("") == "ltr"
