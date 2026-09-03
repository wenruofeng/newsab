#!/usr/bin/env python3
"""Run the standalone public toolkit's complete, offline acceptance gate.

This command is intentionally executed from an exported tree or from a clone of one,
never from the private operating repository.  It checks the released files, then proves
that all active skills are packaged, schemas are current, tests pass, and the fictional
eight-stage closure builds through candidate review and publication without network or
model access.

``--scope workspace`` (the default) is what a user or a contributor runs in their own Git
clone: the released files must all be present and clean, and the clone is free to carry
its own history, editable installs, caches and edits.  ``--scope release`` is the
publisher's stricter check on a pristine export and additionally requires the tree to be
exactly ``export-manifest.json``, byte for byte; ``tools/public_release.py`` runs it that
way before any release is synced.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
PACKAGE_DIRS = ("schema", "corpus", "a1", "editorial", "publish")
TOPIC_ID = "aabb-river-light-2026"


class GateError(RuntimeError):
    pass


def _environment() -> dict[str, str]:
    env = os.environ.copy()
    paths = [str(REPO / "packages" / name) for name in PACKAGE_DIRS]
    if env.get("PYTHONPATH"):
        paths.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(paths)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


_RESOLVE_PROGRAM = """
import importlib.util, json, sys
found = {}
for name in json.loads(sys.argv[1]):
    spec = importlib.util.find_spec(name)
    found[name] = spec.origin if spec is not None else None
print(json.dumps(found))
"""


def _check_toolkit_is_this_tree() -> None:
    """Refuse to gate one tree while importing another tree's code.

    ``_environment()`` prepends this tree's ``packages/*`` to ``PYTHONPATH``, which beats a
    ``.pth``-style editable install of some other checkout.  It does not beat every one:
    a PEP 660 editable install can instead register a finder on ``sys.meta_path``, and
    meta-path finders outrank ``PYTHONPATH`` entirely.  On such a machine every check below
    would pass while saying nothing about the tree under the cursor, so resolve each package
    exactly the way the child processes will and require it to live here.
    """
    names = [f"newsab_{name}" for name in PACKAGE_DIRS]
    proc = subprocess.run(
        [sys.executable, "-c", _RESOLVE_PROGRAM, json.dumps(names)],
        cwd=REPO, env=_environment(), capture_output=True, text=True, check=False,
    )
    if proc.returncode:
        raise GateError(f"could not resolve the toolkit packages: {proc.stderr.strip()}")
    found = json.loads(proc.stdout)
    missing = sorted(name for name, origin in found.items() if origin is None)
    if missing:
        raise GateError(
            "toolkit packages are not importable: " + ", ".join(missing) + "\n"
            "install them from this tree: `uv sync` in the repo root, then run the gate "
            "with `uv run python tools/public_release_gate.py`"
        )
    foreign = {
        name: origin for name, origin in sorted(found.items())
        if REPO not in Path(origin).resolve().parents
    }
    if foreign:
        listed = "\n".join(f"  {name} -> {origin}" for name, origin in foreign.items())
        raise GateError(
            "these packages resolve outside this tree, so gating it would prove nothing "
            f"about it:\n{listed}\n"
            "an editable install elsewhere wins over PYTHONPATH; run the gate in this "
            "tree's own environment (`uv sync`, then `uv run python tools/public_release_gate.py`)."
        )
    import pydantic  # noqa: PLC0415 — reported, not used, so drift is visible in any log

    print(f"toolkit imports resolve inside this tree (pydantic {pydantic.VERSION})")


def _run(label: str, *command: str) -> None:
    print(f"\n== {label} ==", flush=True)
    proc = subprocess.run(command, cwd=REPO, env=_environment(), check=False)
    if proc.returncode:
        raise GateError(f"{label} failed with exit code {proc.returncode}")


def _assert_stage_outputs(demo: Path, result: dict) -> None:
    topic = demo / "topics" / TOPIC_ID
    publication = result.get("publication_id", "")
    required = {
        "scope": topic / "topic_manifest.yaml",
        "collect": topic / "corpus/versions/s2s-202608290900-f1000001/corpus_run.json",
        "annotate": topic / "answers/versions/ans-202608290902-f1000003/answers.jsonl",
        "normalize": topic / "normalization/versions/nrm-202608290903-f1000004/category_map.json",
        "analyze": topic / "analysis/qa-202608290904-f1000005/findings.jsonl",
        "write": topic / "editorial/versions/edt-202608290905-f1000006/page.json",
        "render-localize": demo / f"review-render/zh-CN/topics/{TOPIC_ID}/index.html",
        "publish": demo / f"site/publications/{publication}/publication.json",
    }
    missing = [stage for stage, path in required.items() if not path.is_file()]
    if missing:
        raise GateError(f"synthetic stage outputs missing: {', '.join(missing)}")
    expected = {
        "candidate_verified": True,
        "site_verified": True,
        "finding_kinds": ["divergence", "consensus", "attention_gap"],
        "clusters_per_group": {"aa": 3, "bb": 3},
        "syndicated_articles": 1,
    }
    mismatches = {
        key: {"expected": value, "actual": result.get(key)}
        for key, value in expected.items()
        if result.get(key) != value
    }
    if mismatches:
        raise GateError(f"synthetic acceptance mismatch: {json.dumps(mismatches, sort_keys=True)}")
    print("eight stage proofs: " + ", ".join(required))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scope", choices=("workspace", "release"), default="workspace",
        help="workspace (default): released files present and clean inside a working "
             "clone.  release: the tree must also be exactly the manifest, byte for byte.",
    )
    args = parser.parse_args(argv)
    try:
        print("\n== toolkit provenance ==")
        _check_toolkit_is_this_tree()
        _run(f"{args.scope} export, leak, link, and license checks", sys.executable,
             "tools/public_export.py", "verify", ".", "--scope", args.scope)
        _run("eight active skill package preflights", sys.executable,
             "tools/skills_check.py", "--strict")
        _run("schema regeneration diff", sys.executable, "-m", "newsab_schema",
             "export", "--check")
        _run(
            "full clean-clone tests",
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "no:cacheprovider",
            "packages",
            "tests",
        )
        with tempfile.TemporaryDirectory(prefix="newsab-public-demo-") as temporary:
            demo = Path(temporary)
            _run("synthetic eight-stage build", sys.executable,
                 "examples/synthetic-topic/build_demo.py", str(demo))
            result = json.loads((demo / "demo-result.json").read_text(encoding="utf-8"))
            _assert_stage_outputs(demo, result)
    except (GateError, OSError, json.JSONDecodeError) as exc:
        print(f"public gate refused ({args.scope} scope): {exc}", file=sys.stderr)
        return 1
    print(f"\npublic gate passed ({args.scope} scope)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
