"""Generic helpers for adding language entries to an existing en/zh-CN literal.

The chrome catalogs (renderer strings, site copy, about/suggest modals,
theme and category labels) carry translations for the halo's other seven locales
(``newsab_schema.locales.EXTRA_HALO_LOCALES``).  Rather than typing roughly 2,300 new
dict entries by hand across five files, every one of those literals grows through the
two functions below, fed by a small versioned JSON translation table living beside each
module's other package data — the same "load a JSON, merge it in" shape ``strings.py``
already used for ``site_identity.v1.json``'s ``footer_site``.

Two catalog shapes exist in this repo and need two different functions:

- **leaf-first** (``newsab_editorial.render.strings``'s constants): every translatable
  string already sits inside its own ``{"en": ..., "zh-CN": ...}`` dict, nested anywhere
  inside dicts/lists/tuples of arbitrary shape.  ``merge_lang_leaf`` walks the *live*
  object and mutates each leaf in place, adding the new language's key.
- **locale-first** (``newsab_publish.site_strings``'s ``_STRINGS``,
  ``newsab_publish.about``'s ``_COPY``, ``newsab_publish.suggest``'s ``_COPY``): the
  outer dict is keyed by locale, and a locale's value is a plain nested structure with
  string leaves (no ``{"en": ...}`` wrapper).  A new locale is assigned wholesale, so
  there is nothing to mutate — only a shape check, which ``assert_matching_shape``
  performs against the existing ``"zh-CN"`` entry before the new locale's dict lands.

Both raise rather than silently leaving a hole: a page must never render a locale with a
missing string, and a build-time exception is far cheaper to see than a blank corner of
the site.
"""

from __future__ import annotations

from typing import Any


def merge_lang_leaf(node: Any, target: Any, lang: str) -> None:
    """Add ``lang`` to every ``{"en": ..., "zh-CN": ...}`` leaf under ``node``, in place.

    ``target`` must mirror ``node``'s shape exactly, with each leaf replaced by the
    plain translated string for ``lang``.
    """
    if isinstance(node, dict) and isinstance(node.get("en"), str) and isinstance(
        node.get("zh-CN"), str
    ):
        if not isinstance(target, str) or not target.strip():
            raise ValueError(f"missing {lang!r} translation for {node['en']!r}")
        node[lang] = target
        return
    if isinstance(node, dict):
        if not isinstance(target, dict):
            raise ValueError(f"shape mismatch merging {lang!r}: expected dict, got {type(target)}")
        missing = set(node) - set(target)
        if missing:
            raise ValueError(f"shape mismatch merging {lang!r}: target missing keys {sorted(missing)}")
        for key, value in node.items():
            merge_lang_leaf(value, target[key], lang)
        return
    if isinstance(node, (list, tuple)):
        if not isinstance(target, (list, tuple)) or len(target) != len(node):
            raise ValueError(f"shape mismatch merging {lang!r}: expected {len(node)} items")
        for item, target_item in zip(node, target):
            merge_lang_leaf(item, target_item, lang)
        return
    # A bare scalar sitting beside a leaf dict inside a container — e.g.
    # ``PROVENANCE_COUNTS``'s ``(counter_name, {"en": ..., "zh-CN": ...})`` pairs, where
    # ``counter_name`` is a stable machinery key, not translatable prose.  Nothing to
    # merge here; the container-level length/key checks above already caught any real
    # shape drift.


def assert_matching_shape(reference: Any, candidate: Any, lang: str) -> None:
    """Verify ``candidate`` mirrors ``reference``'s shape with non-blank strings at every leaf.

    For locale-first catalogs a new locale's whole entry is assigned wholesale; this
    checks the assignment is complete before it lands, so a missing key fails at build
    time, not at render.  A non-string scalar (e.g. an optional ``edge_label`` of
    ``None``) passes through unchecked — there is nothing to translate there.
    """
    if isinstance(reference, str):
        if not isinstance(candidate, str) or not candidate.strip():
            raise ValueError(f"missing {lang!r} translation for {reference!r}")
        return
    if isinstance(reference, dict):
        if not isinstance(candidate, dict):
            raise ValueError(f"shape mismatch for {lang!r}: expected dict")
        missing = set(reference) - set(candidate)
        if missing:
            raise ValueError(f"shape mismatch for {lang!r}: missing keys {sorted(missing)}")
        for key, value in reference.items():
            assert_matching_shape(value, candidate[key], lang)
        return
    if isinstance(reference, (list, tuple)):
        if not isinstance(candidate, (list, tuple)) or len(candidate) != len(reference):
            raise ValueError(f"shape mismatch for {lang!r}: expected {len(reference)} items")
        for item, cand_item in zip(reference, candidate):
            assert_matching_shape(item, cand_item, lang)
        return
    return
