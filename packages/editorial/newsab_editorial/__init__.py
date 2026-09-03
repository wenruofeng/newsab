"""``newsab_editorial`` — the deterministic half of write (stage 5) and render (stage 6).

The writer, the mechanical checks and the renderer all need the same joined view of a
topic: which findings analyze ranked, what their counts are, which sentences may be
quoted, and which caveats must reach the page.  Assembling that is counting and joining,
so by D10 it is Python and not a prompt — and doing it once is what keeps a card, a claim
and the rendered page from quietly disagreeing about the same number.

    from newsab_editorial import check_page, render_page

    report = check_page(page, articles, findings, stats, answers=answers)  # refusals
    html = render_page(page, articles, manifest, stats, lang="zh-CN")      # the preview

Two CLI entry points, matching the two artifacts this package owns:

    python -m newsab_editorial page-check  <topics_root> <topic_id> --page … --qa-run …
    python -m newsab_editorial page-render <topics_root> <topic_id> --page … --qa-run … -o …
"""

from __future__ import annotations

__version__ = "0.2.0"

from .evidence import AnswerIndex
from .page_checks import PageCheckReport, check_page
from .page_render import render_page

__all__ = ["AnswerIndex", "PageCheckReport", "check_page", "render_page"]
