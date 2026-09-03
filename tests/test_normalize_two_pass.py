"""The normalize stage's second pass is conditional, and every run records it.

The rule these tests pin is arithmetic, not taste: `intersect` is a set intersection, so
`agreed = A ∩ B ⊆ A`.  A second pass can only ever remove groups — on a question pass A
left alone it cannot change the outcome, and running it there is a proven no-op
(measured over five real topics).  `assemble` therefore refuses a run that does not say
what the second pass was asked to do.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from newsab_schema.io import write_jsonl, write_yaml
from newsab_schema.models.qa import ClusterAnswer, Question, QuestionSet
from newsab_schema.paths import TopicPaths

pytestmark = pytest.mark.cli_e2e

REPO = Path(__file__).resolve().parents[1]
CHECK_MAP = REPO / "skills" / "normalize" / "scripts" / "check_map.py"
TOPIC = "aabb-river-light-2026"
QUESTION = "QST-aabb-river-light-001"
OTHER_QUESTION = "QST-aabb-river-light-002"
RUN_ID = "nrm-20260824010203040506-aabbccdd"
#: The fixture topic has no manifest, so `assemble` and `_as_map` both name its
#: answers run with the same "unversioned" sentinel a real topic never uses.
ANSWERS_RUN = "unversioned"


def _run(*args: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *(str(a) for a in args)],
        cwd=REPO,
        text=True,
        capture_output=True,
        check=False,
    )


def _provenance(run_id: str = "qst-20260824000000000000-00000001") -> dict:
    return {
        "skill_version": "fixture-0.1.0",
        "model_id": "fixture-model",
        "run_id": run_id,
        "timestamp": "2026-08-24T00:00:00Z",
    }


def _question(question_id: str) -> Question:
    return Question.model_validate(
        {
            "question_id": question_id,
            "topic_id": TOPIC,
            "tier": "reader",
            "text": {"values": {"en": "Who is blamed?"}},
            "rationale": {"text": "fixture", "lang": "en"},
            "category_guidance": {"text": "one actor per answer", "lang": "en"},
            "provenance": _provenance(),
        }
    )


def _answer(serial: int, question_id: str, group: str, category: str) -> ClusterAnswer:
    prefix = group.upper()
    return ClusterAnswer.model_validate(
        {
            "answer_id": f"ANS-aabb-river-light-{serial:06d}",
            "topic_id": TOPIC,
            "question_id": question_id,
            "question_set_version": "qst-20260824000000000000-00000001",
            "reporting_cluster_id": f"RC-{prefix}-{serial:08x}",
            "group_id": group,
            "addressed": True,
            "answer_summary": {"text": "An answer.", "lang": "en"},
            "answer_category": category,
            "evidence": [f"{prefix}_{serial:08x}:P01:S01"],
            "provenance": _provenance("ans-20260824000000000000-00000001"),
        }
    )


def _topic(tmp_path: Path) -> tuple[Path, TopicPaths]:
    """A topic carrying only what the normalize stage reads: questions and answers."""
    topics_root = tmp_path / "topics"
    paths = TopicPaths.for_topic(topics_root, TOPIC).ensure()
    write_yaml(
        paths.questions,
        QuestionSet(
            topic_id=TOPIC,
            question_set_version="qst-20260824000000000000-00000001",
            questions=[_question(QUESTION), _question(OTHER_QUESTION)],
            provenance=_provenance(),
        ),
    )
    answers = []
    serial = 0
    for question_id in (QUESTION, OTHER_QUESTION):
        for group in ("cn", "us"):
            for category in ("us_government", "us_state_department", "universities"):
                serial += 1
                answers.append(_answer(serial, question_id, group, category))
    write_jsonl(paths.answers, answers)
    paths.stage_run_dir("normalization", RUN_ID).mkdir(parents=True)
    return topics_root, paths


def _draft(*questions: str) -> dict:
    group = {
        "canonical": "us_government",
        "members": ["us_government", "us_state_department"],
        "rationale": {"text": "Same actor, same direction.", "lang": "en"},
    }
    return {"merges": {q: [group] for q in questions}}


def _write(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _assemble(topics_root: Path, draft: Path, record: dict):
    return _run(
        CHECK_MAP, "assemble", topics_root, TOPIC, draft,
        "--run-id", RUN_ID, "--model-id", "fixture-model",
        "--two-pass-json", json.dumps(record),
    )


# --- plan: what a second pass could still change ---------------------------------------


def test_plan_skips_the_second_pass_when_pass_a_drew_nothing(tmp_path):
    draft = _write(tmp_path / "a.json", {"merges": {}})
    result = _run(CHECK_MAP, "plan", draft, "--answers-run-id", ANSWERS_RUN)
    assert result.returncode == 0, result.stderr
    assert "skip the second pass" in result.stdout
    skeleton = json.loads(result.stdout.strip().splitlines()[-1])
    assert skeleton == {
        "answers_run_id": ANSWERS_RUN,
        "pass_a_groups": 0,
        "pass_b_questions": [],
        "pass_b_groups": None,
        "dropped": 0,
    }


def test_plan_scopes_the_second_pass_to_the_questions_pass_a_touched(tmp_path):
    draft = _write(tmp_path / "a.json", _draft(QUESTION))
    result = _run(CHECK_MAP, "plan", draft)
    assert result.returncode == 0, result.stderr
    assert "pass B is owed" in result.stdout
    assert QUESTION in result.stdout
    # The untouched question is out of scope: no merge there can survive an intersection
    # with a draft that has none.
    assert OTHER_QUESTION not in result.stdout


# --- assemble: the run must say what the second pass did -------------------------------


def test_assemble_refuses_without_a_two_pass_record(tmp_path):
    topics_root, _ = _topic(tmp_path)
    draft = _write(tmp_path / "a.json", {"merges": {}})
    result = _run(
        CHECK_MAP, "assemble", topics_root, TOPIC, draft,
        "--run-id", RUN_ID, "--model-id", "fixture-model",
    )
    assert result.returncode == 2
    assert "--two-pass-json" in result.stderr


def test_skipped_second_pass_is_recorded_as_an_artifact(tmp_path):
    topics_root, paths = _topic(tmp_path)
    draft = _write(tmp_path / "a.json", {"merges": {}})
    result = _assemble(
        topics_root, draft,
        {"answers_run_id": ANSWERS_RUN, "pass_a_groups": 0, "pass_b_questions": [], "pass_b_groups": None, "dropped": 0,
         "sent_upstream": "Q002 residual bucket mixes two answers"},
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert "second pass: skipped (pass A drew nothing)" in result.stdout
    run_dir = paths.stage_run_dir("normalization", RUN_ID)
    record = json.loads((run_dir / "two_pass.json").read_text(encoding="utf-8"))
    assert record["pass_b_groups"] is None
    assert record["sent_upstream"].startswith("Q002")
    assert json.loads((run_dir / "category_map.json").read_text(encoding="utf-8"))["merges"] == {}


def test_a_second_pass_run_where_pass_a_drew_nothing_is_rejected(tmp_path):
    topics_root, _ = _topic(tmp_path)
    draft = _write(tmp_path / "a.json", {"merges": {}})
    result = _assemble(
        topics_root, draft,
        {"answers_run_id": ANSWERS_RUN, "pass_a_groups": 0, "pass_b_questions": [QUESTION], "pass_b_groups": 1, "dropped": 1},
    )
    assert result.returncode == 1
    assert "the intersection is empty whatever the second pass says" in result.stderr


def test_surviving_groups_still_require_a_second_pass(tmp_path):
    topics_root, _ = _topic(tmp_path)
    draft = _write(tmp_path / "a.json", _draft(QUESTION))
    result = _assemble(
        topics_root, draft,
        {"answers_run_id": ANSWERS_RUN, "pass_a_groups": 1, "pass_b_questions": [], "pass_b_groups": None, "dropped": 0},
    )
    assert result.returncode == 1
    assert "a second pass is owed" in result.stderr


def test_a_map_group_the_second_pass_never_judged_is_rejected(tmp_path):
    topics_root, _ = _topic(tmp_path)
    draft = _write(tmp_path / "a.json", _draft(QUESTION, OTHER_QUESTION))
    result = _assemble(
        topics_root, draft,
        {"answers_run_id": ANSWERS_RUN, "pass_a_groups": 2, "pass_b_questions": [QUESTION], "pass_b_groups": 2, "dropped": 0},
    )
    assert result.returncode == 1
    assert OTHER_QUESTION in result.stderr


def test_dropped_must_match_the_two_drafts(tmp_path):
    topics_root, _ = _topic(tmp_path)
    draft = _write(tmp_path / "a.json", _draft(QUESTION))
    bad = _assemble(
        topics_root, draft,
        {"answers_run_id": ANSWERS_RUN, "pass_a_groups": 2, "pass_b_questions": [QUESTION, OTHER_QUESTION],
         "pass_b_groups": 2, "dropped": 0},
    )
    assert bad.returncode == 1
    assert "does not match the drafts" in bad.stderr

    good = _assemble(
        topics_root, draft,
        {"answers_run_id": ANSWERS_RUN, "pass_a_groups": 2, "pass_b_questions": [QUESTION, OTHER_QUESTION],
         "pass_b_groups": 2, "dropped": 2},
    )
    assert good.returncode == 0, good.stderr + good.stdout
    assert "dropped 2" in good.stdout


def test_unknown_keys_cannot_hide_in_the_record(tmp_path):
    topics_root, _ = _topic(tmp_path)
    draft = _write(tmp_path / "a.json", {"merges": {}})
    result = _assemble(
        topics_root, draft,
        {"answers_run_id": ANSWERS_RUN, "pass_a_groups": 0, "pass_b_questions": [], "pass_b_groups": None, "dropped": 0,
         "notes": "free text"},
    )
    assert result.returncode == 1
    assert "unknown key" in result.stderr


def test_both_artifacts_are_immutable(tmp_path):
    topics_root, _ = _topic(tmp_path)
    draft = _write(tmp_path / "a.json", {"merges": {}})
    record = {"answers_run_id": ANSWERS_RUN, "pass_a_groups": 0, "pass_b_questions": [], "pass_b_groups": None, "dropped": 0}
    assert _assemble(topics_root, draft, record).returncode == 0
    again = _assemble(topics_root, draft, record)
    assert again.returncode == 1
    assert "refusing to overwrite immutable artifact" in again.stderr


# --- intersect: unchanged behaviour, plus the wasted-pass note -------------------------


def test_intersect_notes_a_second_pass_that_could_not_have_mattered(tmp_path):
    a = _write(tmp_path / "a.json", {"merges": {}})
    b = _write(tmp_path / "b.json", _draft(QUESTION))
    out = tmp_path / "agreed.json"
    result = _run(CHECK_MAP, "intersect", a, b, "--out", out)
    assert result.returncode == 0, result.stderr
    assert "pass A drew no groups" in result.stdout
    assert json.loads(out.read_text(encoding="utf-8"))["merges"] == {}


def test_intersect_keeps_only_what_both_passes_drew(tmp_path):
    a = _write(tmp_path / "a.json", _draft(QUESTION, OTHER_QUESTION))
    b = _write(tmp_path / "b.json", _draft(QUESTION))
    out = tmp_path / "agreed.json"
    result = _run(CHECK_MAP, "intersect", a, b, "--out", out)
    assert result.returncode == 0, result.stderr
    assert "agreed groups: 1 · dropped: 1" in result.stdout
    assert list(json.loads(out.read_text(encoding="utf-8"))["merges"]) == [QUESTION]


# --- the record names the answers run its two passes judged ---------------------------


def test_a_record_that_does_not_name_an_answers_run_is_refused(tmp_path):
    topics_root, _ = _topic(tmp_path)
    draft = _write(tmp_path / "a.json", {"merges": {}})
    result = _assemble(
        topics_root,
        draft,
        {"pass_a_groups": 0, "pass_b_questions": [], "pass_b_groups": None, "dropped": 0},
    )
    assert result.returncode == 1
    assert "answers_run_id" in result.stderr


def test_a_record_copied_from_another_answers_run_is_refused(tmp_path):
    # Two normalize runs have been filed whose two_pass.json were byte-identical while
    # claiming to have judged different answers runs.  Naming the run is what makes the
    # copy-forward visible: the record cannot travel to a different answers run silently.
    topics_root, _ = _topic(tmp_path)
    draft = _write(tmp_path / "a.json", {"merges": {}})
    stale = {
        "answers_run_id": "ans-20260824000000000000-00000001",
        "pass_a_groups": 0,
        "pass_b_questions": [],
        "pass_b_groups": None,
        "dropped": 0,
    }
    result = _assemble(topics_root, draft, stale)
    assert result.returncode == 1
    assert "ans-20260824000000000000-00000001" in result.stderr
    assert ANSWERS_RUN in result.stderr
    assert not (
        TopicPaths.for_topic(topics_root, TOPIC).stage_run_dir("normalization", RUN_ID)
        / "two_pass.json"
    ).exists()


def test_the_written_record_keeps_the_answers_run_it_names(tmp_path):
    topics_root, paths = _topic(tmp_path)
    draft = _write(tmp_path / "a.json", {"merges": {}})
    record = {
        "answers_run_id": ANSWERS_RUN,
        "pass_a_groups": 0,
        "pass_b_questions": [],
        "pass_b_groups": None,
        "dropped": 0,
    }
    assert _assemble(topics_root, draft, record).returncode == 0
    run_dir = paths.stage_run_dir("normalization", RUN_ID)
    written = json.loads((run_dir / "two_pass.json").read_text(encoding="utf-8"))
    assert written["answers_run_id"] == ANSWERS_RUN
    # Both artifacts of the run name the same answers run — that is the pairing a later
    # reader checks the record against.
    cmap = json.loads((run_dir / "category_map.json").read_text(encoding="utf-8"))
    assert cmap["answers_run_id"] == written["answers_run_id"]
