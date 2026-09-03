"""Regenerate ``newsab_corpus/han_fold_data.py`` from OpenCC's TSCharacters.txt.

The frozen table is vendored so that cluster counts stay re-derivable from this repo
alone — a pip-installed converter's data tables can change between versions, and the
cluster count is a published number (cluster.py's determinism promise).  Run this only
to deliberately mint a new fold version; bump ``HAN_FOLD_VERSION`` in ``han_fold.py``
in the same change, because existing run records pin the old behaviour by name.

Usage::

    curl -sL -o /tmp/TSCharacters.txt \
        https://raw.githubusercontent.com/BYVoid/OpenCC/<commit>/data/dictionary/TSCharacters.txt
    python packages/corpus/tools/gen_han_fold_data.py /tmp/TSCharacters.txt <commit> \
        > packages/corpus/newsab_corpus/han_fold_data.py
"""

from __future__ import annotations

import sys
from datetime import date

HEADER = '''\
"""Frozen traditional->simplified character table — GENERATED, do not edit by hand.

Derived from OpenCC's TSCharacters.txt (single-character mappings only, first listed
simplified form when a key offers several, identity mappings dropped).

* Source: https://github.com/BYVoid/OpenCC data/dictionary/TSCharacters.txt
  at commit {commit} (Apache-2.0; see that repo's LICENSE for the notice).
* Generator: packages/corpus/tools/gen_han_fold_data.py, run {today}.
* Pairs: {count}.

Kept as two parallel code-point strings feeding ``str.maketrans`` — compact, and the
diff of any regeneration shows exactly which characters changed.
"""

# fmt: off
'''


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    src, commit = sys.argv[1], sys.argv[2]

    pairs: dict[str, str] = {}
    with open(src, encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line or line.startswith("#"):
                continue
            key, _, values = line.partition("\t")
            first = values.split(" ")[0]
            # Character table only: one code point to one code point.  The handful of
            # one-to-many entries take OpenCC's first (default) form; folding never has
            # to round-trip, so that loss is fine for a fingerprint.
            if len(key) == 1 and len(first) == 1 and key != first:
                pairs[key] = first

    for ch in list(pairs) + list(pairs.values()):
        # The emitted literals are unescaped; keep the generator honest about that.
        assert ch not in "\\\"'" and ord(ch) > 0x7F, f"unexpected character {ch!r}"

    keys = sorted(pairs)
    out = sys.stdout
    out.write(HEADER.format(commit=commit, today=date.today().isoformat(), count=len(keys)))
    for name, chars in (("_FROM", keys), ("_TO", [pairs[k] for k in keys])):
        out.write(f"{name} = (\n")
        for i in range(0, len(chars), 64):
            out.write('    "' + "".join(chars[i : i + 64]) + '"\n')
        out.write(")\n")
    out.write("# fmt: on\n\nT2S_TABLE = str.maketrans(_FROM, _TO)\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
