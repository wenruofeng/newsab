"""Deterministic, public-safe site rendering helpers for value-chain stage 8."""

from .home import daily_catalog_order, render_home
from .metadata import (
    SiteCategory,
    SiteMetadata,
    TaxonomyBackfillApproval,
    default_metadata_path,
    load_site_metadata,
)
from .seo import render_robots, render_sitemap
from .site_strings import SITE_LOCALES, site_strings

__all__ = [
    "SITE_LOCALES",
    "SiteCategory",
    "SiteMetadata",
    "TaxonomyBackfillApproval",
    "daily_catalog_order",
    "default_metadata_path",
    "load_site_metadata",
    "render_home",
    "render_robots",
    "render_sitemap",
    "site_strings",
]

__version__ = "0.1.0"
