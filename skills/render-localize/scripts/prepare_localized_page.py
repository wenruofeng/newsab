#!/usr/bin/env python3
"""Mint a render-localize page copy with a complete topics_raised reader lexicon.

``--locale`` names which language the ``--translations`` file localizes into and is
required: the reviewer's language is the topic manifest's ``review_locale``, and an
extend-language run targets whichever halo language it was told to.  Neither is
something this script may assume — a default here would silently write one operator's
language into another's page.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "packages" / "schema"))

from newsab_schema.common import normalize_lang  # noqa: E402
from newsab_schema.models.page import ReaderPage  # noqa: E402


def skill_version() -> str:
    text = (Path(__file__).resolve().parents[1] / "SKILL.md").read_text(encoding="utf-8")
    match = re.search(r'newsab-version:\s*"([^"]+)"', text)
    if not match:
        raise SystemExit("render-localize SKILL.md has no newsab-version")
    # ReaderPage provenance uses the shared ``name-x.y.z`` schema, while the
    # skill package itself intentionally stores only the semantic version.
    return f"renderlocalize-{match.group(1)}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--page", required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--translations")
    source.add_argument(
        "--preserve-topics",
        action="store_true",
        help="keep the page's complete existing topics lexicon for a renderer-only rerun",
    )
    parser.add_argument("--topic-id", required=True)
    parser.add_argument(
        "--locale",
        required=True,
        help="BCP-47 target locale the --translations file localizes into: the topic "
        "manifest's review_locale for a reviewer's own-language render, or the halo "
        "language an extend-language run was authorized for",
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--drop-visual-question", action="append", default=[])
    args = parser.parse_args()

    locale = normalize_lang(args.locale)
    payload = json.loads(Path(args.page).read_text(encoding="utf-8"))
    lexicon = payload.setdefault("lexicon", {})
    if args.preserve_topics:
        topic_map = lexicon.get("topics")
        if not isinstance(topic_map, dict) or not topic_map:
            raise SystemExit("page has no topics lexicon to preserve")
    else:
        translations = json.loads(Path(args.translations).read_text(encoding="utf-8"))
        topic_map = translations.get(args.topic_id)
        if not isinstance(topic_map, dict) or not topic_map:
            raise SystemExit(f"translation file has no mapping for {args.topic_id}")
        # The pivot key is the stable concept id; ``values.en`` is reader copy the write
        # stage may have reworded ("The 2016 ruling").  The translation file carries only
        # the target-language label, so the page's existing values must survive the merge
        # byte-for-byte — ``en`` falls back to the pivot only for never-worded keys.
        existing = lexicon.get("topics") or {}
        merged = {}
        for pivot, localized in sorted(topic_map.items()):
            values = dict((existing.get(pivot) or {}).get("values") or {})
            values.setdefault("en", pivot)
            values[locale] = localized
            merged[pivot] = {"values": values}
        lexicon["topics"] = merged
    dropped = set(args.drop_visual_question)
    if dropped:
        payload["visuals"] = [
            visual for visual in payload.get("visuals", [])
            if visual.get("question_id") not in dropped
        ]
    payload["provenance"] = {
        "skill_version": skill_version(),
        "model_id": args.model_id,
        "run_id": args.run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    page = ReaderPage.model_validate(payload)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page.model_dump_json(indent=2) + "\n", encoding="utf-8")
    print(f"{out}: {len(topic_map)} topics_raised labels, {len(payload.get('visuals', []))} visuals")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
