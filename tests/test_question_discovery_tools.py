"""Deterministic question-discovery helpers."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from newsab_schema.models.corpus import compute_set_hash
from newsab_schema.ids import make_article_id

from pipeline_fixture import CORPUS_RUN_ID, TOPIC, build_topic

pytestmark = pytest.mark.cli_e2e

REPO = Path(__file__).resolve().parents[1]
DIGEST = REPO / "skills" / "annotate" / "scripts" / "corpus_digest.py"
PROBE = REPO / "skills" / "annotate" / "scripts" / "corpus_probe.py"
TOPICS_CHECK = REPO / "skills" / "collect" / "scripts" / "check_topics_raised.py"


def _run(*args: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *(str(arg) for arg in args)],
        cwd=REPO,
        text=True,
        capture_output=True,
        check=False,
    )


def test_digest_reads_each_cluster_but_only_two_body_paragraphs(tmp_path):
    build_topic(tmp_path, clusters_per_category=1)
    result = _run(DIGEST, tmp_path / "topics", TOPIC)
    assert result.returncode == 0, result.stderr
    assert "clusters: 4" in result.stdout
    assert result.stdout.count("## RC-") == 4
    assert "P01:" in result.stdout
    assert "P02:" not in result.stdout  # fixture articles have only one body paragraph


def test_probe_requires_native_terms_for_every_side_and_logs_budget(tmp_path):
    build_topic(tmp_path, clusters_per_category=1)
    log = tmp_path / "probe.jsonl"
    refused = _run(
        PROBE, "search", tmp_path / "topics", TOPIC,
        "--term", "cn=Body", "--log", log,
    )
    assert refused.returncode == 2
    assert "exactly one native term per side" in refused.stderr

    result = _run(
        PROBE, "search", tmp_path / "topics", TOPIC,
        "--term", "cn=Body", "--term", "us=Body", "--log", log,
    )
    assert result.returncode == 0, result.stderr
    assert "# cn: term='Body' | matched_clusters=2" in result.stdout
    record = json.loads(log.read_text(encoding="utf-8"))
    assert record["terms"] == {"cn": "Body", "us": "Body"}
    assert record["kind"] == "probe"


def test_topics_raised_phrases_are_extractive_and_pivots_are_tallied(tmp_path):
    paths = build_topic(tmp_path, clusters_per_category=1)
    staging = paths.corpus_dir / "staging"
    staging.mkdir(parents=True, exist_ok=True)
    articles = {
        "cn-one.yaml": {
            "group_id": "cn", "url": "https://example.com/cn/001", "title": "签证与大学",
            "subtitle": "", "body": "国家安全审查。学生签证限制。大学财政。",
        },
        "us-one.yaml": {
            "group_id": "us", "url": "https://example.com/us/001", "title": "Visas and colleges",
            "subtitle": "", "body": "Security screening. Student visa limits. University finances.",
        },
    }
    records = []
    for filename, article in articles.items():
        (staging / filename).write_text(json.dumps(article, ensure_ascii=False), encoding="utf-8")
        phrases = (
            [("国家安全审查", "national security screening"),
             ("学生签证限制", "student visa restrictions"), ("大学财政", "university finances")]
            if article["group_id"] == "cn"
            else [("Security screening", "national security screening"),
                  ("Student visa limits", "student visa restrictions"),
                  ("University finances", "university finances")]
        )
        records.append(
            {
                "staging_file": filename,
                "topics_raised": [
                    {"source_phrase": source, "pivot_en": pivot} for source, pivot in phrases
                ],
                "provenance": {
                    "skill_version": "0.10.0", "model_id": "fixture-model",
                    "run_id": "collection-fixture", "timestamp": "2026-08-22T00:00:00Z",
                },
            }
        )
    artifact = paths.topics_raised
    artifact.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )

    result = _run(TOPICS_CHECK, tmp_path / "topics", TOPIC, artifact)
    assert result.returncode == 0, result.stderr
    assert "OK 2 article record(s); tally unit: cluster" in result.stdout
    assert "student visa restrictions\t1\t1" in result.stdout
    # Rates, not just counts: the two sides routinely differ in size, and a raw count
    # inverts whenever they do — every reader of this table is hunting an asymmetry.
    assert "denominator\t" in result.stdout
    header = next(line for line in result.stdout.splitlines() if line.startswith("pivot_en\t"))
    assert header.split("\t")[-2:] == ["cn%", "us%"]
    row = next(line for line in result.stdout.splitlines()
               if line.startswith("student visa restrictions\t"))
    assert row.split("\t")[-2:] == ["50%", "50%"]  # 1 of 2 clusters on each side

    bad = artifact.read_text(encoding="utf-8").replace("学生签证限制", "正文里没有")
    artifact.write_text(bad, encoding="utf-8")
    refused = _run(TOPICS_CHECK, tmp_path / "topics", TOPIC, artifact)
    assert refused.returncode == 1
    assert "source_phrase is not verbatim" in refused.stderr


def test_topics_raised_does_not_require_a_record_for_a_withdrawn_article(tmp_path):
    """A staging file the active run withdrew is out of the sample, so it needs no record.

    Requiring one is unsatisfiable: writing the record trips the membership check, and
    omitting it used to trip the coverage check — which left every corpus that had ever
    withdrawn an article unable to pass this checker at all.
    """
    paths = build_topic(tmp_path, clusters_per_category=1)
    staging = paths.corpus_dir / "staging"
    staging.mkdir(parents=True, exist_ok=True)
    urls = {
        "cn-one.yaml": "https://example.com/cn/001",
        "cn-two.yaml": "https://example.com/cn/002",
    }
    for filename, url in urls.items():
        (staging / filename).write_text(
            json.dumps(
                {"group_id": "cn", "url": url, "title": "Student visa limits",
                 "subtitle": "", "body": "University finances. Security screening."},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def _write_run(withdrawn: list[dict]) -> None:
        run_file = paths.stage_run_dir("corpus", CORPUS_RUN_ID) / "corpus_run.json"
        run = json.loads(run_file.read_text(encoding="utf-8"))
        dropped = {entry["article_id"] for entry in withdrawn} | {second}
        run["articles"] = [a for a in run["articles"] if a["article_id"] not in dropped]
        run["withdrawn"] = withdrawn
        run["set_hash"] = compute_set_hash(
            {a["article_id"]: a["content_hash"] for a in run["articles"]}
        )
        run_file.write_text(json.dumps(run, ensure_ascii=False), encoding="utf-8")

    def _record(filename: str) -> dict:
        return {
            "staging_file": filename,
            "topics_raised": [
                {"source_phrase": "Student visa limits", "pivot_en": "student visa restrictions"},
                {"source_phrase": "University finances", "pivot_en": "university finances"},
                {"source_phrase": "Security screening", "pivot_en": "national security screening"},
            ],
            "provenance": {
                "skill_version": "0.12.0", "model_id": "fixture-model",
                "run_id": "collection-fixture", "timestamp": "2026-08-23T00:00:00Z",
            },
        }

    second = make_article_id("CN", urls["cn-two.yaml"])
    artifact = paths.topics_raised
    artifact.write_text(json.dumps(_record("cn-one.yaml"), ensure_ascii=False) + "\n", "utf-8")

    _write_run([{"article_id": second, "reason": "carrier page", "at": "2026-08-23T00:00:00Z"}])
    result = _run(TOPICS_CHECK, tmp_path / "topics", TOPIC, artifact)
    assert result.returncode == 0, result.stderr
    assert "cn-two.yaml" not in result.stdout + result.stderr

    # A staged article that is neither a member nor withdrawn is still rejected, record or not.
    _write_run([])
    artifact.write_text(
        "".join(json.dumps(_record(name), ensure_ascii=False) + "\n" for name in urls),
        encoding="utf-8",
    )
    refused = _run(TOPICS_CHECK, tmp_path / "topics", TOPIC, artifact)
    assert refused.returncode == 1
    assert "not members of the active corpus run" in refused.stderr
    assert "cn-two.yaml" in refused.stderr
