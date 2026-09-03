"""``SiteIdentity``'s tagline/about/contact fields are per-locale maps.

The checked-in ``site_identity.v1.json`` files (private ``data/`` and the public
``public/neutral/`` mirror) are exercised end-to-end by every other test importing
``newsab_publish`` — ``site_strings.py`` asserts at import time that they cover
``SITE_LOCALES`` — so this file only covers the model's own validation rules.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from newsab_publish.identity import SiteIdentity


def _payload(**overrides: dict) -> dict:
    base = {
        "identity_version": "site-identity-1.0.0",
        "site_name": "Test Site",
        "domain_label": "test.example",
        "dashboard_title": "Test Dashboard",
        "contact": {"en": "hello@example.com", "zh-CN": "hello@example.com"},
        "tagline": {"en": "One story, two tellings", "zh-CN": "横看成岭侧成峰"},
        "about": {"en": "About.", "zh-CN": "关于。"},
    }
    base.update(overrides)
    return base


def test_minimal_en_zh_cn_identity_validates():
    identity = SiteIdentity.model_validate(_payload())
    assert identity.tagline["en"] == "One story, two tellings"
    assert identity.tagline["zh-CN"] == "横看成岭侧成峰"


def test_a_locale_map_may_carry_more_than_site_locales():
    # The halo's other seven languages can be added to these maps without this model
    # needing to change again.
    identity = SiteIdentity.model_validate(
        _payload(tagline={**_payload()["tagline"], "fr": "Chacun voit midi à sa porte"})
    )
    assert identity.tagline["fr"] == "Chacun voit midi à sa porte"


def test_locale_keys_are_normalized():
    identity = SiteIdentity.model_validate(
        _payload(contact={"en": "hello@example.com", "zh-cn": "hello@example.com"})
    )
    assert "zh-CN" in identity.contact
    assert "zh-cn" not in identity.contact


def test_blank_entry_is_refused():
    with pytest.raises(ValidationError, match="empty entry"):
        SiteIdentity.model_validate(_payload(about={"en": "About.", "zh-CN": "   "}))
