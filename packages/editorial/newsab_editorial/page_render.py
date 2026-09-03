"""Render a ReaderPage into a self-contained HTML file.

Deterministic: page structure comes from the ``ReaderPage`` record, verbatim quote text
comes from the pinned corpus run, and every count is the one the checks recomputed —
the renderer never invents or retypes a number (it formats what the artifacts carry).

The implementation lives in :mod:`newsab_editorial.render`; this
module stays as the import path every caller and test already uses.
"""

from __future__ import annotations

from .render.common import group_meta  # noqa: F401
from .render.page import render_page, sentence_load  # noqa: F401

__all__ = ["render_page", "sentence_load", "group_meta"]
