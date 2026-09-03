"""The halo's other seven locales are pre-loaded into every renderer-owned
constant in ``render.strings``, ahead of ``SITE_LOCALES`` growing to include them.
Import already refuses a shape mismatch (``newsab_schema.merge_lang_leaf``);
this test pins the resulting behaviour so a future edit that silently drops a locale
from one constant fails here, not at render time."""

from __future__ import annotations

import re

from newsab_schema import HALO_LOCALE_CODES

from newsab_editorial.render import strings as S

#: "dict of key -> {locale: text}" constants.
_FLAT_DICTS = [
    S.KIND_LABEL, S.KIND_TIP, S.KIND_EMPTY, S.STRENGTH_LABEL, S.TIER_LABEL, S.TIER_TIP,
    S.SOURCE_CATEGORY, S.BEAT_SCOPE, S.COUNTRY_LABEL, S.LANG_LABEL, S.ORIGIN_LABEL,
    S.STRINGS,
]
#: "dict of key -> {locale: template}" constants (one level deeper: kind -> langmap).
_NESTED_DICTS = [S.STAT_TEMPLATE, S.STAT_READING, S.STAT_ESTIMATE]
#: bare "{locale: text}" leaves — no outer key.
_BARE_LEAVES = [
    S.STAT_STABILITY, S.STAT_RATE_LINE, S.STAT_SHARE,
    # render.stats.stat_blocks's actual live templates (see the comment on
    # STAT_STRENGTH_CLAUSE in render.strings) — the dead STAT_TEMPLATE /
    # STAT_STABILITY / STAT_RATE_LINE above were never read by the function that builds
    # the statistics modal, which is why filling those in did not stop the modal
    # from serving English to the seven halo locales.
    S.STAT_STRENGTH_CLAUSE, S.STAT_LOUD_CLAUSE_FLOOR, S.STAT_LOUD_CLAUSE_SPREAD,
    S.STAT_PHENOMENON_SILENCE, S.STAT_PHENOMENON_CONSENSUS, S.STAT_PHENOMENON_DIVERGENCE,
    S.STAT_PHENOMENON_ATTENTION_GAP_GENERIC, S.STAT_REPRODUCIBILITY, S.STAT_RATE_LEAD,
    S.STAT_RATE_DETAIL, S.STAT_EFFECT_LEAD_CONSENSUS, S.STAT_EFFECT_LEAD_DIVERGENCE,
    S.STAT_EFFECT_DETAIL,
]


def test_every_leaf_in_every_flat_constant_covers_all_nine_halo_locales():
    for mapping in _FLAT_DICTS:
        for key, entry in mapping.items():
            assert set(entry) >= set(HALO_LOCALE_CODES), (mapping, key, sorted(entry))
    for mapping in _NESTED_DICTS:
        for key, entry in mapping.items():
            assert set(entry) >= set(HALO_LOCALE_CODES), (mapping, key, sorted(entry))
    for entry in _BARE_LEAVES:
        assert set(entry) >= set(HALO_LOCALE_CODES), sorted(entry)


def test_strength_tip_posterior_and_provenance_and_method_sections_cover_all_nine():
    for entry in S.STRENGTH_TIP_POSTERIOR.values():
        assert set(entry) >= set(HALO_LOCALE_CODES)
    for counters in S.PROVENANCE_COUNTS.values():
        for _name, entry in counters:
            assert set(entry) >= set(HALO_LOCALE_CODES)
    for title, body in S.METHOD_SECTIONS:
        assert set(title) >= set(HALO_LOCALE_CODES)
        assert set(body) >= set(HALO_LOCALE_CODES)


def test_footer_site_stays_identical_across_every_locale():
    """``footer_site`` is the domain label, not prose — never translatable."""
    footer_values = set(S.STRINGS["footer_site"].values())
    assert len(footer_values) == 1


def test_note_label_is_english_on_the_two_live_locales_and_translated_on_the_other_seven():
    """``note`` (the annotation-summary column header) stays deliberately English on
    en/zh-CN — that content column is the English pivot on every page regardless of
    reader locale, so a translated *label* over untranslated English *content* would
    read as a mismatch (see the comment beside the zh-CN literal). That reasoning is a
    standing decision for the two live locales only; the seven halo locales pre-loaded
    ahead of ``SITE_LOCALES`` get a real translation instead, each matching the noun
    already used in the sibling key ``summary``."""
    assert S.STRINGS["note"]["en"] == "Notes"
    assert S.STRINGS["note"]["zh-CN"] == "Notes"
    for locale in ("ru", "fr", "ko", "hi", "es", "ja", "ar"):
        assert S.STRINGS["note"][locale] != "Notes" or locale == "fr"  # fr: "Notes" is
        # itself the correct French word, so an identical value there is a real
        # translation, not a leftover placeholder.


def test_placeholders_survive_translation_in_every_locale():
    """Spot-check a handful of format-string keys: every ``{token}`` in the English
    pivot must appear, verbatim, in every locale's translation."""
    keys = [
        "more_evidence", "window", "cluster_article", "badge_tip_top", "rate_label",
        "modal_para", "evidence_title",
    ]
    token_re = re.compile(r"\{[a-zA-Z0-9_:.%+#<> -]*\}")
    for key in keys:
        entry = S.STRINGS[key]
        pivot_tokens = set(token_re.findall(entry["en"]))
        assert pivot_tokens, f"{key} has no placeholder to check"
        for locale, text in entry.items():
            assert set(token_re.findall(text)) == pivot_tokens, (key, locale, text)
