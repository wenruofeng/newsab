# Merging free-coded categories — working notes for the normalize agent

Why this file: turning free text into countable categories is a solved-enough problem in
qualitative content analysis, and LLM pipelines fail in the same documented ways human
coding teams do. These are the practices that transfer, adapted to this repo's setting
(categories were already minted by the annotate stage; your job is only the codebook
integration step).

## 1. Open coding first, ONE global integration after — never streaming merges

The annotate stage did open coding: each pass minted whatever categories the material
demanded. The failure mode to avoid now is *streaming* consolidation — reading
categories one at a time and merging each into whatever the growing map already holds.
Streaming makes the result order-dependent and over-merges late items (everything looks
"close enough" to some existing group once the map is large).

Instead: for one question, put **every** category from **both** sides on the table at
once (that is what `show_tallies.py` prints), sketch the equivalence classes, then
write them down. The unit of judgement is the question's whole vocabulary, not a
category pair.

## 2. Judge the data, not the labels

Two snake_case labels can look synonymous and code different answers
(`policy_reversal` vs `legal_challenge`: both "pushback", different actors and
mechanisms), or look different and code the same answer
(`chinese_government_or_embassy` vs `beijing_officials`). The label is a hash, not the
meaning. Read each category's `answer_summary` lines and its verbatim evidence
sentences before grouping; if you cannot tell from the summaries whether two categories
answer the question the same way, they stay separate.

## 3. The merge test: substitutable as an answer to THIS question

Merge X and Y only if a reader who asked this exact question would take X and Y as the
same answer — same referent, same direction. Useful probes:

- **Referent**: do they name the same actor/object (at the granularity the question
  asks about)? "US government" absorbs "State Department" for *who is blamed*, but not
  for *who is quoted*.
- **Direction**: a cautious and a confident version of the same claim are different
  answers to a "how certain" question and the same answer to a "what happened" question.
- **Level**: never merge a specific answer into a vague neighbour just to build a
  majority (`economic_concerns` swallowing `nickel_price_drop`). Vague + specific stay
  split unless the summaries show annotators used them interchangeably.

Per-question scope is structural: the same two spellings may merge under one question
and stay apart under another. That is why the map is keyed by `question_id`.

## 4. Asymmetric costs: under-merge is recoverable, over-merge is not visible

An unmerged duplicate shows up as a split tally someone can question; a wrong merge
manufactures a majority and disappears into a clean-looking number. When in doubt,
don't. The analyze stage's `merge_sensitive` flag will surface the cases where your
merge decides the outcome — those are exactly the ones your rationale must survive
review on.

## 5. Two-pass self-consistency

LLM coding decisions are noisy at the margin. The skill requires the same inputs judged
twice, independently (no shared context), then intersected: a group survives only if
both passes drew the same equivalence class. This is the machine version of intercoder
agreement, with the conservative resolution rule (disagreement → no merge) built in.
Expect the intersection to drop the marginal calls; that is the point.

## 6. No "other" bucket

Human codebooks end with an "other" outlet. Here that outlet already exists upstream
(`unclear`, minted by annotate) and downstream (the posterior's *unseen* slot). The map
must never create a catch-all category: a merge into `other_concerns` is an over-merge
by construction.
