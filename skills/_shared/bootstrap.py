"""Put this repo's packages on ``sys.path`` without requiring an install.

Every skill script starts with::

    import _bootstrap  # noqa: F401

``_bootstrap.py`` in each skill's ``scripts/`` is a two-line shim that imports this file.
The duplication is deliberate: skills/README.md rule 1 says a skill must run under any
agent harness, and "run `pip install -e packages/schema` first" is a setup step a
contributor's agent will skip. If the packages *are* installed, this is a no-op.
"""

from __future__ import annotations

import sys
from pathlib import Path

PACKAGES = ("schema", "corpus", "a1", "editorial")


def repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "packages").is_dir() and (parent / "skills").is_dir():
            return parent
    raise RuntimeError(
        f"could not locate the repository root above {here}; expected a directory "
        "containing both packages/ and skills/"
    )


def install() -> Path:
    root = repo_root()
    for name in PACKAGES:
        path = root / "packages" / name
        if path.is_dir() and str(path) not in sys.path:
            sys.path.insert(0, str(path))
    return root


ROOT = install()
