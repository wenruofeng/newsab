# newsab-a1

The deterministic statistics layer (blueprint §3.3 A1). **Not a skill — that is decision
D10**, and it is the reason a submission can be re-verified without running any model.

```
observations + corpus + ontology
  → build_feature_matrix()    cluster × feature support        product 1
  → scan_all()                eight candidate families         product 2
  → metrics per candidate     divergence · prevalence ·
                              source diversity · bootstrap ·
                              cross-stratum consistency        product 3
  → rgate.evaluate_all()      the statistical gate (D8)
```

## Use

```sh
python -m newsab_a1 run       topics aabb-river-light-2026
python -m newsab_a1 gate      topics/aabb-river-light-2026/analysis/a1-...
python -m newsab_a1 recompute topics/.../analysis/a1-... topics/.../angles/versions/s6-.../candidate_angles.jsonl
```

`gate` is a read-only audit command and prints its result. Pipeline S6 uses
`skills/archive/s6-angle-gate/scripts/run_rgate.py`, which writes into an S6 version workspace;
an A1 run directory is never extended or changed after its manifest entry is committed.

`recompute` is the one that matters for review: it rebuilds the feature matrix from the
stored run, re-derives every metric, and fails if a stored number does not match
(§4.4.1 invariant 1). Wire it into validation with:

```python
from newsab_a1 import recompute_metrics
from newsab_schema.validate import validate_angles

validate_angles(angles, topic_id, recompute=recompute_metrics(run_dir))
```

## Decisions baked into this package

| decision | where it lives | what breaks if you undo it |
|---|---|---|
| Clusters, not articles, are the denominator (D7) | `FeatureMatrix.prevalence` | every prevalence figure on the site becomes a wire-copy count |
| No p-values (D16) | absent everywhere; `BootstrapResult` reports direction stability | the site starts making inferential claims its sampling cannot support |
| The gate cannot see `origin` (D9) | `Candidate` has no such field; `tests/test_d9_origin_blindness.py` tokenises the gate modules | confirmation bias re-enters through a threshold branch |
| Editorial never lowers the bar (D8) | R-gate runs on `Candidate`, before any E-score exists | a good story becomes a reason to accept weak evidence |
| Absent denominator ≠ zero | `prevalence()` returns `None` for an empty group | "sample too small" gets published as "0%" |

## Metric selection is deliberately unfinished

`configs/rgate-0.1.yaml` is marked `calibrated: false` and every threshold in it is a
placeholder. Blueprint §0.5 defers these numbers to Phase 0 calibration against the
user's "Defensible" scores, and `calibration.py` is the harness for doing it.
`evaluate_all(..., require_calibrated=True)` raises rather than gating publication-bound
work against uncalibrated thresholds.

Divergence and diversity are **registries**, not fixed formulas, for the same reason —
`divergence_methods()` currently offers `prevalence_diff`, `log_odds_ratio` and
`jensen_shannon_within_dimension`, and calibration picks between them on correlation
with human judgement rather than on elegance.

## Storage note

The matrix is written as parquet when `pyarrow` is importable and CSV otherwise, and
`run.json` records which. `a1_run_id`'s digest is computed from a canonical JSON
serialisation of the rows, so it is identical either way — the container is an
implementation detail, the hash is the contract.

Every successful `run` also appends a hash-bound `model_id=null` entry to the topic
manifest. The already-versioned `analysis/<a1_run_id>/` directory is created with
`exist_ok=False`, so A1 never overwrites an earlier run.
