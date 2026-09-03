"""``page_init.py`` must not undo reader wording that a human already approved.

The reader lexicon is the one part of a page draft that is *not* derivable from the
artifacts: the annotation question is written for an annotator, a category is a counting
key, a collect-stage pivot is a cross-language concept key.  Regenerating those maps on
every rerun silently reverts every rewording the reviewer asked for — a divergence headline
came back with a misleading statistic in it exactly one rerun after it was edited out.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from pipeline_fixture import TOPIC, build_topic, run_script

pytestmark = pytest.mark.cli_e2e

from newsab_schema.ids import make_article_id
from newsab_schema.paths import TopicPaths

QA_RUN = "qa-20260828191023151265-8617269e"
ANNOTATION_WORDING = (
    "What is presented as the problem — the new rules themselves, or what they respond to, "
    "given that 51% of reports frame it the first way?"
)
READER_WORDING = "What does Mongolia actually get from this deal?"


def _prepare(base: Path) -> TopicPaths:
    """A topic with an analysis run page_init can read, and one collect-stage pivot."""
    paths = build_topic(base)

    run_dir = paths.root / "analysis" / QA_RUN
    run_dir.mkdir(parents=True, exist_ok=True)
    stats = {
        "questions": {
            "QST-fixture-001": {
                "question": ANNOTATION_WORDING,
                "groups": {
                    group: {"category_counts": {"tighter_rules": 3, "student_costs": 1}}
                    for group in ("cn", "us")
                },
            }
        }
    }
    (run_dir / "question_stats.json").write_text(json.dumps(stats), encoding="utf-8")
    finding = {
        "finding_id": "FND-fixture-001",
        "question_id": "QST-fixture-001",
        "kind": "divergence",
        "strength": "supported",
        "groups": [
            {
                "group_id": group,
                "top_category": "tighter_rules",
                "top_category_tied": False,
                "category_counts": {"tighter_rules": 3, "student_costs": 1},
                "clusters_total": 8,
                "clusters_addressed": 4,
                "sample_evidence": [f"{group.upper()}_fixture:P01:S01"],
            }
            for group in ("cn", "us")
        ],
    }
    (run_dir / "findings.jsonl").write_text(json.dumps(finding) + "\n", encoding="utf-8")

    active = json.loads(paths.active_versions.read_text(encoding="utf-8"))
    active.update({"questions": "qst-fixture", "answers": "ans-fixture"})
    paths.active_versions.write_text(json.dumps(active), encoding="utf-8")

    # topics_raised is keyed by staging file, so the join needs the staging file too.
    paths.staging_dir.mkdir(parents=True, exist_ok=True)
    url = "https://example.com/cn/001"
    (paths.staging_dir / "a.yaml").write_text(
        yaml.safe_dump({"group_id": "cn", "url": url}), encoding="utf-8"
    )
    make_article_id("CN", url)  # the id the loader recomputes; malformed input would raise
    paths.topics_raised.write_text(
        json.dumps(
            {
                "staging_file": "a.yaml",
                "topics_raised": [
                    {"pivot_en": "student visa backlog", "source_phrase": "签证积压"}
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return paths


def _init(base: Path, *args: str) -> dict:
    out = base / "draft_page.json"
    result = run_script(
        "skills/write/scripts/page_init.py",
        str(base / "topics"),
        TOPIC,
        "--qa-run",
        QA_RUN,
        "-o",
        str(out),
        *args,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(out.read_text(encoding="utf-8"))


def test_a_first_draft_falls_back_to_the_machine_vocabulary(tmp_path):
    paths = _prepare(tmp_path)
    assert not paths.editorial_page.is_file()

    draft = _init(tmp_path)

    lexicon = draft["lexicon"]
    assert lexicon["questions"]["QST-fixture-001"]["values"]["en"] == ANNOTATION_WORDING
    assert lexicon["categories"]["tighter_rules"]["values"]["en"] == "tighter rules"
    # Every displayed pivot gets an entry, or page-check fails the draft outright.
    assert lexicon["topics"] == {
        "student visa backlog": {"values": {"en": "student visa backlog"}}
    }
    assert lexicon["scope"] == {}


def test_the_next_draft_inherits_the_wording_a_reviewer_approved(tmp_path):
    paths = _prepare(tmp_path)
    previous = paths.root / "editorial" / "page.json"
    previous.parent.mkdir(parents=True, exist_ok=True)
    previous.write_text(
        json.dumps(
            {
                "how_we_counted": {"questions_run_id": "qst-fixture"},
                "lexicon": {
                    "questions": {
                        "QST-fixture-001": {
                            "values": {"en": READER_WORDING, "zh-CN": "蒙古国究竟得到什么?"}
                        }
                    },
                    "categories": {"tighter_rules": {"values": {"en": "the rules got tighter"}}},
                    "topics": {"student visa backlog": {"values": {"en": "the visa queue"}}},
                    "scope": {
                        "the synthetic policy round": {"values": {"en": "this policy round"}}
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    draft = _init(tmp_path)

    lexicon = draft["lexicon"]
    question = lexicon["questions"]["QST-fixture-001"]["values"]
    assert question["en"] == READER_WORDING
    assert question["zh-CN"] == "蒙古国究竟得到什么?"
    assert lexicon["categories"]["tighter_rules"]["values"]["en"] == "the rules got tighter"
    assert lexicon["topics"]["student visa backlog"]["values"]["en"] == "the visa queue"
    # The manifest's English is what the scope approval hashed, so its reader wording can
    # only ever be inherited — there is nothing to generate it from.
    assert lexicon["scope"]["the synthetic policy round"]["values"]["en"] == "this policy round"

    # A deliberate rewrite still gets a blank slate.
    blank = _init(tmp_path, "--no-inherit")
    assert blank["lexicon"]["questions"]["QST-fixture-001"]["values"]["en"] == ANNOTATION_WORDING
    assert blank["lexicon"]["scope"] == {}
