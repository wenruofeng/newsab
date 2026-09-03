"""Report-only diagnostics over collect build inputs.

These checks describe the sample and extraction evidence without changing corpus
membership, sentence text, cluster assignment, or build exit status.  Keeping them out of
``staging.py`` is deliberate: staging owns the article transformation, while this module
checks that transformation against adjacent evidence retained on disk.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from newsab_schema.ids import make_article_id
from newsab_schema.models.corpus import Article

from .fetch import _filename_for, visible_text
from .staging import StagingArticle


def _without_whitespace(value: str) -> str:
    """The verbatim comparison allowed by fetch-extract §4.

    Browser-visible whitespace may differ at HTML block boundaries, while punctuation,
    script variants, spelling and every other character must remain identical.
    """

    return "".join(
        character
        for character in unicodedata.normalize("NFC", value)
        if not character.isspace()
    )


def _read_snapshot(path: Path) -> str:
    raw = path.read_bytes()
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        # A few retained pre-fetcher snapshots use the publisher's legacy encoding.  This
        # is the same deterministic fallback used by the measurement that exposed
        # the defect; replacement characters still cannot manufacture a successful hit.
        return raw.decode("gb18030", errors="replace")


@dataclass
class StagedSnapshotVerbatimReport:
    """Sentence-level comparison of staged bodies with retained raw page snapshots."""

    staged_articles: int = 0
    checked_articles: int = 0
    checked_sentences: int = 0
    missing_snapshots: list[dict[str, object]] = field(default_factory=list)
    sentences_not_found: list[dict[str, str]] = field(default_factory=list)
    snapshot_paths: list[Path] = field(default_factory=list, repr=False)

    def to_dict(self) -> dict[str, object]:
        return {
            "raw_projection": "newsab_corpus.fetch.visible_text",
            "comparison": "NFC character-identical after removing whitespace",
            "report_only": True,
            "staged_articles": self.staged_articles,
            "checked_articles": self.checked_articles,
            "checked_sentences": self.checked_sentences,
            "missing_snapshots": self.missing_snapshots,
            "sentences_not_found": self.sentences_not_found,
        }

    def warnings(self) -> list[str]:
        warnings: list[str] = []
        if self.missing_snapshots:
            warnings.append(
                "raw snapshot verbatim check is report-only: "
                f"{len(self.missing_snapshots)} of {self.staged_articles} staged article(s) "
                "have no matching corpus/raw snapshot, so their body sentences could not "
                "be checked"
            )
        missing_by_article: dict[str, list[str]] = {}
        for miss in self.sentences_not_found:
            missing_by_article.setdefault(miss["article_id"], []).append(miss["sentence_id"])
        for article_id, sentence_ids in sorted(missing_by_article.items()):
            warnings.append(
                f"{article_id}: {len(sentence_ids)} staged body sentence(s) are not "
                "character-identical in the raw snapshot's visible text after whitespace "
                "is ignored (report-only, not a build gate): " + " ".join(sentence_ids)
            )
        return warnings


def check_staged_snapshot_verbatim(
    staged: Sequence[tuple[Path, StagingArticle]],
    articles: Sequence[Article],
    raw_dir: Path,
) -> StagedSnapshotVerbatimReport:
    """Compare every built body sentence from current staging with its raw snapshot.

    Headline block ``P00`` is excluded: the measured defect and the extraction promise at
    issue are about staged ``body`` sentences.  Duplicate canonical URLs follow build's
    first-record-wins behavior so the report describes exactly the articles build emitted.
    """

    report = StagedSnapshotVerbatimReport()
    articles_by_id = {article.article_id: article for article in articles}
    seen: set[str] = set()

    for staging_path, entry in staged:
        article_id = make_article_id(entry.group_id.upper(), entry.url)
        if article_id in seen:
            continue
        seen.add(article_id)
        article = articles_by_id.get(article_id)
        if article is None:  # Defensive: build and this check should select identically.
            continue
        report.staged_articles += 1
        body_sentences = [
            (paragraph.index, sentence.index, sentence.text)
            for paragraph in article.structured_text
            if paragraph.index != 0
            for sentence in paragraph.sentences
        ]
        snapshot = raw_dir / _filename_for(entry.url)
        if not snapshot.is_file():
            report.missing_snapshots.append(
                {
                    "article_id": article_id,
                    "staging_file": staging_path.name,
                    "expected_snapshot": snapshot.name,
                    "unchecked_sentences": len(body_sentences),
                }
            )
            continue

        report.snapshot_paths.append(snapshot)
        report.checked_articles += 1
        haystack = _without_whitespace(visible_text(_read_snapshot(snapshot)))
        for paragraph_index, sentence_index, sentence_text in body_sentences:
            report.checked_sentences += 1
            if _without_whitespace(sentence_text) in haystack:
                continue
            sentence_id = f"{article_id}:P{paragraph_index:02d}:S{sentence_index:02d}"
            report.sentences_not_found.append(
                {
                    "article_id": article_id,
                    "sentence_id": sentence_id,
                    "text": sentence_text,
                    "staging_file": staging_path.name,
                    "snapshot": snapshot.name,
                }
            )

    return report
