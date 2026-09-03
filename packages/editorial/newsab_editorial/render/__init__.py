"""Reader-page rendering, one module per concern.

``page_render.py`` was a single 2 200-line file holding the strings, the stylesheet, the
script and every section of the page.  The rebuild roughly doubles all four, so it
is split here along the seams the page itself has: what it *says* (:mod:`strings`), how
it *looks* (:mod:`theme`), how it *behaves* (:mod:`script`), and one module per region —
timeline, storyline, question card, cloud, modals — assembled by :mod:`page`.
"""

from .page import render_page, sentence_load  # noqa: F401
