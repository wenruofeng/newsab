"""Site-owned identity loaded from versioned package data.

The private operating repository ships its own identity file.  The one-way public
export maps a neutral definition source to the same package-data path, so generic code
never needs a brand or operator baked into Python literals.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator

from newsab_schema.common import normalize_lang


class SiteIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    identity_version: str = Field(pattern=r"^site-identity-\d+\.\d+\.\d+$")
    site_name: str = Field(min_length=1)
    domain_label: str = Field(min_length=1)
    dashboard_title: str = Field(min_length=1)
    #: Per-locale maps, keyed by BCP-47 locale.  This model does not know which locales
    #: must be present — that is ``SITE_LOCALES``, a publish-layer decision this module
    #: cannot import without a circular dependency (``site_strings`` imports *this*
    #: module) — so ``newsab_publish.site_strings`` asserts coverage once both are
    #: loaded.  A locale beyond that set is allowed to sit here already — the halo's other
    #: seven were added without touching this shape again.
    contact: dict[str, str] = Field(min_length=1)
    tagline: dict[str, str] = Field(min_length=1)
    about: dict[str, str] = Field(min_length=1)

    @field_validator("contact", "tagline", "about")
    @classmethod
    def _normalized_locale_map(cls, value: dict[str, str]) -> dict[str, str]:
        out: dict[str, str] = {}
        for locale, text in value.items():
            stripped = str(text).strip()
            if not stripped:
                raise ValueError(f"empty entry for locale {locale!r}")
            out[normalize_lang(locale)] = stripped
        return out


def default_identity_path() -> Path:
    return Path(__file__).parent / "data" / "site_identity.v1.json"


@lru_cache(maxsize=8)
def load_site_identity(path: str | Path | None = None) -> SiteIdentity:
    identity_path = Path(path) if path is not None else default_identity_path()
    return SiteIdentity.model_validate(json.loads(identity_path.read_text(encoding="utf-8")))


def site_identity() -> SiteIdentity:
    return load_site_identity()


#: The one domain whose builds carry the official brand art and intake entrance.  The
#: public export maps a neutral identity onto the same package-data path, so everything
#: keyed on this stays out of public-toolkit builds without a second switch.
OFFICIAL_DOMAIN_LABEL = "news-ab.com"


def official_site() -> bool:
    """True only under the official identity; a public clone's neutral identity fails it."""
    return site_identity().domain_label == OFFICIAL_DOMAIN_LABEL
