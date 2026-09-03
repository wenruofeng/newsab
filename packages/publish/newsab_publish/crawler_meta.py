"""Crawler metadata is resolved at release time; a content document never names an origin.

Two facts a social crawler needs are not facts the user approves:

* **the origin.** ``og:url`` and ``og:image`` must be absolute — no crawler resolves a
  relative one — but the site's origin is a release fact (moving it is a rebuild, not a
  re-approval of any page).  Baking a production origin into candidate bytes
  would make every human approval origin-bound, so the content document keeps stating
  root-relative URLs and the release resolves them.
* **which image a crawler can actually render.** Publications up to ``publish-0.7.0``
  shipped per-angle SVG cards, and no platform renders SVG as a card image, so the
  release points the crawler at the site's PNG card instead.  A newer publication names
  that PNG itself, and the same rewrite makes it absolute.  The per-angle facts
  travel in ``og:title`` / ``og:description``, which the share landing pages state per
  angle.

The browser icon is site furniture for the same reason: a topic approval does not bind
the site's logo.  The release therefore adds the stable chrome-owned favicon link without
changing the approved content document.

So this is the deployed page = approved page ⊕ release facts.  The rewrite is narrow,
deterministic and refuses anything it does not recognise, and ``verify_site`` re-checks
every deployed page against ``resolve(bundle bytes)``, which is what keeps the difference
between the two auditable rather than assumed.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from newsab_schema.io import ArtifactError

from .brand import ASSET_URL as LOGO_URL
from .identity import site_identity
from .social_card import ASSET_URL


SITE_NAME = site_identity().site_name
ICON_LINK = f'<link rel="icon" type="image/svg+xml" href="{LOGO_URL}">'

_HEAD = re.compile(r"</head>", re.IGNORECASE)
_ICON = re.compile(r'<link rel="icon"(?: [^>]*)?>', re.IGNORECASE)
_CANONICAL = re.compile(r'<link rel="canonical" href="(?P<url>[^"]*)">')
_META = re.compile(
    r'<meta (?P<kind>property|name)="(?P<key>og:[a-z_:]+|twitter:[a-z_]+)" '
    r'content="(?P<value>[^"]*)">'
)
#: Every key whose value is a URL the release must make absolute.
_URL_KEYS = ("og:url", "og:image", "twitter:image")


def site_origin(base_url: str) -> str:
    value = base_url.rstrip("/")
    split = urlsplit(value)
    if split.scheme not in {"http", "https"} or not split.netloc:
        raise ArtifactError("base_url must be an absolute HTTP(S) origin")
    if split.path not in {"", "/"} or split.query or split.fragment:
        raise ArtifactError("base_url must not contain a path, query or fragment")
    return value


def _absolute(origin: str, url: str, key: str) -> str:
    if not url.startswith("/") or url.startswith("//"):
        raise ArtifactError(f"{key} must be root-relative before release resolves it: {url}")
    return origin + url


def resolve(markup: bytes, *, base_url: str) -> bytes:
    """Resolve one deployed page's site-owned head facts."""
    origin = site_origin(base_url)
    text = markup.decode("utf-8")
    head_end = _HEAD.search(text)
    if head_end is None:
        return markup
    head, rest = text[: head_end.start()], text[head_end.start() :]
    if _ICON.search(head):
        head = _ICON.sub(ICON_LINK, head, count=1)
    else:
        head += ICON_LINK
    if 'property="og:' not in head:
        return (head + rest).encode("utf-8")

    canonical = _CANONICAL.search(head)
    seen: set[str] = set()

    def rewrite(match: re.Match) -> str:
        key = match.group("key")
        value = match.group("value")
        seen.add(key)
        if key == "og:image":
            return f'<meta property="og:image" content="{origin}{ASSET_URL}">'
        if key == "og:image:type":
            return '<meta property="og:image:type" content="image/png">'
        if key == "twitter:card":
            return '<meta name="twitter:card" content="summary_large_image">'
        if key in _URL_KEYS:
            return (
                f'<meta {match.group("kind")}="{key}" '
                f'content="{_absolute(origin, value, key)}">'
            )
        return match.group(0)

    head = _META.sub(rewrite, head)
    additions = []
    if "og:url" not in seen:
        if canonical is None:
            raise ArtifactError("a page stating Open Graph metadata must state a canonical URL")
        additions.append(
            f'<meta property="og:url" content="{_absolute(origin, canonical.group("url"), "og:url")}">'
        )
    if "og:site_name" not in seen:
        additions.append(f'<meta property="og:site_name" content="{SITE_NAME}">')
    if "og:image" not in seen:
        additions.append(f'<meta property="og:image" content="{origin}{ASSET_URL}">')
    if "og:image:type" not in seen:
        additions.append('<meta property="og:image:type" content="image/png">')
    if "og:image:width" not in seen:
        additions.append(
            '<meta property="og:image:width" content="1200">'
            '<meta property="og:image:height" content="630">'
        )
    if "twitter:card" not in seen:
        additions.append('<meta name="twitter:card" content="summary_large_image">')
    if "twitter:image" not in seen:
        additions.append(f'<meta name="twitter:image" content="{origin}{ASSET_URL}">')
    return (head + "".join(additions) + rest).encode("utf-8")


def check_resolved(markup: bytes, *, base_url: str, label: str) -> None:
    """Assert one deployed page carries crawler metadata a platform can actually use."""
    origin = site_origin(base_url)
    text = markup.decode("utf-8")
    head_end = _HEAD.search(text)
    head = text if head_end is None else text[: head_end.start()]
    if head_end is not None and ICON_LINK not in head:
        raise ArtifactError(f"{label}: released page does not link the site favicon")
    if 'property="og:' not in head:
        return
    found = {match.group("key"): match.group("value") for match in _META.finditer(head)}
    for key in _URL_KEYS:
        value = found.get(key)
        if value is None:
            raise ArtifactError(f"{label}: {key} is missing from the released page")
        if not value.startswith(origin + "/"):
            raise ArtifactError(f"{label}: {key} is not absolute under the site origin: {value}")
    if found.get("og:image") != origin + ASSET_URL:
        raise ArtifactError(f"{label}: og:image is not the site card: {found.get('og:image')}")
    if found.get("og:image:type") != "image/png":
        raise ArtifactError(f"{label}: og:image:type is not image/png")
    if found.get("twitter:card") != "summary_large_image":
        raise ArtifactError(f"{label}: twitter:card is not summary_large_image")
