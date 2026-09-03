"""Comparison-time Han script fold: traditional -> simplified, for cluster fingerprints.

A traditional-script reprint of a simplified-script story (or vice versa) is the same
reporting, but character shingles share almost nothing across the two scripts — the
measured case sat at 0.052 containment against a 0.60 threshold.  Folding both sides to
simplified before shingling makes such pairs cluster; the fold is applied **only** inside
the similarity computation, never to stored text, so verbatim evidence stays in the
source's own script.

Character-level is enough here.  Traditional->simplified is many-to-one at the character
level (發/髮 -> 发), which is exactly what a fingerprint fold wants; the folded text is
never displayed, so the rare wrong pick on an ambiguous character (乾隆 -> 干隆) costs
nothing.  Regional vocabulary (軟體/软件) is left unfolded — a mostly-verbatim reprint
clears the threshold on its identical sentences regardless.

The table is frozen in :mod:`newsab_corpus.han_fold_data` (regenerate only via
``tools/gen_han_fold_data.py``) so a reader re-running the clusterer from this repo gets
byte-identical results — no third-party converter whose data shifts between versions.
Every run record names the fold it used (``cluster_han_fold``); runs from before the
fold carry ``None`` and stay re-derivable by not folding.
"""

from __future__ import annotations

from .han_fold_data import T2S_TABLE

#: Recorded in each corpus run record.  Bump when the table or the fold rule changes —
#: the version names the behaviour, and published cluster counts pin it.
HAN_FOLD_VERSION = "t2s-cn-v1"

#: Corner brackets are the traditional-script quotation convention; fold them onto the
#: curly quotes simplified-script text uses so a quoted phrase still shingles alike.
#: (OpenCC's table covers characters only, not punctuation.)
_TABLE = {**T2S_TABLE, **str.maketrans("「」『』", "“”‘’")}


def fold_han(text: str) -> str:
    """Fold ``text`` to simplified script for fingerprinting.  Not for display."""
    return text.translate(_TABLE)
