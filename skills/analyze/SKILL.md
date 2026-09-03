---
name: analyze
description: Compute the ranked consensus/divergence/attention-gap findings from a topic's Q×A answers — a thin wrapper over `python -m newsab_a1 qa`, with no model judgement anywhere; run after annotate and normalize (value chain stage 4), before write.
compatibility: Requires this repository and Python 3. No network, no model.
metadata:
  newsab-stage: "analyze"
  newsab-version: "0.6.0"
  newsab-inputs: "questions,answers,normalization,corpus"
  newsab-outputs: "qa_analysis"
  newsab-language: "en-pivot"
---

# analyze

Turns the active Q×A answers into the writer's candidate pool: one finding per question at
most, each a single assertion with a posterior probability (`stability`) gated into
`supported` / `weak` / `unsupported`. The active category map is applied deterministically
before counting. **No LLM computes or changes anything here** — the statistics live in
`packages/a1/newsab_a1/qa_analyze.py`; this stage runs them and reports what it saw.
Interpreting the findings into a page is the write stage's job, not this one's.

## Start here

Working directory: repo root. The topic's active `questions`, `answers`, `corpus` and
(optional) `normalization` runs are resolved automatically.

    export PYTHONPATH=packages/schema:packages/corpus:packages/a1:packages/editorial
    python -m newsab_schema validate-topic <topics_root> <topic_id>   # must be clean

## Core loop

1. *(command)* `python -m newsab_a1 qa <topics_root> <topic_id>`
   (`--corpus-run-id` to pin a non-active run). This computes the findings, writes the
   run directory and appends the manifest entry itself — never add one by hand.
2. *(command)* `python -m newsab_schema validate-topic <topics_root> <topic_id>` again.
3. *(judgement — the post-analyze sanity read, routing responsibility 9)* Open the anchors
   behind the top few findings —
   `python skills/annotate/scripts/show_cluster.py <topics_root> <topic_id> <cluster_id>`
   prints a cluster's sentences with their anchors attached. You are looking for an
   *annotation* defect surfacing as a finding (a drifted category, a cluster answering a
   question it does not really answer), not re-judging the arithmetic. This step produces
   diagnostics for the run report only; it never edits the analysis artifacts.

   The defect this catches most often is a **category-name collision**: two sides land on
   one category label while their clusters mean different things by it, and the arithmetic
   reports a consensus that no reader of the anchors would recognise. Read a side's *modal
   clusters*, not a sample across both — a collision is invisible from the aggregate and
   obvious the moment you read the five clusters that produced the mode. 

## Done

Both commands exit 0; the run directory holds `findings.jsonl` (`QAFinding` per line,
`packages/schema/dist/qa_finding.schema.json`) and `question_stats.json` (per-question
counts and intervals, including questions with no finding) under
`topics/<topic_id>/analysis/<qa-run-id>/`. Record the printed ranking and anything the
sanity read surfaced in the task report — that record is what the write stage works from.

## Stop and return upstream when

- A finding is plainly wrong given its anchors — an annotate defect. Fix it in a new
  answers run and re-run analyze; never work around it downstream.
- The candidate pool is empty (nothing reaches `weak`) — the corpus is too small for this
  question set; the remedy is more collection or better questions, not softer gates.
- A threshold looks miscalibrated — record it for the calibration track. Thresholds are
  never adjusted by this stage, and never to rescue a finding of any kind. An outcome the
  page might not want — zero attention gaps, nothing above `weak` — is still the honest
  outcome, and it ships as such.
