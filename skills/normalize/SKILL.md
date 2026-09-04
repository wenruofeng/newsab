---
name: normalize
description: Judge which of a topic's answer categories are the same concept and freeze those merges into a versioned category map — run after annotate (value chain stage 3.5), before analyze. Merge-only; the analyze stage applies the map deterministically.
compatibility: Requires this repository and Python 3. No network.
metadata:
  newsab-stage: "normalize"
  newsab-version: "0.3.1"
  newsab-inputs: "questions,answers,corpus"
  newsab-outputs: "normalization"
  newsab-language: "en-pivot"
  newsab-counters: |
    questions_with_merges: number of questions whose category map records at least one merge
    merge_groups: number of merge groups (each grouping 2+ categories into one) across the map
    categories_merged: number of individual category labels absorbed into a merge group
---

# normalize (category map)

The annotate stage mints `answer_category` values freely, so one concept can end up
under two spellings — and the split vote then silently decides every downstream
statistic. This stage is where an agent judges which categories are the same concept,
and **only** here: the judgement is frozen into a versioned `CategoryMap` that analyze
applies deterministically. Merge-only — collapsing spellings is reversible bookkeeping;
splitting a category would need re-annotation and is forbidden. This stage never edits
the question set or the answers.

## Start here

Working directory: repo root. Inputs: the topic's active question set, answers run and
corpus run, resolved automatically.

    export PYTHONPATH=packages/schema:packages/corpus:packages/a1:packages/editorial
    python -m newsab_schema manifest-check <topics_root> <topic_id>   # must be clean

Read `references/coding_practices.md` (how to merge free-coded categories without
flattening real distinctions) and `references/map-contract.md` (the draft form and the
machine-enforced invariants) before the first judgement.

## Core loop

1. *(command, per question)*
   `python skills/normalize/scripts/show_tallies.py <topics_root> <topic_id> --question QST-…`
   — the question, its `category_guidance`, **both** sides' full tallies, each
   category's answer summaries and up to three verbatim evidence sentences.
2. *(judgement)* Decide merges with the question's whole vocabulary on the table at once
   — never streaming, never from labels alone. Merge only what is the same answer to
   *this* question (same referent, same direction); when unsure, don't. One `rationale`
   sentence per group.
3. *(command)* Check the draft:
   `python skills/normalize/scripts/check_map.py check <topics_root> <topic_id> draft.json`
   — invariants plus the raw → merged tally diff per question, for your own eyes.
4. *(command)* Ask what a second pass could still change:
   `python skills/normalize/scripts/check_map.py plan draft_a.json --answers-run-id <ans run>`
   (the answers run `check` just printed)
   — the agreed map is `A ∩ B ⊆ A`, so a second pass can only ever **remove** groups,
   never add one. On a question pass A left alone it is a proven no-op. `plan` prints
   the questions pass A drew groups on — the whole scope of the second pass — and the
   `two_pass` skeleton to fill in.
5. *(judgement — self-consistency, scoped)* If `plan` named questions, judge **those
   questions only** a second time, in a pass that never sees pass A's draft (a subagent,
   or a sitting with cleared context), then:
   `python skills/normalize/scripts/check_map.py intersect draft_a.json draft_b.json --out agreed.json`
   — a group survives only when both passes drew the same equivalence class;
   disagreements downgrade to no-merge and earn a line in the run report. If `plan` said
   pass A drew nothing, the draft **is** the agreed map: skip the second pass and record
   it as skipped. (Measured over five real topics: pass A proposed groups on three of
   nine runs, and the unconditional second pass burned ≈150k tokens of tallies on four
   topics where it could not have changed a thing.)
6. *(command)* Mint the run id off the clock — never hand-typed, so the ledger sorts
   by when the run actually happened — then:

       run_id=$(python -m newsab_schema mint-run-id nrm)   # nrm-<yyyymmddHHMMssffffff>-<8hex>
       python -m newsab_schema prepare-run <topics_root> <topic_id> normalization <run_id>
       python skills/normalize/scripts/check_map.py assemble <topics_root> <topic_id> agreed.json \
           --run-id <run_id> --model-id <model> --two-pass-json @two_pass.json
       python -m newsab_schema finalize-run <topics_root> <topic_id> --run-id <run_id> \
           --activate normalization --skill-id normalize \
           --model-id <model> --status completed --input-run <questions run> --input-run <answers run> \
           --output <category_map.json> --output <two_pass.json> --counters-json \
           '{"questions_with_merges": N, "merge_groups": N, "categories_merged": N}'

   `--skill-version` defaults to this file's frontmatter `newsab-version` (a mismatched
   explicit value is refused); the three counters above are the complete list in this
   file's frontmatter `newsab-counters` — an unlisted `--counters-json` key gets a warning.

   This mint-run-id → prepare-run → assemble → finalize-run sequence has no end-to-end
   test coverage.

   `assemble` refuses without `--two-pass-json`, and writes it into the run directory as
   `two_pass.json` — which answers run the two passes judged, how many groups each pass
   drew, which questions the second pass covered, how many the intersection dropped, plus
   optional `both_passes_rejected` / `sent_upstream` prose. It is an artifact, not
   run-report prose, because "was the second pass worth it" must stay answerable from the
   store years later. `answers_run_id` must be the topic's **active** answers run:
   re-judging a re-coded answers run means writing a new record, and a record carried over
   from the previous run is refused by name rather than passing as identical bytes.

7. *(command)* Re-run analyze so the map takes effect. Findings flagged
   `merge_sensitive: true` are the ones your merges decide — their rationales must
   survive review.

**Incremental**: a new answers run with new categories does not invalidate the map (new
categories pass through as identity), but review whether they belong to an existing
group and produce a new map run if so. A question re-worded in a new questions run
starts from no merges.

## Done

`check_map.py check` on the final map exits 0; `manifest-check` exits 0 after
activation. Artifacts: `normalization/versions/<run>/category_map.json` — merge-only, no
chains, every group with a rationale, provenance carrying the judging model's id — and
`two_pass.json` beside it, recording what the second pass was asked to do and what it
changed (`pass_b_groups: null` when it was rightly skipped).

## Stop and return upstream when

- A category needs **splitting** (one spelling covering two answers) — annotate-stage
  work; file it for a re-annotation pass, never stretch the map.
- The two passes disagree on most groups — the question's `category_guidance` is too
  loose to code against; escalate to question wording rather than shipping a map nobody
  can reproduce.
- A category is **polluted** (one spelling covering two answers that a merge cannot
  separate, e.g. a residual "other" bucket): that is a re-coding job for annotate. Name
  it in `sent_upstream` and file it — do not let it pass silently because the map came
  out empty.
- A merge would flip a finding's kind and the evidence sentences do not clearly read as
  one answer: leave the merge out and note the case in the run report.
