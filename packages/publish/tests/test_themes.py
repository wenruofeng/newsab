from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from newsab_publish.chrome import theme_token_css
from newsab_publish.site_strings import SITE_LOCALES

from newsab_publish.themes import (
    MIN_TEXT_CONTRAST,
    ThemeDefinition,
    ThemeRegistry,
    check_theme_labels,
    contrast_ratio,
    load_theme_registry,
    render_theme_panel,
    resolve_theme,
)


def test_checked_in_theme_tokens_are_controlled_and_accessible():
    registry = load_theme_registry()
    assert registry.default_token == "ember"
    assert [theme.token for theme in registry.themes] == ["ember", "ocean", "plum", "pine"]
    for theme in registry.themes:
        assert contrast_ratio(theme.accent_light, "#FBFAF7") >= MIN_TEXT_CONTRAST
        assert contrast_ratio(theme.accent_dark, "#171B20") >= MIN_TEXT_CONTRAST
    # The palette a token stands for now lives once in the chrome stylesheet, and still
    # reaches nothing but --accent and the topic rule width.
    css = theme_token_css(registry)
    for theme in registry.themes:
        assert theme.accent_light in css and theme.accent_dark in css
        assert f'data-theme-token="{theme.token}"' in css
    assert "--a:" not in css and "--b:" not in css


def test_a_theme_record_names_itself_in_the_choosers_two_languages():
    # The *record's* floor is the two languages the chooser is written in.  Coverage of
    # today's ``SITE_LOCALES`` is not a model rule: a publication archives the
    # registry bytes it was built with, and re-judging those archives every time the site
    # learns a language would fail verification on history that was correct when made.
    ThemeDefinition(
        token="halo-ready",
        labels={locale: "Halo" for locale in (*SITE_LOCALES, "ar", "de")},
        accent_light="#8C2F1E",
        accent_dark="#E08265",
    )
    with pytest.raises(ValidationError, match="must name the theme in"):
        ThemeDefinition(
            token="incomplete",
            labels={"en": "Incomplete"},
            accent_light="#8C2F1E",
            accent_dark="#E08265",
        )


def test_the_live_registry_speaks_every_site_locale_and_a_use_site_is_checked():
    # Where the SITE_LOCALES rule went: onto the live registry as loaded, and onto the
    # exact locale set a build is about to render.
    registry = load_theme_registry()
    for theme in registry.themes:
        check_theme_labels(theme, SITE_LOCALES)
    archived = ThemeDefinition(
        token="archived",
        labels={"en": "Archived", "zh-CN": "存档"},
        accent_light="#8C2F1E",
        accent_dark="#E08265",
    )
    check_theme_labels(archived, ("en", "zh-CN"))
    with pytest.raises(ValueError, match="has no label for"):
        check_theme_labels(archived, ("en", "zh-CN", "ja"))


def test_unknown_or_inaccessible_theme_is_refused():
    registry = load_theme_registry()
    with pytest.raises(ValueError, match="unknown theme token"):
        resolve_theme("user-css", registry)

    payload = registry.model_dump(mode="json")
    payload["themes"][0]["accent_light"] = "#EEEEEE"
    with pytest.raises(ValidationError, match="fails 4.5:1"):
        ThemeRegistry.model_validate(payload)


def test_visual_panel_emits_only_a_registry_token():
    registry = load_theme_registry()
    panel = render_theme_panel(registry)
    assert "theme_token" in panel
    assert "allowed=new Set" in panel
    assert "<textarea" not in panel
    for token in (theme.token for theme in registry.themes):
        assert f'value="{token}"' in panel

    checked_in = Path(__file__).parents[3] / "site" / "theme_panel.html"
    if not checked_in.exists():
        checked_in = Path(__file__).parents[3] / "examples" / "theme_panel.html"
    assert checked_in.read_text(encoding="utf-8") == panel
