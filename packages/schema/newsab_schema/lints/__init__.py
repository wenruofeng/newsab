"""Mechanical text lints shared by S4 (§4.2.2) and S8 L0 (§3.3 S8)."""

from .rules import (
    PROFILES,
    LintFinding,
    LintProfile,
    check_quantifier,
    lint_text,
    load_lexicons,
    load_quantifiers,
)

__all__ = [
    "PROFILES",
    "LintFinding",
    "LintProfile",
    "check_quantifier",
    "lint_text",
    "load_lexicons",
    "load_quantifiers",
]
