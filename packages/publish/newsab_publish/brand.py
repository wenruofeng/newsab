"""Reusable site-brand artwork shipped by the chrome release."""

from __future__ import annotations

from pathlib import Path


ASSET_PATH = "assets/favicon.svg"
ASSET_URL = f"/{ASSET_PATH}"
TRANSPARENT_LIGHT_ASSET_PATH = "assets/logo-transparent-light.svg"
TRANSPARENT_LIGHT_ASSET_URL = f"/{TRANSPARENT_LIGHT_ASSET_PATH}"
TRANSPARENT_DARK_ASSET_PATH = "assets/logo-transparent-dark.svg"
TRANSPARENT_DARK_ASSET_URL = f"/{TRANSPARENT_DARK_ASSET_PATH}"


def asset_path() -> Path:
    return Path(__file__).resolve().parent / "data" / "favicon.svg"


def logo_bytes() -> bytes:
    """Return the checked-in vector mark used by browsers and site furniture."""
    return asset_path().read_bytes()


def transparent_light_asset_path() -> Path:
    return Path(__file__).resolve().parent / "data" / "logo-transparent-light.svg"


def transparent_light_logo_bytes() -> bytes:
    """Return the flat foreground mark for light chrome surfaces."""
    return transparent_light_asset_path().read_bytes()


def transparent_dark_asset_path() -> Path:
    return Path(__file__).resolve().parent / "data" / "logo-transparent-dark.svg"


def transparent_dark_logo_bytes() -> bytes:
    """Return the flat foreground mark for dark chrome surfaces."""
    return transparent_dark_asset_path().read_bytes()
