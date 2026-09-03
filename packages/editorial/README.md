# `editorial/` — the deterministic half of write and render

The writer, the mechanical checks and the renderer need the same joined view of a topic.
Building it once is what stops an angle card, a claim and the rendered page from quietly
disagreeing about the same number.

| module | owns |
|---|---|
| `evidence.py` | the **answer index**: which clusters a badge counts, which sentences may be quoted for a finding, and the per-side answer blocks a card is assembled from. Every quote is read from the article store and is byte-identical to it (non-negotiable 2). |
| `page_checks.py` | the **mechanical refusals** of value chain stage 6: count badges recomputed from the analysis run, character-exact quotations, claim provenance, no unsupported contrast stated or visually implied, required languages complete. Failures are refusals, not warnings. |
| `page_render.py` | the **reader page**: one self-contained HTML file per topic and language, rendered straight from the artifacts with no smoothing. The user's touchpoint-two question — does this page mislead? — cannot be answered against JSONL. |

```sh
python -m newsab_editorial page-check  topics aabb-river-light-2026 \
    --page page.json --qa-run topics/aabb-river-light-2026/analysis/<qa-run> --langs en,zh-CN
python -m newsab_editorial page-render topics aabb-river-light-2026 \
    --page page.json --qa-run topics/aabb-river-light-2026/analysis/<qa-run> \
    --lang zh-CN -o preview.zh-CN.html
```

The retired S5/S7/S8 interface (`brief` / `check` / `preview`, and the `brief.py`,
`checks.py`, `render.py` that backed it) was removed with the G2 gate it served.
It required a gate ruling that the value chain no longer produces, so calling it could
only ever block a run that was correct.

## What this package deliberately does not do

- **It does not derive numbers.** Every count badge is recomputed from the analysis run
  it names (D10). A number the analysis run cannot reproduce is a refusal, not a warning.
- **It does not decide.** `check_page` refuses a page that states an `unsupported`
  contrast rather than downgrading it to a hedge — what survives the refusals is the
  writer's problem, and quietly weakening the sentence would hide that (V-3).
- **It does not localise.** S5 writes the source's own language, S7 the English pivot; S9
  translates the master (D6). Nothing here writes a second research version of anything.

## The three claim types, and why the third exists

`corpus_aggregate` says our sample looks like this and points at a metric.
`source_claim` says someone said this and points at the sentence.
`corpus_reading` (D24, product ruling at G2) says *we read the coverage and
this is what the two sides answer* — the layer readers actually care about, which no
current metric measures. It may carry no `computed_from` and no quantifier, and needs two
anchors; `validate_claims` enforces all three. That is how the cost of publishing it stays
visible instead of being absorbed into a number.
