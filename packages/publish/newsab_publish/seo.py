"""Pure sitemap.xml and robots.txt rendering for a closed production catalog."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Iterable
from urllib.parse import urlsplit
from xml.sax.saxutils import escape, quoteattr

from newsab_schema import CatalogRecord

from .metadata import SiteMetadata


def _site_origin(base_url: str) -> str:
    value = base_url.rstrip("/")
    split = urlsplit(value)
    if split.scheme not in {"http", "https"} or not split.netloc:
        raise ValueError("base_url must be an absolute HTTP(S) origin")
    if split.path not in {"", "/"} or split.query or split.fragment:
        raise ValueError("base_url must not contain a path, query or fragment")
    return value


def _absolute(origin: str, root_relative_url: str) -> str:
    if not root_relative_url.startswith("/") or root_relative_url.startswith("//"):
        raise ValueError(f"site URL must be root-relative: {root_relative_url}")
    return origin + root_relative_url


def _url_entry(
    location: str,
    last_modified: date,
    alternates: list[tuple[str, str]],
) -> str:
    alternate_xml = "".join(
        f'<xhtml:link rel="alternate" hreflang={quoteattr(locale)} href={quoteattr(url)}/>'
        for locale, url in alternates
    )
    return (
        f"<url><loc>{escape(location)}</loc><lastmod>{last_modified.isoformat()}</lastmod>"
        f"{alternate_xml}</url>"
    )


def render_sitemap(
    records: Iterable[CatalogRecord],
    *,
    metadata: SiteMetadata,
    base_url: str,
    build_date: date,
) -> str:
    """Render stable URL order with alternate links only for locales that exist."""

    origin = _site_origin(base_url)
    rows = list(records)
    page_urls = [record.page_url for record in rows]
    if len(page_urls) != len(set(page_urls)):
        raise ValueError("catalog contains duplicate page URLs")

    by_publication: dict[str, list[CatalogRecord]] = defaultdict(list)
    for record in rows:
        if record.locale not in metadata.locales:
            raise ValueError(f"catalog locale absent from site metadata: {record.locale}")
        by_publication[record.publication_id].append(record)

    entries: list[tuple[str, date, list[tuple[str, str]]]] = []
    home_alternates = [
        (locale, _absolute(origin, f"/{locale}/")) for locale in sorted(metadata.locales)
    ]
    for locale in metadata.locales:
        entries.append((_absolute(origin, f"/{locale}/"), build_date, home_alternates))

    for publication_id in sorted(by_publication):
        publication_rows = by_publication[publication_id]
        locales = [row.locale for row in publication_rows]
        if len(locales) != len(set(locales)):
            raise ValueError(f"{publication_id}: duplicate catalog locale")
        alternates = sorted(
            (row.locale, _absolute(origin, row.page_url)) for row in publication_rows
        )
        for row in publication_rows:
            entries.append(
                (
                    _absolute(origin, row.page_url),
                    row.published_at.date(),
                    alternates,
                )
            )

    body = "".join(
        _url_entry(location, last_modified, alternates)
        for location, last_modified, alternates in sorted(entries, key=lambda item: item[0])
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
        f'xmlns:xhtml="http://www.w3.org/1999/xhtml">{body}</urlset>\n'
    )


def render_robots(*, base_url: str) -> str:
    """Render the public site's literal crawler policy and absolute sitemap URL."""

    origin = _site_origin(base_url)
    return f"User-agent: *\nAllow: /\n\nSitemap: {origin}/sitemap.xml\n"
