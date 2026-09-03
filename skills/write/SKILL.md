---
name: write
description: Turn a topic's ranked Q×A findings into the reader page — intro, storyline, 2–6 angle cards with both sides' answers, verbatim quotes and recomputable count badges — run after analyze (value chain stage 5), before render-localize.
compatibility: Requires this repository and Python 3. No network.
metadata:
  newsab-stage: "write"
  newsab-version: "0.17.0"
  newsab-inputs: "questions,answers,qa_analysis,corpus,topic_manifest"
  newsab-outputs: "page"
  newsab-language: "en-pivot"
---

# write

Writes the English-pivot master of one topic's reader page (`ReaderPage`,
`packages/schema/dist/reader_page.schema.json`) from the analyze stage's ranked findings.
The statistics already decided *what may be said*; this stage decides **what is worth
reading and in what order**, and binds every reader-facing sentence to its provenance path
at the moment it is written. Findings are the only source of comparative statements; the
renderer and checks own everything recomputable, including the complete page record — the
writer never supplies disclosure copy.

## Start here

Working directory: repo root. Inputs: the pinned analyze run's `findings.jsonl` +
`question_stats.json`, the active questions/answers/corpus runs, and the topic manifest
— all under `topics/<topic_id>/`.

    export PYTHONPATH=packages/schema:packages/corpus:packages/a1:packages/editorial
    python -m newsab_schema validate-topic <topics_root> <topic_id>   # must be clean

## Choose a mode

- **new-page** — no page yet for this topic (or a rewrite): read
  `references/style.md` (sentence-level rules) and `references/page-authoring.md`
  (angles, sides, badges, lexicon, appendix), then the core loop below.
- **repin-page** — the page exists and only the analysis run moved: do **not** re-read
  the authoring references; run the tool and write only what it hands back:

      python skills/write/scripts/repin_page.py <topics_root> <topic_id> \
          --page <previous page.json> \
          --qa-run topics/<topic_id>/analysis/<new-qa-run> \
          --old-qa-run topics/<topic_id>/analysis/<pinned-run> \
          --out topics/<topic_id>/editorial/versions/<new-edt>/page.json

  It remaps every `finding_id` and `computed_from` (ids are rank-free, so only a meaning
  change renames a finding), recomputes every badge, moves the machine-owned pin block,
  then reports `PROSE` (a claim whose text states a number — take the new number from the
  pinned finding, never from the old sentence) and `PROBLEM` (the rerun changed the story —
  an angle went `unsupported`, changed kind, lost its modal category: writing decisions
  the tool refuses to make). Then `page-check … --langs en` arbitrates (step 4), and the
  run is finalized exactly like step 5, with the new qa run among the `--input-run`s.
- **fix-page** — the page exists, the analysis has not moved, and render-localize's spot
  check named specific defects. Read `references/style.md`; read
  `references/page-authoring.md` only for the sections an escalation actually reaches.
  Your input is the current `page.json` plus the escalation list — nothing else, and in
  particular not a brief to improve the page.

  **Change only what an escalation names, and change it as narrowly as the escalation
  allows.** A section the judge did not fault is not yours this round: an unrequested
  rewrite is a fresh surface for the next round to fault, and it re-opens text an earlier
  judge already passed. If an escalation cannot be fixed without touching something it
  does not name, say so and stop rather than widening the edit yourself.

  Two escalation kinds are **not** yours to fix, and both go back with a reason: one that
  can only be answered by changing a finding, a count or an annotation (upstream's call),
  and one whose remedy this skill's own rules forbid — the judge asking for a hedge on a
  `weak` card is the standing example, since §2 of `references/style.md` reserves that to
  the renderer's badge. Name the rule and the rubric line; a human rules on one of them.

  Then step 4's `page-check` and step 5's finalize, exactly as new-page. A fix round is a
  new `edt-` run like any other — the page is append-only, so never edit an earlier run's
  `page.json` in place.
- Input carries `blindspot`/`coverage_gap` kinds or rank-positional finding ids? Read
  `references/legacy-runs.md` first.

## Core loop (new-page)

1. *(judgement)* **Read the findings in rank order** plus `question_stats.json` — kind,
   strength, stability, delta, `total_silence` / `merge_sensitive` flags, each side's
   `top_categories`. The rank proposes; you decide, on editorial value plus statistical
   evidence alone. Do not inspect scope question-candidate material or
   `topic_manifest.question_seeds` while selecting angles; human-required status ended
   after annotation coverage, and analyze applied ordinary thresholds.
2. *(command)* Start from a structurally complete draft instead of guessing the schema:

       python skills/write/scripts/page_init.py <topics_root> <topic_id> \
           --qa-run <qa-run-id> -o draft_page.json

   The reader lexicon comes from the topic's active page where it has one — reader
   wording is a human's, and regenerating it reverts every rewording a reviewer asked
   for. What the command prints as newly generated is machine vocabulary and still has to
   be rewritten. `--no-inherit` for a first draft or a deliberate rewrite;
   `--previous-page` to inherit from another page.
3. *(command + judgement)* Build the authoring packet from the page draft before writing
   angle prose; it puts the material in the order the finished page presents it, followed
   by every counted report behind each card:

       python skills/write/scripts/angle_authoring_packet.py <topics_root> <topic_id> \
           --page <draft-or-current-page.json> --qa-run topics/<topic_id>/analysis/<qa-run-id> \
           -o <scratch>/angle_authoring_packet.md

   **Choose 2–6 angles and write both sides of each** as Q–A–explain: read every counted
   annotation and its original anchors in the packet, synthesize the modal reports'
   shared causal or evidentiary route, and write only the concise journalistic logic the
   card itself does not already say. Then the intro (4–6 one-fact claims), the reader
   lexicon and the visuals. Leave `how_we_counted` exactly as `page_init.py` generated it
   — a compatibility pin block, not a writing surface. Every constraint and decision
   table: `references/page-authoring.md`; every sentence rule: `references/style.md`.
4. *(command)* Check, fix, recheck until clean — errors block, and every warning gets an
   answer in the run report. `page-check` refuses `provenance` still carrying
   `page_init.py`'s placeholder stamps, so mint the page's run id and name the writing
   model no later than here — a placeholder that survives to finalize costs the whole
   immutable run:

       run_id=$(python -m newsab_schema mint-run-id edt)   # off the clock, never typed
       python -m newsab_editorial page-check <topics_root> <topic_id> \
           --page <page.json> --qa-run topics/<topic_id>/analysis/<qa-run-id>

5. *(command)* Write the page into `editorial/versions/<run>/page.json`, then finalize:

       python -m newsab_schema finalize-run <topics_root> <topic_id> --run-id <edt-run> \
           --activate editorial --skill-id write --skill-version <frontmatter version> \
           --model-id <model> --status completed --input-run <qa run> --input-run <answers run> \
           --input-run <corpus run> --output <run dir>/page.json \
           --counters-json '{"angles": N, "quotes": N, "badges": N}'

## Done

`page-check` exits 0 with all warnings answered in the run report;
`python -m newsab_schema validate-topic <topics_root> <topic_id>` exits 0 after
activation. Artifact: `editorial/versions/<run>/page.json`, English pivot complete
(render-localize fills other languages).

## Stop and return upstream when

- The candidate pool is empty (no finding reaches `weak`) — there is no page at this
  corpus size. Say so and stop; never lower the evidence bar for a story, and never
  touch `qa-*` thresholds to rescue an angle.
- A finding contradicts what its anchors plainly say — an annotation defect; file it
  and stop rather than writing around it.
- The story needs a question nobody asked — mint a new questions run and re-run
  annotate + analyze (incremental is normal); never stretch an existing question's
  meaning in the lexicon.
