# Style guide — the reader page

The page is data journalism for a curious non-specialist, not a methods section. The
discipline lives in what a sentence is *allowed to claim*; it must not leak into how every
sentence *sounds*.

## 1. The subject is the coverage, not the world

Every comparative statement is about the sampled coverage: "the sampled US-language
coverage frames the rule itself as the problem". This constrains **what the claim
asserts** — it is not a formula to repeat in every sentence. The side block's header
already carries the side's tag (中方 / 美方, group definition on hover), so the sentences
inside it name nobody: "Most often, the coverage here frames…". Naming the sample in a
claim already scoped reads as flinching, and readers stop believing sentences that
apologise.

**Never**: "Indonesian media ignore layoffs." (adjudicates the world)
**Never**: "In the sampled Indonesian-language coverage of the 32 clusters analysed under
run ans-… , it appears that…" (defensive noise in the reader's line of sight)
**Yes**: "No cluster in the Indonesian-language sample was annotated as answering who
loses their job." (annotation-layer silence, stated once, plainly)

A silence claim never stands alone: it sits next to the speaking side's **contrast
anchors** — the analyze stage attaches to every attention-gap finding the sentences where
the other side *did* answer — so the reader sees what the silence is silent about, not
just an absence asserted.

## 2. Never assert or draw what the statistics do not support

- `unsupported` findings do not exist on the page — not in prose, not in a caption, not as
  a bar someone can eyeball into a contrast. The checks refuse them.
- `weak` findings are labelled by the renderer, not by you: one badge whose tooltip carries
  the pinned thresholds. Never write the hedge yourself — "at this sample size the gap
  could go either way" in prose is the thing the label exists to replace, and two copies of
  it read as an apology. `caveat` is for what code cannot know (a sampling limitation, an
  asymmetric window), never for restating the statistics.
- `caveat` and `detail` reach the reader only through **numbered inline footnote
  markers** opening a light bubble — never a second marker row or badges beside the
  question. Write each to survive being read alone: two or three sentences, no "as noted
  above", no pronoun whose antecedent sits in the paragraph beside it. They are overflow,
  not a second body: an angle that needs three footnotes to land is an angle whose two
  paragraphs are doing the wrong work. Point at one with `[^1]`; source numbering is
  angle-local (`caveat` first, then each `detail`), the renderer assigns page-wide display
  numbers. A marker with no note is dropped, an unreferenced note is not rendered, and
  markers are punctuation, not quantities — they never make a `corpus_reading` claim a
  counted one.
- Insinuation counts as assertion. Two adjacent sentences that let the reader draw an
  unsupported contrast are the same violation as stating it.

## 3. Magnitudes carry their interval

Any stated gap carries the finding's interval or its stability, in reader words: "about
twice as often (roughly 1.4–3× across resamples)". A bare point estimate for a `weak`
finding is a claim the analyze stage did not make.

Digit discipline is mechanical: a `corpus_reading` claim carries **no digits and no
quantifier words** (`all`, `none`, `no`, `every`, `most`, `majority`, `half`, `twice`,
`double`) — the moment you count, the claim is a `corpus_aggregate` bound to a finding. A
`source_claim`'s numbers must appear verbatim in its own anchored sentences.

## 4. Counts are clickable, not decorative

A badge says `11/12`; its tooltip explains that the unit is independent reports. The
separate evidence control opens the eleven supporting reports. Never mix units within a
page. Percentages over denominators below ~20 are noise dressed as precision; give the
fraction.

## 5. Quotes

One to three per side per angle, each a verbatim sentence with a link to the source and a
translation for the reader's language. Choose the sentence that shows the framing, not the
one that summarises the article. Never stitch two sentences into one quote; never
paraphrase inside quote marks. A side's column quotes only that side's articles.

When quoting part of a sentence, sentence punctuation stays **outside** the closing quote
mark (`…"stay indefinitely".`): pasting the quoted span into the publisher's page must
Ctrl-F to a hit, and that beats typographic convention.

**A quote whose sentence is not English needs `translation.en`, written now, by you.**
English is the page's pivot master, not one more localized language render-localize will
get to later — leave it out and the English page itself ships an unfinished sentence.
Measured, 2026-09-03: a nine-locale ship found the English page's non-English quotes
carried translations for every other language but never English, so an English reader met
a bare foreign sentence, and every other-locale localization judge flagged the same
quotes for having no pivot text to compare their own translation against. Faithful, not
polished: keep the original's hedges and register: report what it says, not a smoother
paraphrase. `page-check` refuses a missing one; `angle_authoring_packet.py` marks each
non-English evidence sentence so you catch it while picking the quote, not after.

## 6. Internal vocabulary stays in the footer records

Run IDs, `RC-…` / `QST-…` / `FND-…` identifiers, "cluster answer", "threshold version",
"bootstrap", "R-gate", skill names — none of these appear in the reader flow.

- **Method** is renderer-owned template text, identical on every page: counting
  unit, the Q×A model, support labels and silence semantics. You write none of it.
- **Page record** is also renderer-owned. It is generated from the signed scope, pinned
  run pointers and append-only manifest ledger. It lists component run IDs, timestamps,
  producer versions and fingerprints. You write none of it; leave `how_we_counted.notes`
  empty and never use the footer to carry an editorial caveat.

## 7. Structure carries the story

Intro (what happened, and over what timeline — 4–6 claims) → angles in the order a reader's
questions arrive, not in score order, the one contrast worth repeating first → visuals where
they carry weight → appendix. If an angle needs a paragraph of setup to land, it is either
the wrong angle or belongs later.

**What a reader actually sees for one angle**: the question, then two answer cards
with the relation between them drawn in the middle (= agreement / × divergence / a broken
line for silence), each card carrying its side's tag and `X/Y` count — then **your two
paragraphs, and nothing else**, tight under the cards. The original supporting reports and
statistics are behind icons; the data card is folded under the angle. So the two paragraphs
are the only prose on the page and they are read directly against the cards above them.

**Intro order.** If most intro claims carry a date, put them in ascending chronological
order — a reader who meets April after July stops trusting the sequence. The exception is
§"Order" in `page-authoring.md`: when the causal chain is itself what the two coverages
disagree about, lead with what both sides report and let the angle carry the sequence.

## 8. Tone

Plain, specific, unhurried. No editorialising verbs about the sources ("admits", "claims",
"finally concedes"). No suspense-building. The interesting thing is the contrast itself;
it does not need help.


## 9. Say the question the way a person would ask it

The reader meets one question per angle and one per row of the data view, both from
`page.lexicon.questions`, both prefixed `Q:`. The annotation wording is written to make an
annotator reproducible; the reader wording is written to be asked out loud.

**Annotate**: "What is presented as the problem — what the new visa rules respond to, or
the rules themselves?"
**Reader**: "在整个事件里，问题出在哪儿？"

**Annotate**: "Is the policy presented as targeting Chinese students specifically, or
international students in general?"
**Reader**: "签证新规针对的是中国学生，还是国际学生整体？"

If the frozen question is **compound** and only one half was ever coded, the reader
wording states the coded half and drops the other; the run report records the trim. That
is the one narrowing this rule allows, and it is a repair — showing a reader a question
whose second half the page never answers is worse. Prevention belongs upstream:
`skills/annotate/references/questions.md`, "One question asks one thing".

The two must ask the same thing. If the plain version is narrower, broader, or about
something else, you have invented a question — that belongs to annotate, not here.

## 10. Answer categories are counting keys; give them reader words

`international_students_generally` is a key, not a phrase. Every category the page can
display gets three to six reader words in `page.lexicon.categories`. Keep them parallel
within a question so the chart reads as one axis: "The rules themselves" / "Overstaying and
security" / "Falling international enrolment", not one noun phrase, one clause and one
gerund.

`page-check` warns when a label equals `page-init`'s machine default (the raw key,
title-cased) — that is a hint to look, not proof the label is wrong. A short key's default
can already be the best reader word: measured, `Mixed` / `See it` / `Guilt and atonement`
all tripped this warning and were already correct — the fix that run made,
`Genuinely mixed` / `Go and see it`, was longer and not better, added purely to make the
checker stop talking. If the flagged label is already the right reader word, say so in the
run report and leave it; do not add words just to silence the warning.

## 11. Q–A–explain: the two paragraphs justify the answers

Each side's `answer` is one paragraph in its own column under its own answer card. The
reader has just read the question and the answer label; their next thought is **why did
this side arrive at that answer?** — the paragraph answers exactly that. The visible
structure is Q → A → explain, not Q → A → a writer's impression of A.

Before drafting, inspect the answers and anchored sentences behind the category the `X/Y`
badge counts, and find the concise shared logic of those reports — the causal sequence
they repeat, the evidence they foreground, the actor whose decision changes the outcome,
the premise they treat as given. Write that logic on behalf of that side's reporters: a
synthesis of their work, not a description of your own interpretive process.

They are read as a pair, immediately under two cards that already say the answers. So they
must not **say the answers again in mirrored sentences**:

**Never**: "The question here is who is to blame, and the coverage here says the
government." / "The question here is likewise who is to blame, and the coverage here
likewise says the government." (Two sentences of scaffolding, no information, and the
symmetry makes the emptiness louder.)

**Never**: "This side gives that answer from the position of capital already invested…"
or "The logic here is…" — announcing an interpretation instead of reporting it. Lead with
the concrete mechanism: the smelters were built under one set of terms; quota,
benchmark-price and supply restrictions then changed their costs after the capital was
committed.

Use compact news prose: concrete subject, active verb, causal connection. Remove throat
clearing ("what matters here is", "seen from this side") and any sentence that merely
paraphrases the card; one short paragraph is enough when every sentence advances the
justification. Put `[^n]` exactly where a caveat or supplementary fact qualifies that
logic — the footnote extends the explanation, never becomes a detached second argument.

Hold each paragraph to the triangle **angle kind — question — answer**: given that this is
an agreement / a divergence / a silence, on *this* question, what does *this* answer mean?

- **Agreement** — the two sides reached the same answer from different evidence or routes.
  Report each route: who is quoted, which facts or sequence support the answer, what is at
  stake for that side's readers. Same destination, two roads is the story; "both sides say
  the same thing" is the card, not the paragraph.
- **Divergence** — explain the evidentiary route to each answer: which actor's actions the
  reports foreground, where their causal timeline begins, and what they treat as the
  decisive fact. A divergence paragraph that only names a vantage or restates the labels
  has explained nothing.
- **Silence** — on the speaking side, the reason its coverage has an answer at all: whose
  question it is, why it matters there. On the quiet side, the *weak signal* — the one or
  two mentions that do exist, what they were attached to — without asserting an answer the
  data does not support.

When the angle is genuinely one thought for both sides — where a divergence comes from,
why an agreement is not the obvious answer, a shared source both coverages work off —
write it once as `commentary_joint` (`AngleBlock.commentary_joint`, a `PageClaim` like any
other), rendered as one full-width paragraph instead of two columns. Use it only when one
concise chain of evidence immediately justifies both cards, never to avoid finding the
second side's logic. It does **not** replace the two side `answer` claims — those stay,
anchored and checked — but it replaces what the reader is *shown*, so it must carry the
angle alone.

### Every outlet you name and every fact you cite needs an anchor in that side's `evidence`

The two explanation paragraphs read as reporting, so they attract reporting's specifics
("Le Figaro opens on the coup", "Sfen adds the half-year loss"). Each is a checkable
assertion, and the independent judge checks them against the **angle's own anchors** — not
the corpus, which it cannot see. A true fact whose anchor is missing scores exactly like
an invented one, and should: the reader's click has nowhere to land either. So
`answer.evidence` is not the two anchors `page_init.py` copied from the finding's sample —
it is every sentence the paragraph leans on. Draft, then read back naming the anchor for
each specific; anything left over gets an anchor or is deleted. Measured,
`aabb-steppe-stone-2025`: two consecutive spot-check rounds fired on this (six, then five
unanchored specifics), every one a fact genuinely in the corpus that was simply not
anchored.

`page-check` now warns on the mechanical half of this: an outlet named in a paragraph
whose side anchors no sentence from that outlet, a decimal figure the side's anchors do
not carry, and (with `--strict-names`) a proper name absent from them. It resolves a
masthead through `sources/registry.yaml` and an anchor through the corpus, so that half
holds across languages; a name or figure only compares within one script, and nothing
mechanical compares meaning. It therefore catches **named but unanchored** and never
**anchored but wrong** — "Variety pairs the CinemaScore grade with the second-weekend
gross *to argue that audiences were not troubled*" has both names anchored and the causal
claim is still the writer's. Silence from it is not clearance; the read-back above and the
judge panel remain the check on everything it cannot see.

### Write to the rendered frame

Do not review an explanation as a free-standing paragraph. Review the exact sequence the
reader sees: **reader question → answer label and count → relation symbol → explanation**.
The label has already spent the words that answer “what”; the paragraph earns its place
only by answering “why”. Delete its opening sentence if the sequence still makes sense
without it — that is the usual sign the sentence merely restated the card.

On desktop the two explanations are parallel columns under equal-sized cards — a layout
that amplifies false symmetry and density imbalance. Pair-read them before finalizing:
neither column may become background exposition while the other carries the actual
justification, and mirrored prose manufactured to fill the second column is the sign the
angle wanted `commentary_joint`. The required `angle_authoring_packet.py` packet is the
pre-draft view of this frame; its counted-report section is the evidence universe for the
explanation — the two hand-picked claim anchors alone are never enough for a modal
synthesis.
