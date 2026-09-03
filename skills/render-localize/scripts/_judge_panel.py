"""Merge N independent judge passes on one packet into a single panel record.

Why a panel instead of serial rounds, measured on real runs:

* **A single judge pass has low recall.**  Rounds two and three of a serial run kept
  reporting *true* defects in paragraphs nobody had touched — the extra rounds were
  buying recall, not convergence, and they cost 96 minutes of wall clock for five of
  them.  N judges reading the same packet in parallel buy the same recall in one round.
* **Union, not vote.**  A defect one judge saw and two missed is still a defect, so the
  merged score of an axis is the *worst* score any judge gave it and the merged lists are
  unions.  Agreement counts are printed to order the fixer's work, never to filter it.
* **Churn is only measurable against what was rewritten.**  The old stop condition said
  "more new defects than last round, in sections that previously passed", which conflated
  two different things: discovery variance on untouched text (real defects, keep fixing)
  and new defects on text the fix pass actually rewrote (the fix is making it worse,
  stop).  This module locates every finding on a page locus and hashes those loci, so the
  difference is arithmetic rather than a judgement call.

Loci are deliberately coarse — ``title``, ``intro``, ``hook``, ``lexicon``, ``visuals``,
``how_we_counted`` and one per ``angle N`` — because that is the granularity a judge names
in its ``refs`` and the granularity ``write``'s fix-page mode edits at.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

#: 0.2: ``judge_consensus_one`` — two or more members scoring the *same* axis 1 escalates
#: even when only that one axis is below 2 (a 2-of-3 entailment fault shipped through
#: the old gap, which required two axes at 1 or one at 0).
PANEL_VERSION = "rl-judge-panel-0.2"

#: Top-level page keys that a judge can name and a fix pass can rewrite.  ``topic_id``
#: and ``provenance`` are excluded: they are machine-owned and change every run, so a
#: diff on them would mark the whole page rewritten.
_PAGE_LOCUS_KEYS = ("title", "intro", "hook", "lexicon", "visuals", "how_we_counted")

_ANGLE_RE = re.compile(r"angle\s*#?\s*(\d+)", re.IGNORECASE)
_NAMED_LOCUS_RES = (
    ("intro", re.compile(r"\bintro(?:duction)?\b", re.IGNORECASE)),
    ("title", re.compile(r"\btitle\b", re.IGNORECASE)),
    ("hook", re.compile(r"\bhook\b", re.IGNORECASE)),
    ("lexicon", re.compile(r"\blexicon\b", re.IGNORECASE)),
    ("visuals", re.compile(r"\bvisual", re.IGNORECASE)),
    ("how_we_counted", re.compile(r"how[ _]we[ _]counted|appendix", re.IGNORECASE)),
)
_PREFIXED_ID_RE = re.compile(r"\b(?:QST|FND)-[A-Za-z0-9_.-]+")


def _digest(value: object) -> str:
    canonical = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def page_loci(page: dict) -> dict[str, str]:
    """Hash every locus of a page, so two rounds can be compared without the pages.

    The hash covers the whole subtree, not only its reader-facing strings: a fix that
    swapped an anchor or a category on angle 3 rewrote angle 3 as surely as one that
    reworded it, and the next round's findings on angle 3 must be read in that light.
    """
    out: dict[str, str] = {}
    for key in _PAGE_LOCUS_KEYS:
        if key in page:
            out[key] = _digest(page[key])
    for angle in page.get("angles") or []:
        rank = angle.get("rank")
        if rank is None:
            continue
        out[f"angle {int(rank)}"] = _digest(angle)
    return out


def id_locus_map(page: dict) -> dict[str, str]:
    """``QST-…``/``FND-…`` → the locus that carries it, for judges who cite ids."""
    out: dict[str, str] = {}
    for angle in page.get("angles") or []:
        rank = angle.get("rank")
        if rank is None:
            continue
        locus = f"angle {int(rank)}"
        for key in ("question_id", "finding_id"):
            value = angle.get(key)
            if isinstance(value, str) and value:
                out[value] = locus
    return out


def ref_text(entries: object) -> list[str]:
    """Flatten a judge's reference list, whatever shape it chose to write it in.

    The rubric asks for strings, but a judge that writes richer objects is being more
    helpful, not malformed — and a gate that cannot read a verbose judge fails open.
    """
    if entries is None:
        return []
    if not isinstance(entries, list):
        entries = [entries]
    out: list[str] = []
    for entry in entries:
        if isinstance(entry, dict):
            for key in ("ref", "claim", "claim_id", "id", "where", "angle"):
                if key in entry:
                    value = str(entry[key])
                    # ``{"angle": 1}`` means angle 1; the bare number would parse as no
                    # locus at all.
                    if key == "angle" and not _ANGLE_RE.search(value):
                        value = f"angle {value}"
                    out.append(value)
                    break
            else:
                out.append("; ".join(f"{k}={v}" for k, v in entry.items()))
        elif entry is not None:
            out.append(str(entry))
    return out


def parse_loci(texts: list[str], ids: dict[str, str] | None = None) -> list[str]:
    """Every page locus named in these strings, sorted and deduplicated."""
    found: set[str] = set()
    for text in texts:
        if not text:
            continue
        for match in _ANGLE_RE.finditer(text):
            found.add(f"angle {int(match.group(1))}")
        for name, pattern in _NAMED_LOCUS_RES:
            if pattern.search(text):
                found.add(name)
        for match in _PREFIXED_ID_RE.finditer(text):
            locus = (ids or {}).get(match.group(0))
            if locus:
                found.add(locus)
    return sorted(found, key=_locus_sort_key)


def _locus_sort_key(locus: str) -> tuple[int, int, str]:
    match = _ANGLE_RE.fullmatch(locus)
    if match:
        return (1, int(match.group(1)), "")
    return (0, 0, locus)


def load_judge(path: Path, axes: tuple[str, ...]) -> dict:
    """Read one judge's JSON, or raise ValueError naming what is wrong with it."""
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}: not JSON ({exc})") from exc
    if not isinstance(doc, dict):
        raise ValueError(f"{path}: top level is {type(doc).__name__}, expected an object")
    scores = doc.get("scores")
    if not isinstance(scores, dict):
        raise ValueError(f"{path}: no `scores` object")
    missing = [axis for axis in axes if axis not in scores]
    if missing:
        raise ValueError(f"{path}: missing axes {', '.join(missing)}")
    for axis in axes:
        entry = scores[axis]
        if not isinstance(entry, dict) or "score" not in entry:
            raise ValueError(f"{path}: axis {axis} has no score")
        try:
            value = int(entry["score"])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{path}: axis {axis} score {entry['score']!r} is not a number") from exc
        if value not in (0, 1, 2):
            raise ValueError(f"{path}: axis {axis} score {value} is outside 0/1/2")
    return doc


def merge_panel(
    judges: list[dict],
    *,
    axes: tuple[str, ...],
    list_fields: tuple[str, ...],
    ids: dict[str, str] | None = None,
) -> dict:
    """Union N judge documents into one panel record.

    ``list_fields`` are the judge's blocking lists (``unverified_readings`` and
    ``contradicted_notes`` for L1).  Each entry becomes a finding keyed by
    ``(kind, locus)``, which is what the churn check compares across rounds: prose notes
    are never byte-comparable, but "which axis faulted which locus" is.
    """
    n = len(judges)
    scores: dict[str, dict] = {}
    findings: dict[tuple[str, str], dict] = {}

    def record(kind: str, loci: list[str], judge_index: int, detail: str) -> None:
        for locus in loci or [""]:
            entry = findings.setdefault(
                (kind, locus), {"kind": kind, "locus": locus, "judges": [], "detail": []}
            )
            if judge_index not in entry["judges"]:
                entry["judges"].append(judge_index)
            if detail and detail not in entry["detail"]:
                entry["detail"].append(detail)

    for axis in axes:
        per_judge = []
        for index, doc in enumerate(judges, start=1):
            entry = doc["scores"][axis]
            score = int(entry["score"])
            refs = ref_text(entry.get("refs"))
            note = str(entry.get("note", "") or "")
            per_judge.append(
                {"judge": index, "score": score, "note": note, "refs": refs}
            )
            if score < 2:
                # A locus needs a defect statement behind it.  The note is that
                # statement, so wherever it names is where the judge located the fault;
                # when it names nowhere, a single ref still stands in ("the anchor does
                # not support the claim" + refs: ["angle 3"]).  But a *list* of refs
                # under a note that locates nothing is a reading list, not N located
                # defects — pooling it manufactured a churn hard stop on an angle no
                # judge had faulted (measured on a real run), so that case now falls into
                # the unlocated bucket panel.md already routes to manual triage.
                note_loci = parse_loci([note], ids)
                if note_loci:
                    loci = note_loci
                else:
                    ref_loci = parse_loci(refs, ids)
                    loci = ref_loci if len(ref_loci) == 1 else []
                record(
                    f"axis:{axis}",
                    loci,
                    index,
                    f"[{score}] {note}" if note else f"[{score}]",
                )
        scores[axis] = {
            "score": min(item["score"] for item in per_judge),
            "judges": per_judge,
        }

    lists: dict[str, list[str]] = {}
    for field in list_fields:
        merged: list[str] = []
        for index, doc in enumerate(judges, start=1):
            for text in ref_text(doc.get(field)):
                if text not in merged:
                    merged.append(text)
                record(field, parse_loci([text], ids), index, text)
        lists[field] = merged

    ordered = [
        dict(value, agreement=f"{len(value['judges'])}/{n}")
        for _, value in sorted(
            findings.items(), key=lambda kv: (kv[0][0], _locus_sort_key(kv[0][1]))
        )
    ]
    return {
        "panel_version": PANEL_VERSION,
        "panel_size": n,
        "scores": scores,
        "findings": ordered,
        **lists,
    }


def rewritten_loci(previous: dict, current: dict) -> list[str]:
    """Loci whose bytes changed between the page two rounds judged."""
    keys = set(previous) | set(current)
    return sorted(
        (k for k in keys if previous.get(k) != current.get(k)), key=_locus_sort_key
    )


def classify_findings(
    findings: list[dict], previous_panel: dict, rewritten: list[str]
) -> list[dict]:
    """Label each finding of a confirmation round against the round before it.

    * ``persistent`` — the same axis faulted the same locus last round: the fix did not
      land, or was refused with a reason.  Never churn, however heavily rewritten.
    * ``churn`` — a *new* fault on a locus the fix pass rewrote.  This, and only this, is
      the fix pass making the page worse; it stops the loop.
    * ``recall`` — a new fault on a locus nobody touched.  Discovery variance: the panel
      is still finding pre-existing defects.  Verify each against the packet and fix it;
      a fault on byte-identical text that the packet does not support is score variance
      and is recorded, not rewritten.
    * ``unlocated`` — the judge named no locus, so no classification is possible; triage
      by hand.
    """
    seen = {
        (item.get("kind"), item.get("locus"))
        for item in previous_panel.get("findings") or []
    }
    rewritten_set = set(rewritten)
    out = []
    for finding in findings:
        locus = finding.get("locus") or ""
        if not locus:
            verdict = "unlocated"
        elif (finding.get("kind"), locus) in seen:
            verdict = "persistent"
        elif locus in rewritten_set:
            verdict = "churn"
        else:
            verdict = "recall"
        out.append(dict(finding, classification=verdict))
    return out
