# newsab-schema

The single definition site for this project's data. Blueprint ④ describes five schemas;
this package makes them executable, and adds the corpus-side records they reference,
the controlled vocabularies (§4.1), the sentence-ID grammar, the lint lexicons and the
§4.2.2 / §4.4.1 invariant checkers.

**Nothing in this repo may define a controlled enum value anywhere else.** Non-Python
consumers read `dist/enums.json`; documents link to `dist/enums.md`.

## Install

```sh
uv sync                                  # preferred: the repo-root uv workspace installs it into ./.venv
export PYTHONPATH=packages/schema:$PYTHONPATH   # no-install fallback
pip install -e packages/schema           # only inside a venv owned by this checkout, never a shared interpreter
```

## Layout

| path | what it holds |
|---|---|
| `newsab_schema/enums.py` | every controlled vocabulary; §4.1's four are marked `LOCKED` |
| `newsab_schema/ids.py` | `sentence_id` / `article_id` / `OBS`-`ANG`-`CLM` grammar and parsers |
| `newsab_schema/common.py` | `LangText`, `Provenance`, `GateRecord`, the immutable `Record` base |
| `newsab_schema/models/` | the record types (`corpus`, `annotation`, `analysis`, `gold`, `manifest`) |
| `newsab_schema/lints/` | lint engine + the word lists it runs on (`data/*.yaml`) |
| `newsab_schema/validate/` | cross-record invariants, incl. the S6 `constraint_report` |
| `newsab_schema/paths.py` | the `topics/<id>/…` layout as a typed object |
| `newsab_schema/io.py` | JSONL/YAML artifact readers and writers |
| `newsab_schema/artifacts.py` | locked manifest append, version selectors, correction validation |
| `dist/` | **generated**: JSON Schema + enum tables for non-Python consumers |

## CLI

```sh
python -m newsab_schema validate-topic topics aabb-river-light-2026
python -m newsab_schema validate observations topics/<id>/observations/observations.jsonl \
    --corpus topics/<id>/corpus/articles --ontology topics/<id>/ontology/concepts.yaml
python -m newsab_schema lint --lang zh-CN --text "…"
python -m newsab_schema export --check      # fails if dist/ is stale
python -m newsab_schema manifest-check topics <id>
python -m newsab_schema record-correction topics <id> correction.json
```

Exit codes: `0` clean · `1` validation failed · `2` usage or IO problem.
`--strict` turns warnings into failures; use it when no judge or human will review the run.

## Things that will bite you

- **Records and run outputs are immutable.** `Record` sets `frozen=True` and
  `extra="forbid"`; stage outputs live below unique run directories and the manifest writer
  rejects duplicate run IDs (§3.2). A correction is a new record plus a mapping, never an edit,
  and an unknown field is an
  error rather than a silent drop.
- **`dist/` is generated.** Edit the Python, run `python -m newsab_schema export`.
  `tests/test_dist_in_sync.py` fails if you forget.
- **Metric recomputation is opt-in.** `validate_angles` warns loudly when no `recompute`
  hook is passed — pass `newsab_a1.recompute_metrics` in any run that matters, or
  §4.4.1 invariant 1 is not actually being checked.
- **`origin` must never reach a threshold.** D9 is enforced by
  `tests/test_d9_origin_blindness.py`, which scans the gate implementations' source.
