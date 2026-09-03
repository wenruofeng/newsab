# Answer rubric — how to fill one ClusterAnswer

## The unit

One record = one reporting cluster × one question. A cluster is usually one article;
when it has several members (wire copies, syndications), read them all — the answer is
the cluster's, and evidence may come from any member.

## `addressed`

`true` iff some sentence(s) in the cluster **answer the question** — not merely touch
its topic. "美国政府收紧签证" mentions the government; it does not *blame* it. The
test: could you write the summary as a direct reply to the question, citing only this
cluster's sentences? If not, `addressed: false`.

`addressed: false` is a finding, not a failure, and it must be an explicit record —
the assembler rejects a pass with coverage holes. Never pad: an invented answer is
worse than silence because analysis cannot tell padding from coverage.

## The answer, evidence-first

1. Find the sentence(s) that answer the question. Copy their anchors from
   `show_cluster.py` output. If you cannot name the sentence, there is no answer.
2. Write `summary` — one or two sentences in **English pivot**, describing
   what THIS cluster's answer is. It is a statement about the text ("报道将责任归于美
   方政策"), never about the world ("美方政策造成了损失").
3. Pick `category` per the question's `category_guidance` (see questions.md). Before
   minting a new category, re-read the tally of what you already used — near-duplicate
   categories are the main way counts rot.
4. One question × one cluster has exactly **three** possible outcomes (confidence
   scoring is retired — the 0–1 scale was never calibrated across topics
   and nothing reads it): `addressed: false`; `addressed: true` with a clear category;
   or `addressed: true` with `category: unclear` — the cluster takes the question up
   but the answer resists bucketing. `unclear` counts toward the answer rate and stays
   out of the cross-side comparison; it is the honest outlet that used to hide in a
   low confidence number. Do not write `confidence` at all.
5. `notes` (English): judgement calls a reviewer should see — entity normalisation,
   ambiguous referents, why a plausible reading was rejected. Normalise entities at this
   semantic layer: the same person under different transliterations across outlets
   (Fanta Aw = 范塔·欧 = 范塔·阿夫) is **one** speaker, never two, and the call is
   recorded here.

### A `none_*` category is an answer, not a synonym for silence

Most `category_guidance` vocabularies end with a negative bucket — `no_date_given`,
`none_quoted`, `risk_not_discussed`, `no_fiscal_detail`, `no_opposition_mentioned`,
`none_notable`. These are answers, and `addressed: true` requires evidence, so a negative
bucket is available **only when you can anchor a sentence that characterises the
absence**: the article says the start date has not been set, says the terms were not
disclosed, says no one has claimed responsibility. A cluster that simply never takes the
sub-topic up is `addressed: false` — no category, no evidence.

Get this backwards and the damage is invisible in your own batch and severe in the
aggregate: a negative bucket counts toward the addressed rate, silence does not.
Measured, `aabb-steppe-stone-2025`: one worker of six read "the article is on-topic but never
touches this dimension" as licence for a negative bucket and used 26 of them, where the
other five shards used 0-2 between them. Its addressed rate ran 20-40 points above its
siblings' on four questions — a difference analyze cannot tell from a real attention gap.
Settle this reading before the pass, and read `check`'s per-shard table before assembling:
one column standing far off the others on a question is this, not coverage.

## Anchoring constraints (id-side defects, `docs/decisions.md`)

- Never anchor on navigation/copyright residue. Post split-0.2.0 the known shapes are
  stripped, but if you see one that survived, do not anchor to it — record it in the
  run report instead (it is a new rule for `strip_residue`).
- Fallback-splitter articles (`id`): if an anchor's sentence is a fragment cut at an
  abbreviation, include the next sentence ID too, so the quote is whole.

## What this stage never does

- Never compares sides. You annotate one cluster at a time against the question; the
  analyze stage does the comparing. If you notice a striking contrast, note it in the
  run report — not in the records.
- Never alters or "cleans up" source evidence. Evidence stays verbatim in the source
  language; only the summary and normalized category use English pivot.
- Never counts. No "most clusters say…" anywhere in a summary — a summary describes
  its own cluster only.
