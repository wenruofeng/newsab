---
name: annotate
description: Build or extend a topic's question set, then answer every question for every reporting cluster in English pivot with source-language sentence anchors — run after the corpus is built (value chain stage 3), before analyze.
compatibility: Requires this repository and Python 3. No network.
metadata:
  newsab-stage: "annotate"
  newsab-version: "0.9.0"
  newsab-inputs: "topic_manifest,corpus,questions"
  newsab-outputs: "questions,answers"
  newsab-language: "en-pivot"
---

# annotate (Q×A)

Turns the corpus into per-cluster, per-question answer records — the semantic core the
whole product aggregates. The unit of comparison is one question × one answer;
consensus/divergence/attention-gap findings are *computed* later from what this stage
records, so an error here is invisible later and unfixable at the end. This stage never
compares sides, never counts across clusters, and never touches a sentence ID it did not
copy from a tool.

## Start here

Working directory: repo root. Inputs resolve from the topic's active runs; anything
outside the manifest's `include` is not annotated even when an article mentions it.

    export PYTHONPATH=packages/schema:packages/corpus:packages/a1:packages/editorial
    python -m newsab_schema manifest-check <topics_root> <topic_id>   # must be clean
    python skills/annotate/scripts/preflight.py <topics_root> <topic_id>   # must exit 0

Preflight is the backfill-debt gate: it exits 1 while the active corpus run owes a
debt with retry budget remaining — that corpus goes back to collect for a targeted retry,
it is not annotated. When it exits 0 with a residual-debt list, every budget is spent:
proceed, but quote the list in the run report so it reaches touchpoint two.

The corpus build must have run clean on current staging; a corpus run with disputed
cluster assignments is not worth annotating — resolve that upstream first. And the corpus
must be **settled, not just built**: an extractor, splitter or strip-rule change
mid-annotation re-derives content hashes and voids every anchor written so far (measured,
`aabb-steppe-stone-2025`: one mid-pass extractor fix invalidated all six shards — 826k tokens).
Land pending extraction fixes and rebuild first, then start the pass on the run that build
activated — and read `manifest/active.json` rather than assuming: a build can end
`stopped` without moving the pointer.

## Choose a mode

- **design-questions** — no active question set yet, or the set itself is being extended.
  Read `references/questions.md` (the six template questions, reader-tier criteria,
  approved scope seeds, category guidance, probe budget, freeze commands). The only scope
  question input is `topic_manifest.question_seeds` (or legacy `seed_questions`);
  **do not read `scope/question_candidates.yaml`** — its discovery origins were
  intentionally stripped at touchpoint one. Loop: digest → audited probe → draft 12–15
  questions → required-seed coverage check → assemble → finalize.
- **answer-clusters** — an active question set exists and clusters need answers. Read
  `references/answer-rubric.md`; core loop below.
- **incremental** — the topic already has an active answers run (new articles from a
  collect extension, or new questions across existing clusters). Read
  `references/incremental.md` first; it is the answer loop plus append-only guarantees.

## Core loop (answer-clusters)

1. *(command)* List the clusters:
   `python skills/annotate/scripts/show_cluster.py <topics_root> <topic_id> --list`
2. *(judgement)* Per cluster: print it —
   `python skills/annotate/scripts/show_cluster.py <topics_root> <topic_id> <RC-…>` —
   read **every member article in full**, then write one batch line per active question,
   `addressed: false` lines included. Anchors are copied from the printout, never
   reconstructed by hand. The three-outcome rule, evidence-first order, and entity
   normalisation are `references/answer-rubric.md`.
3. *(command, every few clusters)*
   `python skills/annotate/scripts/qa_batch.py check <topics_root> <topic_id> batch*.jsonl --scope-clusters <covered>`
   (add `--scope-questions` when the shard owns only some questions — `references/incremental.md`)
   — dangling anchors, membership violations, coverage holes and the per-question
   category tally come back while the cluster is still in front of you. Merge
   near-duplicate categories the moment the tally shows them.
4. *(command)* Full check (no `--scope-clusters`), then mint the run id off the clock
   — never hand-typed, so the ledger sorts by when the run actually happened:

       run_id=$(python -m newsab_schema mint-run-id ans)   # ans-<yyyymmddHHMMssffffff>-<8hex>
       python -m newsab_schema prepare-run <topics_root> <topic_id> answers <run_id>
       python skills/annotate/scripts/qa_batch.py assemble <topics_root> <topic_id> batch*.jsonl \
           --run-id <run_id> --model-id <model>
       python -m newsab_schema finalize-run <topics_root> <topic_id> --run-id <run_id> \
           --activate answers --skill-id annotate --skill-version <frontmatter version> \
           --model-id <model> --status completed --input-run <corpus run> --input-run <questions run> \
           --output <run file> --counters-json '{"answers": N, "addressed": N, "clusters": N}'

Evidence stays verbatim in each article's source language; summaries and normalized
categories use English pivot throughout, so one comparison group may span languages.

## Sharding to subagents

A pass may be split across workers as a working convenience that leaves no trace: all
batches assemble into one run. A worker's packet is `SKILL.md` + explicit cluster IDs +
the active questions path + its own batch output path + the check command + a stop
condition — nothing else; the integrating agent only assembles, never silently
re-categorizes. Provenance rules for carried answers: `references/incremental.md`.

Never let a shard boundary fall on a group boundary. Every worker settles its own
micro-conventions about what counts as answering a question, and that drift is tolerable
only while it lands on both sides' denominators. Give one side to the strict workers and
the other to the lenient ones and the drift becomes a difference in addressed rate — which
analyze cannot tell apart from a real attention gap, and which will be defended all the way
to the reader page. Split by cluster list interleaved across groups, so every shard carries
both sides.

Before assembling, read `check`'s per-shard addressed-rate table: same question, one column
per worker. A question whose columns disagree far more than the others is a convention
question, not a coverage one — settle the reading, re-answer the affected shards, and only
then assemble. 

## Done

`qa_batch.py check` over all batches exits 0;
`python -m newsab_schema validate-topic <topics_root> <topic_id>` exits 0 after
activation. Artifacts: `questions/versions/<run>/questions.yaml` (`QuestionSet`) and
`answers/versions/<run>/answers.jsonl` (one `ClusterAnswer` per line; complete coverage —
every active question × every cluster of the active corpus run, exactly once).

## Stop and return upstream when

- The corpus run carries blocking warnings (disputed cluster assignment) — annotating a
  disputed denominator wastes the pass; back to collect.
- A question proves unanswerable as worded (both sides ~100% `unclear`): stop and
  re-word in a new questions run rather than stretching categories.
- Navigation/copyright residue survived into a sentence: finish the pass without
  anchoring to it, and file the shape in the run report so it becomes a strip rule.
