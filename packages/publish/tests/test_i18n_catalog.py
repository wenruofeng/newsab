"""The halo's other seven locales (``newsab_schema.EXTRA_HALO_LOCALES``) are
pre-loaded into every site-owned chrome catalog — ``site_strings``, ``about``,
``suggest``, the checked-in theme registry and site metadata's category labels — ahead
of ``SITE_LOCALES`` growing to include them. Each module's own import-time
assertion already refuses a shape mismatch; this test pins the resulting coverage so a
future edit that silently drops a locale from one catalog fails here, not at render or
build time.
"""

from __future__ import annotations

from newsab_schema import HALO_LOCALE_CODES

from newsab_publish import about as A
from newsab_publish import suggest as G
# ``newsab_publish/__init__.py`` re-exports the *function* ``site_strings`` under the
# package's own ``site_strings`` attribute, which shadows the submodule there — so the
# submodule's private tables have to be imported directly by name, not via
# ``from newsab_publish import site_strings as SS``.
from newsab_publish.metadata import default_metadata_path, load_site_metadata
from newsab_publish.site_strings import (
    SITE_LOCALES,
    _LANGUAGE_NAMES,
    _STRINGS,
    language_name,
    site_strings,
)
from newsab_publish.themes import load_theme_registry


def test_site_strings_and_language_names_cover_all_nine_halo_locales():
    assert set(_STRINGS) >= set(HALO_LOCALE_CODES)
    assert set(_LANGUAGE_NAMES) >= set(HALO_LOCALE_CODES)
    for locale in HALO_LOCALE_CODES:
        assert site_strings(locale)  # does not raise
        assert language_name("en", locale)


def test_about_copy_and_flow_cover_all_nine_halo_locales():
    assert set(A.ABOUT_LOCALES) == set(HALO_LOCALE_CODES)
    assert set(A._FLOW) == set(HALO_LOCALE_CODES)
    for locale in HALO_LOCALE_CODES:
        markup = A.about_modal_html(locale)
        assert "<script" not in markup
        assert markup.strip()


def test_about_flow_stage_labels_are_identical_machinery_across_every_locale():
    """The pipeline-stage node labels (``"1. scope"`` etc.) and every loop's back-edge
    target are shared verbatim across languages — only the surrounding prose differs."""
    fixed_index = {1, 3, 5, 7, 9, 11, 13, 14}
    reference = [A._FLOW["en"][i][1][0] for i in fixed_index]
    for locale in HALO_LOCALE_CODES:
        actual = [A._FLOW[locale][i][1][0] for i in fixed_index]
        assert actual == reference, locale
        # every loop's target text is one of the fixed stage labels above
        for _kind, _lines, loops, _edge in A._FLOW[locale]:
            for _label, target in loops:
                assert target in reference, (locale, target)


def test_suggest_copy_covers_all_nine_halo_locales():
    assert set(G._COPY) == set(HALO_LOCALE_CODES)
    for locale in HALO_LOCALE_CODES:
        assert G.suggest_button_html(locale)
        assert G.suggest_modal_html(locale)


def test_theme_labels_cover_all_nine_halo_locales():
    registry = load_theme_registry()
    for theme in registry.themes:
        assert set(theme.labels) >= set(HALO_LOCALE_CODES), theme.token


def test_site_metadata_category_labels_cover_all_nine_halo_locales():
    metadata = load_site_metadata(default_metadata_path())
    for category in metadata.categories:
        assert set(category.labels) >= set(HALO_LOCALE_CODES), category.category_id
    # The shipped set is now whatever ``SITE_LOCALES`` says, and the article half (`locales`) and the chrome half must
    # name exactly the same languages, all of them inside the halo's nine.
    assert set(SITE_LOCALES) <= set(HALO_LOCALE_CODES)
    assert metadata.locales == list(SITE_LOCALES)
