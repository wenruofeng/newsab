"""Read a skill's own ``SKILL.md`` frontmatter — the one definition site for its
behaviour version (``metadata.newsab-version``, `skills/README.md` §Frontmatter) and its
recommended `finalize-run --counters-json` keys (`metadata.newsab-counters`) — so
`finalize-run` never has to trust a hand-typed copy of either.

Mirrors the frontmatter parsing in ``tools/skills_check.py`` (which enforces the same
contract on every skill at commit time); duplicated here in miniature rather than
imported, because ``tools/`` is a repo-root dev-script directory, not an installed
package, and this module ships inside ``newsab_schema``.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

_FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)


def parse_frontmatter(text: str) -> dict | None:
    """The YAML frontmatter block at the top of a ``SKILL.md``, or ``None``."""
    match = _FRONTMATTER.match(text)
    if not match:
        return None
    try:
        data = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        return None
    return data if isinstance(data, dict) else None


def skill_md_path(repo_root: Path, skill_id: str) -> Path:
    """Where a ``--skill-id`` value's ``SKILL.md`` would live, whether or not it exists.

    A ``skill_id`` may carry a ``/<suffix>`` — legacy and normalize/annotate runs record
    e.g. ``s4-annotate/normalise`` or ``s8-verify/judge`` — only the segment before the
    first ``/`` is a directory name under ``skills/``.
    """
    directory = skill_id.split("/", 1)[0]
    return repo_root / "skills" / directory / "SKILL.md"


def load_skill_frontmatter(repo_root: Path, skill_id: str) -> dict | None:
    """The active skill's parsed frontmatter, or ``None`` if there is none to read.

    Deliberately returns ``None`` (rather than raising) both when no ``SKILL.md`` exists
    at the resolved path and when one exists but fails to parse — a retired skill under
    ``skills/archive/`` is never found here (it lives one directory deeper), so a run
    naming one keeps the old, fully-explicit contract. Callers fall back to requiring an
    explicit value in either case.
    """
    md = skill_md_path(repo_root, skill_id)
    if not md.is_file():
        return None
    try:
        text = md.read_text(encoding="utf-8")
    except OSError:
        return None
    return parse_frontmatter(text)


def declared_version(fm: dict) -> str | None:
    """``metadata.newsab-version`` — the single definition site for a skill's version."""
    meta = fm.get("metadata") or {}
    if isinstance(meta, dict) and meta.get("newsab-version"):
        return str(meta["newsab-version"])
    return None


def declared_counters(fm: dict) -> dict[str, str] | None:
    """Parse ``metadata.newsab-counters`` into ``{name: one-sentence meaning}``.

    The frontmatter contract (`skills/README.md`) restricts every ``metadata`` value to a
    plain string, so the list is written as a YAML block scalar, one ``name: meaning`` pair
    per line, e.g.::

        metadata:
          newsab-counters: |
            angles: number of candidate angle cards written to the page
            quotes: number of verbatim quotes selected across all angles

    Returns ``None`` when the skill declares no counters list at all, which callers read
    as "nothing to check the ``--counters-json`` keys against" rather than "zero keys
    allowed".
    """
    meta = fm.get("metadata") or {}
    if not isinstance(meta, dict):
        return None
    raw = meta.get("newsab-counters")
    if not isinstance(raw, str) or not raw.strip():
        return None
    out: dict[str, str] = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        name, sep, meaning = line.partition(":")
        if sep:
            out[name.strip()] = meaning.strip()
    return out or None
