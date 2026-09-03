# Legacy analyze runs — read only when the input is actually old

Trigger: the pinned analyze run's findings carry `kind: blindspot` or
`kind: coverage_gap`, or its finding ids read as rank-positional serials. Current runs
need none of this file.

- **Kinds**: `blindspot` / `coverage_gap` are the retired ancestors of
  `attention_gap`. A `blindspot` angle follows the same contract: the quiet side is
  marked `is_silent_side: true`, carries no writer quotes, and its answer states
  annotation-layer silence only. Older runs may also carry a `secondary` flag on
  findings; it is retired and nothing reads it.
- **Finding ids**: legacy runs minted `FND-…-007` = "seventh by interest in that run" —
  a rank, not a name, so a rerun renamed everything. `repin_page.py` detects the legacy
  form and carries the page forward by meaning (question serial + kind); never remap a
  legacy id by eye.
- **Statistics**: legacy runs gate on bootstrap intervals rather than posterior
  probabilities. Do not mix vocabulary: describe a legacy finding in its own run's
  terms, or — better — re-run analyze and repin the page instead of writing against a
  retired statistic.
