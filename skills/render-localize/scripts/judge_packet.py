#!/usr/bin/env python3
"""Build the spot-check judge's entire input, as text.

Step 3 of this skill says the judge's input is the rendered English page, `page.json`, the
pinned `findings.jsonl` and the anchored sentences.  The first of those is a self-contained
HTML file that embeds the whole corpus for its record modals — 0.3–1.5 MB on the live
topics — so handing it to a model is not practical, and the step has been skipped in
practice.  The judge does not need the HTML: it needs *what a reader meets*, in reading
order, plus the sentences behind it.  Both are derivable from the artifacts.

The packet is deliberately ordered the way the rubric reads:

1. **The overview layer** — everything a reader sees before clicking anything.  Axis 5 asks
   what impression *this* leaves, so it is separated rather than mixed into the detail.
2. **On expansion** — details, caveats, quotes.
3. **The anchored sentences**, verbatim, every one the page cites.  Axis 1 is unanswerable
   without them and they must not be paraphrased.
4. **The findings** the page pins, with each side's counts.

Every claim the packet prints — intro, side answer, detail — carries its own anchor list
inline.  Without it the judge has to guess which sentence backs which reading, and it
guesses from the one thing it can see next to the card: the displayed quote.

It carries no writer reasoning, no SKILL.md and no repo docs, which is what makes the check
independent.

    python skills/render-localize/scripts/judge_packet.py topics <topic_id> \
        --page topics/<t>/editorial/versions/<edt>/page.json \
        --qa-run topics/<t>/analysis/<qa-run> -o judge_packet.md
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import _bootstrap  # noqa: F401

from newsab_schema.ids import SentenceId
from newsab_schema.io import read_yaml
from newsab_schema.models.corpus import TopicManifest
from newsab_schema.models.page import ReaderPage
from newsab_schema.paths import TopicPaths
from newsab_schema.store import load_run_articles

LANG = "en"


def _t(multi, lang: str = LANG) -> str:
    if multi is None:
        return ""
    if hasattr(multi, "get"):
        return multi.get(lang) or multi.get("en") or ""
    return str(multi)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("topics_root")
    ap.add_argument("topic_id")
    ap.add_argument("--page", required=True)
    ap.add_argument("--qa-run", required=True)
    ap.add_argument(
        "--corpus-run",
        help="explicit pinned corpus run (required when no active pointer exists)",
    )
    ap.add_argument("-o", "--out", required=True)
    args = ap.parse_args(argv)

    paths = TopicPaths.for_topic(args.topics_root, args.topic_id)
    page = ReaderPage.model_validate_json(Path(args.page).read_text(encoding="utf-8"))
    manifest = read_yaml(paths.topic_manifest, TopicManifest)
    articles = {
        a.article_id: a for a in load_run_articles(paths, args.corpus_run)
    }
    findings = {
        r["finding_id"]: r
        for r in (
            json.loads(line)
            for line in (Path(args.qa_run) / "findings.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip()
        )
    }

    sides = {g.group_id: (_t(g.short_label), _t(g.definition)) for g in manifest.groups}
    cited: list[str] = []

    def cite(sid: str) -> None:
        if sid not in cited:
            cited.append(sid)

    out: list[str] = []
    out.append(f"# Judge packet — {args.topic_id}\n")
    out.append("The two sides of this comparison, as the topic scope defines them:\n")
    for gid, (short, definition) in sorted(sides.items()):
        out.append(f"- `{gid}` — **{short}**: {definition}")
    out.append("")

    out.append(
        "---\n\n## 1. The overview layer (what a reader sees before clicking anything)\n"
    )
    out.append(
        "*How to read a side badge below: `N of M answering reports` means M of that "
        "side's pinned reports answered that question and N of those M gave the answer "
        "shown.  M is the same quantity section 4 calls `clusters_addressed`, not the "
        "side's whole pinned pool; the two denominators are different quantities and a "
        "difference between them is not a defect.  On the silent side of an attention "
        "gap the badge shows the side's whole pool instead, and is marked SILENT SIDE.*\n"
    )
    out.append(f"### Title\n\n> {_t(page.title)}\n")
    out.append("### Intro\n")
    for claim in page.intro:
        out.append(f"- ({claim.claim_type.value}) {_t(claim.text)}")
        for sid in claim.evidence:
            cite(sid)
        if claim.evidence:
            out.append("  - anchors: " + ", ".join(f"`{s}`" for s in claim.evidence))
    out.append("")
    for angle in page.angles:
        q = _t(page.lexicon.questions.get(angle.question_id)) or _t(
            angle.question_display
        )
        out.append(f"### Angle {angle.rank} — {q}")
        fnd = findings.get(angle.finding_id)
        strength = f", strength: {fnd['strength']}" if fnd else ""
        out.append(
            f"*card kind: {angle.kind.value}{strength}. The renderer prints both of "
            f"these on the card itself as badges — a `weak` card is labelled weak "
            f"for every reader, in the same words on every page, with the pinned "
            f"thresholds behind the label.*"
        )
        if angle.shared_answer_label:
            out.append(f"\n**Both sides:** {_t(angle.shared_answer_label)}")
        if angle.caveat:
            out.append(
                f"\n**Caveat, opened from an inline footnote marker:** {_t(angle.caveat)}"
            )
        if angle.commentary_joint is not None:
            # One paragraph written for both sides instead of one each: the judge sees it
            # in place of the two side paragraphs, because that is what the reader sees.
            out.append(
                f"\n**Joint commentary ({angle.commentary_joint.claim_type.value}), "
                f"shown as one full-width paragraph instead of two columns:** "
                f"{_t(angle.commentary_joint.text)}"
            )
            for sid in angle.commentary_joint.evidence:
                cite(sid)
            if angle.commentary_joint.evidence:
                out.append(
                    "  - anchors: "
                    + ", ".join(f"`{s}`" for s in angle.commentary_joint.evidence)
                )
        for side in angle.sides:
            short = sides.get(side.group_id, (side.group_id, ""))[0]
            out.append(
                f"\n**{short} ({side.group_id})** — badge: "
                f"{side.badge.numerator} of {side.badge.denominator} answering reports"
                f"{' — SILENT SIDE' if side.is_silent_side else ''}"
            )
            if side.answer_label:
                out.append(f"  - label: {_t(side.answer_label)}")
            out.append(
                f"  - answer ({side.answer.claim_type.value}): {_t(side.answer.text)}"
            )
            for sid in side.answer.evidence:
                cite(sid)
            if side.answer.evidence:
                out.append(
                    "  - anchors: " + ", ".join(f"`{s}`" for s in side.answer.evidence)
                )
        out.append("")

    out.append("---\n\n## 2. On expansion (detail, quotes)\n")
    for angle in page.angles:
        if not angle.detail and not any(s.quotes for s in angle.sides):
            continue
        out.append(f"### Angle {angle.rank}")
        for claim in angle.detail:
            out.append(f"- detail ({claim.claim_type.value}): {_t(claim.text)}")
            for sid in claim.evidence:
                cite(sid)
            if claim.evidence:
                out.append(
                    "  - anchors: " + ", ".join(f"`{s}`" for s in claim.evidence)
                )
        for side in angle.sides:
            for quote in side.quotes:
                cite(quote.sentence_id)
                out.append(
                    f"- quote shown for `{side.group_id}`: `{quote.sentence_id}`"
                )
        out.append("")

    out.append("---\n\n## 3. The anchored sentences, verbatim\n")
    out.append(
        "Every sentence the page cites, in its own language. Judge entailment "
        "against these and nothing else.\n"
    )
    for sid in cited:
        parsed = SentenceId.parse(sid)
        article = articles.get(parsed.article_id)
        if article is None:
            out.append(f"- `{sid}` — **NOT IN THE PINNED CORPUS RUN**")
            continue
        text = next(
            (
                s.text
                for p in article.structured_text
                for s in p.sentences
                if f"P{p.index:02d}:S{s.index:02d}" == sid.split(":", 1)[1]
            ),
            None,
        )
        head = (
            f"- `{sid}` ({article.source_id}, {article.publish_date}, {article.lang})"
        )
        out.append(
            head + (f"\n    {text}" if text else "\n    **ANCHOR DOES NOT RESOLVE**")
        )
    out.append("")

    out.append("---\n\n## 4. The findings this page pins\n")
    for angle in page.angles:
        f = findings.get(angle.finding_id)
        if f is None:
            out.append(
                f"- angle {angle.rank}: `{angle.finding_id}` **is not in the pinned run**"
            )
            continue
        counts = "; ".join(
            f"{g['group_id']} {g['clusters_addressed']} of {g['clusters_total']} "
            f"reports addressed the question, "
            f"top={g.get('top_category')}"
            f"{' (TIED)' if g.get('top_category_tied') else ''}"
            for g in f["groups"]
        )
        out.append(
            f"- angle {angle.rank} `{f['finding_id']}` {f['question_id']} "
            f"{f['kind']}/{f['strength']} — {counts}"
        )
    out.append("")

    body = "\n".join(out)
    Path(args.out).write_text(body, encoding="utf-8")
    print(f"written {args.out} ({len(body):,} chars, {len(cited)} anchored sentences)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
