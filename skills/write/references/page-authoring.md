# Page authoring — angles, sides, badges, lexicon, appendix

Read this when writing a new page (with `references/style.md` for sentence-level rules).
Everything here is enforced by the schema or `page-check`; it is written down so you
build with the constraints instead of against them.

## Choosing 2–6 angles

Each angle is one distinct question, ordered as a storyline — the contrast worth
repeating first, then what the reader asks next. The candidate rank proposes; you
decide, and the run report says why angle 1 leads (there is no hook field: angle 1 *is*
the hook).

- An `unsupported` finding may not become an angle, be asserted in prose, or be drawn in
  a visual. This bar outranks the count: if the evidence yields only two angles, the page
  ships with two (the catalog floor; product ruling) — never pad the
  storyline to reach a number. One angle is not a comparison and does not ship.
- A `weak` finding may — and you write **nothing** about its weakness; the renderer
  labels it identically on every page (an icon before the question, its words on hover).
  `caveat` is only for what code cannot know; footnote rendering and standalone rules for
  `caveat`/`detail`: `references/style.md` §2.
- An `attention_gap` finding is a first-class candidate. It asserts one side is
  *near-silent*, so its angle **always** marks that side `is_silent_side: true` — the
  checks refuse anything else. The quiet side gets no writer answer, label or quotes:
  the renderer words the near-silence (with the mention count when non-zero) and lists
  the quiet side's few mentions itself. The silent side's `answer` text, where present,
  states *annotation-layer* silence ("no cluster in the sampled X-language coverage was
  annotated as answering this"), never absence from the world; the speaking side
  supplies the contrast anchors.
- A `merge_sensitive` finding's kind or top answer depends on the category map: compare
  `category_counts_raw` with `category_counts` for both sides before using it — if the
  story only exists under the merged tally, say so in the run report or drop the angle.
- Every angle carries one line of `editorial_interest` (English pivot): why a reader
  would care. It is never rendered — an angle's value has to come
  through the writing, not through a note explaining the writing — so the checks require it
  as the audit trail of "interesting" and the reader never sees it.
- One question gets at most one angle block.
- **`commentary_joint`** (optional, a `PageClaim`): one paragraph for both sides,
  rendered full-width instead of the two side columns, when the angle is genuinely one
  thought and splitting it would produce mirrored filler. The side `answer` claims stay
  required and checked either way. Rules: `references/style.md` §11.

## Writing a side (`SideAnswerBlock`)

- **`answer`** — what *that side's coverage* answers. Usually `corpus_reading`
  (≥ 2 anchors, no digits, no quantifier words) or `corpus_aggregate` (must name
  `computed_from`). Never name the side in it — the card header already carries the
  side's tag, so "Most often, the coverage here frames…", not "The sampled
  Chinese-language coverage most often frames…".
- **`answer_label`** — the answer itself in three to eight words, shown on the answer
  card above both side blocks. `answer_category` names the annotate category it puts
  into words; the checks refuse a label whose category is not the one the badge counts.
  When both sides land on the same category, word it once at angle level as
  `shared_answer_label` — both cards then carry those same words, joined by the =
  connector, and the checks require it.
- **`quotes`** — the side's representative quote (one is enough, up to three), sentence
  IDs from **that side's own articles**, drawn from the finding's `sample_evidence` or
  equally strong answers. The renderer builds the full evidence list itself (one original
  per counted cluster, your pick leading) and puts it behind the card's **evidence icon**, so
  a quote must come from a cluster the badge actually counts. Quote text is never typed —
  the renderer pulls it verbatim from the corpus.
- **`badge`** — `computed_from: "<FND-…>"` or `"<FND-…>:addressed"` (addressed/total),
  or `"<FND-…>:top_category"` (modal category over addressed clusters). A tied side
  states the tie explicitly in its answer and may **not** use the singular
  `top_category` selector — use `addressed`. The checks recompute both numbers; never
  type a number that is not one of these pairs.

## The title

The title is the one line a reader meets in a catalog row, a share card and a browser tab,
often before they know anything about the topic. Spend it on **what is specific to this
topic**.

**Never spend it on the comparison.** Every page on this site compares two coverages;
that is the product, not the news. "One X, two Y", "…and how the two sides differ" say
the same thing on every page there will ever be and crowd out the words that would have
named the topic. Measured, 2026-08-28: six of eight titles were built on that pattern,
and read together they are nearly interchangeable.

What earns the space:

- the **proper noun** a reader will not know but should (`Zuuvch-Ovoo`, `Somaïr`, the name
  of the rule) — a title is also how someone finds this page again;
- a **concrete quantity or span** both coverages report (thirty years, 90,000 tonnes) —
  specific, checkable, and it makes the topic's scale immediate;
- a **question the topic itself poses**, if the coverage genuinely argues about it
  ("Who gets to define a döner") — not a question about the coverage.

Two constraints carry over. A title **adopts neither side's interpretive frame** — on a
divergence, the two modal answers are exactly what it may not assert; build it from what
both report. And it **adjudicates nothing**: the topic's name, not the page's conclusion.

## The intro (4–6 claims)

Enough for someone who has read nothing: what the policy/event is, what it replaces,
when it was decided and when it takes effect, the stated official reason, whatever else
is in motion. One fact per claim, each with its own anchor — the renderer sets claims as
a list, so a claim needing three sentences is two claims. Most are `source_claim`s:
their digits must appear verbatim in their anchored sentences. Do not state the sampling
window or corpus size — the renderer computes that line from the manifest and corpus.

The intro is the page's least checkable section and its most dangerous. Nothing here is
bound to a finding, so every claim can be individually true while the set of them asserts
something the statistics never did. Two failures no script can see:

- Composition. Count the claims by whose actions they describe before writing the angles.
  Five facts about one side's moves and one about the other's give the reader "that side is
  the active, unsettled party" — a comparative claim, made by arithmetic the reader does
  unconsciously, that no finding supports. Aim for parity in *acting* claims; the shared
  facts of the event (the figures, the timeline) sit outside that count.
- Order. Chronology is not neutral when the sequence *is* the disagreement. Listing
  A-then-B-then-outcome states A caused B where the two coverages differ on exactly that,
  and it does so before the reader reaches the angle where the dispute is named. When the
  causal chain is contested, lead with what both sides report — the event, the figures —
  and let the angle carry the sequence.

## The reader lexicon (`page.lexicon`)

The page's whole reader-facing vocabulary, in one place; a gap in either map is a
`page-check` warning and the reader being shown internal vocabulary.

- `questions`: **every** question in the active set (not only the angles), worded as a
  reader would ask it. It must ask the same thing as the annotation wording — narrower
  or different means a new question for annotate, not a rewording here.
- `categories`: **every** `answer_category` appearing in any group's `category_counts`,
  in three-to-six reader words, parallel within a question so the chart reads as one
  axis.
- `scope`: every `include` and `exclude` bullet of the topic manifest, keyed by its
  **verbatim English original**, in the reader's language (the manifest cannot carry the
  translation — `scope_hash()` covers every field, so adding one would invalidate every
  existing `scope_approval`). Keep the wording faithful: it is what touchpoint one signed
  off on, not a chance to re-scope. render-localize fills this; `page-check` warns per
  missing bullet.

## Visuals

Only where they carry story weight (`answer_distribution`, `addressed_rates`,
`coverage_timeline`). A visual may not draw a contrast the text may not assert; one on a
question no angle asserts raises a warning — resolve it or drop it. Every question's own
distribution is already one click away in the data card; a declared `answer_distribution`
has to earn its place against that.

**`concept_cloud` is the exception — declare exactly one per page:**

```json
{"kind": "concept_cloud", "data_from": "qa_run:question_stats",
 "caption": {"values": {"en": "Key concept cloud", "zh-CN": "关键概念云"}}}
```

You write the caption and nothing else; the mechanism sentence, sizes, ranking and
threshold footnote are the renderer's, identical on every page. `data_from` stays
`qa_run:question_stats`; what the section actually counts is a render-time switch
(`page-render --concept-cloud`) over the annotated answer categories or the collect
stage's per-report topic phrases, and is render-localize's to set.

## Machine-owned pin block

`page_init.py` fills the four legacy `how_we_counted` run pointers; do not edit them and
do not write `notes` (it stays empty; old stored notes are ignored). The renderer
combines those pointers with the signed scope and the manifest ledger to generate the
**Page record**, and the **Method** panel is renderer-owned template text — the writer
contributes no text to either footer panel.

## Claim-type invariants (mechanically enforced)

| kind | requires | forbids |
|---|---|---|
| `source_claim` | ≥ 1 anchor; its digits verbatim in the anchored sentences | `computed_from` |
| `corpus_reading` | ≥ 2 anchors | digits; quantifier words; `computed_from` |
| `corpus_aggregate` | `computed_from` naming a finding of the pinned run | any number that does not recompute from it |

Angle ranks are 1..n with no gaps; every claim carries `text.en`.
