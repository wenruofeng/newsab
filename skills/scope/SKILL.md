---
name: scope
description: Turn the user's one-sentence topic into a signed-off scope — topic manifest, collection plan and reviewed reader-question seeds — in a single sitting; run before collect (value chain stage 1), with the user present or an explicitly requested AI stand-in.
compatibility: Requires this repository, Python 3, and permitted web/browser access for bounded reader-question reconnaissance.
metadata:
  newsab-stage: "scope"
  newsab-version: "0.10.0"
  newsab-inputs: "source_registry"
  newsab-outputs: "topic_manifest,collection_plan,question_candidate_review"
  newsab-language: "en-pivot"
---

# scope

Touchpoint #1, and it is a *sitting*, not a process: the user gives one sentence
— the issue, the A/B split, a rough window — the agent enriches it into something
concrete enough to collect against and hands it straight back in the same session.
Anything that cannot be settled in the sitting is a default the agent picks and records,
not a question queued for later. The gate approves **scope and risk, never a
conclusion**: no output of this stage has a field for an expected finding, and none may
smuggle one in as prose. This stage does not collect, and it does not decide what the
comparison will show. When the user explicitly asks an AI to stand in at this
touchpoint, the record says so; that stand-in has less authority over questions than a
human, never equal authority by implication.

## Start here

Working directory: repo root. Input: the user's sentence, plus the registry slice this
topic needs (a lookup, never a gate — a topic may need outlets not in it yet):

    export PYTHONPATH=packages/schema:packages/corpus:packages/a1:packages/editorial
    python -m newsab_corpus registry find --country <CC> --lang <lang>
    python skills/scope/scripts/scope_tool.py init <topics_root> <topic_id> \
        --title-en "…" --group <id>:<PREFIX> --group <id>:<PREFIX> [--model-id <model>] \
        --contributor <name> --review-locale <bcp47> [--review-stand-in-model-id <model>]

`topic_id` is `<sides>-<subject>-<year>`: the two groups' abbreviations concatenated in
manifest order (`cnjp`, `jpkr`, `detr`; `intl` for a side that is not one country), a
one-or-two-word subject, and the year of the events compared. **`aabb` is the test
fixtures' placeholder for "side A + side B" and never names a real topic** — you will see
it all over `packages/*/tests`; copying it into a production tree is a real mistake that
has happened, and the id is pinned into the run closure by the time anyone notices, so it
cannot be renamed. Full convention: [`topics/README.md`](../../topics/README.md),
"Naming a topic".

## Core loop

1. *(judgement)* **Fix the comparison.** Two groups minimum, each
   `{group_id, prefix, label, short_label, definition}`. `definition` is the membership
   rule in natural language; it may span countries and languages — country and language
   stay article metadata, never group selectors. Each side must be collectable through
   its *own* channels. `short_label` is the short pronoun (two to four words or
   characters, whichever the language counts in) the reader meets everywhere a side is
   named, decided here with the user, in every reader language you expect to publish; keep the pair symmetrical — two sides named on the
   same axis ("中方"/"美方"), never one by country and the other by language.
2. *(judgement)* **Write `include` / `exclude` as specific lines** — who, what, which
   window. "Coverage of the nickel industry" is not a scope; "Indonesian 2026 RKAB
   nickel-quota decisions and reported effects on miners and smelters" is. `exclude`
   earns its place by naming the adjacent things a collector would otherwise sweep in.
3. *(judgement)* **Set the window and draft the plan** — read
   `references/collection-plan.md` for this step only: per-side terms and outlets,
   channel status, the **access policy** (fetch identity, browser-retry rule, retention
   row — one policy, both sides, fixed here because taken later it is taken silently at
   fetch time and moves which media reach the sample), cluster-denominated targets,
   `expected_silence`, and the window rationale (checked answerable on both sides — a
   window one side had not yet begun reporting in reads downstream as an attention gap).
4. *(judgement + bounded web reconnaissance)* **Acquire and review reader questions** —
   read `references/question-acquisition.md` for this step only. Search systematically but
   cheaply in the relevant reader languages, add the agent's own candidates and any
   user-authored questions to `scope/question_candidates.yaml`, then present one compact
   checklist. The user has two boxes per candidate: approve, and require annotate to
   ask a semantically equivalent question. Unapproved candidates stay in this scope-only
   file and leave the downstream context. If the user explicitly delegated touchpoint
   one to an AI, it may check approve only; the tool rejects any AI-created requirement.

       python skills/scope/scripts/scope_tool.py apply-question-review \
           <topics_root> <topic_id> --decided-by human

   Use `--decided-by llm_stand_in --stand-in-model-id <model>` only under that explicit
   delegation. The manifest receives only `seed_id`, multilingual text and
   `reference|required`; it receives no discovery origin. These seeds do not feed the
   collect query matrix.
5. *(judgement)* **Name who answers for this topic, and in which language they read.**
   `--contributor <name>` for each human who put it forward — the page record shows them,
   and unless a stand-in is declared they are also who signs this scope and who takes
   touchpoint two. No contributor publishes as "anonymous", which is a choice, not a
   default to drift into. If the user wants an AI to take touchpoint two, it has to be
   decided *here*: `--review-stand-in-model-id <model>` writes the fact into the manifest
   so the rendered page can state who reviews it. Nothing may be injected into approved
   bytes afterwards, so a review authority discovered late costs a re-render.

   `--review-locale <bcp47>` is the same kind of fact and is required: **the language
   touchpoint two will be read and signed in.** It is not yours to default — read it off
   the sitting itself (the language the user is speaking to you in, and the language they
   read news in), and when the two disagree or you are working from a relayed request,
   ask; one word settles it. Every later stage reads this field rather than guessing:
   render-localize localizes into it, publish makes it half the localization floor
   (English pivot plus this), and the dashboard keys the approval hash and the reviewer's
   own recorded words to it. It must be one of the site's nine languages
   (`newsab_schema.HALO_LOCALES`), because touchpoint two is a page the renderer has to
   be able to produce. It sits outside `scope_hash`, so a correction later is an edit, not
   a re-signature — but a topic that reaches render-localize without it stops there.
6. *(judgement)* **Set `risk_level`.** Anything naming private individuals is at least
   `high`. Legal and safety questions are user decisions, in this sitting, never agent
   defaults.
7. *(command)* `python skills/scope/scripts/scope_tool.py check <topics_root> <topic_id>`
   — validates the draft, lints both artifacts for expected-finding language, and prints
   the scope hash plus everything the user is about to rule on.

## Done

The user reads, edits in place, and gives their explicit OK — then, and only then, for
a human sitting:

    python skills/scope/scripts/scope_tool.py approve <topics_root> <topic_id> \
        --approved-by user --decided-by human

    python -m newsab_schema validate-topic <topics_root> <topic_id>

For an explicitly requested stand-in, use `--decided-by llm_stand_in` and
`--stand-in-model-id <model>`; the question review must use the same authority. The command
binds the approval to the exact current scope hash and sets `status: active`; collect
mechanically refuses a missing or stale approval, so an agent-typed `active` enum
alone cannot pass the touchpoint. Artifacts: `topics/<topic_id>/topic_manifest.yaml` and
`topics/<topic_id>/scope/{collection_plan.md,question_candidates.yaml}`. The candidate file
is retained for scope audit but is not an annotate input. The manifest is the topic's root
artifact, not a versioned run — later scope changes are git commits with a reason,
re-approved because the hash went stale.

## Stop and hand to the user when

Scope or window, thresholds that would move a published number, and legal/safety — all
settled in the sitting itself. Everything else the agent decides and records. If the
user is absent and has not explicitly requested an AI stand-in, this stage does not
run: a relayed request ("they mentioned last week…") is neither presence nor delegation,
and `--decided-by human` on anyone else's say-so falsifies the record. Read-only
reconnaissance may happen ahead of the sitting; checkmarks and approval happen in it, or
under the recorded limited stand-in authority.
