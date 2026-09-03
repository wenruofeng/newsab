"""The social card is a constant, and every allowed identity can reproduce it."""

import importlib.util
from pathlib import Path

from newsab_publish import chrome
from newsab_publish.themes import load_theme_registry
from newsab_publish.social_card import (
    ASSET_PATH,
    ASSET_URL,
    HEIGHT,
    WIDTH,
    card_bytes,
    decode_png,
    encode_png,
    render_pixels,
)


def test_the_shipped_card_is_exactly_what_the_renderer_draws():
    """Compare decoded pixels, not compressed bytes.

    Deflate output is not stable across zlib builds, so re-encoding would make this test
    a host check rather than a drawing check.  Decoding is exact everywhere, which is
    also why the card is checked in rather than generated during a build: the deployed
    asset must be the same bytes on every host that rebuilds the site.
    """
    width, height, pixels = decode_png(card_bytes())
    assert (width, height) == (WIDTH, HEIGHT)
    production_pixels = bytes(render_pixels())
    if pixels == production_pixels:
        return

    # A public export deliberately replaces the production mark with an original neutral
    # placeholder.  Its definition source is copied beside the exporter, so a mismatch is
    # accepted only when those checked-in neutral pixels reproduce it exactly.
    repo = Path(__file__).resolve().parents[3]
    candidates = (
        repo / "tools/generate_neutral_assets.py",
        repo / "public/neutral/generate_assets.py",
    )
    generator = next((path for path in candidates if path.is_file()), None)
    assert generator is not None, "shipped card matches neither renderer nor neutral source"
    spec = importlib.util.spec_from_file_location("neutral_card_generator", generator)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert pixels == decode_png(module.build_png())[2]


def test_the_drawing_is_deterministic_and_the_card_is_a_png_no_platform_refuses():
    assert bytes(render_pixels()) == bytes(render_pixels())
    payload = card_bytes()
    assert payload.startswith(b"\x89PNG\r\n\x1a\n")
    # 1200x630 is the size every platform documents for a large summary card.
    assert decode_png(encode_png(bytes(render_pixels())))[:2] == (1200, 630)


def test_the_card_is_a_chrome_asset_at_a_stable_url():
    """It is site dressing, so shipping it never touches an approved content document."""
    assets = chrome.chrome_assets(load_theme_registry())
    assert assets[ASSET_PATH] == card_bytes()
    assert ASSET_URL == "/assets/share-card.png"
