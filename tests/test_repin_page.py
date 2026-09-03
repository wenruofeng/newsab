"""Regression tests for the deterministic reader-page repin helper."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "skills" / "write" / "scripts" / "repin_page.py"


def _load_repin_module():
    sys.path.insert(0, str(SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("newsab_repin_page", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_repin_moves_every_computed_run_pointer_including_qa_run_id():
    repin = _load_repin_module()
    payload = {
        "how_we_counted": {
            "corpus_run_id": "s2s-old",
            "questions_run_id": "qst-old",
            "answers_run_id": "ans-old",
            "qa_run_id": "qa-old",
        }
    }
    run_json = {
        "qa_run_id": "qa-new",
        "inputs": {"corpus_run_id": "s2s-new"},
    }

    remaps = repin._repin_run_ids(payload, run_json, "ans-new", "qst-new")

    assert payload["how_we_counted"] == {
        "corpus_run_id": "s2s-new",
        "questions_run_id": "qst-new",
        "answers_run_id": "ans-new",
        "qa_run_id": "qa-new",
    }
    assert any("questions_run_id qst-old -> qst-new" in line for line in remaps)
    assert any("qa_run_id qa-old -> qa-new" in line for line in remaps)


def test_repin_resolves_questions_from_the_new_analysis_lineage(tmp_path):
    repin = _load_repin_module()
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text(
        "\n".join(
            [
                '{"run_id":"ans-old","inputs":["s2s-old","qst-old"]}',
                '{"run_id":"qa-old","inputs":["s2s-old","qst-old","ans-old"]}',
                '{"run_id":"ans-new","inputs":["s2s-new","qst-new"]}',
                '{"run_id":"qa-new","inputs":["s2s-new","qst-new","ans-new"]}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    assert repin._analysis_lineage_runs(manifest, "qa-new") == ("ans-new", "qst-new")


def test_repin_follows_answers_lineage_for_legacy_analysis_entries(tmp_path):
    repin = _load_repin_module()
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text(
        "\n".join(
            [
                '{"run_id":"ans-new","inputs":["s2s-new","qst-new"]}',
                '{"run_id":"qa-new","inputs":["s2s-new","ans-new"]}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    assert repin._analysis_lineage_runs(manifest, "qa-new") == ("ans-new", "qst-new")
