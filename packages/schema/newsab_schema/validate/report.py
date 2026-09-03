"""Validation findings and reports.

Deliberately not exceptions: a stage validating 800 observations needs to see all the
problems at once, not the first one.  Severity mirrors the lint verdicts — ``error`` stops
the stage, ``warning`` needs a judge or a human to sign off, ``info`` is a statistic the
run log should carry.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Optional


@dataclass(frozen=True)
class Finding:
    severity: str  # "error" | "warning" | "info"
    code: str
    target: str
    message: str
    hint: Optional[str] = None

    def __str__(self) -> str:  # pragma: no cover - display only
        tail = f"\n      hint: {self.hint}" if self.hint else ""
        return f"[{self.severity:7}] {self.code:28} {self.target}\n      {self.message}{tail}"


@dataclass
class ValidationReport:
    """Result of one validation pass, plus the counters the manifest wants."""

    findings: list[Finding] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)

    def add(
        self,
        severity: str,
        code: str,
        target: str,
        message: str,
        hint: Optional[str] = None,
    ) -> None:
        if severity not in ("error", "warning", "info"):
            raise ValueError(f"unknown severity {severity!r}")
        self.findings.append(Finding(severity, code, target, message, hint))

    def error(self, code: str, target: str, message: str, hint: Optional[str] = None) -> None:
        self.add("error", code, target, message, hint)

    def warning(self, code: str, target: str, message: str, hint: Optional[str] = None) -> None:
        self.add("warning", code, target, message, hint)

    def info(self, code: str, target: str, message: str, hint: Optional[str] = None) -> None:
        self.add("info", code, target, message, hint)

    def extend(self, other: "ValidationReport", prefix: str = "") -> None:
        self.findings.extend(other.findings)
        for key, value in other.stats.items():
            self.stats[f"{prefix}{key}" if prefix else key] = value

    def of(self, severity: str) -> list[Finding]:
        return [f for f in self.findings if f.severity == severity]

    @property
    def errors(self) -> list[Finding]:
        return self.of("error")

    @property
    def warnings(self) -> list[Finding]:
        return self.of("warning")

    def ok(self, strict: bool = False) -> bool:
        """Clean run.  ``strict`` also refuses warnings — used when no judge or human is
        going to look at this run, so an unresolved flag cannot quietly pass through."""
        return not self.errors and (not strict or not self.warnings)

    def exit_code(self, strict: bool = False) -> int:
        return 0 if self.ok(strict=strict) else 1

    def summary(self) -> str:
        counts = {sev: len(self.of(sev)) for sev in ("error", "warning", "info")}
        return (
            f"{counts['error']} error(s), {counts['warning']} warning(s), "
            f"{counts['info']} info"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "findings": [asdict(f) for f in self.findings],
            "stats": self.stats,
            "summary": self.summary(),
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    def render(self, show: Iterable[str] = ("error", "warning")) -> str:
        wanted = set(show)
        lines = [str(f) for f in self.findings if f.severity in wanted]
        if self.stats:
            lines.append("stats: " + json.dumps(self.stats, ensure_ascii=False, sort_keys=True))
        lines.append(self.summary())
        return "\n".join(lines)
