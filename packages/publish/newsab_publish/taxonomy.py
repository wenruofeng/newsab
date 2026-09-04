"""Folding one reviewer-approved topic-categories decision into site metadata.

The dev shell already writes the reviewer's category choice to disk at touchpoint two
as ``site/private/approvals/topic-categories-<topic_id>-<hash8>.json`` (a
``TopicCategoryApproval``, see ``dev_shell.py``'s ``record_release_approval``).  Getting
that decision into ``SiteMetadata.topic_categories`` — the field ``prepare`` actually reads
— used to mean an agent hand-copying the same category ids into two places (the mapping and
the approvals list) with **zero judgement content**: the file already says everything.  A
hand copy is exactly the kind of step that goes wrong the way a hand copy goes wrong
(a dropped category, a list out of order), and the validator's only recourse is "does not
match" with no repair suggestion.  This module makes the transcription a command instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from newsab_schema.io import ArtifactError
from newsab_schema.paths import SitePaths

from .dev_shell import APPROVALS_DIR
from .metadata import (
    SiteMetadata,
    TopicCategoryApproval,
    default_metadata_path,
    load_site_metadata,
)


@dataclass(frozen=True)
class TaxonomyAdoption:
    """What ``adopt_taxonomy`` did, for the CLI to report."""

    metadata_path: Path
    topic_id: str
    category_ids: tuple[str, ...]
    approval_path: Path
    #: ``"adopted"`` — metadata was written; ``"already-adopted"`` — this exact approval
    #: was already folded in, so nothing changed (idempotent replay).
    status: str


def _find_approval(site_root: str | Path, topic_id: str) -> Path:
    """The sole ``topic-categories-<topic_id>-*.json`` under ``site/private/approvals/``.

    Refuses rather than guessing when there is none (touchpoint two has not proposed
    categories for this topic yet) or more than one (a topic re-reviewed under a
    different page hash) — either way the operator names the file explicitly instead.
    """
    approvals_dir = SitePaths.at(site_root).private_dir / APPROVALS_DIR
    matches = sorted(approvals_dir.glob(f"topic-categories-{topic_id}-*.json"))
    if not matches:
        raise ArtifactError(
            f"no topic-categories approval found for {topic_id} under {approvals_dir}; "
            "take touchpoint two first, or pass --approval <file> explicitly"
        )
    if len(matches) > 1:
        raise ArtifactError(
            f"{len(matches)} topic-categories approvals found for {topic_id} under "
            f"{approvals_dir}: {[str(p) for p in matches]}; pass --approval <file> to "
            "pick the one to adopt"
        )
    return matches[0]


def adopt_taxonomy(
    site_root: str | Path,
    topic_id: str,
    *,
    approval_path: Optional[str | Path] = None,
    metadata_path: Optional[str | Path] = None,
) -> TaxonomyAdoption:
    """Apply one approved ``TopicCategoryApproval`` to a site metadata revision.

    Idempotent on the *same* approval file: adopting it twice (a resumed or re-run
    operation) writes nothing the second time and reports ``"already-adopted"`` rather
    than duplicating the mapping or the approvals-list entry — ``SiteMetadata`` refuses a
    topic id appearing twice in ``topic_category_approvals`` regardless.

    A *different* approval for a topic that already carries one (a different page hash,
    a different category choice) is refused outright: ``SiteMetadata`` allows exactly one
    ``TopicCategoryApproval`` per topic, so switching one is a correction to an already
    recorded human decision, not a mechanical transcription — a human reconciles that by
    hand, this command never replaces a recorded approval.  The same refusal covers a
    topic already named in the one-time ``taxonomy_backfill_approval``, which the schema
    forbids from also carrying a per-topic record.
    """
    resolved_metadata_path = (
        Path(metadata_path) if metadata_path else default_metadata_path()
    )
    metadata = load_site_metadata(resolved_metadata_path)

    resolved_approval_path = (
        Path(approval_path) if approval_path else _find_approval(site_root, topic_id)
    )
    try:
        approval = TopicCategoryApproval.model_validate_json(
            resolved_approval_path.read_text(encoding="utf-8")
        )
    except (OSError, ValueError) as exc:
        raise ArtifactError(
            f"{resolved_approval_path}: invalid TopicCategoryApproval — {exc}"
        ) from exc
    if approval.topic_id != topic_id:
        raise ArtifactError(
            f"{resolved_approval_path} approves {approval.topic_id!r}, not {topic_id!r}"
        )

    backfilled = set(
        metadata.taxonomy_backfill_approval.topic_ids
        if metadata.taxonomy_backfill_approval is not None
        else ()
    )
    if topic_id in backfilled:
        raise ArtifactError(
            f"{topic_id} is already covered by the taxonomy backfill approval "
            f"({metadata.taxonomy_backfill_approval.approval_id}); it must not also carry "
            "a per-topic approval, so there is nothing to adopt"
        )

    existing_mapping = metadata.topic_categories.get(topic_id)
    existing_approval = next(
        (a for a in metadata.topic_category_approvals if a.topic_id == topic_id), None
    )
    if existing_mapping is not None or existing_approval is not None:
        same = (
            existing_mapping == list(approval.category_ids)
            and existing_approval is not None
            and existing_approval == approval
        )
        if same:
            return TaxonomyAdoption(
                metadata_path=resolved_metadata_path,
                topic_id=topic_id,
                category_ids=tuple(approval.category_ids),
                approval_path=resolved_approval_path,
                status="already-adopted",
            )
        raise ArtifactError(
            f"{topic_id} already carries a different topic-categories decision "
            f"({existing_approval.approval_id if existing_approval else '?'}: "
            f"{existing_mapping}) than {resolved_approval_path} names "
            f"({approval.approval_id}: {list(approval.category_ids)}) — reconcile by "
            "hand; this command never replaces a recorded decision"
        )

    updated = metadata.model_dump(mode="json")
    updated["topic_categories"] = {
        **metadata.topic_categories,
        topic_id: list(approval.category_ids),
    }
    updated["topic_category_approvals"] = [
        *[a.model_dump(mode="json") for a in metadata.topic_category_approvals],
        approval.model_dump(mode="json"),
    ]
    new_metadata = SiteMetadata.model_validate(updated)
    resolved_metadata_path.write_text(
        new_metadata.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    return TaxonomyAdoption(
        metadata_path=resolved_metadata_path,
        topic_id=topic_id,
        category_ids=tuple(approval.category_ids),
        approval_path=resolved_approval_path,
        status="adopted",
    )
