"""The site chrome layer: what it must contain, and what it may not silently change."""

from __future__ import annotations

import pytest

from newsab_publish import chrome
from newsab_publish.builder import bytes_digest, write_chrome_assets
from newsab_publish.themes import load_theme_registry
from newsab_schema.io import ArtifactError


def test_stylesheet_carries_fonts_base_m2_and_every_registry_token():
    registry = load_theme_registry()
    css = chrome.stylesheet(registry)

    # @import is only honoured before any other rule; fonts are chrome, so this is where
    # they load from now.
    assert css.startswith("@import url(")
    assert "fonts.googleapis.com" in css
    assert css.index("@import") < css.index("{")
    # base editorial tokens and the M2 production layer, in that order
    assert "--serif:" in css and "--paper:#FBFAF7" in css
    assert "--tap:2.75rem" in css
    assert css.index("--serif:") < css.index("--tap:2.75rem")
    # every registry token resolves, and the token blocks come last so they win
    for theme in registry.themes:
        selector = f':root[data-theme-token="{theme.token}"]'
        assert selector in css
        assert css.index(selector) > css.index("--tap:2.75rem")


def test_script_carries_the_base_and_m2_behaviour():
    js = chrome.script()
    assert "document.documentElement.classList.add('js')" in js
    # The M2 touch fixes verified by the browser gate live here now, not in a page.
    assert "data-m2-nearest" in js or "m2-nearest" in js
    assert "setAttribute('r','22')" not in js
    assert "if(tappedTip&&floatTip){floatTip.hidden=true}" in js
    assert "target.scrollIntoView()" in js
    assert "syncStoryTabs" in js


def test_chrome_assembly_reasserts_the_contrast_gate():
    registry = load_theme_registry()
    # Model validation already refuses this, so build the failure the only way a chrome
    # edit could actually cause it: an accent that passes against one paper colour and
    # not against the paper the stylesheet really uses.
    payload = registry.model_dump(mode="json")
    payload["themes"][0]["accent_light"] = registry.themes[0].accent_light
    broken = type(registry).model_validate(payload)
    object.__setattr__(broken.themes[0], "accent_light", "#EEEEEE")
    with pytest.raises(ArtifactError, match="contrast gate"):
        chrome.stylesheet(broken)


def test_assets_are_deterministic_and_land_at_stable_paths(tmp_path):
    registry = load_theme_registry()
    first = chrome.chrome_assets(registry)
    second = chrome.chrome_assets(registry)
    assert first == second
    assert set(first) == {
        "assets/favicon.svg",
        "assets/logo-transparent-dark.svg",
        "assets/logo-transparent-light.svg",
        "assets/share-card.png",
        "assets/site.css",
        "assets/site.js",
    }
    assert chrome.STYLESHEET_URL == "/assets/site.css"
    assert chrome.SCRIPT_URL == "/assets/site.js"
    assert first["assets/favicon.svg"].startswith(b'<svg xmlns="http://www.w3.org/2000/svg"')
    for path in ("assets/logo-transparent-dark.svg", "assets/logo-transparent-light.svg"):
        transparent = first[path]
        assert transparent.startswith(b'<svg xmlns="http://www.w3.org/2000/svg"')
        assert b'<rect ' not in transparent
        assert b"linearGradient" not in transparent and b"<filter" not in transparent

    written = write_chrome_assets(tmp_path, registry)
    assert written == {path: bytes_digest(payload) for path, payload in first.items()}
    assert (tmp_path / "assets" / "site.css").read_bytes() == first["assets/site.css"]


def test_release_record_names_the_chrome_bytes_and_verification_catches_drift(tmp_path):
    registry = load_theme_registry()
    write_chrome_assets(tmp_path, registry)
    release = chrome.chrome_release(registry, bytes_digest)
    assert release["version"] == chrome.CHROME_VERSION
    assert release["theme_registry_version"] == registry.schema_version
    chrome.verify_chrome_release(tmp_path, release, bytes_digest)

    (tmp_path / "assets" / "site.css").write_text("body{display:none}", encoding="utf-8")
    with pytest.raises(ArtifactError, match="chrome asset bytes changed"):
        chrome.verify_chrome_release(tmp_path, release, bytes_digest)

    (tmp_path / "assets" / "site.css").unlink()
    with pytest.raises(ArtifactError, match="chrome asset is missing"):
        chrome.verify_chrome_release(tmp_path, release, bytes_digest)


def test_a_release_without_chrome_facts_is_left_alone(tmp_path):
    chrome.verify_chrome_release(tmp_path, {}, bytes_digest)


def test_site_controls_are_one_shape_and_the_script_assembles_them():
    """Home, language and theme are site-level, so chrome — not a page — gathers them.

    The relocation deliberately lives here: moving these controls in the renderer would
    rewrite every content document the user approved for a change to furniture.
    """
    css = chrome.stylesheet(load_theme_registry())
    assert "--toolsize:" in css
    # One shape, one size: the two controls the script relocates both resolve to it.
    assert ".site-tools[data-toolbar] .theme-fab" in css
    assert "width:var(--toolsize);height:var(--toolsize)" in css
    # A fixed control that becomes ``static`` gets the viewport as its containing block,
    # which turns the touch-reach pseudo-element into a full-screen tap trap.
    assert ".site-tools[data-toolbar] .theme-fab{position:relative" in css
    # One control height for badges and icon buttons alike.
    assert "--ctl:" in css and ".badge{min-height:var(--ctl)}" in css

    js = chrome.script()
    assert "buildToolbar" in js
    assert "data-toolbar" in js
    # Every label the document wrote survives as the control's accessible name.
    assert "toollabel" in js and "setAttribute('aria-label'" in js
    assert "LOCALE_NAMES" in js
    # Chrome audit: the topic-page switcher used to say "简体中文" (a hand-typed
    # literal) while the home page said "中文（简体）"; both endonyms now come from
    # ``HALO_LOCALES`` alone, so the embedded table can only ever carry the one spelling.
    assert '"zh-CN": "中文（简体）"' in js
    assert "简体中文" not in js


def test_chrome_version_moves_with_the_bytes():
    """The release record names a chrome version; it has to mean something."""
    assert chrome.CHROME_VERSION == "chrome-1.12.2"


def test_stylesheet_carries_the_five_new_script_font_families_and_the_rtl_layer():
    """hi/ar/ko/ja/ru reading faces and the RTL flow-mirrors/sides-don't layer."""
    css = chrome.stylesheet(load_theme_registry())
    for family in (
        "Noto+Serif+KR", "Noto+Sans+KR",
        "Noto+Serif+JP", "Noto+Sans+JP",
        "Noto+Serif+Devanagari", "Noto+Sans+Devanagari",
        "Noto+Naskh+Arabic", "Noto+Sans+Arabic",
    ):
        assert family in css
    for lang in ("ko", "ja", "hi", "ar"):
        assert f":root:lang({lang})" in css
    assert '[dir="rtl"] .duo,' in css
    assert '[dir="rtl"] .theme-fab{right:auto;left:1rem}' in css


def test_the_theme_moon_is_outlined_from_chrome_not_from_the_document():
    """The sprite is inlined in approved content documents, so the fix has to be chrome.

    A ``<use>`` instance takes the computed style of the symbol it clones, so a rule on
    the symbol's own path reaches every page that carries it — without moving one byte a
    human approved.  Solid was the odd one out beside the outlined sun.
    """
    css = chrome.stylesheet(load_theme_registry())
    assert "#i-moon path{fill:none;stroke:currentColor;stroke-width:1.5" in css


def test_script_rehomes_modals_that_the_page_renders_inside_main():
    """Opening a modal makes ``<main>`` inert, and inertness cannot be opted out of.

    The concept cloud's explanation panel is rendered beside its own section, so it lived
    inside ``<main>``: it opened and then refused every click, including its own close
    button.  Chrome moves such a panel to ``<body>`` before anything binds to it.
    """
    js = chrome.script()
    assert "mainRegion.querySelectorAll('.modal')" in js
    assert "document.body.appendChild(modal)" in js
    assert js.index("document.body.appendChild(modal)") < js.index(
        "var modalNodes=Array.prototype.slice.call(document.querySelectorAll('.modal'))"
    )


def test_the_top_modal_is_the_one_opened_last_not_the_last_one_in_the_document():
    """A record opened from a record could not be clicked at all.

    The shared record panels (sentence, outlet, cluster) are emitted before the question
    modals, and re-homing ``main``'s modals to the end of ``body`` moves them further
    apart still.  Reading DOM order therefore judged the *older* layer to be on top and
    made the new one ``inert`` — visible, above everything, and closable only with
    Escape.  The page script stamps each layer with a stacking level as it opens it.
    """
    js = chrome.script()
    assert "function openModals()" in js
    assert "parseInt(modal.style.zIndex,10)" in js
    assert "modal.inert=!modal.hidden&&modal!==top" in js
    # The observer has to see the stacking level land, not only `hidden`.
    assert "attributeFilter:['hidden','style']" in js
    # The focus trap reads the same order.
    assert "var stackTop=openModals()" in js
    # And the scroll lock follows the document rather than one handler's bookkeeping.
    assert "document.body.style.overflow=open.length?'hidden':''" in js


def test_a_control_that_does_something_shows_its_note_on_hover_not_on_click():
    """The bubble landed on top of whatever the click just opened.

    Badges, whose only click behaviour is to pin their own note, keep the tap; on a touch
    screen a long press is what hover is, and the click it turns into is swallowed.
    """
    js = chrome.script()
    assert "var ACTION_TIP=" in js
    for selector in ("[data-open]", "[data-media]", "[data-cluster]", "[data-sid]"):
        assert selector in js.split("var ACTION_TIP=")[1].split(";")[0]
    assert "if(!tipped||actionTip(tipped)){hideTappedTip();return}" in js
    assert "pressFired=true;showTipFor(tipped)" in js
    assert "pressFired=false;event.preventDefault();event.stopPropagation();" in js


def test_the_two_explanations_go_full_width_when_the_answer_cards_stack():
    """This layer's own `.comm` rule is unconditional and later than the editorial
    layer's media query, so the desktop three-column grid won on a phone and each
    explanation printed in a 2/5-wide column."""
    css = chrome.stylesheet(load_theme_registry())
    # The editorial layer opens a block at the same width; this layer's is the later one.
    mobile = css.split("@media (max-width:720px){")[-1]
    assert ".comm{grid-template-columns:1fr}" in mobile
    assert ".comm:not(.joint) p:last-child{grid-column:1}" in mobile
    # The connector already turned a quarter turn; its mark now turns with it.
    assert ".relmark .kindicon,.story-tabs .kindicon{transform:rotate(90deg)}" in mobile
    assert ".relmark .kindicon.flip{transform:rotate(90deg) scaleX(-1)}" in mobile


def test_search_hit_labels_cannot_be_squeezed_onto_their_side():
    """A shrinking flex item wraps CJK one character per line and stands the label up."""
    css = chrome.stylesheet(load_theme_registry())
    assert ".sr-hitgroup b{font-weight:600;color:var(--ink2);flex:none;white-space:nowrap}" in css


def test_the_share_control_is_centred_on_the_question_line_and_stays_quiet():
    css = chrome.stylesheet(load_theme_registry())
    # One token drives both the heading size and the offset that centres the control on it.
    assert "--qh2:clamp(21px,2.4vw,28px)" in css
    assert "margin:calc((1.35 * var(--qh2) - var(--sharesize)) / 2) 0 0 .5rem" in css
    # Transparent, muted: an angle's share control must not outrank the angle.
    assert "background:transparent;color:var(--muted);cursor:pointer" in css


def test_the_site_bar_sits_in_the_page_corners_and_does_not_follow_the_viewport():
    """Site controls that line up with the article read as part of the article.

    ``absolute``, not ``fixed``: the same shape and shadow as back-to-top, but pinned to
    the top of the *page* — it scrolls away, it does not follow.
    """
    css = chrome.stylesheet(load_theme_registry())
    assert ".site-tools[data-toolbar]{position:absolute" in css
    assert "box-shadow:0 5px 18px rgba(0,0,0,.12)" in css
    # Out of the flow, so the page has to be told to make room for it.
    assert ":root[data-sitebar] main{padding-top:" in css
    assert "document.documentElement.setAttribute('data-sitebar','on')" in chrome.script()
    # A full-width bar over the title must not eat clicks meant for the title.
    assert ".site-tools[data-toolbar]>*{pointer-events:auto}" in css
