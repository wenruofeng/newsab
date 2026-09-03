"""The site chrome layer: shared stylesheet, behaviour script and font loading.

Why this module exists is a contract decision, not a packaging preference.  Touchpoint
two approves **what a page states** — its claims, order, counts, quotes, anchors and
labels.  It does not approve the site's typography.  While CSS, fonts and behaviour were
inlined into every page, the two were the same bytes, so changing one colour invalidated
every human approval on the site and forced a full re-review.

So the page keeps the content document and this module owns everything else:

* one stylesheet at a **stable** URL (no content hash in the path), so a chrome release
  never touches an approved content document's bytes;
* the topic theme expressed as ``data-theme-token`` on the content document plus one
  variable block per registry token here — a token is a name the page states, the colours
  behind it are chrome;
* the behaviour script, served the same way.
* reusable site artwork, including the vector logo at ``/assets/favicon.svg``.

The trust boundary that moves with it: chrome CSS could in principle hide approved
content.  That risk is carried by the contrast gate, the browser gate and the site
operator's own commit, never by a submission — a submission can still only ever carry an
opaque ``theme_token``.
"""

from __future__ import annotations

from typing import Mapping

from newsab_editorial.render.m2 import CSS as M2_CSS
from newsab_editorial.render.m2 import JS as M2_JS
from newsab_editorial.render.script import JS as BASE_JS
from newsab_editorial.render.theme import CSS as BASE_CSS
from newsab_schema.io import ArtifactError

from .about import ABOUT_CSS, chrome_about_js
from .brand import ASSET_PATH as LOGO_PATH
from .brand import logo_bytes
from .brand import TRANSPARENT_DARK_ASSET_PATH as TRANSPARENT_DARK_LOGO_PATH
from .brand import TRANSPARENT_LIGHT_ASSET_PATH as TRANSPARENT_LIGHT_LOGO_PATH
from .brand import transparent_dark_logo_bytes, transparent_light_logo_bytes
from .social_card import ASSET_PATH as SHARE_CARD_PATH
from .social_card import ASSET_URL as SHARE_CARD_URL
from .social_card import card_bytes
from .themes import (
    MIN_TEXT_CONTRAST,
    ThemeRegistry,
    contrast_ratio,
)


#: Bumped whenever the chrome bytes change for a reason a reader could notice.  It is
#: recorded in the site release record, not in any PublicationRecord: chrome is a site
#: release fact, and a content document must not learn about it.
#: 1.2.0: the behaviour script learned to fetch externalized data islands
#: (``data-src`` + ``lang-overlay`` hydration) and stays backward-compatible with
#: pages that still inline their islands.
#: 1.3.0: the theme control's moon is outlined rather than solid, restyled from chrome
#: because the sprite itself sits inside approved content documents.
#: 1.5.0: the dark palette is lifted off near-black for readability, and each answer
#: card wears its side as a top-down colour wash under a thicker top bar.
#: 1.5.1: the answer-card wash is a flat tint rather than a gradient.
#: 1.6.0: a "?" control beside the home button opens the "About this site" modal —
#: intro, the process flow chart and the small print — injected entirely from chrome
#: so no approved content document changes a byte.
#: 1.8.0: the site ships a PNG social card at a stable chrome URL — the image every
#: crawler falls back to, since no platform renders the per-angle SVG cards.
#: 1.7.0: about-modal second round — larger "?" glyph, rewritten copy with an English
#: flow chart, right-aligned legend, text-fitted nodes and a contact line.
#: 1.9.0: the reusable vector A/B brand mark replaces the home-only two-rectangle data
#: favicon and is pinned at the stable ``/assets/favicon.svg`` chrome URL.
#: 1.10.0: the two analysis shells lost their warm wash and became ordinary panels; the
#: question-data card inside them sank onto the palette's one achromatic surface, so the
#: cool/warm bar pair sits on a ground that favours neither; and the answer card's own
#: surface became a token, which the home grid's card now shares.
#: 1.11.0: flat, foreground-only light/dark variants of the approved A/B mark appear at
#: the top of the shared About modal, following the homepage palette.
#: 1.12.0: RTL support for the Arabic halo locale — the reading-direction
#: font stacks for ko/ja/hi/ar, and the layer that lets `dir="rtl"` mirror prose and
#: furniture while keeping the duo/comm/axis3/cc-grid/timeline's A-vs-B and
#: chronological layout semantics unmirrored.  Site-own chrome, no content re-review.
#: 1.12.1: the locale-menu's zh-CN entry now reads "中文（简体）" everywhere — the
#: endonym table (``LOCALE_NAMES``) reads it straight off ``HALO_LOCALES``, which is now
#: the only place it is written, so the topic-page menu can no longer show "简体中文"
#: while the home page shows "中文（简体）".
CHROME_VERSION = "chrome-1.12.2"

STYLESHEET_PATH = "assets/site.css"
SCRIPT_PATH = "assets/site.js"
STYLESHEET_URL = f"/{STYLESHEET_PATH}"
SCRIPT_URL = f"/{SCRIPT_PATH}"

#: Fonts load from the stylesheet so that changing a typeface is a chrome change too.
#: The full local fallback stack lives in the base CSS: offline the page must be plain,
#: never broken.
FONT_IMPORT = (
    '@import url("https://fonts.googleapis.com/css2?'
    "family=Source+Serif+4:opsz,wght@8..60,400;8..60,600;8..60,700"
    "&family=Noto+Serif+SC:wght@400;500;600"
    "&family=Noto+Sans+SC:wght@400;500;600"
    "&family=Noto+Serif+KR:wght@400;500;600"
    "&family=Noto+Sans+KR:wght@400;500;600"
    "&family=Noto+Serif+JP:wght@400;500;600"
    "&family=Noto+Sans+JP:wght@400;500;600"
    "&family=Noto+Serif+Devanagari:wght@400;500;600"
    "&family=Noto+Sans+Devanagari:wght@400;500;600"
    "&family=Noto+Naskh+Arabic:wght@400;500;600"
    "&family=Noto+Sans+Arabic:wght@400;500;600"
    "&family=IBM+Plex+Sans:wght@400;500;600"
    "&family=IBM+Plex+Mono:wght@400;500"
    '&display=swap");\n'
)

#: The light/dark paper colours the accent contrast gate measures against.  They are the
#: base stylesheet's own ``--paper`` values; a chrome change that moves them must move
#: these with it or the gate silently measures the wrong background.
LIGHT_PAPER = "#FBFAF7"
DARK_PAPER = "#171B20"


def theme_token_css(registry: ThemeRegistry) -> str:
    """One custom-property block per registry token, in registry order.

    Written after the base and M2 rules so the token block wins by document order at
    equal specificity, and by an extra attribute where the base uses a dark guard.
    """
    blocks = []
    for theme in registry.themes:
        selector = f':root[data-theme-token="{theme.token}"]'
        decoration = "1px" if theme.decoration == "fine-rule" else "0px"
        blocks.append(
            f"{selector}{{--accent:{theme.accent_light};--topic-decoration:{decoration}}}"
            "@media(prefers-color-scheme:dark){"
            f'{selector}:not([data-theme="light"]){{--accent:{theme.accent_dark}}}'
            "}"
            f'{selector}[data-theme="dark"]{{--accent:{theme.accent_dark}}}'
        )
    return "\n".join(blocks) + "\n"


def check_chrome_contrast(registry: ThemeRegistry) -> None:
    """Re-assert the 4.5:1 accent gate against the chrome layer's own paper colours.

    ``ThemeDefinition`` validates each token as it is loaded.  This repeats the check at
    the point where the stylesheet is actually assembled, because that is where a chrome
    edit could move the paper out from under an already-validated accent.
    """
    failures = []
    for theme in registry.themes:
        light = contrast_ratio(theme.accent_light, LIGHT_PAPER)
        dark = contrast_ratio(theme.accent_dark, DARK_PAPER)
        if light < MIN_TEXT_CONTRAST or dark < MIN_TEXT_CONTRAST:
            failures.append(f"{theme.token} (light={light:.2f}, dark={dark:.2f})")
    if failures:
        raise ArtifactError(
            f"site chrome fails the {MIN_TEXT_CONTRAST:g}:1 accent contrast gate: "
            + ", ".join(failures)
        )


def stylesheet(registry: ThemeRegistry) -> str:
    check_chrome_contrast(registry)
    return f"{FONT_IMPORT}{BASE_CSS}{M2_CSS}\n{ABOUT_CSS}\n{theme_token_css(registry)}"


def script() -> str:
    return f"{BASE_JS}\n{M2_JS}\n{chrome_about_js()}"


def chrome_assets(registry: ThemeRegistry) -> dict[str, bytes]:
    """The complete chrome file set, keyed by its bundle-relative path."""
    return {
        STYLESHEET_PATH: stylesheet(registry).encode("utf-8"),
        SCRIPT_PATH: script().encode("utf-8"),
        LOGO_PATH: logo_bytes(),
        TRANSPARENT_DARK_LOGO_PATH: transparent_dark_logo_bytes(),
        TRANSPARENT_LIGHT_LOGO_PATH: transparent_light_logo_bytes(),
        SHARE_CARD_PATH: card_bytes(),
    }


def chrome_release(registry: ThemeRegistry, digest) -> dict:
    """The chrome facts a site release record carries: version plus per-asset hash."""
    assets = chrome_assets(registry)
    return {
        "version": CHROME_VERSION,
        "theme_registry_version": registry.schema_version,
        "assets": {path: digest(payload) for path, payload in sorted(assets.items())},
    }


def verify_chrome_release(root, release: Mapping, digest) -> None:
    """Check a deployed tree still carries exactly the chrome bytes its release names."""
    declared = (release or {}).get("assets") or {}
    for path, expected in sorted(declared.items()):
        target = root / path
        if not target.is_file():
            raise ArtifactError(f"release chrome asset is missing from production: {path}")
        if digest(target.read_bytes()) != expected:
            raise ArtifactError(f"release chrome asset bytes changed: {path}")
