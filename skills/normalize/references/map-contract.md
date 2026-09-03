# The category map — draft form and the invariants that shape judgement

Authoritative schema: `packages/schema/dist/category_map.schema.json` (generated from
`packages/schema/newsab_schema/models/category_map.py`). Never restate it — this file
covers only what an agent must know while judging.

**The draft form** — all an agent ever writes by hand; `assemble` stamps every header
and the provenance:

```json
{"merges": {"QST-…": [
  {"canonical": "us_government",
   "members": ["us_state_department", "trump_administration_officials"],
   "rationale": {"text": "Both name the US executive as the blamed actor; the articles do not distinguish department from administration.", "lang": "en"}}
]}}
```

Invariants that change what you may write (all machine-enforced, by the model or
`check_map.py`):

- **Merge-only, no chains**: within one question no member appears in two groups and no
  canonical is another group's member — applying the map is one lookup. Splitting a
  category is annotate-stage work, forbidden here.
- Every member must be a category actually **observed** in the pinned answers run for
  that question. The canonical is normally one of the members; a fresh umbrella spelling
  is allowed but flagged for review.
- `unclear` never appears on either side of a merge.
- A question with nothing to merge is **omitted** — identity is the default, and an
  empty `merges` object is a valid identity map. "Judged and found nothing to merge" is
  still a run with provenance; it is never conflated with "not judged".
- One `rationale` sentence per group, English pivot, concrete enough for a reviewer to
  challenge.

**The two-pass record** (`two_pass.json`, written by `assemble` beside the map) is the
second artifact of every run:

```json
{"answers_run_id": "ans-…", "pass_a_groups": 0, "pass_b_questions": [],
 "pass_b_groups": null, "dropped": 0,
 "both_passes_rejected": "…optional…", "sent_upstream": "…optional…"}
```

`answers_run_id` names the answers run the two passes actually judged, and `assemble`
refuses it unless it is the topic's active answers run. It exists because a two-pass
record is otherwise indistinguishable from a copy of the previous run's: two normalize
runs once shipped byte-identical records while claiming to have judged different answers.

`assemble` refuses the run without it and checks it against the map: pass A drawing no
groups forces `pass_b_groups: null` (the agreed map is `A ∩ B ⊆ A`, so a second pass
cannot change an empty draft); pass A drawing groups forces a second pass that covered
at least every question the map keeps, and `dropped` must equal
`(A − agreed) + (B − agreed)`, the number `intersect` printed.

Downstream, so you know what your merges move: analyze projects every answer's category
through the map before counting and keeps the merged tally beside the raw one; a finding
whose kind or top answers differ between the two tallies is flagged
`merge_sensitive: true`, and the write stage is required to open both tallies before
using it. Those findings are exactly the ones your rationale must survive review on.
