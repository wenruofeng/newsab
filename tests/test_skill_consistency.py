"""Static consistency checks pinning the first round of skills-refactor fixes.

Each test guards one confirmed drift class: a fact stated in two places (frontmatter vs. script constant, prose vs. code behaviour)
must have exactly one definition site.  The broader packaging checker arrives in unit 1;
these stay as the regression floor for the specific drifts already found in the wild.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SKILLS = REPO / "skills"

ACTIVE_SKILLS = [
    p
    for p in sorted(SKILLS.iterdir())
    if (p / "SKILL.md").exists() and p.name not in {"archive", "_template"}
]


def _frontmatter(skill_dir: Path) -> dict[str, str]:
    """Parse frontmatter, folding metadata `newsab-*` fields onto their legacy names."""
    text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    match = re.match(r"\A---\n(.*?)\n---\n", text, re.DOTALL)
    assert match, f"{skill_dir.name}/SKILL.md has no frontmatter block"
    fields: dict[str, str] = {}
    for line in match.group(1).splitlines():
        m = re.match(r"^\s*(\w[\w-]*):\s*(.*)$", line)
        if m:
            key = m.group(1).removeprefix("newsab-")
            fields.setdefault(key, m.group(2).strip().strip('"'))
    return fields


def test_frontmatter_stage_matches_directory_name():
    # Drift found: normalize/SKILL.md said `stage: normalization`.  The value-chain
    # stage name and the directory name are the same name.
    for skill_dir in ACTIVE_SKILLS:
        fm = _frontmatter(skill_dir)
        assert fm.get("stage") == skill_dir.name, (
            f"{skill_dir.name}/SKILL.md declares stage '{fm.get('stage')}', "
            f"expected '{skill_dir.name}'"
        )


def test_skill_version_literals_in_entry_match_frontmatter():
    # Drift found: write/SKILL.md frontmatter was 0.10.0 while its manifest command
    # still said `--skill-version 0.9.0`.
    for skill_dir in ACTIVE_SKILLS:
        fm = _frontmatter(skill_dir)
        body = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
        for literal in re.findall(r"--skill-version\s+([0-9][\w.]*)", body):
            assert literal == fm.get("version"), (
                f"{skill_dir.name}/SKILL.md writes --skill-version {literal} "
                f"but its frontmatter says {fm.get('version')}"
            )


def test_qa_batch_provenance_version_comes_from_annotate_frontmatter():
    # Drift found: qa_batch.py hardcoded `annotate-0.1.0` while SKILL.md was 0.5.0.
    # The script now derives its version from the frontmatter; verify the derivation.
    scripts_dir = SKILLS / "annotate" / "scripts"
    sys.path.insert(0, str(scripts_dir))
    try:
        spec = importlib.util.spec_from_file_location(
            "qa_batch", scripts_dir / "qa_batch.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(scripts_dir))
    expected = "annotate-" + _frontmatter(SKILLS / "annotate")["version"]
    assert module.SKILL_VERSION == expected


def test_analyze_inputs_include_normalization():
    # Drift found: analyze consumes the active category map but did not declare it.
    fm = _frontmatter(SKILLS / "analyze")
    assert "normalization" in fm.get("inputs", ""), (
        "analyze/SKILL.md inputs must declare the normalization category map"
    )


def test_repin_prose_describes_rank_free_finding_ids():
    # Drift found: write/SKILL.md's repin section still called current finding ids
    # rank-positional; qa_analyze.py mints them keyed by question serial + kind.
    body = (SKILLS / "write" / "SKILL.md").read_text(encoding="utf-8")
    repin_section = body.split("## ", 1)[-1]
    assert "rank-free" in body, (
        "write/SKILL.md must describe current finding ids as rank-free"
    )
    assert "finding ids are rank-positional" not in repin_section.replace(
        "were", "are"
    ), "write/SKILL.md must not present rank-positional ids as the current contract"


def test_judge_reference_names_the_packet_as_its_input():
    # Drift found: references/judge.md claimed the judge reads the rendered English
    # page and full ReaderPage JSON; its actual input is rubric + judge packet.
    body = (SKILLS / "render-localize" / "references" / "judge.md").read_text(
        encoding="utf-8"
    )
    assert "judge_packet.py" in body, (
        "judge.md must name the judge packet as the judge's input"
    )
    assert "It reads only artifacts — the rendered English page" not in body


def test_write_requires_the_render_order_authoring_packet():
    body = (SKILLS / "write" / "SKILL.md").read_text(encoding="utf-8")
    style = (SKILLS / "write" / "references" / "style.md").read_text(encoding="utf-8")
    assert "angle_authoring_packet.py" in body
    assert "question → answer label and count → relation symbol → explanation" in style
    assert (SKILLS / "write" / "scripts" / "angle_authoring_packet.py").is_file()
    assert (SKILLS / "write" / "scripts" / "apply_angle_rewrites.py").is_file()


def test_localize_pair_reads_the_rendered_qa_frame():
    body = (SKILLS / "render-localize" / "SKILL.md").read_text(encoding="utf-8")
    rubric = (SKILLS / "render-localize" / "references" / "judge.md").read_text(
        encoding="utf-8"
    )
    assert "Translate labels first, then explanations" in body
    assert "question → answer cards → relation → explanation pair" in rubric
    assert (
        SKILLS / "render-localize" / "scripts" / "apply_angle_localizations.py"
    ).is_file()
