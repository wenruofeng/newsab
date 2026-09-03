from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml
from newsab_schema.models.corpus import ScopeApproval
from newsab_schema.ids import RUN_ID_RE

ROOT = Path(__file__).resolve().parents[1]
SCOPE_TOOL = ROOT / "skills" / "scope" / "scripts" / "scope_tool.py"
QA_BATCH = ROOT / "skills" / "annotate" / "scripts" / "qa_batch.py"


def _env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = ":".join(
        str(ROOT / "packages" / name)
        for name in ("schema", "corpus", "a1", "editorial")
    )
    return env


def _manifest() -> dict:
    now = datetime(2026, 8, 24, tzinfo=timezone.utc).isoformat()
    return {
        "topic_id": "test-seeds-2026",
        "title": {"values": {"en": "Question seed test"}},
        "status": "candidate",
        "groups": [
            {
                "group_id": group,
                "prefix": group.upper(),
                "label": {"values": {"en": f"{group} coverage"}},
                "short_label": {"values": {"en": f"{group} side"}},
                "definition": {"values": {"en": f"Coverage produced by {group} newsrooms"}},
            }
            for group in ("aa", "bb")
        ],
        "period": {"start": "2026-01-01", "end": None},
        "include": ["reporting about the test policy"],
        "exclude": [],
        "risk_level": "low",
        "seed_questions": [],
        "target_clusters_per_group": {"aa": 2, "bb": 2},
        "review_locale": "zh-CN",
        "provenance": {
            "skill_version": "scope-0.6.0",
            "model_id": "test-model",
            "run_id": "scope-20260824000000",
            "timestamp": now,
        },
    }


def _topic(tmp_path: Path, candidates: list[dict]) -> Path:
    topics = tmp_path / "topics"
    topic = topics / "test-seeds-2026"
    (topic / "scope").mkdir(parents=True)
    (topic / "topic_manifest.yaml").write_text(
        yaml.safe_dump(_manifest(), allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    (topic / "scope" / "collection_plan.md").write_text(
        "# Plan\n\nBoth groups use their own terms and public news channels.\n",
        encoding="utf-8",
    )
    (topic / "scope" / "question_candidates.yaml").write_text(
        yaml.safe_dump(
            {"candidates": candidates, "review_record": None},
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return topics


def _candidate(seed_id: str, *, approved: bool, required: bool, question: str) -> dict:
    return {
        "candidate_id": seed_id,
        "text": {"values": {"en": question}},
        "why": "One short scope-only discovery note.",
        "signals": [{"lang": "en", "url": "https://example.org/q", "wording": question}],
        "review": {"approved": approved, "required": required},
    }


def test_legacy_stand_in_approval_remains_truthful_without_topic_rewrite() -> None:
    approval = ScopeApproval.model_validate(
        {
            "approved_by": "agent stand-in (legacy-model)",
            "approved_at": "2026-08-21T00:00:00Z",
            "scope_hash": "sha256:" + "0" * 64,
        }
    )
    assert approval.decided_by.value == "llm_stand_in"
    assert approval.stand_in_model_id == "legacy-model"


def test_the_cluster_threshold_is_outside_the_signed_surface() -> None:
    """Founder ruling 2026-08-30: a per-topic threshold is the collecting agent's call,
    so pinning or changing it must not invalidate the touchpoint-one signature."""
    from newsab_schema.models.corpus import TopicManifest

    unsigned = TopicManifest.model_validate(_manifest())
    signed = unsigned.model_copy(
        update={
            "scope_approval": ScopeApproval(
                approved_by="fixture founder",
                approved_at="2026-08-24T00:00:00Z",
                scope_hash=unsigned.scope_hash(),
            )
        }
    )
    repinned = signed.model_copy(update={"cluster_threshold": 0.94})
    assert signed.scope_hash() == repinned.scope_hash()
    # …and a signed synthetic record binds the threshold-free hash.
    assert signed.scope_approval.scope_hash == signed.scope_hash()


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args],
        cwd=ROOT,
        env=_env(),
        text=True,
        capture_output=True,
        check=False,
    )


@pytest.mark.cli_e2e
def test_scope_init_mints_publishable_canonical_run_id(tmp_path: Path) -> None:
    topics = tmp_path / "topics"
    result = _run(
        str(SCOPE_TOOL), "init", str(topics), "test-init-2026",
        "--title-en", "Scope init test", "--group", "aa:AA", "--group", "bb:BB",
        "--review-locale", "zh-CN", "--model-id", "test-model",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    raw = yaml.safe_load((topics / "test-init-2026" / "topic_manifest.yaml").read_text())
    assert RUN_ID_RE.fullmatch(raw["provenance"]["run_id"])


@pytest.mark.cli_e2e
def test_human_review_exports_only_approved_source_blind_seeds(tmp_path: Path) -> None:
    topics = _topic(
        tmp_path,
        [
            _candidate("SQ-001", approved=True, required=True, question="What changes?"),
            _candidate("SQ-002", approved=True, required=False, question="Who is affected?"),
            _candidate("SQ-003", approved=False, required=False, question="Rejected question?"),
        ],
    )

    applied = _run(
        str(SCOPE_TOOL), "apply-question-review", str(topics), "test-seeds-2026",
        "--decided-by", "human",
    )
    assert applied.returncode == 0, applied.stdout + applied.stderr

    raw = yaml.safe_load((topics / "test-seeds-2026" / "topic_manifest.yaml").read_text())
    assert [(seed["seed_id"], seed["mandate"]) for seed in raw["question_seeds"]] == [
        ("SQ-001", "required"),
        ("SQ-002", "reference"),
    ]
    serialized = json.dumps(raw["question_seeds"])
    assert "signals" not in serialized
    assert "why" not in serialized
    assert "SQ-003" not in serialized

    approved = _run(
        str(SCOPE_TOOL), "approve", str(topics), "test-seeds-2026",
        "--approved-by", "founder", "--decided-by", "human",
    )
    assert approved.returncode == 0, approved.stdout + approved.stderr
    raw = yaml.safe_load((topics / "test-seeds-2026" / "topic_manifest.yaml").read_text())
    assert raw["scope_approval"]["decided_by"] == "human"


@pytest.mark.cli_e2e
def test_llm_stand_in_cannot_create_required_seed(tmp_path: Path) -> None:
    topics = _topic(
        tmp_path,
        [_candidate("SQ-001", approved=True, required=True, question="What changes?")],
    )

    result = _run(
        str(SCOPE_TOOL), "apply-question-review", str(topics), "test-seeds-2026",
        "--decided-by", "llm_stand_in", "--stand-in-model-id", "test-model",
    )
    assert result.returncode == 1
    assert "reference questions only" in result.stdout


@pytest.mark.cli_e2e
def test_explicit_llm_stand_in_can_approve_reference_seed(tmp_path: Path) -> None:
    topics = _topic(
        tmp_path,
        [_candidate("SQ-001", approved=True, required=False, question="What changes?")],
    )
    applied = _run(
        str(SCOPE_TOOL), "apply-question-review", str(topics), "test-seeds-2026",
        "--decided-by", "llm_stand_in", "--stand-in-model-id", "test-model",
    )
    assert applied.returncode == 0, applied.stdout + applied.stderr

    approved = _run(
        str(SCOPE_TOOL), "approve", str(topics), "test-seeds-2026",
        "--approved-by", "agent stand-in", "--decided-by", "llm_stand_in",
        "--stand-in-model-id", "test-model",
    )
    assert approved.returncode == 0, approved.stdout + approved.stderr
    raw = yaml.safe_load((topics / "test-seeds-2026" / "topic_manifest.yaml").read_text())
    assert raw["question_seeds"][0]["mandate"] == "reference"
    assert raw["scope_approval"]["decided_by"] == "llm_stand_in"
    assert raw["scope_approval"]["stand_in_model_id"] == "test-model"


@pytest.mark.cli_e2e
def test_question_batch_requires_declared_semantic_coverage(tmp_path: Path) -> None:
    topics = _topic(tmp_path, [])
    manifest_path = topics / "test-seeds-2026" / "topic_manifest.yaml"
    manifest = yaml.safe_load(manifest_path.read_text())
    manifest["question_seeds"] = [
        {
            "seed_id": "SQ-001",
            "text": {"values": {"en": "What changes?"}},
            "mandate": "required",
        }
    ]
    manifest_path.write_text(
        yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    batch = tmp_path / "questions.jsonl"
    row = {
        "tier": "reader",
        "text": {"en": "How does the policy change?"},
        "rationale": "The answer changes how a reader understands the policy.",
        "category_guidance": "Bucket by the concrete change reported.",
    }
    batch.write_text(json.dumps(row) + "\n", encoding="utf-8")

    missing = _run(
        str(QA_BATCH), "check-questions", str(topics), "test-seeds-2026", str(batch)
    )
    assert missing.returncode == 1
    assert "required seed SQ-001 has no semantically equivalent question row" in missing.stdout

    row["covers_required_seeds"] = ["SQ-001"]
    batch.write_text(json.dumps(row) + "\n", encoding="utf-8")
    covered = _run(
        str(QA_BATCH), "check-questions", str(topics), "test-seeds-2026", str(batch)
    )
    assert covered.returncode == 0, covered.stdout + covered.stderr
    assert "required SQ-001 -> QST-test-seeds-001" in covered.stdout


def test_a_rationale_naming_the_mandate_is_refused(tmp_path: Path) -> None:
    """The mechanical mandate fields are stripped at build; prose must not re-leak them.

    Six rationales naming a seed as required have shipped this way — a preference signal
    the writer is forbidden to see (value_chain non-negotiable 9).
    """
    topics = _topic(tmp_path, [])
    batch = tmp_path / "questions.jsonl"
    leaky = {
        "tier": "reader",
        "text": {"en": "How does the policy change?"},
        "rationale": "Founder-required question; tests concrete institutional effects.",
        "category_guidance": "Bucket by the concrete change reported.",
    }
    batch.write_text(json.dumps(leaky) + "\n", encoding="utf-8")
    refused = _run(
        str(QA_BATCH), "check-questions", str(topics), "test-seeds-2026", str(batch)
    )
    assert refused.returncode == 1
    assert "leaks the seed mandate" in refused.stdout

    leaky["rationale"] = "Separates the timing question from the mechanism (SQ-003)."
    batch.write_text(json.dumps(leaky) + "\n", encoding="utf-8")
    refused = _run(
        str(QA_BATCH), "check-questions", str(topics), "test-seeds-2026", str(batch)
    )
    assert refused.returncode == 1
    assert "leaks the seed mandate" in refused.stdout

    leaky["rationale"] = "The answer changes how a reader understands the policy."
    batch.write_text(json.dumps(leaky) + "\n", encoding="utf-8")
    clean = _run(
        str(QA_BATCH), "check-questions", str(topics), "test-seeds-2026", str(batch)
    )
    assert clean.returncode == 0, clean.stdout + clean.stderr


@pytest.mark.cli_e2e
def test_the_sitting_asks_which_language_touchpoint_two_is_read_in(tmp_path: Path) -> None:
    """``review_locale`` is captured at the scope sitting, not defaulted later.

    Everything downstream — the localization floor a publication ships, the page hash an
    approval is keyed to, the language the user's own words are recorded as — reads
    this field.  A stage that has to guess picks the *agent's* language, not the
    reviewer's, so the one moment a human is present is where it gets asked.
    """
    topics = tmp_path / "topics"
    missing = _run(
        str(SCOPE_TOOL), "init", str(topics), "test-locale-2026",
        "--title-en", "Reviewer language", "--group", "aa:AA", "--group", "bb:BB",
        "--model-id", "test-model",
    )
    assert missing.returncode == 2
    assert "--review-locale" in missing.stderr

    outside = _run(
        str(SCOPE_TOOL), "init", str(topics), "test-locale-2026",
        "--title-en", "Reviewer language", "--group", "aa:AA", "--group", "bb:BB",
        "--review-locale", "sv", "--model-id", "test-model",
    )
    assert outside.returncode == 2
    assert "nine languages" in outside.stderr

    made = _run(
        str(SCOPE_TOOL), "init", str(topics), "test-locale-2026",
        "--title-en", "Reviewer language", "--group", "aa:AA", "--group", "bb:BB",
        "--review-locale", "ja", "--model-id", "test-model",
    )
    assert made.returncode == 0, made.stdout + made.stderr
    raw = yaml.safe_load((topics / "test-locale-2026" / "topic_manifest.yaml").read_text())
    assert raw["review_locale"] == "ja"
    # The skeleton's own placeholders follow the reviewer, not the tool's author.
    assert set(raw["groups"][0]["short_label"]["values"]) == {"en", "ja"}


@pytest.mark.cli_e2e
def test_check_refuses_a_scope_that_never_named_its_review_language(tmp_path: Path) -> None:
    """A manifest written before the field existed still has to name it before signing."""
    topics = _topic(tmp_path, [_candidate("Q1", approved=True, required=False,
                                          question="What changed?")])
    manifest_file = topics / "test-seeds-2026" / "topic_manifest.yaml"
    raw = yaml.safe_load(manifest_file.read_text(encoding="utf-8"))
    del raw["review_locale"]
    manifest_file.write_text(
        yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    checked = _run(str(SCOPE_TOOL), "check", str(topics), "test-seeds-2026")
    assert checked.returncode == 1
    assert "review_locale is unset" in checked.stdout
