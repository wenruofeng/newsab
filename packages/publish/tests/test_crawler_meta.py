"""The release resolves crawler metadata; the content document never names an origin."""

import pytest

from newsab_publish.crawler_meta import check_resolved, resolve
from newsab_schema.io import ArtifactError


ORIGIN = "https://example.com"

TOPIC_PAGE = (
    '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
    '<link rel="canonical" href="/zh-CN/topics/aabb-market-meal-2024/">'
    '<link rel="alternate" hreflang="en" href="/en/topics/aabb-market-meal-2024/">'
    '<meta property="og:type" content="article">'
    '<meta property="og:title" content="Döner">'
    '<meta property="og:url" content="/zh-CN/topics/aabb-market-meal-2024/">'
    '<meta property="og:image" content="/zh-CN/topics/aabb-market-meal-2024/share/angle-Q001.svg">'
    '<meta property="og:image:type" content="image/svg+xml">'
    '<meta property="og:image:width" content="1200">'
    '<meta property="og:image:height" content="630">'
    "</head><body>page</body></html>"
).encode("utf-8")


def _head(markup: bytes) -> str:
    return markup.decode("utf-8").split("</head>", 1)[0]


def test_an_approved_page_gains_the_origin_and_a_card_a_platform_can_render():
    released = resolve(TOPIC_PAGE, base_url=ORIGIN)
    head = _head(released)
    assert f'<meta property="og:url" content="{ORIGIN}/zh-CN/topics/aabb-market-meal-2024/">' in head
    assert f'<meta property="og:image" content="{ORIGIN}/assets/share-card.png">' in head
    assert '<meta property="og:image:type" content="image/png">' in head
    assert '<meta name="twitter:card" content="summary_large_image">' in head
    assert f'<meta name="twitter:image" content="{ORIGIN}/assets/share-card.png">' in head
    assert '<link rel="icon" type="image/svg+xml" href="/assets/favicon.svg">' in head
    # Nothing the user approved beyond that block moves.
    assert '<meta property="og:title" content="Döner">' in head
    assert released.decode("utf-8").split("</head>", 1)[1] == "<body>page</body></html>"
    check_resolved(released, base_url=ORIGIN, label="topic")


def test_the_body_and_the_canonical_link_are_left_exactly_as_approved():
    released = resolve(TOPIC_PAGE, base_url=ORIGIN).decode("utf-8")
    assert '<link rel="canonical" href="/zh-CN/topics/aabb-market-meal-2024/">' in released
    assert '<link rel="alternate" hreflang="en" href="/en/topics/aabb-market-meal-2024/">' in released


def test_a_page_without_open_graph_gains_only_the_site_favicon():
    plain = b'<html><head><link rel="canonical" href="/zh-CN/"></head><body>x</body></html>'
    released = resolve(plain, base_url=ORIGIN)
    assert released == plain.replace(
        b"</head>",
        b'<link rel="icon" type="image/svg+xml" href="/assets/favicon.svg"></head>',
    )
    check_resolved(released, base_url=ORIGIN, label="plain")


def test_a_home_page_takes_its_og_url_from_its_canonical_link():
    home = (
        '<html><head><meta property="og:type" content="website">'
        '<meta property="og:site_name" content="Narrative Diff Toolkit">'
        '<meta name="twitter:card" content="summary">'
        '<link rel="canonical" href="/zh-CN/"></head><body></body></html>'
    ).encode("utf-8")
    released = _head(resolve(home, base_url=ORIGIN))
    assert f'<meta property="og:url" content="{ORIGIN}/zh-CN/">' in released
    assert released.count('property="og:site_name"') == 1
    assert '<meta name="twitter:card" content="summary_large_image">' in released


def test_the_legacy_inline_icon_is_replaced_not_duplicated():
    home = (
        '<html><head><meta property="og:type" content="website">'
        '<meta name="twitter:card" content="summary">'
        '<link rel="canonical" href="/zh-CN/">'
        '<link rel="icon" href="data:image/svg+xml,old"></head><body></body></html>'
    ).encode("utf-8")
    released = _head(resolve(home, base_url=ORIGIN))
    assert "data:image/svg+xml" not in released
    assert released.count('rel="icon"') == 1
    assert '<link rel="icon" type="image/svg+xml" href="/assets/favicon.svg">' in released


def test_an_origin_already_inside_the_page_is_refused_rather_than_doubled():
    """A content document must not carry an origin; finding one is a contract breach."""
    already = TOPIC_PAGE.replace(
        b'content="/zh-CN/topics/aabb-market-meal-2024/">'
        b'<meta property="og:image"',
        b'content="https://elsewhere.example/zh-CN/">'
        b'<meta property="og:image"',
    )
    with pytest.raises(ArtifactError, match="root-relative"):
        resolve(already, base_url=ORIGIN)


def test_a_bad_base_url_is_refused():
    for bad in ("example.com", "https://example.com/zh-CN", "https://example.com/?a=1"):
        with pytest.raises(ArtifactError):
            resolve(TOPIC_PAGE, base_url=bad)


def test_the_released_check_catches_an_unresolved_or_unrenderable_card():
    unresolved = TOPIC_PAGE.replace(
        b"</head>",
        b'<link rel="icon" type="image/svg+xml" href="/assets/favicon.svg"></head>',
    )
    with pytest.raises(ArtifactError, match="not absolute"):
        check_resolved(unresolved, base_url=ORIGIN, label="topic")
    released = resolve(TOPIC_PAGE, base_url=ORIGIN).replace(
        f'content="{ORIGIN}/assets/share-card.png">'.encode("utf-8"),
        f'content="{ORIGIN}/zh-CN/topics/x/share/angle-Q001.svg">'.encode("utf-8"),
        1,
    )
    with pytest.raises(ArtifactError, match="not the site card"):
        check_resolved(released, base_url=ORIGIN, label="topic")


def test_the_released_check_catches_a_missing_favicon():
    released = resolve(TOPIC_PAGE, base_url=ORIGIN).replace(
        b'<link rel="icon" type="image/svg+xml" href="/assets/favicon.svg">', b""
    )
    with pytest.raises(ArtifactError, match="does not link the site favicon"):
        check_resolved(released, base_url=ORIGIN, label="topic")
