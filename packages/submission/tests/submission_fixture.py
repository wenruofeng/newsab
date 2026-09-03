"""Test helpers: the public synthetic closure plus deterministic pack parameters.

Lives beside ``conftest.py`` (not inside it) so test modules can import the helpers
directly — the same pattern as the repo-level ``pipeline_fixture``.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "examples" / "synthetic-topic"))

import demo_fixture as fx  # noqa: E402

from newsab_submission.pack import pack  # noqa: E402

FIXED_SUBMISSION_ID = "SUB-00c0ffee00c0ffee"
FIXED_CREATED_AT = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)


def build_tree(root: Path):
    """The synthetic topics/ + sources/ tree inside ``root``; returns TopicPaths."""
    return fx.build_topic(root / "topics")


#: The synthetic page is written in exactly these two languages, so this is what a
#: submission built from it can request — not today's whole ``SITE_LOCALES``, which grows
#: with the site and would make the fixture fail ``required_langs`` for languages
#: it was never localized into.
FIXTURE_LOCALES = ("en", "zh-CN")


def pack_fixture(tree_root: Path, out: Path, **overrides) -> dict:
    kwargs = dict(
        submission_id=FIXED_SUBMISSION_ID,
        created_at=FIXED_CREATED_AT,
        requested_locales=FIXTURE_LOCALES,
    )
    kwargs.update(overrides)
    return pack(tree_root / "topics", fx.TOPIC_ID, out, **kwargs)
