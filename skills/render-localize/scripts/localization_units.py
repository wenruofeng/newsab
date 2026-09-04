#!/usr/bin/env python3
"""Enumerate every localizable unit on a reader page and list one language's gaps.

A page is localized by filling one language into every reader-facing string it carries.
Those strings are scattered across the whole artifact — title, intro claims, visual
captions, angle labels and explanations, quote translations, and seven lexicon maps — and
until this script existed each run re-derived that list by hand, which is how a run ships
a Russian page whose side badge still says "China side".

Two properties are the point:

* **The unit key is the page's own JSON path** — the same string
  ``localization_packet.py`` prints as the judge's location label — so the extraction, the
  merge (``apply_localization.py``) and the judge packet all name a unit identically.
  There is one key convention in this stage, not three.
* **A quote unit carries the verbatim source sentence**, resolved from the run's
  ``data/sentence-index.*.json``, with its language and ``source_id`` in the note. A
  quote's English translation is *not* the thing being translated — the source sentence
  is — and a translator handed an empty field can only guess.

``--lang`` is any language, the English pivot included: on an English master the gaps are
the write stage's own missing reader wording (every answer category, question, scope
bullet and topic concept the page displays, plus any non-English quote with no English
translation), which until now was discovered one ``page-check`` warning at a time.

Optional inputs widen the gap list from "what the page already carries" to "what the page
*should* carry": the topic manifest adds the scope bullets and the three group tables
(with the manifest's own wording as the master to translate from), the analyze run adds
every question and answer category the page displays, and the collect artifact adds every
topics_raised concept.  Without them the script still enumerates every unit on the page.

    # extend an approved page into a new site language
    python skills/render-localize/scripts/localization_units.py \
        --page topics/<t>/editorial/versions/<rl>/page.json --lang ru \
        --topics-root topics --topic-id <t> -o <scratch>/units.ru.json

    # what the English master is still missing (write stage)
    python skills/render-localize/scripts/localization_units.py \
        --page <page.json> --lang en --topics-root topics --topic-id <t> \
        --qa-run topics/<t>/analysis/<qa-run-id>

The packet is JSON: ``{"units": [{"key", "kind", "where", "note", "en", "<lang>", …}]}``.
A translator returns ``{key: text}`` — that map is exactly what ``apply_localization.py``
merges back.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import _bootstrap  # noqa: F401

from newsab_schema.common import normalize_lang


# --------------------------------------------------------------------------------------
# The key convention.  ``localization_packet.py`` imports these three: the judge's location
# label and this script's unit key must be the same string, or a defect the judge reports
# cannot be looked up in the packet a translator was given.
# --------------------------------------------------------------------------------------


def is_lang_map(node: object) -> bool:
    """True for a serialized ``MultiLangText`` — ``{"values": {lang: text}}``."""
    return (
        isinstance(node, dict)
        and set(node.keys()) == {"values"}
        and isinstance(node["values"], dict)
        and bool(node["values"])
        and all(isinstance(v, str) for v in node["values"].values())
    )


def walk_lang_maps(node: object, path: str = "", out: Optional[list] = None) -> list:
    """Every language map in the page, as ``(json path, values dict)``."""
    if out is None:
        out = []
    if is_lang_map(node):
        out.append((path, node["values"]))
        return out
    if isinstance(node, dict):
        for key, value in node.items():
            walk_lang_maps(value, f"{path}.{key}" if path else str(key), out)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            walk_lang_maps(value, f"{path}[{index}]", out)
    return out


def angle_label(page: dict, path: str) -> str:
    """`angles[2]...` → `angle rank 3 (QST-...)`: cite what a human can find."""
    if not path.startswith("angles["):
        return path
    index = int(path[len("angles[") : path.index("]")])
    angle = page.get("angles", [])[index]
    rest = path[path.index("]") + 1 :].lstrip(".")
    return f"angle {angle.get('rank', index + 1)} ({angle.get('question_id', '?')}) {rest}"


# --------------------------------------------------------------------------------------
# Units
# --------------------------------------------------------------------------------------


@dataclass
class Unit:
    """One localizable string on the page, located by ``key`` and writable via ``parent``.

    ``parent``/``slot`` point at the dict entry that holds (or *would* hold) the language
    map, so a unit the page does not carry yet — a quote with no ``translation``, a group
    label the write stage never wrote — is a first-class unit rather than an invisible gap.
    """

    key: str
    kind: str
    where: str
    note: str
    #: The dict (or list) holding the language map, and the key (or index) inside it.
    parent: Any
    slot: Any
    #: Drawn by the renderer.  ``False`` marks dead fields (a retired ``hook``, the
    #: deprecated ``how_we_counted.notes``): enumerated so the coverage self-check stays
    #: complete, never put in front of a translator.
    reader_facing: bool = True
    #: Quote units only: the sentence being quoted, in its own language.
    source: Optional[dict] = None
    #: Master text when the page carries no English value — the manifest's group wording,
    #: the signed scope bullet, the collect-stage pivot.
    fallback_en: Optional[str] = None
    fallback_en_from: Optional[str] = None
    extra: dict = field(default_factory=dict)

    @property
    def node(self) -> Optional[dict]:
        try:
            node = self.parent[self.slot]
        except (KeyError, IndexError, TypeError):
            return None
        return node if isinstance(node, dict) else None

    @property
    def exists(self) -> bool:
        return self.node is not None

    @property
    def values(self) -> dict:
        node = self.node
        if node is not None and isinstance(node.get("values"), dict):
            return node["values"]
        return {}

    def writable_values(self) -> dict:
        """The ``values`` dict, created (with its node) if the page has neither yet."""
        node = self.node
        if node is None:
            node = {"values": {}}
            self.parent[self.slot] = node
        if not isinstance(node.get("values"), dict):
            node["values"] = {}
        return node["values"]

    def text(self, lang: str) -> Optional[str]:
        value = self.values.get(lang)
        return value if isinstance(value, str) and value.strip() else None

    def english(self) -> Optional[str]:
        return self.text("en") or self.fallback_en

    def status(self, lang: str) -> str:
        """``present`` / ``missing`` / ``not_applicable``.

        A quote already written in the target language has nothing to translate: the
        renderer shows the verbatim original, and asking for a "translation" of an English
        sentence into English is how a page grows a paraphrase beside its own quote.
        """
        if self.kind == "quote_translation" and self.source:
            if normalize_lang(self.source.get("lang") or "en") == lang:
                return "not_applicable"
        return "present" if self.text(lang) else "missing"

    def as_json(self, lang: str, reference_langs: tuple[str, ...]) -> dict:
        out: dict[str, Any] = {
            "key": self.key,
            "kind": self.kind,
            "where": self.where,
            "note": self.note,
        }
        for ref in reference_langs:
            out[ref] = self.text(ref)
        out[lang] = self.text(lang)
        # A unit the page carries no English for still has a master somewhere — the
        # manifest's own group wording, the signed scope bullet, the collect pivot, the
        # annotation question.  Naming it is the difference between a translator with a
        # source text and one inventing reader copy.
        if self.text("en") is None and self.fallback_en:
            out["en_master"] = self.fallback_en
            out["en_master_from"] = self.fallback_en_from
        if self.source:
            out["source"] = self.source
        out.update(self.extra)
        return out


_KIND_ORDER = (
    "title",
    "intro",
    "visual_caption",
    "angle_shared_answer_label",
    "side_answer_label",
    "side_explanation",
    "angle_commentary_joint",
    "angle_question_display",
    "angle_caveat",
    "angle_detail",
    "side_badge_label",
    "quote_translation",
    "lexicon_question",
    "lexicon_category",
    "lexicon_topic",
    "lexicon_scope",
    "lexicon_group_label",
    "lexicon_group_short_label",
    "lexicon_group_definition",
    "hook",
    "how_we_counted_note",
)

_LEXICON_KINDS = {
    "questions": "lexicon_question",
    "categories": "lexicon_category",
    "topics": "lexicon_topic",
    "scope": "lexicon_scope",
    "group_labels": "lexicon_group_label",
    "group_short_labels": "lexicon_group_short_label",
    "group_definitions": "lexicon_group_definition",
}

_LEXICON_NOTES = {
    "questions": "the question as a reader meets it — ask the same thing, do not narrow it",
    "categories": "short reader label for a counting key; the key itself never changes",
    "topics": "a collect-stage concept the topic cloud displays; translate the concept",
    "scope": (
        "a signed scope bullet — translate it in full, keep every number and date; "
        "a summary is a defect (page-check refuses a dropped number)"
    ),
    "group_labels": "the side's full noun phrase (tag tooltip)",
    "group_short_labels": "the side's two-to-four-character pronoun, used in running text",
    "group_definitions": "the side's membership definition, shown in the tag detail",
}


def enumerate_units(
    page: dict,
    *,
    sentences: Optional[dict] = None,
    manifest: Optional[dict] = None,
    question_stats: Optional[dict] = None,
    question_texts: Optional[dict] = None,
    topic_pivots: Optional[list] = None,
) -> list[Unit]:
    """Every localizable unit on ``page``, in reading order then lexicon order.

    ``page`` is the raw parsed JSON and is used *by reference*: ``apply_localization.py``
    writes through ``Unit.parent``.  The only mutation this makes is materializing empty
    lexicon tables, which serialize identically to the schema's own defaults.
    """
    units: list[Unit] = []

    def add(key, kind, parent, slot, note, **kw) -> Unit:
        unit = Unit(
            key=key,
            kind=kind,
            where=angle_label(page, key),
            note=note,
            parent=parent,
            slot=slot,
            **kw,
        )
        units.append(unit)
        return unit

    add("title", "title", page, "title", "the page headline")

    for index, claim in enumerate(page.get("intro") or []):
        add(
            f"intro[{index}].text",
            "intro",
            claim,
            "text",
            f"intro claim {index + 1} ({claim.get('claim_type', '?')}) — reader prose",
        )

    if page.get("hook") is not None:
        add(
            "hook.text",
            "hook",
            page["hook"],
            "text",
            "retired field the renderer no longer draws — do not translate",
            reader_facing=False,
        )

    for index, angle in enumerate(page.get("angles") or []):
        rank = angle.get("rank", index + 1)
        base = f"angles[{index}]"
        if angle.get("question_display") is not None:
            add(
                f"{base}.question_display",
                "angle_question_display",
                angle,
                "question_display",
                f"angle {rank}: this angle's own question wording, overriding the lexicon",
            )
        if angle.get("shared_answer_label") is not None:
            add(
                f"{base}.shared_answer_label",
                "angle_shared_answer_label",
                angle,
                "shared_answer_label",
                f"angle {rank}: the one answer both sides give — both cards show these words",
            )
        if angle.get("caveat") is not None:
            add(
                f"{base}.caveat",
                "angle_caveat",
                angle,
                "caveat",
                f"angle {rank}: caveat badge — keep the [^n] marker's referent intact",
            )
        for d_index, detail in enumerate(angle.get("detail") or []):
            add(
                f"{base}.detail[{d_index}].text",
                "angle_detail",
                detail,
                "text",
                f"angle {rank}: expansion note {d_index + 1}",
            )
        if angle.get("commentary_joint") is not None:
            add(
                f"{base}.commentary_joint.text",
                "angle_commentary_joint",
                angle["commentary_joint"],
                "text",
                f"angle {rank}: the joint paragraph written for both sides — it stays joint",
            )
        for s_index, side in enumerate(angle.get("sides") or []):
            group = side.get("group_id", "?")
            side_base = f"{base}.sides[{s_index}]"
            if side.get("answer_label") is not None:
                add(
                    f"{side_base}.answer_label",
                    "side_answer_label",
                    side,
                    "answer_label",
                    f"angle {rank}, {group} side: headline-length answer on the card",
                )
            add(
                f"{side_base}.answer.text",
                "side_explanation",
                side["answer"],
                "text",
                f"angle {rank}, {group} side: the explanation paragraph — local-language "
                "news prose, evidence and causal chain preserved, [^n] markers in place",
            )
            if side.get("badge", {}).get("label") is not None:
                add(
                    f"{side_base}.badge.label",
                    "side_badge_label",
                    side["badge"],
                    "label",
                    f"angle {rank}, {group} side: what the count badge counts",
                )
            for q_index, quote in enumerate(side.get("quotes") or []):
                sentence_id = quote.get("sentence_id", "?")
                card = (sentences or {}).get(sentence_id) or {}
                source = None
                if card:
                    source = {
                        "sentence_id": sentence_id,
                        "lang": card.get("lang"),
                        "source_id": card.get("source_id"),
                        "text": card.get("text"),
                    }
                    note = (
                        f"VERBATIM quoted sentence in {card.get('lang')} from "
                        f"{card.get('source_id')} ({sentence_id}), angle {rank} {group} "
                        "side — translate the source sentence itself, not the English "
                        "gloss; the original stays on the page beside it"
                    )
                else:
                    note = (
                        f"translation of quoted sentence {sentence_id} (angle {rank}, "
                        f"{group} side) — source sentence unresolved, no sentence index "
                        "was given"
                    )
                add(
                    f"{side_base}.quotes[{q_index}].translation",
                    "quote_translation",
                    quote,
                    "translation",
                    note,
                    source=source,
                )

    for index, visual in enumerate(page.get("visuals") or []):
        add(
            f"visuals[{index}].caption",
            "visual_caption",
            visual,
            "caption",
            f"caption of the {visual.get('kind', '?')} figure",
        )

    lexicon = page.setdefault("lexicon", {})
    manifest_groups = {g["group_id"]: g for g in (manifest or {}).get("groups") or []}
    for section, kind in _LEXICON_KINDS.items():
        table = lexicon.setdefault(section, {})
        expected = _expected_lexicon_keys(
            section,
            table,
            manifest=manifest,
            question_stats=question_stats,
            topic_pivots=topic_pivots,
        )
        for entry_key in expected:
            unit = add(
                f"lexicon.{section}.{entry_key}",
                kind,
                table,
                entry_key,
                _LEXICON_NOTES[section],
            )
            if entry_key not in table:
                unit.note += " — absent from the page's lexicon entirely"
            fallback, origin = _lexicon_master(
                section, entry_key, manifest_groups, question_texts
            )
            unit.fallback_en = fallback
            unit.fallback_en_from = origin

    notes = (page.get("how_we_counted") or {}).get("notes") or []
    for index in range(len(notes)):
        add(
            f"how_we_counted.notes[{index}]",
            "how_we_counted_note",
            notes,
            index,
            "deprecated field — renderer, checker and judge ignore it",
            reader_facing=False,
        )

    # Grouped by kind, page order kept inside each group: localize.md's rule is to
    # translate the labels first and the explanations after, and a packet ordered that
    # way is the one a translator can follow.
    order = {kind: i for i, kind in enumerate(_KIND_ORDER)}
    decorated = sorted(
        enumerate(units), key=lambda pair: (order.get(pair[1].kind, len(order)), pair[0])
    )
    return [unit for _, unit in decorated]


def _expected_lexicon_keys(
    section: str,
    table: dict,
    *,
    manifest: Optional[dict],
    question_stats: Optional[dict],
    topic_pivots: Optional[list],
) -> list[str]:
    """The entries this lexicon table should carry: what it has, plus what it owes.

    "What it owes" is derivable only from the artifacts the page was built from, which is
    why the extra inputs are optional: with none of them this lists the page's own
    entries, which is all an extend-language run needs.  A write-stage ``--lang en`` run
    passes them and gets the gap list ``page-check`` reports one warning at a time.
    """
    keys = list(table)
    if section == "scope" and manifest:
        keys += [*(manifest.get("include") or []), *(manifest.get("exclude") or [])]
    elif section == "questions" and question_stats:
        keys += list(question_stats)
    elif section == "categories" and question_stats:
        for stats in question_stats.values():
            for group_stats in (stats.get("groups") or {}).values():
                keys += list(group_stats.get("category_counts") or {})
    elif section == "topics" and topic_pivots:
        keys += list(topic_pivots)
    elif section.startswith("group_") and manifest:
        keys += [g["group_id"] for g in manifest.get("groups") or []]
    seen: dict[str, None] = {}
    for key in keys:
        if key:
            seen.setdefault(key, None)
    ordered = list(seen)
    # A stable order the translator and the report can both cite: the page's own entries
    # keep their order, additions sort after them.
    known = [k for k in ordered if k in table]
    added = sorted(k for k in ordered if k not in table)
    return known + added


def _lexicon_master(
    section: str, key: str, manifest_groups: dict, question_texts: Optional[dict]
) -> tuple[Optional[str], Optional[str]]:
    """English master for a lexicon entry the page carries no ``en`` for."""
    if section == "scope":
        return key, "the signed manifest bullet (verbatim)"
    if section == "topics":
        return key, "the collect-stage pivot_en concept key"
    if section == "questions" and question_texts:
        text = question_texts.get(key)
        if text:
            return text, "the annotation question (rewrite it for a reader)"
    if section.startswith("group_"):
        field_name = {
            "group_labels": "label",
            "group_short_labels": "short_label",
            "group_definitions": "definition",
        }[section]
        group = manifest_groups.get(key) or {}
        value = ((group.get(field_name) or {}).get("values") or {}).get("en")
        if value:
            return value, f"topic_manifest groups[{key}].{field_name}"
    return None, None


GROUP_TABLES = {
    "group_labels": "label",
    "group_short_labels": "short_label",
    "group_definitions": "definition",
}


def seed_group_lexicon(page: dict, manifest: dict) -> list[tuple[str, str, str]]:
    """Copy the manifest's group wording into the lexicon for languages it lacks.

    The manifest carries each side's ``label`` / ``short_label`` / ``definition`` in the
    languages touchpoint one approved, and cannot gain another without invalidating the
    ``scope_approval`` hash — which is why the lexicon holds the multilingual completion.
    A run that fills the lexicon only with the *new* languages leaves the localization
    judge comparing a Russian badge against ``(missing)``: there is no master on the page.
    Copying the manifest's own values in changes no rendered byte (the renderer already
    falls back to exactly these) and gives every later language something to be judged
    against.

    Returns the ``(key, lang, text)`` triples written.  Never overwrites an existing value:
    an entry the write stage or an earlier localize run made is that run's judgement.
    """
    written: list[tuple[str, str, str]] = []
    lexicon = page.setdefault("lexicon", {})
    for group in manifest.get("groups") or []:
        group_id = group.get("group_id")
        if not group_id:
            continue
        for table_name, field_name in GROUP_TABLES.items():
            values = (group.get(field_name) or {}).get("values") or {}
            if not values:
                continue
            table = lexicon.setdefault(table_name, {})
            entry = table.setdefault(group_id, {"values": {}})
            if not isinstance(entry.get("values"), dict):
                entry["values"] = {}
            for lang, text in values.items():
                lang = normalize_lang(lang)
                if lang in entry["values"] or not str(text).strip():
                    continue
                entry["values"][lang] = str(text).strip()
                written.append((f"lexicon.{table_name}.{group_id}", lang, str(text).strip()))
            if not entry["values"]:
                del table[group_id]
    return written


def uncovered_lang_maps(page: dict, units: list[Unit]) -> list[str]:
    """Language maps on the page that ``enumerate_units`` does not know about.

    The schema grows; a field added to ``page.py`` and not to this enumerator would be
    silently left untranslated on every page.  Callers refuse rather than under-report.
    """
    covered = {unit.key for unit in units}
    return [path for path, _ in walk_lang_maps(page) if path not in covered]


# --------------------------------------------------------------------------------------
# Inputs
# --------------------------------------------------------------------------------------


def load_sentence_index(page_path: Path, explicit: Optional[str]) -> tuple[dict, str]:
    """The run's ``data/sentence-index.<hash>.json``, found beside the page by default."""
    if explicit:
        path = Path(explicit)
        return json.loads(path.read_text(encoding="utf-8")), str(path)
    candidates = sorted((page_path.parent / "data").glob("sentence-index.*.json"))
    if not candidates:
        return {}, ""
    if len(candidates) > 1:
        raise SystemExit(
            f"{page_path.parent / 'data'} holds {len(candidates)} sentence indexes; "
            "name one with --sentence-index"
        )
    return json.loads(candidates[0].read_text(encoding="utf-8")), str(candidates[0])


def load_topic_inputs(
    topics_root: Optional[str], topic_id: Optional[str], manifest_path: Optional[str]
) -> tuple[Optional[dict], Optional[dict], Optional[list]]:
    """``(manifest dict, question_id -> text, topics_raised pivots)`` — each best-effort.

    Read as plain data rather than through the schema models: this script must keep
    working on a page whose topic tree is partly absent (the corpus store is gitignored
    and a reviewing agent may not have it), and a missing input degrades the gap list
    rather than stopping the run.
    """
    import yaml

    manifest: Optional[dict] = None
    questions: Optional[dict] = None
    pivots: Optional[list] = None

    path = Path(manifest_path) if manifest_path else None
    if path is None and topics_root and topic_id:
        path = Path(topics_root) / topic_id / "topic_manifest.yaml"
    if path is not None:
        if not path.is_file():
            raise SystemExit(f"no topic manifest at {path}")
        manifest = yaml.safe_load(path.read_text(encoding="utf-8"))

    if topics_root and topic_id:
        root = Path(topics_root) / topic_id
        active = root / "manifest" / "active.json"
        question_file = None
        if active.is_file():
            pointer = json.loads(active.read_text(encoding="utf-8")).get("questions")
            run_id = pointer.get("run_id") if isinstance(pointer, dict) else pointer
            if run_id:
                question_file = root / "questions" / "versions" / run_id / "questions.yaml"
        if question_file is None or not question_file.is_file():
            found = sorted((root / "questions" / "versions").glob("*/questions.yaml"))
            question_file = found[-1] if found else None
        if question_file is not None and question_file.is_file():
            data = yaml.safe_load(question_file.read_text(encoding="utf-8")) or {}
            questions = {}
            for item in data.get("questions") or []:
                text = item.get("text")
                if isinstance(text, dict):
                    text = (text.get("values") or {}).get("en") or text.get("text")
                if item.get("question_id") and isinstance(text, str):
                    questions[item["question_id"]] = text
        raised = root / "corpus" / "topics_raised.jsonl"
        if raised.is_file():
            pivots = []
            for line in raised.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                for item in record.get("topics_raised") or []:
                    pivot = (item.get("pivot_en") or "").strip()
                    if pivot:
                        pivots.append(pivot)
    return manifest, questions, pivots


def load_question_stats(qa_run: Optional[str]) -> Optional[dict]:
    if not qa_run:
        return None
    path = Path(qa_run)
    if path.is_dir():
        path = path / "question_stats.json"
    if not path.is_file():
        raise SystemExit(f"no question_stats.json at {path}")
    return json.loads(path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------------------


def summarize(units: list[Unit], lang: str) -> tuple[list[tuple], dict]:
    rows: dict[str, dict] = {}
    totals = {"total": 0, "present": 0, "missing": 0, "not_applicable": 0}
    for unit in units:
        row = rows.setdefault(
            unit.kind, {"total": 0, "present": 0, "missing": 0, "not_applicable": 0}
        )
        status = unit.status(lang)
        row["total"] += 1
        row[status] += 1
        totals["total"] += 1
        totals[status] += 1
    order = {kind: i for i, kind in enumerate(_KIND_ORDER)}
    ordered = sorted(rows.items(), key=lambda kv: order.get(kv[0], len(order)))
    return [(kind, counts) for kind, counts in ordered], totals


def render_summary(units: list[Unit], lang: str) -> str:
    rows, totals = summarize(units, lang)
    width = max([len(kind) for kind, _ in rows] + [len("kind")])
    lines = [
        f"{'kind'.ljust(width)}  total  present  missing  n/a",
        f"{'-' * width}  -----  -------  -------  ---",
    ]
    for kind, counts in rows:
        lines.append(
            f"{kind.ljust(width)}  {counts['total']:>5}  {counts['present']:>7}  "
            f"{counts['missing']:>7}  {counts['not_applicable']:>3}"
        )
    lines.append(
        f"{'TOTAL'.ljust(width)}  {totals['total']:>5}  {totals['present']:>7}  "
        f"{totals['missing']:>7}  {totals['not_applicable']:>3}"
    )
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--page", required=True, help="the page.json to enumerate")
    parser.add_argument(
        "--lang",
        required=True,
        help="BCP-47 language whose gaps to list; 'en' lists the master's own gaps. "
        "Never defaulted — a packet labelled with the wrong language is unreviewable.",
    )
    parser.add_argument(
        "--reference-lang",
        action="append",
        default=[],
        help="an already-present language to show the translator beside the pivot "
        "(repeatable); 'en' is always included unless --lang is en",
    )
    parser.add_argument("--sentence-index", help="override the run's data/sentence-index.*.json")
    parser.add_argument("--topics-root", help="e.g. topics — with --topic-id, widens the gap list")
    parser.add_argument("--topic-id")
    parser.add_argument("--manifest", help="topic_manifest.yaml (implied by --topics-root/--topic-id)")
    parser.add_argument("--qa-run", help="analysis/<qa-run-id> dir: questions and answer categories")
    parser.add_argument(
        "--all",
        action="store_true",
        help="emit every unit, not only the ones missing --lang",
    )
    parser.add_argument(
        "--no-seed-group-lexicon",
        action="store_true",
        help="count the three group lexicon tables as gaps in every language, instead of "
        "treating the manifest's own wording as already supplied (apply_localization.py "
        "copies it in)",
    )
    parser.add_argument(
        "--include-non-reader-facing",
        action="store_true",
        help="also emit retired/deprecated fields the renderer never draws",
    )
    parser.add_argument(
        "--allow-unresolved-quotes",
        action="store_true",
        help="emit quote units with no verbatim source sentence (a translator then "
        "guesses; only for a page whose run directory has no data/ island)",
    )
    parser.add_argument("-o", "--out", help="write the packet JSON here")
    args = parser.parse_args(argv)

    lang = normalize_lang(args.lang)
    page_path = Path(args.page)
    page = json.loads(page_path.read_text(encoding="utf-8"))
    sentences, sentence_source = load_sentence_index(page_path, args.sentence_index)
    manifest, question_texts, pivots = load_topic_inputs(
        args.topics_root, args.topic_id, args.manifest
    )
    question_stats = load_question_stats(args.qa_run)

    # In memory only: this script writes no page.  The point is that the gap list matches
    # what ``apply_localization.py`` will actually do, so a translator is never asked for a
    # side name the manifest already carries.
    seeded: list[tuple[str, str, str]] = []
    if manifest and not args.no_seed_group_lexicon:
        seeded = seed_group_lexicon(page, manifest)

    units = enumerate_units(
        page,
        sentences=sentences,
        manifest=manifest,
        question_stats=question_stats,
        question_texts=question_texts,
        topic_pivots=pivots,
    )
    stray = uncovered_lang_maps(page, units)
    if stray:
        print(
            "the page carries language-carrying field(s) this enumerator does not know "
            "about, so a localization run would silently skip them — teach "
            f"localization_units.py about them first:\n  " + "\n  ".join(stray),
            file=sys.stderr,
        )
        return 2

    references: list[str] = []
    if lang != "en":
        references.append("en")
    for ref in args.reference_lang:
        ref = normalize_lang(ref)
        if ref != lang and ref not in references:
            references.append(ref)

    selected = [
        unit
        for unit in units
        if (unit.reader_facing or args.include_non_reader_facing)
        and (args.all or unit.status(lang) == "missing")
    ]
    unresolved = [
        unit.key
        for unit in selected
        if unit.kind == "quote_translation" and not unit.source
    ]

    print(f"page: {page_path}  ({len(units)} localizable units)")
    if sentence_source:
        print(f"sentence index: {sentence_source}  ({len(sentences)} sentences)")
    else:
        print("sentence index: none found beside the page")
    if seeded:
        print(
            f"group lexicon: {len(seeded)} value(s) the topic manifest supplies and the "
            "page does not yet carry — apply_localization.py copies them in verbatim"
        )
    print(render_summary(units, lang))

    if unresolved and not args.allow_unresolved_quotes:
        print(
            f"\n{len(unresolved)} quote unit(s) have no verbatim source sentence: a "
            "translator handed an empty field can only guess. Point --sentence-index at "
            "the run's data/sentence-index.*.json, or pass --allow-unresolved-quotes to "
            "accept the risk.\n  " + "\n  ".join(unresolved[:10]),
            file=sys.stderr,
        )
        return 2

    if args.out:
        packet = {
            "topic_id": page.get("topic_id"),
            "page_run_id": (page.get("provenance") or {}).get("run_id"),
            "lang": lang,
            "reference_langs": references,
            "counts": {kind: counts for kind, counts in summarize(units, lang)[0]},
            "totals": summarize(units, lang)[1],
            "instructions": (
                f"Return a JSON object mapping every 'key' below to its {lang} text. "
                "Do not change any key. Keys are the page's own JSON paths; "
                "apply_localization.py merges the map back and refuses to overwrite a "
                "language the page already carries."
            ),
            "units": [unit.as_json(lang, tuple(references)) for unit in selected],
        }
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"\n{out}: {len(selected)} unit(s) for {lang}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
