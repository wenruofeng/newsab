#!/usr/bin/env python3
"""Apply a reviewed set of angle-body rewrites to a new English master.

This helper exists for targeted multi-angle rewrites: it changes only each named side's
English explanation and evidence (plus an existing joint explanation when supplied),
removes the now-stale translations of changed prose, and updates page provenance. It
refuses incomplete angle/side mappings so a bulk pass cannot silently leave old prose.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import _bootstrap  # noqa: F401

from newsab_schema.models.page import ReaderPage


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--page", required=True, help="current bilingual ReaderPage")
    ap.add_argument("--rewrites", required=True, help="reviewed rewrite mapping JSON")
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--model-id", required=True)
    ap.add_argument("--skill-version", default="write-0.14.1")
    ap.add_argument("-o", "--out", required=True)
    args = ap.parse_args(argv)

    raw = json.loads(Path(args.page).read_text(encoding="utf-8"))
    ReaderPage.model_validate(raw)
    rewrite = json.loads(Path(args.rewrites).read_text(encoding="utf-8"))
    by_rank = {int(item["rank"]): item for item in rewrite["angles"]}
    page_ranks = {int(angle["rank"]) for angle in raw["angles"]}
    if set(by_rank) != page_ranks:
        raise SystemExit(
            f"rewrite ranks {sorted(by_rank)} do not cover page ranks {sorted(page_ranks)}"
        )

    for angle in raw["angles"]:
        change = by_rank[int(angle["rank"])]
        side_changes = {item["group_id"]: item for item in change["sides"]}
        page_groups = {side["group_id"] for side in angle["sides"]}
        if set(side_changes) != page_groups:
            raise SystemExit(
                f"angle {angle['rank']}: rewrite groups {sorted(side_changes)} do not "
                f"cover page groups {sorted(page_groups)}"
            )
        for side in angle["sides"]:
            item = side_changes[side["group_id"]]
            side["answer"]["text"]["values"] = {"en": item["text"]}
            side["answer"]["evidence"] = list(item["evidence"])

        joint_change = change.get("commentary_joint")
        if angle.get("commentary_joint") is not None:
            if not joint_change:
                raise SystemExit(
                    f"angle {angle['rank']}: existing commentary_joint needs a rewrite"
                )
            angle["commentary_joint"]["text"]["values"] = {"en": joint_change["text"]}
            angle["commentary_joint"]["evidence"] = list(joint_change["evidence"])
        elif joint_change is not None:
            raise SystemExit(
                f"angle {angle['rank']}: mapping cannot create a new commentary_joint"
            )

    raw["provenance"] = {
        "skill_version": args.skill_version,
        "model_id": args.model_id,
        "run_id": args.run_id,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    page = ReaderPage.model_validate(raw)
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(page.model_dump_json(indent=2) + "\n", encoding="utf-8")
    print(f"written {target}: {len(page.angles)} complete angle rewrites")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
