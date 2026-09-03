#!/usr/bin/env python3
"""Build the fictional eight-stage demo and publish it into a caller-owned directory.

No model, network request, production topic, site state, credential, or current clock is
used.  The destination must be absent or empty; the checked-in example is never modified.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
for package in ("schema", "corpus", "a1", "editorial", "publish"):
    sys.path.insert(0, str(REPO / "packages" / package))

import demo_fixture as fx  # noqa: E402
from newsab_publish.builder import (  # noqa: E402
    activate_publication,
    default_theme_registry_path,
    prepare_publication,
    render_candidate_bundle,
    resolve_inputs,
    verify_candidate,
    verify_site,
)
from newsab_publish.themes import load_theme_registry, resolve_theme  # noqa: E402
from newsab_schema.io import read_jsonl  # noqa: E402
from newsab_schema.models.findings import QAFinding  # noqa: E402
from newsab_schema.models.publication import (  # noqa: E402
    HumanApproval,
    PublicationReview,
)
from newsab_schema.store import load_corpus_run  # noqa: E402


FIXED_BUILD_DATE = date(2026, 8, 29)
FIXED_REVIEW_TIME = datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc)
FIXED_ACTIVATION_TIME = datetime(2026, 8, 29, 12, 5, tzinfo=timezone.utc)
DEMO_ORIGIN = "https://example.com"


class DemoError(RuntimeError):
    pass


def _semantic_finding(finding: QAFinding) -> dict:
    """Fields the analyzer owns, excluding the fixed fixture run provenance."""
    return finding.model_dump(
        mode="json",
        exclude={"provenance"},
        exclude_none=True,
    )


def _assert_analysis_reproduces(paths: object) -> list[QAFinding]:
    stored = read_jsonl(paths.a1_run_dir(fx.QA_RUN_ID) / "findings.jsonl", QAFinding)
    corpus_run = load_corpus_run(paths, fx.CORPUS_RUN_ID)
    recomputed = fx.recompute_analysis(corpus_run).findings
    if [_semantic_finding(row) for row in stored] != [
        _semantic_finding(row) for row in recomputed
    ]:
        raise DemoError("newsab_a1 did not reproduce the checked-in synthetic findings")
    kinds = {row.kind.value for row in stored}
    expected = {"consensus", "divergence", "attention_gap"}
    if kinds != expected:
        raise DemoError(f"synthetic findings are {sorted(kinds)}, expected {sorted(expected)}")
    return stored


def build(destination: Path) -> dict:
    destination = destination.resolve()
    if destination.exists() and any(destination.iterdir()):
        raise DemoError(f"destination must be absent or empty: {destination}")
    destination.mkdir(parents=True, exist_ok=True)

    topics_root = destination / "topics"
    site_root = destination / "site"
    metadata_path = destination / "site_metadata.json"
    paths = fx.build_topic(topics_root)
    findings = _assert_analysis_reproduces(paths)
    metadata = fx.build_metadata(metadata_path)

    review_render = destination / "review-render"
    review_render.mkdir()
    resolved = resolve_inputs(topics_root, fx.TOPIC_ID, fx.PAGE_RUN_ID)
    theme = resolve_theme(None, load_theme_registry(default_theme_registry_path()))
    bundles, _, _ = render_candidate_bundle(
        resolved,
        metadata.locales,
        review_render,
        m2=True,
        theme=theme,
    )
    review_hash = next(
        bundle.page_hash for bundle in bundles if bundle.locale == fx.REVIEW_LOCALE
    )
    review = PublicationReview(
        approval_id="APR-aabb-river-light-0123abcd",
        reviewer_id="synthetic-reviewer",
        decided_at=FIXED_REVIEW_TIME,
        locale=fx.REVIEW_LOCALE,
        page_hash=review_hash,
    )
    publication = prepare_publication(
        topics_root,
        site_root,
        fx.TOPIC_ID,
        page_run_id=fx.PAGE_RUN_ID,
        review=review,
        metadata=metadata,
        metadata_path=metadata_path,
    )
    verify_candidate(topics_root, site_root, publication.publication_id)

    production = site_root / "public"
    activation = HumanApproval(
        approval_id="APR-aabb-river-light-1123abcd",
        reviewer_id="synthetic-reviewer",
        decided_at=FIXED_ACTIVATION_TIME,
    )
    event = activate_publication(
        topics_root,
        site_root,
        publication.publication_id,
        approval=activation,
        metadata=metadata,
        production_dir=production,
        base_url=DEMO_ORIGIN,
        build_date=FIXED_BUILD_DATE,
        now=FIXED_ACTIVATION_TIME,
    )
    site_fingerprint = verify_site(
        topics_root, site_root, production, metadata=metadata
    )
    result = {
        "schema_version": "synthetic-demo-result-0.1.0",
        "topic_id": fx.TOPIC_ID,
        "publication_id": publication.publication_id,
        "event_id": event.event_id,
        "finding_kinds": [row.kind.value for row in findings],
        "clusters_per_group": {"aa": 3, "bb": 3},
        "articles": len(fx.ARTICLES),
        "syndicated_articles": 1,
        "review_locale": fx.REVIEW_LOCALE,
        "review_page_sha256": review_hash,
        "production_fingerprint": site_fingerprint,
        "preview": f"/{fx.REVIEW_LOCALE}/topics/{fx.TOPIC_ID}/",
        "candidate_verified": True,
        "site_verified": True,
    }
    (destination / "demo-result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args(argv)
    try:
        result = build(args.destination)
    except (DemoError, OSError, ValueError) as exc:
        print(f"synthetic demo refused: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
