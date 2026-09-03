#!/usr/bin/env python3
"""Build and verify the one-way, fresh-history public toolkit export.

The exporter reads every selected byte from one exact Git commit and assembles the
result in an empty directory.  It never copies the private checkout recursively and it
never creates a Git repository.  ``export-manifest.json`` is the closed output list: a
file absent from that list is not part of the release.

Verification has two scopes.  ``release`` is the publisher's check on a pristine export:
the tree must be exactly the manifest, byte for byte.  ``workspace`` is the check a user
or a contributor can run inside their own Git clone, where the released files still have
to be present and clean but the clone also carries its own history, installs, caches and
edits; it never demands byte identity with the release.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import io
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tokenize
from pathlib import Path, PurePosixPath
from urllib.parse import unquote

import yaml


EXPORTER_VERSION = "public-exporter-0.1.0"
MANIFEST_NAME = "export-manifest.json"
TEXT_SUFFIXES = {
    "", ".css", ".html", ".ini", ".json", ".md", ".py", ".toml", ".txt",
    ".yaml", ".yml",
}
WORKSPACE_ONLY_DIRS = frozenset({
    ".git", ".hg", ".svn", ".tox", ".venv", "venv", "node_modules",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
})
LINK_RE = re.compile(r"!?(?:\[[^]]*\])\(([^)\s]+)(?:\s+['\"][^)]*['\"])?\)")
TOPIC_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9_-])(?:[a-z]{4,}(?:-[a-z0-9]+)+-\d{4})(?![A-Za-z0-9_-])")
PUBLICATION_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9_-])PUB-[a-z0-9-]+-[0-9a-f]{12}(?![A-Za-z0-9_-])")
SECRET_PATTERNS = {
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "github_token": re.compile(r"\bgh[opusr]_[A-Za-z0-9_]{30,}\b"),
    "aws_access_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "credential_url": re.compile(r"https?://[^\s/:]+:[^\s/@]+@"),
    "assigned_secret": re.compile(
        r"(?i)\b(?:api[_-]?key|access[_-]?token|client[_-]?secret|password)\b\s*[:=]\s*['\"][^'\"]{8,}['\"]"
    ),
}


class ExportError(RuntimeError):
    """A fail-closed public release error."""


def _run(repo: Path, *args: str, text: bool = False) -> bytes | str:
    proc = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=text, check=False
    )
    if proc.returncode:
        stderr = proc.stderr if text else proc.stderr.decode("utf-8", "replace")
        raise ExportError(f"git {' '.join(args)} failed: {stderr.strip()}")
    return proc.stdout


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _parts(path: str) -> tuple[str, ...]:
    return PurePosixPath(path).parts


def _under(path: str, prefix: str) -> bool:
    parts, wanted = _parts(path), _parts(prefix)
    return parts[: len(wanted)] == wanted


def _tree(repo: Path, revision: str) -> dict[str, tuple[str, str]]:
    raw = _run(repo, "ls-tree", "-r", "-z", "--full-tree", revision)
    assert isinstance(raw, bytes)
    entries: dict[str, tuple[str, str]] = {}
    for record in raw.split(b"\0"):
        if not record:
            continue
        meta, name = record.split(b"\t", 1)
        mode, kind, oid = meta.decode("ascii").split()
        if kind != "blob":
            continue
        entries[name.decode("utf-8")] = (mode, oid)
    return entries


def _blob(repo: Path, oid: str) -> bytes:
    result = _run(repo, "cat-file", "blob", oid)
    assert isinstance(result, bytes)
    return result


def _contract_at(repo: Path, revision: str) -> tuple[dict, bytes]:
    raw = _run(repo, "show", f"{revision}:public_export.yaml")
    assert isinstance(raw, bytes)
    contract = yaml.safe_load(raw)
    if not isinstance(contract, dict):
        raise ExportError("public_export.yaml must contain one mapping")
    return contract, raw


def _selected_files(
    contract: dict, tree: dict[str, tuple[str, str]]
) -> list[tuple[str, str, str, str, tuple[str, str] | None]]:
    """Return ``(source, target, mode, oid, appended)`` rows in target order.

    ``appended`` is the optional ``(source, oid)`` of a second tracked file whose bytes are
    concatenated after the first.  It exists so one document can be single-sourced across
    both repositories while the public tree still carries the sections that are true only
    there: the private file stays authoritative, the appendix is public-only, and neither
    is rewritten on the way out.
    """
    forbidden_targets = contract["forbidden_path_prefixes"]
    forbidden_sources = [
        *forbidden_targets,
        *contract.get("forbidden_source_path_prefixes", []),
    ]
    resolved: list[tuple[str, str, str, str, tuple[str, str] | None]] = []
    targets: dict[str, str] = {}
    for rule in contract["copies"]:
        source, target, selection = rule["source"], rule["target"], rule["select"]
        appended: tuple[str, str] | None = None
        append_source = rule.get("append_source")
        if append_source is not None:
            if selection != "file":
                raise ExportError(f"{rule['id']}: append_source requires select: file")
            if append_source not in tree:
                raise ExportError(
                    f"{rule['id']}: append source is not tracked at revision: {append_source}"
                )
            if any(_under(append_source, prefix) for prefix in forbidden_sources):
                raise ExportError(f"{rule['id']}: forbidden path resolved: {append_source}")
            append_mode, append_oid = tree[append_source]
            if append_mode not in {"100644", "100755"}:
                raise ExportError(
                    f"{rule['id']}: unsupported Git mode {append_mode}: {append_source}"
                )
            appended = (append_source, append_oid)
        candidates: list[str] = []
        if selection == "file":
            if source not in tree:
                raise ExportError(f"{rule['id']}: source is not tracked at revision: {source}")
            candidates = [source]
        else:
            prefix = source.rstrip("/") + "/"
            candidates = [path for path in tree if path.startswith(prefix)]
            if selection == "tracked_patterns":
                patterns = rule.get("patterns") or []
                candidates = [
                    path for path in candidates
                    if any(fnmatch.fnmatchcase(path[len(prefix):], pattern) for pattern in patterns)
                ]
            if not candidates:
                raise ExportError(f"{rule['id']}: selection is empty at revision {source}")
        for path in sorted(candidates):
            relative = "" if selection == "file" else path[len(source.rstrip("/")) + 1 :]
            out = target if not relative else f"{target.rstrip('/')}/{relative}"
            source_forbidden = any(_under(path, prefix) for prefix in forbidden_sources)
            target_forbidden = any(_under(out, prefix) for prefix in forbidden_targets)
            if source_forbidden or target_forbidden:
                raise ExportError(f"{rule['id']}: forbidden path resolved: {path} -> {out}")
            mode, oid = tree[path]
            if mode == "120000":
                raise ExportError(f"{rule['id']}: symlinks are forbidden: {path}")
            if mode not in {"100644", "100755"}:
                raise ExportError(f"{rule['id']}: unsupported Git mode {mode}: {path}")
            if out in targets:
                raise ExportError(f"target collision: {out} from {targets[out]} and {path}")
            targets[out] = path
            resolved.append((path, out, mode, oid, appended))
    return sorted(resolved, key=lambda row: row[1])


def _forbidden_identity_hashes(tree: dict[str, tuple[str, str]]) -> dict[str, list[str]]:
    topics = {
        path.split("/", 2)[1]
        for path in tree
        if path.startswith("topics/") and len(path.split("/", 2)) == 3
        and path.split("/", 2)[1] not in {"README.md", ".gitignore"}
    }
    publications = {
        path.split("/", 3)[2]
        for path in tree
        if path.startswith("site/publications/") and len(path.split("/", 3)) >= 4
    }
    return {
        "topic_sha256": sorted(_digest(value.encode()) for value in topics),
        "publication_sha256": sorted(_digest(value.encode()) for value in publications),
    }


def _walk_files(root: Path) -> list[Path]:
    """Every candidate release file under ``root``.

    Directories a working clone grows on its own — version control, byte caches,
    editable-install metadata, virtualenvs — are never release output, so they are
    pruned here.  That keeps one verifier honest on a pristine export and usable in a
    clone that has been installed, tested and committed to.
    """
    found: list[Path] = []
    for parent, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            name for name in dirnames
            if name not in WORKSPACE_ONLY_DIRS and not name.endswith(".egg-info")
        )
        base = Path(parent)
        for name in sorted(filenames):
            if name.endswith(".pyc"):
                continue
            path = base / name
            if path.is_file():
                found.append(path)
    return found


def _text_files(files: list[Path]) -> list[Path]:
    return [path for path in files if path.suffix.lower() in TEXT_SUFFIXES]


def _entropy(token: str) -> float:
    counts = {char: token.count(char) for char in set(token)}
    size = len(token)
    return -sum((count / size) * math.log2(count / size) for count in counts.values())


def scan_secrets(root: Path, files: list[Path]) -> list[str]:
    findings: list[str] = []
    entropy_token = re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9+/=_-]{48,}(?![A-Za-z0-9])")
    for path in _text_files(files):
        relative = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        for name, pattern in SECRET_PATTERNS.items():
            if pattern.search(text):
                findings.append(f"{relative}: secret pattern {name}")
        for match in entropy_token.finditer(text):
            token = match.group(0)
            if re.fullmatch(r"(?:sha256:)?[0-9a-f]{48,}", token, re.IGNORECASE):
                continue
            if _entropy(token) >= 4.5:
                findings.append(f"{relative}: high-entropy token at byte {match.start()}")
    return findings


def scan_identities(root: Path, files: list[Path], manifest: dict) -> list[str]:
    findings: list[str] = []
    topic_hashes = set(manifest["forbidden_identity_hashes"]["topic_sha256"])
    publication_hashes = set(manifest["forbidden_identity_hashes"]["publication_sha256"])
    for path in _text_files(files):
        relative = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        for token in set(TOPIC_TOKEN_RE.findall(text)):
            if _digest(token.encode()) in topic_hashes:
                findings.append(f"{relative}: private topic identifier")
        for token in set(PUBLICATION_TOKEN_RE.findall(text)):
            if _digest(token.encode()) in publication_hashes:
                findings.append(f"{relative}: private publication identifier")
    return findings


def scan_links(root: Path, files: list[Path]) -> list[str]:
    findings: list[str] = []
    for path in [path for path in files if path.suffix.lower() == ".md"]:
        relative = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8")
        for raw in LINK_RE.findall(text):
            target = unquote(raw.split("#", 1)[0].split("?", 1)[0])
            if not target or target.startswith(("http://", "https://", "mailto:", "/")):
                continue
            resolved = (path.parent / target).resolve()
            try:
                resolved.relative_to(root.resolve())
            except ValueError:
                findings.append(f"{relative}: link escapes export root: {raw}")
                continue
            candidates = [resolved]
            if resolved.is_dir():
                candidates.extend([resolved / "README.md", resolved / "index.md"])
            if not any(candidate.exists() for candidate in candidates):
                findings.append(f"{relative}: missing internal link: {raw}")
    return findings


def scan_license(root: Path, contract: dict, manifest: dict) -> list[str]:
    policy = contract["license_policy"]
    findings: list[str] = []
    for key in ("license_file", "scope_file", "notices_file"):
        path = root / policy[key]
        if not path.is_file() or not path.read_text(encoding="utf-8").strip():
            findings.append(f"missing or empty {key}: {policy[key]}")
    license_text = (root / policy["license_file"]).read_text(encoding="utf-8", errors="replace")
    if "MIT License" not in license_text or "Permission is hereby granted" not in license_text:
        findings.append("LICENSE is not the reviewed MIT text")
    neutral_assets = {
        "packages/publish/newsab_publish/data/favicon.svg": "public/neutral/favicon.svg",
        "packages/publish/newsab_publish/data/logo-transparent-dark.svg":
            "public/neutral/logo-transparent-dark.svg",
        "packages/publish/newsab_publish/data/logo-transparent-light.svg":
            "public/neutral/logo-transparent-light.svg",
        "packages/publish/newsab_publish/data/share-card.png":
            "public/neutral/share-card.png",
    }
    sources = {row["path"]: row["source"] for row in manifest["files"]}
    for target, source in neutral_assets.items():
        if sources.get(target) != source:
            findings.append(f"neutral asset provenance mismatch: {target}")
    return findings


#: Halo-locale translation files copied from the private tree unchanged (public_export.yaml
#: ``editorial-package`` / ``publish-package``).  They carry no site identity: the code that
#: loads them fills ``{site_name}``, the about paragraph, the contact line and the footer
#: domain from the identity files that *are* overlaid.  Verified below.
IDENTITY_FREE_DATA = (
    "packages/editorial/newsab_editorial/render/data/chrome_strings_i18n.v1.json",
    "packages/editorial/newsab_editorial/render/data/stat_panel_i18n.v1.json",
    "packages/publish/newsab_publish/data/about_i18n.v1.json",
    "packages/publish/newsab_publish/data/site_strings_i18n.v1.json",
    "packages/publish/newsab_publish/data/suggest_i18n.v1.json",
)


def scan_neutral_defaults(root: Path) -> list[str]:
    """Ensure executable defaults do not impersonate the private service/operator."""
    findings: list[str] = []
    paths = (
        "packages/corpus/newsab_corpus/data/operator_identity.v1.json",
        "packages/editorial/newsab_editorial/render/data/site_identity.v1.json",
        "packages/publish/newsab_publish/data/site_identity.v1.json",
        "packages/publish/newsab_publish/data/site_metadata.v1.json",
    )
    for relative in paths:
        path = root / relative
        if not path.is_file():
            findings.append(f"missing neutral default: {relative}")
            continue
        folded = path.read_text(encoding="utf-8").casefold()
        for private_token in ("news-ab.com", "wenruofeng", "gmail.com"):
            if private_token in folded:
                findings.append(f"{relative}: production identity token {private_token}")
    # Translation data exported as-is (not overlaid): every site-specific string in these
    # files is an identity slot filled at import, so a production token here means a
    # translator or agent wrote the brand back into copy and the neutral clone would leak it.
    for relative in IDENTITY_FREE_DATA:
        path = root / relative
        if not path.is_file():
            findings.append(f"missing identity-free translation data: {relative}")
            continue
        folded = path.read_text(encoding="utf-8").casefold()
        for private_token in ("news-ab.com", "news a/b", "wenruofeng", "gmail.com"):
            if private_token in folded:
                findings.append(f"{relative}: production identity token {private_token}")
    operator_path = root / paths[0]
    if operator_path.is_file():
        try:
            operator = json.loads(operator_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            findings.append(f"{paths[0]}: invalid JSON")
        else:
            if operator.get("configured") is not False:
                findings.append(f"{paths[0]}: public starter identity must be unconfigured")
            if operator.get("operator_url") is not None or operator.get("operator_email") is not None:
                findings.append(f"{paths[0]}: public starter identity must not invent contact values")
    return findings


#: sha256 of the production collector's casefolded contact email.  A digest, not the
#: address: this file ships in every public copy, and the guard only has to recognise
#: the production identity when a clone copies it, never to print it.
PRODUCTION_OPERATOR_EMAIL_SHA256 = "eb7e87757c72ab4ac9432be84b4020620ee46d6195c640bec817bc2f6d8557c0"


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.strip().casefold().encode("utf-8")).hexdigest()


def scan_local_runtime(root: Path, contract: dict) -> list[str]:
    """Validate the one user-owned runtime identity file allowed outside the manifest."""
    findings: list[str] = []
    allowed = contract.get("local_runtime_paths", [])
    if allowed != [".newsab/operator_identity.json"]:
        return ["local_runtime_paths must contain only .newsab/operator_identity.json"]
    path = root / allowed[0]
    if not path.exists():
        return findings
    if path.is_symlink() or not path.is_file():
        return [f"{allowed[0]}: local runtime identity must be a regular file"]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"{allowed[0]}: invalid JSON ({exc})"]
    url = str(payload.get("operator_url") or "")
    email = str(payload.get("operator_email") or "")
    if payload.get("configured") is not True:
        findings.append(f"{allowed[0]}: configured must be true")
    if not re.match(r"^https?://[^/\s]+", url):
        findings.append(f"{allowed[0]}: operator_url must be an absolute HTTP(S) URL")
    if "@" not in email or any(char.isspace() for char in email):
        findings.append(f"{allowed[0]}: operator_email must be contactable")
    if "news-ab.com" in f"{url}\n{email}".casefold():
        findings.append(f"{allowed[0]}: operator identity names the production site")
    if _sha256_text(email) == PRODUCTION_OPERATOR_EMAIL_SHA256:
        findings.append(f"{allowed[0]}: operator_email is the production operator's contact")
    return findings


#: Text files the residue scan reads.  Data files (registry, i18n, fixtures, lock files)
#: are excluded: an outlet's own history or a fictional date is content, not workflow.
RESIDUE_TEXT_SUFFIXES = (".py", ".md", ".yaml", ".yml", ".toml", ".ini", ".template")
RESIDUE_SKIP_PREFIXES = ("sources/", "examples/", ".github/")
#: Files that describe the public boundary have to name what lies on the other side of
#: it (the contract, its tests, and this scanner, which names its own tokens).
RESIDUE_SKIP_PATHS = (
    "public_export.yaml",
    "tools/public_export.py",
    "tests/test_public_export_contract.py",
    "tests/test_public_exporter.py",
)
#: Private-workflow tokens that must not reach a public copy: the private repo's ticket
#: numbers, and its word for its own operator.  Inside prose that word survives only as
#: the two schema identifiers; in code it is a stored value and is not prose at all.
RESIDUE_TICKET = re.compile(r"\bT-[0-9]{3}\b")
RESIDUE_FOUNDER = re.compile(r"founder")
RESIDUE_FOUNDER_ALLOWED = re.compile(r"founder_annotation|is_founder")
RESIDUE_DOC_POINTER = re.compile(r"\bdocs/[A-Za-z0-9_./-]+\.md\b")


def _prose_lines(path: Path, text: str) -> list[tuple[int, str]]:
    """The lines of a file that are prose: comments and triple-quoted strings in Python
    (docstrings, and the stylesheet/script literals that ship inside pages), everything
    in Markdown and configuration.  Single-quoted Python strings are values — an error
    message, a fixture, a regex — and a value is data, not workflow provenance."""
    if path.suffix != ".py":
        return list(enumerate(text.splitlines(), start=1))
    lines: list[tuple[int, str]] = []
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenError, SyntaxError):
        return list(enumerate(text.splitlines(), start=1))
    for token in tokens:
        if token.type == tokenize.COMMENT:
            lines.append((token.start[0], token.string))
        elif token.type == tokenize.STRING and token.string.lstrip("rRbBuUfF")[:3] in ('"""', "'''"):
            for offset, line in enumerate(token.string.splitlines()):
                lines.append((token.start[0] + offset, line))
    return lines


def scan_workflow_residue(root: Path, files: list[Path]) -> list[str]:
    """Refuse private workflow provenance in exported prose.

    Three shapes leaked before this scan existed: bare ticket numbers, the private
    repo's name for its operator with a ruling date attached, and pointers to docs that
    are not exported (so the reader follows a link to nothing).  The rule they replace
    is the one skills/README.md already states: write the rule, not the number.
    """
    findings: list[str] = []
    for path in files:
        relative = path.relative_to(root).as_posix()
        if path.suffix not in RESIDUE_TEXT_SUFFIXES or relative.startswith(RESIDUE_SKIP_PREFIXES):
            continue
        if relative in RESIDUE_SKIP_PATHS:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for number, line in _prose_lines(path, text):
            if RESIDUE_TICKET.search(line):
                findings.append(f"{relative}:{number}: private ticket number")
            if RESIDUE_FOUNDER.search(RESIDUE_FOUNDER_ALLOWED.sub("", line)):
                findings.append(f"{relative}:{number}: private operator word")
            for pointer in RESIDUE_DOC_POINTER.findall(line):
                if not (root / pointer).is_file():
                    findings.append(f"{relative}:{number}: points at unexported {pointer}")
    return findings


def verify_export(root: Path, scope: str = "release") -> dict:
    if scope not in ("release", "workspace"):
        raise ExportError(f"unknown verification scope: {scope}")
    manifest_path = root / MANIFEST_NAME
    if not manifest_path.is_file():
        raise ExportError(f"missing {MANIFEST_NAME}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    contract_bytes = (root / "public_export.yaml").read_bytes()
    contract = yaml.safe_load(contract_bytes)
    if _digest(contract_bytes) != manifest.get("contract_sha256"):
        raise ExportError("public_export.yaml does not match the manifest contract hash")
    expected = {row["path"]: row["sha256"] for row in manifest["files"]}
    forbidden = contract["forbidden_path_prefixes"]
    local_runtime = set(contract.get("local_runtime_paths", []))
    forbidden_paths = sorted(
        path for path in expected if any(_under(path, prefix) for prefix in forbidden)
    )
    if forbidden_paths:
        raise ExportError(f"manifest contains forbidden targets: {forbidden_paths}")
    tree_files = _walk_files(root)
    actual_paths = {
        path.relative_to(root).as_posix() for path in tree_files
        if path.name != MANIFEST_NAME
        and path.relative_to(root).as_posix() not in local_runtime
    }
    missing = sorted(set(expected) - actual_paths)
    if scope == "release":
        if actual_paths != set(expected):
            extra = sorted(actual_paths - set(expected))
            raise ExportError(f"closed manifest mismatch; missing={missing}, extra={extra}")
        bad_hashes = [
            relative for relative, digest in expected.items()
            if _digest((root / relative).read_bytes()) != digest
        ]
        if bad_hashes:
            raise ExportError(f"exported file hash mismatch: {bad_hashes}")
        scanned = [path for path in tree_files if path.name != MANIFEST_NAME]
    else:
        # A clone is allowed to add its own files and to edit the released ones —
        # that is what working in it means.  Deleting a released file is not: the
        # toolkit is only complete as shipped.
        if missing:
            raise ExportError(f"released files are missing from this clone: {missing}")
        scanned = [root / relative for relative in sorted(expected)]
    findings = {
        "secret_entropy": scan_secrets(root, scanned),
        "private_identifiers": scan_identities(root, scanned, manifest),
        "neutral_defaults": scan_neutral_defaults(root),
        "local_runtime": scan_local_runtime(root, contract),
        "internal_links": scan_links(root, scanned),
        "workflow_residue": scan_workflow_residue(root, scanned),
        "license": scan_license(root, contract, manifest),
    }
    failed = {name: rows for name, rows in findings.items() if rows}
    if failed:
        raise ExportError(json.dumps(failed, ensure_ascii=False, indent=2))
    return {"files": len(expected), "scope": scope, "checks": sorted(findings)}


def export(repo: Path, destination: Path, revision: str) -> dict:
    repo = repo.resolve()
    destination = destination.resolve()
    resolved_revision = str(_run(repo, "rev-parse", f"{revision}^{{commit}}", text=True)).strip()
    contract, contract_bytes = _contract_at(repo, resolved_revision)
    gates = contract.get("release_gates") or []
    not_ready = [gate["id"] for gate in gates if gate.get("status") != "ready"]
    if not_ready:
        raise ExportError(f"release gates are not ready: {', '.join(not_ready)}")
    if contract["source_policy"].get("require_clean_worktree"):
        status = str(_run(repo, "status", "--porcelain", "--untracked-files=all", text=True))
        if status.strip():
            raise ExportError("source worktree is not clean")
    destination_preexisted = destination.exists()
    if destination_preexisted and any(destination.iterdir()):
        raise ExportError(f"destination must be absent or empty: {destination}")
    destination.mkdir(parents=True, exist_ok=True)
    tree = _tree(repo, resolved_revision)
    rows = _selected_files(contract, tree)
    written: list[dict] = []
    try:
        for source, target, mode, oid, appended in rows:
            data = contract_bytes if source == "public_export.yaml" else _blob(repo, oid)
            row = {"path": target, "source": source, "mode": mode}
            if appended is not None:
                append_source, append_oid = appended
                if not data.endswith(b"\n"):
                    raise ExportError(f"{source}: an appended base must end with a newline")
                data += _blob(repo, append_oid)
                row["appended_source"] = append_source
            out = destination / target
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(data)
            os.chmod(out, 0o755 if mode == "100755" else 0o644)
            written.append({**row, "sha256": _digest(data)})
        manifest = {
            "schema_version": "public-export-manifest-0.1.0",
            "exporter_version": EXPORTER_VERSION,
            "source_commit": resolved_revision,
            "contract_sha256": _digest(contract_bytes),
            "destination_repository": contract["destination"]["repository"],
            "history": contract["destination"]["history"],
            "files": written,
            "forbidden_identity_hashes": _forbidden_identity_hashes(tree),
        }
        (destination / MANIFEST_NAME).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        verify_export(destination)
        return manifest
    except Exception:
        # A failed destination is never a release artifact.  Only remove the directory
        # this invocation just created; an initially non-empty target was refused above.
        shutil.rmtree(destination)
        if destination_preexisted:
            destination.mkdir(parents=True)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("export", help="assemble a public tree from an exact commit")
    build.add_argument("destination", type=Path)
    build.add_argument("--repo", type=Path, default=Path.cwd())
    build.add_argument("--revision", default="HEAD")
    check = sub.add_parser("verify", help="verify an already assembled export")
    check.add_argument("root", type=Path, nargs="?", default=Path.cwd())
    check.add_argument(
        "--scope", choices=("release", "workspace"), default="release",
        help="release: the tree must be exactly the manifest, byte for byte (publisher's "
             "check on a pristine export).  workspace: every released file must still be "
             "present and clean inside a working Git clone, which may also carry its own "
             "history, installs, caches and edits.",
    )
    args = parser.parse_args(argv)
    try:
        if args.command == "export":
            manifest = export(args.repo, args.destination, args.revision)
            print(f"exported {len(manifest['files'])} files from {manifest['source_commit']}")
        else:
            result = verify_export(args.root.resolve(), args.scope)
            print(
                f"verified {result['files']} files ({result['scope']} scope): "
                + ", ".join(result["checks"])
            )
    except (ExportError, OSError, ValueError, yaml.YAMLError, json.JSONDecodeError) as exc:
        print(f"public export refused: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
