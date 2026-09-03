"""``python tools/skills_check.py`` — the News A/B skills packaging checker.

Enforces the contract in ``skills/README.md`` on one skill directory or on every active
skill.  Two severities:

* **error** — objectively broken for a stranger's agent: unparseable or wrong-name
  frontmatter, a dead relative link, a command path that does not resolve from repo root,
  a script whose ``--help`` fails, a version stated in two places with two values, a
  reference file the entry never routes to.
* **warn** — contract targets that migration brings in (legacy frontmatter fields, entry
  CHANGELOG section, internal ticket numbers, time-bound wording, links into archive,
  entry length).  ``--strict`` promotes warnings to errors; use it on migrated skills.

Exit codes: 0 clean (or warnings only, without ``--strict``) · 1 findings · 2 bad usage.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
SKILLS = REPO / "skills"

STANDARD_KEYS = {"name", "description", "compatibility", "license", "metadata", "allowed-tools"}
LEGACY_KEYS = {"stage", "version", "inputs", "outputs", "language"}

# Words that date an entry: they describe this repo's state on some day, not the stage.
TIME_BOUND = re.compile(
    r"\blive topics?\b|\bcurrently\b|\bas of 20\d\d\b|\btoday\b", re.IGNORECASE
)
# Bare internal numbering: a spec-section or issue id standing in for a rule instead of
# stating it.
INTERNAL_NUMBER = re.compile(r"(?<![\w/-])(?:[DVG]-?\d+|T-\d+)(?![\w-])")
MD_LINK = re.compile(r"\[[^\]]*\]\(([^)#\s]+)(?:#[^)\s]*)?\)")
# A path-looking token ending in .py after `python` (possibly with flags in between).
PY_COMMAND = re.compile(r"\bpython3?\s+([\w./-]+\.py)\b")
SKILL_VERSION_FLAG = re.compile(r"--skill-version\s+([0-9][\w.]*)")
HARDCODED_VERSION = re.compile(r'^SKILL_VERSION\s*=\s*"[^"]*\d[^"]*"', re.MULTILINE)

MAX_ENTRY_LINES = 150


@dataclass
class Finding:
    skill: str
    severity: str  # "error" | "warn"
    rule: str
    message: str

    def __str__(self) -> str:
        return f"{self.severity:5} {self.skill}: [{self.rule}] {self.message}"


def parse_frontmatter(text: str) -> dict | None:
    match = re.match(r"\A---\n(.*?)\n---\n", text, re.DOTALL)
    if not match:
        return None
    try:
        data = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        return None
    return data if isinstance(data, dict) else None


def declared_version(fm: dict) -> str | None:
    meta = fm.get("metadata") or {}
    if isinstance(meta, dict) and meta.get("newsab-version"):
        return str(meta["newsab-version"])
    if fm.get("version") is not None:
        return str(fm["version"])
    return None


def check_frontmatter(skill_dir: Path, text: str, out: list[Finding]) -> dict:
    name = skill_dir.name
    fm = parse_frontmatter(text)
    if fm is None:
        out.append(Finding(name, "error", "frontmatter", "missing or unparseable YAML frontmatter"))
        return {}
    if fm.get("name") != name:
        out.append(Finding(name, "error", "frontmatter", f"name '{fm.get('name')}' != directory name"))
    desc = fm.get("description")
    if not isinstance(desc, str) or len(desc.strip()) < 40:
        out.append(Finding(name, "error", "description", "missing or too short to route on (< 40 chars)"))
    elif not re.search(r"\b(?:use|run|after|before|when)\b", desc, re.IGNORECASE):
        out.append(Finding(name, "warn", "description", "says what but not when to use the skill"))
    legacy = LEGACY_KEYS & set(fm)
    if legacy:
        out.append(Finding(name, "warn", "legacy-frontmatter",
                           f"non-standard top-level fields {sorted(legacy)}; move into metadata strings"))
    unknown = set(fm) - STANDARD_KEYS - LEGACY_KEYS
    if unknown:
        out.append(Finding(name, "error", "frontmatter", f"unknown fields {sorted(unknown)}"))
    meta = fm.get("metadata")
    if meta is not None:
        if not isinstance(meta, dict) or not all(isinstance(v, str) for v in meta.values()):
            out.append(Finding(name, "error", "frontmatter", "metadata values must all be strings"))
        elif meta.get("newsab-stage") not in (None, name):
            out.append(Finding(name, "error", "frontmatter",
                               f"metadata newsab-stage '{meta.get('newsab-stage')}' != directory name"))
    if isinstance(fm.get("stage"), str) and fm["stage"] != name:
        out.append(Finding(name, "error", "frontmatter", f"stage '{fm['stage']}' != directory name"))
    return fm


def check_links(skill_dir: Path, out: list[Finding]) -> None:
    name = skill_dir.name
    for md in [skill_dir / "SKILL.md", *sorted((skill_dir / "references").glob("*.md"))]:
        if not md.exists():
            continue
        rel = md.relative_to(skill_dir)
        for target in MD_LINK.findall(md.read_text(encoding="utf-8")):
            if re.match(r"[a-z]+://", target):
                continue
            resolved = (md.parent / target).resolve()
            if not resolved.exists():
                out.append(Finding(name, "error", "dead-link", f"{rel}: link target '{target}' does not exist"))
            elif "archive" in target:
                out.append(Finding(name, "warn", "archive-link",
                                   f"{rel}: links into archive; durable rules belong here, history in reports"))
            elif rel.parts[0] == "references" and re.match(r"references/", target):
                continue  # sibling reference: still one hop from the entry
            elif rel.parts[0] == "references" and target.endswith(".md") and "/" in target and not target.startswith("../"):
                out.append(Finding(name, "warn", "deep-link", f"{rel}: reference links deeper than one level ('{target}')"))


def check_commands(skill_dir: Path, out: list[Finding], run_help: bool) -> None:
    name = skill_dir.name
    seen: set[str] = set()
    for md in [skill_dir / "SKILL.md", *sorted((skill_dir / "references").glob("*.md"))]:
        if not md.exists():
            continue
        for script in PY_COMMAND.findall(md.read_text(encoding="utf-8")):
            if "<" in script or script in seen:
                continue
            seen.add(script)
            if not (REPO / script).exists():
                hint = f"skills/{name}/{script}"
                fix = f" (did you mean '{hint}'?)" if (REPO / hint).exists() else ""
                out.append(Finding(name, "error", "command-path",
                                   f"'{script}' does not resolve from repo root{fix}"))
    if run_help:
        for script in sorted((skill_dir / "scripts").glob("*.py")):
            if script.name.startswith("_"):
                continue
            proc = subprocess.run([sys.executable, str(script), "--help"],
                                  capture_output=True, text=True, timeout=60, cwd=REPO)
            if proc.returncode != 0:
                tail = (proc.stderr or proc.stdout).strip().splitlines()[-1:]
                out.append(Finding(name, "error", "script-help",
                                   f"{script.relative_to(REPO)} --help exited {proc.returncode}: {' '.join(tail)}"))


def check_body(skill_dir: Path, text: str, fm: dict, out: list[Finding]) -> None:
    name = skill_dir.name
    body = text.split("---\n", 2)[-1]
    lines = body.splitlines()
    if len(lines) > MAX_ENTRY_LINES:
        out.append(Finding(name, "warn", "entry-length",
                           f"entry body is {len(lines)} lines (advisory target ≤ {MAX_ENTRY_LINES})"))
    if re.search(r"^#+\s*CHANGELOG", body, re.MULTILINE | re.IGNORECASE):
        out.append(Finding(name, "warn", "changelog",
                           "entry carries a CHANGELOG section; history lives in git + task reports"))
    version = declared_version(fm or {})
    for literal in SKILL_VERSION_FLAG.findall(body):
        if version is not None and literal != version:
            out.append(Finding(name, "error", "version-drift",
                               f"body writes --skill-version {literal}, frontmatter says {version}"))
    for script in sorted((skill_dir / "scripts").glob("*.py")):
        if HARDCODED_VERSION.search(script.read_text(encoding="utf-8")):
            out.append(Finding(name, "error", "version-drift",
                               f"{script.name} hardcodes SKILL_VERSION; derive it from SKILL.md"))
    for md in [skill_dir / "SKILL.md", *sorted((skill_dir / "references").glob("*.md"))]:
        if not md.exists():
            continue
        rel = md.relative_to(skill_dir)
        content = md.read_text(encoding="utf-8")
        numbers = sorted(set(INTERNAL_NUMBER.findall(content)))
        if numbers:
            out.append(Finding(name, "warn", "internal-numbering",
                               f"{rel}: bare internal ids {numbers}; state the rule, keep ids as optional provenance"))
        dated = sorted(set(TIME_BOUND.findall(content)))
        if dated:
            out.append(Finding(name, "warn", "time-bound",
                               f"{rel}: time-bound wording {dated}; snapshots belong in registry/reports"))
    entry_text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    for ref in sorted((skill_dir / "references").glob("*.md")):
        if ref.name not in entry_text:
            out.append(Finding(name, "error", "unrouted-reference",
                               f"references/{ref.name} is never mentioned by SKILL.md — no one knows when to read it"))


def check_skill(skill_dir: Path, run_help: bool = True) -> list[Finding]:
    out: list[Finding] = []
    entry = skill_dir / "SKILL.md"
    if not entry.exists():
        return [Finding(skill_dir.name, "error", "frontmatter", "no SKILL.md")]
    text = entry.read_text(encoding="utf-8")
    fm = check_frontmatter(skill_dir, text, out)
    check_links(skill_dir, out)
    check_commands(skill_dir, out, run_help)
    check_body(skill_dir, text, fm, out)
    return out


def active_skills(root: Path = SKILLS) -> list[Path]:
    return [p for p in sorted(root.iterdir())
            if (p / "SKILL.md").exists() and p.name not in {"archive", "_template"}]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("skills", nargs="*", help="skill directories (default: every active skill)")
    ap.add_argument("--strict", action="store_true", help="treat warnings as errors")
    ap.add_argument("--no-help", action="store_true", help="skip running each script's --help")
    args = ap.parse_args(argv)

    dirs = [Path(s) for s in args.skills] if args.skills else active_skills()
    for d in dirs:
        if not d.is_dir():
            print(f"not a directory: {d}", file=sys.stderr)
            return 2

    findings: list[Finding] = []
    for d in dirs:
        findings.extend(check_skill(d, run_help=not args.no_help))

    for f in findings:
        print(f)
    errors = sum(1 for f in findings if f.severity == "error")
    warns = len(findings) - errors
    print(f"\n{len(dirs)} skill(s): {errors} error(s), {warns} warning(s)")
    if errors or (args.strict and warns):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
