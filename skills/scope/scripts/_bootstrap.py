"""Import shim — see ``skills/_shared/bootstrap.py``.

Walks up rather than counting parents, so a skill directory can be nested (archived) or
moved without every script in it breaking.
"""

import sys
from pathlib import Path

for _parent in Path(__file__).resolve().parents:
    _shared = _parent / "_shared"
    if (_shared / "bootstrap.py").exists():
        sys.path.insert(0, str(_shared))
        break
else:  # pragma: no cover - only when the repo layout is broken
    raise ImportError("could not locate skills/_shared/bootstrap.py")
from bootstrap import ROOT, install  # noqa: E402,F401
