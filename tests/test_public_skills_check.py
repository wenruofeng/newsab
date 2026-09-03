"""The standalone skills checker must accept a clean skill and name each drift."""

from __future__ import annotations

from pathlib import Path

from tools.skills_check import check_skill


CLEAN_ENTRY = """---
name: goodskill
description: Turns staged articles into a checked corpus. Use after scope approval, before annotate.
compatibility: Requires this repository and Python 3.
metadata:
  newsab-stage: "goodskill"
  newsab-version: "1.2.0"
  newsab-inputs: "topic_manifest"
  newsab-outputs: "corpus"
  newsab-language: "en-pivot"
---

# goodskill

Read [references/extra.md](references/extra.md) only when extending an existing corpus.

Finalize with `--skill-id goodskill --skill-version 1.2.0`.
"""


def make_skill(root: Path, name: str, entry: str, refs: dict[str, str] | None = None) -> Path:
    directory = root / name
    (directory / "references").mkdir(parents=True)
    (directory / "scripts").mkdir()
    (directory / "SKILL.md").write_text(entry, encoding="utf-8")
    for filename, text in (refs or {}).items():
        (directory / "references" / filename).write_text(text, encoding="utf-8")
    return directory


def test_clean_skill_has_no_findings(tmp_path):
    skill = make_skill(tmp_path, "goodskill", CLEAN_ENTRY, {"extra.md": "Durable rules only.\n"})
    assert check_skill(skill, run_help=False) == []


def test_each_drift_class_is_named(tmp_path):
    entry = """---
name: badskill
description: short
stage: wrongname
version: 0.2.0
mystery: true
---

# badskill

See [references/missing.md](references/missing.md) and D7 for why.
As of 2026 the live topics all pass. See the [archive](../archive/old.md).

    python scripts/nowhere.py topics t --skill-version 0.1.0

## CHANGELOG
- 0.1.0 — initial.
"""
    skill = make_skill(tmp_path, "badskill", entry, {"orphan.md": "never routed\n"})
    (skill.parent / "archive").mkdir()
    (skill.parent / "archive" / "old.md").write_text("x", encoding="utf-8")
    rules = {finding.rule for finding in check_skill(skill, run_help=False)}
    assert {
        "frontmatter", "description", "legacy-frontmatter", "dead-link",
        "archive-link", "command-path", "version-drift", "changelog",
        "internal-numbering", "time-bound", "unrouted-reference",
    } <= rules


def test_script_version_hardcode_is_flagged(tmp_path):
    skill = make_skill(tmp_path, "goodskill", CLEAN_ENTRY, {"extra.md": "ok\n"})
    (skill / "scripts" / "tool.py").write_text(
        'SKILL_VERSION = "goodskill-0.9.0"\n', encoding="utf-8"
    )
    assert "version-drift" in {
        finding.rule for finding in check_skill(skill, run_help=False)
    }


def test_all_active_skills_pass_strict():
    from tools.skills_check import active_skills

    findings = [
        finding
        for directory in active_skills()
        for finding in check_skill(directory, run_help=False)
    ]
    assert findings == [], "\n".join(str(finding) for finding in findings)
