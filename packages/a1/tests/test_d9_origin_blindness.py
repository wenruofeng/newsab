"""D9, enforced at the source level.

"Prior hypotheses and data-discovered candidates compete on identical terms before the
R-gate" is a claim about code, not about intentions. A comment saying "remember not to
branch on origin" survives exactly one refactor. So this module checks two things
mechanically:

1. **The decision modules cannot see origin at all.** In the R-gate, the scans, the metrics
   and the calibration harness, the identifier must not appear in executable code —
   tokenised, so prose is free to explain the rule the code may not implement.
2. **Everywhere else, origin may be recorded but never branched on.** ``build_angles.py``
   legitimately writes ``origin`` into the audit trail after every decision is made; what it
   must never do is let that value reach an ``if``. That is an AST check on branch
   conditions rather than a ban on the word.

If either fails on a change you meant to make, that is the intended outcome: it is a
blueprint decision, and AGENTS.md §2.7 sends those to the user rather than into a patch.
"""

from __future__ import annotations

import ast
import tokenize
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]

#: Modules where a threshold decision is taken. Origin must be invisible here.
DECISION_SOURCES = [
    "packages/a1/newsab_a1/rgate.py",
    "packages/a1/newsab_a1/scan.py",
    "packages/a1/newsab_a1/metrics.py",
    "packages/a1/newsab_a1/calibration.py",
]

#: Retired modules may still be checked in the private operating repository, but their
#: absence from the standalone toolkit must not invalidate the current A1 package.
RECORDING_SOURCES = [
    "skills/archive/s6-angle-gate/scripts/build_angles.py",
]

FORBIDDEN = {"origin", "prior_hypothesis", "data_discovered", "AngleOrigin"}


def _existing(paths: list[str]) -> list[Path]:
    return [REPO / rel for rel in paths if (REPO / rel).exists()]


def code_identifiers(path: Path) -> set[str]:
    """Every NAME token; comments and string literals excluded."""
    names: set[str] = set()
    with open(path, "rb") as fh:
        for token in tokenize.tokenize(fh.readline):
            if token.type == tokenize.NAME:
                names.add(token.string)
    return names


def branch_conditions(tree: ast.AST) -> list[ast.AST]:
    """Every expression that decides which way execution goes."""
    tests: list[ast.AST] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.If, ast.IfExp, ast.While)):
            tests.append(node.test)
        elif isinstance(node, ast.Assert):
            tests.append(node.test)
        elif isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            for generator in node.generators:
                tests.extend(generator.ifs)
        elif isinstance(node, ast.Match):
            tests.append(node.subject)
    return tests


def names_in(node: ast.AST) -> set[str]:
    found: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            found.add(child.id)
        elif isinstance(child, ast.Attribute):
            found.add(child.attr)
        elif isinstance(child, ast.Constant) and isinstance(child.value, str):
            found.add(child.value)
    return found


def test_every_decision_source_exists():
    missing = [rel for rel in DECISION_SOURCES if not (REPO / rel).exists()]
    assert not missing, f"decision modules moved or were renamed: {missing}"


@pytest.mark.parametrize(
    "path", _existing(DECISION_SOURCES), ids=lambda p: str(p.relative_to(REPO))
)
def test_decision_code_cannot_see_candidate_origin(path: Path):
    found = sorted(code_identifiers(path) & FORBIDDEN)
    assert not found, (
        f"{path.relative_to(REPO)} references {found} in executable code. D9 requires prior "
        "hypotheses and data-discovered candidates to face identical thresholds; a module "
        "that decides must not be able to tell them apart."
    )


@pytest.mark.parametrize(
    "path", _existing(RECORDING_SOURCES), ids=lambda p: str(p.relative_to(REPO))
)
def test_origin_is_recorded_but_never_branched_on(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    offenders = [
        ast.dump(test)[:120]
        for test in branch_conditions(tree)
        if names_in(test) & FORBIDDEN
    ]
    assert not offenders, (
        f"{path.relative_to(REPO)} branches on origin: {offenders}. Recording it for the "
        "audit trail is fine and required; letting it change an outcome is D9's exact "
        "prohibition."
    )


def test_candidate_has_no_origin_field():
    from newsab_a1.scan import Candidate

    assert not (set(Candidate.__dataclass_fields__) & FORBIDDEN)


def test_the_schema_still_records_origin_for_audit():
    """D9 forbids origin from *deciding*, not from being recorded — the audit trail needs it."""
    from newsab_schema.models.analysis import CandidateAngle

    assert "origin" in CandidateAngle.model_fields
