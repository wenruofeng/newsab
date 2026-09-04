#!/usr/bin/env python3
"""Build the localization judge's entire input for one target language, as text.

A site language the reviewer cannot read never reaches a human: its only quality gate is
the AI check this packet feeds (`skills/publish/references/localization.md`).  The check
is a comparison against the English pivot — the canonical, mechanically recomputable
master (V-5) — so the packet is the complete set of pivot↔target pairs the page carries,
each labelled with where on the page it lives.

The packet is derived from `page.json` alone: every reader-facing string is a language
map inside it, so the pairs are enumerated by walking the artifact rather than by a field
list that would go stale.  Quote *originals* are source-language sentences resolved from
the corpus at render time and are not in the page; for those the pair is the English
translation ↔ the target translation, and the packet says so.

Completeness is not this check's job: `page-check --langs` refuses a missing translation
mechanically before any judge runs.  A `(missing)` in the packet therefore marks a pair
the judge cannot score, not a defect it should report.

    python skills/render-localize/scripts/localization_packet.py \
        --page topics/<t>/editorial/versions/<edt>/page.json \
        --locale <target-locale> -o localization_packet.<locale>.md
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import _bootstrap  # noqa: F401

# One key convention for this stage: the location label the judge cites, the unit key a
# translator fills and the path ``apply_localization.py`` writes to are the same string.
from localization_units import angle_label as _angle_label
from localization_units import walk_lang_maps as _walk


def build_packet(page: dict, locale: str) -> str:
    pairs = _walk(page)
    lines = [
        f"# Localization packet — English pivot vs {locale}",
        "",
        f"Topic: {page.get('topic_id', '?')}  ·  page run: "
        f"{page.get('provenance', {}).get('run_id', '?')}",
        "",
        "Each entry: where it lives on the page, the English pivot text, the "
        f"{locale} text.  Judge the pair, per the rubric; the location tells you what "
        "kind of text it is (an answer label, an explanation, a caption, a lexicon "
        "label).  Entries under `lexicon.` are labels for counting keys — the English "
        "key itself is stable machinery, only its reader label is under judgement.",
        "",
    ]
    missing = 0
    for path, values in pairs:
        en = values.get("en")
        target = values.get(locale)
        if en is None and target is None:
            continue
        label = _angle_label(page, path)
        if path.endswith(".translation") or ".translation" in path:
            label += "  (both sides are translations of a source-language quote)"
        lines.append(f"## {label}")
        lines.append(f"- en: {en if en is not None else '(missing)'}")
        lines.append(f"- {locale}: {target if target is not None else '(missing)'}")
        lines.append("")
        if target is None:
            missing += 1
    lines.append("---")
    lines.append(
        f"{len(pairs)} language-carrying fields; {missing} with no "
        f"{locale} text (completeness is page-check's refusal, not yours)."
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--page", required=True, help="the localized page.json")
    parser.add_argument("--locale", required=True, help="target locale to pair with en")
    parser.add_argument("-o", "--out", required=True)
    args = parser.parse_args()

    page = json.loads(Path(args.page).read_text(encoding="utf-8"))
    if args.locale == "en":
        print("the English pivot is the master; there is nothing to judge it against", file=sys.stderr)
        return 2
    packet = build_packet(page, args.locale)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(packet, encoding="utf-8")
    print(f"{out}: {len(packet.encode('utf-8'))} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
