"""The shared About modal uses the one chrome-owned brand mark."""

from newsab_publish.about import ABOUT_CSS, ABOUT_LOCALES, about_modal_html, chrome_about_js
from newsab_publish.brand import TRANSPARENT_DARK_ASSET_URL, TRANSPARENT_LIGHT_ASSET_URL


def test_about_modal_centres_the_reusable_logo_without_copying_its_svg():
    for locale in ("en", "zh-CN"):
        markup = about_modal_html(locale)
        assert markup.count('class="about-logo"') == 1
        assert f'src="{TRANSPARENT_LIGHT_ASSET_URL}"' in markup
        assert f'src="{TRANSPARENT_DARK_ASSET_URL}"' in markup
        assert markup.count('width="440" height="372"') == 2
        assert markup.count('alt=""') == 2 and 'aria-hidden="true"' in markup
        assert markup.index('class="about-logo"') < markup.index('id="about-title"')
        assert "<svg" not in markup.split('class="about-logo"', 1)[1].split(">", 1)[0]


def test_logo_size_and_edge_treatment_follow_both_themes():
    rule = ABOUT_CSS.split(".about-logo{", 1)[1].split("}", 1)[0]
    assert "display:block" in rule
    assert "width:clamp(4.75rem,18vw,6.25rem)" in rule
    assert "margin:.15rem auto .9rem" in rule
    assert "aspect-ratio:440/372" in rule
    image_rule = ABOUT_CSS.split(".about-logo-img{", 1)[1].split("}", 1)[0]
    # A drop-shadow follows the foreground strokes; box-shadow would redraw the removed
    # background as a faint rectangle.
    assert "filter:drop-shadow(" in image_rule
    assert "box-shadow" not in rule
    assert ':root[data-theme="dark"] .about-logo-dark{display:block}' in ABOUT_CSS
    assert ':root[data-theme="light"] .about-logo-light{display:block}' in ABOUT_CSS


def test_topic_page_injector_carries_the_same_logo_url():
    """One embedded modal per locale the injector knows — all nine halo locales
    (pre-loaded ahead of ``SITE_LOCALES``), so the count grows with it."""
    script = chrome_about_js()
    assert len(ABOUT_LOCALES) == 9
    assert script.count(TRANSPARENT_LIGHT_ASSET_URL) == len(ABOUT_LOCALES)
    assert script.count(TRANSPARENT_DARK_ASSET_URL) == len(ABOUT_LOCALES)


def test_flow_note_ends_by_naming_where_the_code_lives_in_every_locale():
    """After the methodology sentence, one more names the repository — the same
    placeholder link the footer and the suggest modal carry."""
    from newsab_publish.suggest import TOOLKIT_PLACEHOLDER_URL

    for locale in ABOUT_LOCALES:
        markup = about_modal_html(locale)
        note = markup.split('<p class="about-note">', 1)[1].split("</p>", 1)[0]
        assert note.count(f'<a href="{TOOLKIT_PLACEHOLDER_URL}"') == 1, locale
        assert 'rel="noopener noreferrer"' in note and "{link}" not in note, locale
        assert "GitHub" in note.split("<a ", 1)[1].split("</a>", 1)[0], locale
