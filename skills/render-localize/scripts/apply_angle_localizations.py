#!/usr/bin/env python3
"""Add reviewed localized angle explanations to an English master.

The mapping covers every visible side explanation and every existing joint explanation.
All English text, anchors and computed fields remain untouched; validation then catches a
mapping that missed an angle or tried to change the page structure.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "packages" / "schema"))

from newsab_schema.models.page import ReaderPage  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--page", required=True)
    ap.add_argument("--translations", required=True)
    ap.add_argument(
        "--lang",
        required=True,
        help="BCP-47 locale these explanations are written in — the topic manifest's "
             "review_locale, or the halo language an extend-language run targets; "
             "never defaulted, a wrong one mislabels the page's own text",
    )
    ap.add_argument("-o", "--out", required=True)
    args = ap.parse_args(argv)

    raw = json.loads(Path(args.page).read_text(encoding="utf-8"))
    ReaderPage.model_validate(raw)
    mapping = json.loads(Path(args.translations).read_text(encoding="utf-8"))
    by_rank = {int(item["rank"]): item for item in mapping["angles"]}
    page_ranks = {int(angle["rank"]) for angle in raw["angles"]}
    if set(by_rank) != page_ranks:
        raise SystemExit(
            f"translation ranks {sorted(by_rank)} do not cover {sorted(page_ranks)}"
        )

    for angle in raw["angles"]:
        translated = by_rank[int(angle["rank"])]
        sides = {item["group_id"]: item for item in translated["sides"]}
        page_groups = {side["group_id"] for side in angle["sides"]}
        if set(sides) != page_groups:
            raise SystemExit(
                f"angle {angle['rank']}: translated groups {sorted(sides)} do not "
                f"cover {sorted(page_groups)}"
            )
        for side in angle["sides"]:
            side["answer"]["text"]["values"][args.lang] = sides[side["group_id"]]["text"]

        joint = translated.get("commentary_joint")
        if angle.get("commentary_joint") is not None:
            if not joint:
                raise SystemExit(
                    f"angle {angle['rank']}: existing commentary_joint needs localization"
                )
            angle["commentary_joint"]["text"]["values"][args.lang] = joint["text"]
        elif joint is not None:
            raise SystemExit(
                f"angle {angle['rank']}: mapping cannot create commentary_joint"
            )

    page = ReaderPage.model_validate(raw)
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(page.model_dump_json(indent=2) + "\n", encoding="utf-8")
    print(f"written {target}: {len(page.angles)} localized angle frames")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
