"""The site's legal notices as static pages: ``/{locale}/legal/privacy/``.

The notice is operator-editable Markdown under ``data/legal/`` (English authoritative,
zh-CN translation).  Only the official identity ships it — a neutral public clone does
not render the suggestion/submission forms and must not carry news-ab.com's promises, so
``data/legal/`` is not in the public export (``public_export.yaml``) and the tests that
read it are marked official-only.
The page is deliberately self-contained (inline CSS, no chrome script) so it survives
on its own like the locale fallback pages do.

The converter below is intentionally tiny: headings, paragraphs, bullet / numbered
lists, pipe tables, ``**bold**``, backtick code and ``[text](https://…)`` links.  Legal
text does not need more, and a dependency-free renderer keeps the release fingerprint a
pure function of this package and the two Markdown files.
"""

from __future__ import annotations

import html
import re
from pathlib import Path

from newsab_schema.locales import direction as locale_direction

from .identity import official_site, site_identity

#: Locales the notice is written in.  Every other locale links to the English text.
LEGAL_LOCALES: tuple[str, ...] = ("en", "zh-CN")
AUTHORITATIVE_LOCALE = "en"

_DATA = Path(__file__).with_name("data") / "legal"


def notice_locale(locale: str) -> str:
    """The notice locale a site locale reads: its own when written, else English."""
    return locale if locale in LEGAL_LOCALES else AUTHORITATIVE_LOCALE


def privacy_notice_url(locale: str) -> str:
    return f"/{notice_locale(locale)}/legal/privacy/"


def privacy_notice_source(locale: str) -> str:
    return (_DATA / f"privacy.{notice_locale(locale)}.md").read_text(encoding="utf-8")


_INLINE_LINK = re.compile(r"\[([^\]]+)\]\((https://[^)\s]+)\)")
_INLINE_BOLD = re.compile(r"\*\*(.+?)\*\*")
_INLINE_CODE = re.compile(r"`([^`]+)`")


def _inline(text: str) -> str:
    out = html.escape(text, quote=False)
    out = _INLINE_CODE.sub(lambda m: f"<code>{m.group(1)}</code>", out)
    out = _INLINE_BOLD.sub(lambda m: f"<strong>{m.group(1)}</strong>", out)
    out = _INLINE_LINK.sub(
        lambda m: f'<a href="{html.escape(m.group(2), quote=True)}" rel="noopener noreferrer">{m.group(1)}</a>',
        out,
    )
    return out


def markdown_to_html(source: str) -> str:
    """Convert the notice's restricted Markdown to HTML; unknown shapes are paragraphs."""
    blocks: list[str] = []
    lines = source.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            i += 1
            continue
        heading = re.match(r"^(#{1,3})\s+(.*)$", stripped)
        if heading:
            level = len(heading.group(1))
            blocks.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
            i += 1
            continue
        if stripped.startswith("|"):
            rows: list[list[str]] = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{3,}:?", c) for c in cells):
                    rows.append(cells)
                i += 1
            head, body = rows[0], rows[1:]
            thead = "".join(f"<th>{_inline(c)}</th>" for c in head)
            tbody = "".join(
                "<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in row) + "</tr>" for row in body
            )
            blocks.append(
                '<div class="tablewrap"><table><thead><tr>'
                f"{thead}</tr></thead><tbody>{tbody}</tbody></table></div>"
            )
            continue
        bullet = re.match(r"^[-*]\s+(.*)$", stripped)
        numbered = re.match(r"^\d+\.\s+(.*)$", stripped)
        if bullet or numbered:
            tag = "ul" if bullet else "ol"
            pattern = r"^[-*]\s+(.*)$" if bullet else r"^\d+\.\s+(.*)$"
            items: list[str] = []
            while i < len(lines):
                item = re.match(pattern, lines[i].strip())
                if not item:
                    break
                items.append(f"<li>{_inline(item.group(1))}</li>")
                i += 1
            blocks.append(f"<{tag}>{''.join(items)}</{tag}>")
            continue
        paragraph = [stripped]
        i += 1
        while i < len(lines):
            nxt = lines[i].strip()
            if not nxt or nxt.startswith(("#", "|", "- ", "* ")) or re.match(r"^\d+\.\s", nxt):
                break
            paragraph.append(nxt)
            i += 1
        blocks.append(f"<p>{_inline(' '.join(paragraph))}</p>")
    return "\n".join(blocks)


_STYLE = (
    ":root{color-scheme:light dark;--ink:#18201d;--muted:#5d655f;--line:#d9d8d0;--bg:#f7f5ef;--panel:#fff;--link:#1f5fa8}"
    "@media(prefers-color-scheme:dark){:root{--ink:#e8e6df;--muted:#a9ada6;--line:#3a3d39;--bg:#151715;--panel:#1d201d;--link:#8fbcf0}}"
    "*{box-sizing:border-box}html{font:16px/1.65 system-ui,-apple-system,'Segoe UI',Roboto,'Noto Sans','Noto Sans CJK SC','Noto Sans SC',sans-serif;color:var(--ink);background:var(--bg)}"
    "body{margin:0}.chrome{display:flex;align-items:center;gap:.75rem;flex-wrap:wrap;padding:max(.75rem,env(safe-area-inset-top)) max(1rem,env(safe-area-inset-right)) .75rem max(1rem,env(safe-area-inset-left));border-bottom:1px solid var(--line);background:var(--panel)}"
    ".brand{font-weight:750;margin-right:auto;text-decoration:none;color:inherit}[dir=rtl] .brand{margin-right:0;margin-left:auto}"
    ".chrome a{display:inline-flex;align-items:center;min-height:44px;color:inherit}.chrome nav a{margin-inline-start:.75rem}"
    "main{max-width:44rem;margin:0 auto;padding:1.5rem max(1rem,env(safe-area-inset-right)) 4rem max(1rem,env(safe-area-inset-left))}"
    "h1{font-size:1.75rem;line-height:1.25;margin:.5rem 0 1rem}h2{font-size:1.25rem;margin:2rem 0 .5rem;padding-top:1rem;border-top:1px solid var(--line)}h3{font-size:1.05rem;margin:1.25rem 0 .35rem}"
    "p,li{overflow-wrap:anywhere}ul,ol{padding-inline-start:1.4rem}li{margin:.25rem 0}a{color:var(--link)}code{font-size:.9em;padding:.05em .3em;border:1px solid var(--line);border-radius:.25rem}"
    ".tablewrap{overflow-x:auto;margin:1rem 0}table{border-collapse:collapse;min-width:30rem;font-size:.95rem}th,td{text-align:start;padding:.4rem .6rem;border-bottom:1px solid var(--line);vertical-align:top}th{color:var(--muted);font-weight:600}"
    ".legal-meta{color:var(--muted);font-size:.9rem}"
)

_LANGUAGE_LABEL = {"en": "English", "zh-CN": "中文"}
_HOME_LABEL = {"en": "Home", "zh-CN": "首页"}


def render_privacy_notice(locale: str) -> str:
    """One self-contained HTML document for the notice in a written locale."""
    if locale not in LEGAL_LOCALES:
        raise ValueError(f"privacy notice is not written in {locale}")
    identity = site_identity()
    body = markdown_to_html(privacy_notice_source(locale))
    title_match = re.search(r"<h1>(.*?)</h1>", body)
    title = re.sub(r"<[^>]+>", "", title_match.group(1)) if title_match else "Privacy"
    alternates = "".join(
        f'<link rel="alternate" hreflang="{html.escape(item)}" '
        f'href="{html.escape(privacy_notice_url(item), quote=True)}">'
        for item in LEGAL_LOCALES
    )
    language_links = "".join(
        f'<a lang="{html.escape(item)}" hreflang="{html.escape(item)}" '
        f'href="{html.escape(privacy_notice_url(item), quote=True)}">{html.escape(_LANGUAGE_LABEL[item])}</a>'
        for item in LEGAL_LOCALES
        if item != locale
    )
    return (
        "<!doctype html>\n"
        f'<html lang="{html.escape(locale)}" dir="{html.escape(locale_direction(locale))}"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<link rel="canonical" href="{html.escape(privacy_notice_url(locale), quote=True)}">{alternates}'
        f"<title>{title} · {html.escape(identity.site_name)}</title>"
        f"<style>{_STYLE}</style></head><body>"
        f'<header class="chrome"><a class="brand" href="/{html.escape(locale)}/">{html.escape(identity.site_name)}</a>'
        f'<nav><a href="/{html.escape(locale)}/">{html.escape(_HOME_LABEL[locale])}</a>{language_links}</nav></header>'
        f"<main>{body}</main></body></html>\n"
    )


def legal_pages() -> dict[str, bytes]:
    """Release-relative path → bytes for every legal page the identity ships."""
    if not official_site():
        return {}
    return {
        f"{locale}/legal/privacy/index.html": render_privacy_notice(locale).encode("utf-8")
        for locale in LEGAL_LOCALES
    }
