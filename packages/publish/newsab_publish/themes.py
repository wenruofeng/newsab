"""Controlled topic-theme tokens and their deterministic accessibility gate.

Publications carry one opaque ``theme_token``.  The token resolves through this
site-owned registry; submissions never supply colours, CSS or component parameters.
The relationship colours (A/B, supported/weak/unsupported) are intentionally absent
from this contract and therefore cannot be changed by a topic theme.

Since the content/chrome split the colours behind a token are emitted once into the site
stylesheet (``newsab_publish.chrome.theme_token_css``) rather than inlined per page: the
page states its token, the chrome layer answers with the palette.
"""

from __future__ import annotations

import html
import json
from pathlib import Path
from types import MappingProxyType
from typing import Iterable, Literal, Mapping

from pydantic import Field, field_validator, model_validator

from newsab_schema import Record

from .identity import site_identity
from .site_strings import SITE_LOCALES


MIN_TEXT_CONTRAST = 4.5
_LIGHT_PAPER = "#FBFAF7"
_DARK_PAPER = "#171B20"


class ThemeDefinition(Record):
    token: str = Field(pattern=r"^[a-z][a-z0-9-]{0,31}$")
    labels: dict[str, str]
    accent_light: str = Field(pattern=r"^#[0-9A-F]{6}$")
    accent_dark: str = Field(pattern=r"^#[0-9A-F]{6}$")
    default_mode: Literal["system", "light", "dark"] = "system"
    decoration: Literal["plain", "fine-rule"] = "plain"

    @field_validator("labels")
    @classmethod
    def _labels(cls, value: dict[str, str]) -> dict[str, str]:
        # The floor a *record* must meet is the two languages the chooser itself is
        # written in (``render_theme_panel``).  Coverage of the site's current locale set
        # is deliberately **not** checked here: every publication archives the exact
        # registry bytes it was built with, and ``verify-candidate`` re-validates those
        # historical bytes.  A model-level SITE_LOCALES rule would therefore invalidate
        # every past publication the day the site learns a language — a
        # verification failure that says nothing about the archive it flagged.  The live
        # registry is held to the site set in :func:`load_theme_registry`, and the set a
        # publication actually ships is checked against its theme in ``prepare``.
        missing = sorted({"en", "zh-CN"} - set(value))
        if missing:
            raise ValueError(f"theme labels must name the theme in {missing}")
        if any(not label.strip() for label in value.values()):
            raise ValueError("theme labels must not be blank")
        return value

    @model_validator(mode="after")
    def _accessible_accents(self) -> "ThemeDefinition":
        light = contrast_ratio(self.accent_light, _LIGHT_PAPER)
        dark = contrast_ratio(self.accent_dark, _DARK_PAPER)
        if light < MIN_TEXT_CONTRAST or dark < MIN_TEXT_CONTRAST:
            raise ValueError(
                f"theme {self.token!r} fails {MIN_TEXT_CONTRAST:g}:1 accent contrast "
                f"(light={light:.2f}, dark={dark:.2f})"
            )
        return self


class ThemeRegistry(Record):
    schema_version: str = Field(pattern=r"^theme-tokens-\d+\.\d+\.\d+$")
    default_token: str
    themes: list[ThemeDefinition] = Field(min_length=1)

    @model_validator(mode="after")
    def _controlled(self) -> "ThemeRegistry":
        tokens = [theme.token for theme in self.themes]
        if len(tokens) != len(set(tokens)):
            raise ValueError("theme registry repeats a token")
        if self.default_token not in tokens:
            raise ValueError("default theme token is absent from the registry")
        return self


def _channel(value: int) -> float:
    normalized = value / 255
    return normalized / 12.92 if normalized <= 0.04045 else ((normalized + 0.055) / 1.055) ** 2.4


def relative_luminance(value: str) -> float:
    if len(value) != 7 or not value.startswith("#"):
        raise ValueError(f"colour must be #RRGGBB: {value!r}")
    try:
        red, green, blue = (int(value[offset : offset + 2], 16) for offset in (1, 3, 5))
    except ValueError as exc:
        raise ValueError(f"colour must be #RRGGBB: {value!r}") from exc
    return 0.2126 * _channel(red) + 0.7152 * _channel(green) + 0.0722 * _channel(blue)


def contrast_ratio(first: str, second: str) -> float:
    high, low = sorted((relative_luminance(first), relative_luminance(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def default_theme_registry_path() -> Path:
    return Path(__file__).with_name("data") / "theme_tokens.v1.json"


def check_theme_labels(theme: ThemeDefinition, locales: Iterable[str]) -> None:
    """Refuse a theme that cannot name itself in a language the page will ship in."""
    missing = sorted(set(locales) - set(theme.labels))
    if missing:
        raise ValueError(
            f"theme {theme.token!r} has no label for {missing}: add them to the theme "
            "registry before shipping these languages"
        )


def load_theme_registry(path: str | Path | None = None) -> ThemeRegistry:
    """Load a registry; the *live* one must also speak every current site locale.

    A path names an archived registry — the exact bytes some past publication was built
    with — and is loaded as written, because re-validating history against today's locale
    set is how a verifier starts failing on archives that were correct when made.  The
    default path is the live registry, which is the one a new build will render from, so
    that one is held to ``SITE_LOCALES`` here rather than silently rendering a theme
    switcher with a missing label.
    """
    if path is not None:
        return ThemeRegistry.model_validate_json(
            Path(path).read_text(encoding="utf-8")
        )
    registry = ThemeRegistry.model_validate_json(
        default_theme_registry_path().read_text(encoding="utf-8")
    )
    for theme in registry.themes:
        check_theme_labels(theme, SITE_LOCALES)
    return registry


def theme_map(registry: ThemeRegistry) -> Mapping[str, ThemeDefinition]:
    return MappingProxyType({theme.token: theme for theme in registry.themes})


def resolve_theme(token: str | None, registry: ThemeRegistry) -> ThemeDefinition:
    selected = token or registry.default_token
    try:
        return theme_map(registry)[selected]
    except KeyError as exc:
        raise ValueError(f"unknown theme token: {selected!r}") from exc


def render_theme_panel(registry: ThemeRegistry) -> str:
    """Render a local visual chooser whose output is a schema-valid token only."""
    identity = site_identity()
    cards = []
    for theme in registry.themes:
        cards.append(
            f'<label class="card" style="--light:{theme.accent_light};--dark:{theme.accent_dark}">'
            f'<input type="radio" name="theme" value="{html.escape(theme.token)}"'
            f'{" checked" if theme.token == registry.default_token else ""}>'
            '<span class="swatches" aria-hidden="true"><i></i><i></i></span>'
            f'<strong>{html.escape(theme.labels["zh-CN"])}</strong>'
            f'<small>{html.escape(theme.labels["en"])} · {html.escape(theme.token)}</small></label>'
        )
    registry_json = json.dumps(
        [theme.token for theme in registry.themes], ensure_ascii=True, separators=(",", ":")
    )
    return (
        '<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>{html.escape(identity.site_name)} theme tokens</title><style>'
        ':root{font:16px/1.5 system-ui;color:#18201d;background:#f7f5ef}*{box-sizing:border-box}'
        'main{width:min(56rem,calc(100% - 2rem));margin:3rem auto}fieldset{border:0;padding:0}'
        '.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(12rem,1fr));gap:1rem}'
        '.card{display:grid;gap:.5rem;background:white;border:2px solid #d9d8d0;border-radius:1rem;padding:1rem;cursor:pointer}'
        '.card:has(input:checked){border-color:#18201d}.swatches{display:grid;grid-template-columns:1fr 1fr;height:5rem;border-radius:.5rem;overflow:hidden}'
        '.swatches i:first-child{background:var(--light)}.swatches i:last-child{background:var(--dark)}'
        '.card small{color:#626a66}output{display:block;margin-top:1.5rem;padding:1rem;background:#18201d;color:white;border-radius:.5rem;font-family:monospace;white-space:pre-wrap}'
        'input{width:1.25rem;height:1.25rem}@media(max-width:480px){main{margin:1.5rem auto}.card{min-height:11rem}}'
        '</style><main><h1>议题主题 token</h1><p>选择面板只会输出受控 token；颜色、布局与脚本不能由投稿者提交。</p>'
        f'<fieldset><legend>Theme</legend><div class="grid">{"".join(cards)}</div></fieldset>'
        '<output id="out"></output><script>'
        f'const allowed=new Set({registry_json});const out=document.getElementById("out");'
        'function draw(){const value=document.querySelector("input:checked").value;'
        'if(!allowed.has(value))throw new Error("invalid theme token");'
        'out.textContent=JSON.stringify({theme_token:value},null,2)}'
        'document.addEventListener("change",draw);draw();</script></main></html>\n'
    )
