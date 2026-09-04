#!/usr/bin/env python3
"""Merge one language's translations back into a reader page, by unit key.

The input is the ``{key: text}`` map a translator returns for the packet
``localization_units.py`` produced — the keys are the page's own JSON paths, so the merge
is mechanical and this script never has to guess where a string belongs.

Three safety properties, in order of how much they have cost when absent:

1. **An existing language is never overwritten.**  A page reaching this stage may already
   carry bytes a human approved at touchpoint two; the whole extend-language path exists
   because one own-language approval covers every *later* localization of the *same*
   bytes.  Silently rewriting an approved string breaks that, and nothing downstream would
   notice.  ``--overwrite-lang <lang>`` is the only way past it, and every overwritten key
   is printed with its old and new text.
2. **Nothing but the new language moves.**  After the merge the script reverts every write
   it recorded and asserts the page is byte-identical to the input — so a bug that
   reordered a list, dropped an anchor or re-wrote an English label fails here rather than
   at ``review-preview``.
3. **The page states which run produced it.**  ``--run-id`` / ``--model-id`` are required
   and stamp ``provenance`` exactly as ``prepare_localized_page.py`` does: a localized page
   carrying the write run's stamp is refused by ``review-preview`` at the very end of the
   chain, after every panel and every locale has already been paid for.

It also seeds the three group lexicon tables from the topic manifest by default (the
manifest's own ``label`` / ``short_label`` / ``definition``, copied verbatim, only for
languages the table lacks).  The values are identical, so the rendered bytes do not move;
what changes is that the localization judge now has an English master to compare each
side's badge against instead of ``(missing)``.  ``--no-seed-group-lexicon`` opts out.

    python skills/render-localize/scripts/apply_localization.py \
        --page <in page.json> --translations <ru.json> --lang ru \
        --topics-root topics --topic-id <t> \
        --run-id <rl run id> --model-id <localizer model> \
        -o <run dir>/page.json
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import _bootstrap  # noqa: F401

from newsab_schema.common import normalize_lang
from newsab_schema.models.page import ReaderPage

from localization_units import (
    Unit,
    enumerate_units,
    load_question_stats,
    load_sentence_index,
    load_topic_inputs,
    seed_group_lexicon,
    uncovered_lang_maps,
)

# One definition site for "which version of this skill produced these bytes"; the sibling
# script that mints a localized page copy owns it.
from prepare_localized_page import skill_version


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--page", required=True)
    parser.add_argument(
        "--translations",
        required=True,
        help="JSON object mapping unit keys (from localization_units.py) to their text",
    )
    parser.add_argument(
        "--lang",
        required=True,
        help="BCP-47 language the translations are written in; never defaulted — a page "
        "mislabelled as one language while carrying another is a defect the renderer "
        "cannot see and the reviewer cannot read",
    )
    parser.add_argument("--run-id", required=True, help="the run directory these bytes belong to")
    parser.add_argument("--model-id", required=True, help="the model that produced the translations")
    parser.add_argument("--sentence-index", help="override the run's data/sentence-index.*.json")
    parser.add_argument("--topics-root")
    parser.add_argument("--topic-id")
    parser.add_argument("--manifest", help="topic_manifest.yaml (implied by --topics-root/--topic-id)")
    parser.add_argument("--qa-run", help="analysis/<qa-run-id> dir, for the completeness check")
    parser.add_argument(
        "--no-seed-group-lexicon",
        action="store_true",
        help="do not copy the manifest's group label/short_label/definition into the "
        "lexicon for languages it lacks",
    )
    parser.add_argument(
        "--overwrite-lang",
        help="explicit permission to replace text this page already carries in this "
        "language; every replaced key is printed. Without it, an existing language is a "
        "refusal.",
    )
    parser.add_argument(
        "--allow-incomplete",
        action="store_true",
        help="accept a translation map that leaves some units without this language",
    )
    parser.add_argument("-o", "--out", required=True)
    args = parser.parse_args(argv)

    lang = normalize_lang(args.lang)
    overwrite = normalize_lang(args.overwrite_lang) if args.overwrite_lang else None
    if overwrite is not None and overwrite != lang:
        raise SystemExit(
            f"--overwrite-lang {overwrite} does not match --lang {lang}: this script "
            "writes exactly one language"
        )

    page_path = Path(args.page)
    original = json.loads(page_path.read_text(encoding="utf-8"))
    working = copy.deepcopy(original)
    translations = json.loads(Path(args.translations).read_text(encoding="utf-8"))
    if not isinstance(translations, dict):
        raise SystemExit(
            "--translations must be a JSON object mapping unit key -> text; a packet "
            "file is the *input* to a translator, not its answer"
        )

    sentences, _ = load_sentence_index(page_path, args.sentence_index)
    manifest, question_texts, pivots = load_topic_inputs(
        args.topics_root, args.topic_id, args.manifest
    )
    question_stats = load_question_stats(args.qa_run)

    seeded: list[tuple[str, str, str]] = []
    if manifest and not args.no_seed_group_lexicon:
        seeded = seed_group_lexicon(working, manifest)

    units = enumerate_units(
        working,
        sentences=sentences,
        manifest=manifest,
        question_stats=question_stats,
        question_texts=question_texts,
        topic_pivots=pivots,
    )
    stray = uncovered_lang_maps(working, units)
    if stray:
        print(
            "the page carries language-carrying field(s) the unit enumerator does not "
            "know about; merging would leave them untranslated:\n  " + "\n  ".join(stray),
            file=sys.stderr,
        )
        return 2

    by_key = {unit.key: unit for unit in units}
    unknown = sorted(key for key in translations if key not in by_key)
    if unknown:
        print(
            f"{len(unknown)} translated key(s) name nothing on this page — a stale packet "
            "or a hand-edited key:\n  " + "\n  ".join(unknown[:20]),
            file=sys.stderr,
        )
        return 1

    occupied = sorted(
        key
        for key in translations
        if by_key[key].text(lang) is not None
    )
    if occupied and overwrite is None:
        print(
            f"{len(occupied)} unit(s) already carry {lang} on this page. These bytes may "
            "be what a human approved; this script will not rewrite them silently. Drop "
            f"them from the map, or pass --overwrite-lang {lang} to replace them "
            "deliberately:\n  " + "\n  ".join(occupied[:20]),
            file=sys.stderr,
        )
        return 1

    if not args.allow_incomplete:
        untranslated = [
            unit.key
            for unit in units
            if unit.reader_facing
            and unit.status(lang) == "missing"
            and not (translations.get(unit.key) or "").strip()
        ]
        if untranslated:
            print(
                f"{len(untranslated)} unit(s) have no {lang} text and none in the map — a "
                "page-check --langs run will refuse the page. Translate them, or pass "
                "--allow-incomplete for a deliberate partial merge:\n  "
                + "\n  ".join(untranslated[:20]),
                file=sys.stderr,
            )
            return 1

    #: ``(unit, lang, previous text or None)`` — the complete record of what this run
    #: changed, used both for the report and for the revert self-check.
    writes: list[tuple[Unit, str, Optional[str]]] = []
    replaced: list[tuple[str, str, str]] = []
    for key, text in translations.items():
        if not isinstance(text, str) or not text.strip():
            raise SystemExit(f"{key}: translation is empty")
        unit = by_key[key]
        values = unit.writable_values()
        previous = values.get(lang)
        if previous is not None:
            replaced.append((key, previous, text.strip()))
        writes.append((unit, lang, previous))
        values[lang] = text.strip()

    # The seeding above ran before enumeration, so its writes are already on the page;
    # record them here so the self-check reverts them too.
    for key, lang_written, _text in seeded:
        unit = by_key.get(key)
        if unit is not None:
            writes.append((unit, lang_written, None))

    previous_provenance = working.get("provenance")
    working["provenance"] = {
        "skill_version": skill_version(),
        "model_id": args.model_id,
        "run_id": args.run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    page = ReaderPage.model_validate(working)

    # -- self-check: revert every recorded write and the page must be the input page ----
    for unit, lang_written, previous in reversed(writes):
        values = unit.values
        if previous is None:
            values.pop(lang_written, None)
        else:
            values[lang_written] = previous
        if not values:
            # ``MultiLangText`` cannot be empty: a node this run created (a quote that had
            # no translation, a lexicon entry the manifest seeded) has to disappear again
            # rather than validate as ``{"values": {}}``.
            try:
                del unit.parent[unit.slot]
            except (KeyError, IndexError, TypeError):
                pass
    working["provenance"] = previous_provenance
    if _canonical(working) != _canonical(original):
        print(
            "self-check failed: reverting this run's writes did not reproduce the input "
            "page, so the merge changed something it did not report. Refusing to write.",
            file=sys.stderr,
        )
        return 2

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page.model_dump_json(indent=2) + "\n", encoding="utf-8")

    print(f"{out}: {len(translations)} unit(s) localized into {lang}")
    if seeded:
        print(f"seeded {len(seeded)} group lexicon value(s) from the topic manifest:")
        for key, lang_written, text in seeded:
            print(f"  {key} [{lang_written}] = {text}")
    if replaced:
        print(f"OVERWROTE {len(replaced)} existing {lang} value(s) (--overwrite-lang):")
        for key, before, after in replaced:
            print(f"  {key}\n    was: {before}\n    now: {after}")
    print("self-check: every byte outside the reported writes is unchanged")
    return 0


def _canonical(page: dict) -> Any:
    """The page as the schema sees it — defaults filled, so ``{}`` and absent agree."""
    return ReaderPage.model_validate(page).model_dump(mode="json")


if __name__ == "__main__":
    raise SystemExit(main())
