# Skills — packaging & execution contract

Every stage of the pipeline (`docs/value_chain.md` §The chain) is one skill directory
here. A skill is the unit a *stranger's* agent runs to produce a submission: it must be
readable and executable with nothing but this directory, explicit input paths, and the
repo checked out — no chat history, no TODO, no old reports, no single vendor's features.

The contract below is enforced by `python tools/skills_check.py [skills/<stage>]`
(add `--strict` on a migrated skill; warnings then fail too). External spec compliance is
checked with the `skills-ref` npm tool (`npx skills-ref validate skills/<stage>`).

## Layout of one skill

```
skills/collect/
  SKILL.md               short driver: outcome, preflight, mode router, core loop, done/stop
  references/            conditional depth, one file per mode or decision, one hop from entry
    search-strategy.md
  scripts/               deterministic helpers over packages/ — no model calls
```

## Frontmatter

Only the fields of the open Agent Skills spec; repo-specific facts go in `metadata` as
strings. `name` and `metadata: newsab-stage` both equal the directory name, which is the
value-chain stage name.

```yaml
---
name: collect
description: One line saying what this stage does AND when to run it. Harnesses route on this.
compatibility: Requires this repository, Python 3, and (only if true) network/browser access.
metadata:
  newsab-stage: "collect"
  newsab-version: "0.11.0"          # bump on behavioural change; the ONLY definition site
  newsab-inputs: "topic_manifest,source_registry"    # artifact kinds read
  newsab-outputs: "corpus"                           # artifact kinds written
  newsab-language: "source-local"   # source-local | en-pivot | reader-local
---
```

## What goes in `SKILL.md` — six kinds of information, nothing else

1. **Outcome** — one or two sentences: what input becomes what artifact, and what this
   stage does *not* do.
2. **Start here** — working directory is repo root; the input paths; one preflight
   command. Never require reading TODO, reports, or the whole canonical spec.
3. **Choose a mode** — only if genuinely different flows exist (new / extend / repair…),
   with "read `references/x.md` only when …" routing per mode.
4. **Core loop** — 3–7 steps, each marked as semantic judgement or an exact command.
5. **Done** — the single validator/finalize command, what its output must show, and the
   artifact paths written.
6. **Stop / return upstream** — only the conditions that change the stage boundary or
   need a human; ordinary recoverable errors belong in script diagnostics.

Free-form headings are fine; the six kinds are the completeness test. Advisory length:
60–120 lines, up to ~150 for a mode router — the checker warns, behaviour evals decide.

What stays *out* of the entry: product spec restatements, algorithm explanations, site
snapshots, renderer internals, legacy-run compatibility (a `references/legacy-*.md` read
only when legacy input is detected), history. **No CHANGELOG section** — history lives in
git and task reports; the behaviour version lives in `newsab-version` and in artifact
provenance, derived from the frontmatter by scripts, never copied by hand.

Write rules as rules, not as internal issue ids: a bare id carries no meaning for a
stranger's agent. State the rule in full; an id may follow as optional provenance.
Nothing time-bound ("currently", "the live topics", dated site behaviour): channel
measurements go in `sources/registry.yaml` with a date, incidents go in task reports.

## References — admission rules

A `references/*.md` file exists only if **all** hold:

- the entry names it with an explicit read-condition ("only when adding a new outlet");
- it changes a decision, and `--help`, the schema, a package, or the input artifact
  cannot answer it;
- it is one hop from `SKILL.md` and never requires following a link into `archive/`;
- it contains no fast-decaying site state (that goes to the registry, dated);
- every rule in it has exactly one definition site repo-wide.

Name files by mode or decision (`references/incremental.md`), not by artifact type.
Schema references only cover traps the schema cannot express; field lists and enums live
in `packages/schema` / `packages/schema/dist` — link, never restate.

## Scripts and commands

- Every documented command runs verbatim from repo root:
  `python skills/annotate/scripts/qa_batch.py …`.
- Every script's `--help` exits 0 standalone; failure modes and fixes are in the help or
  the error message, so normal runs never require reading script source.
- Prefer few task-shaped subcommands over long hand-assembled pipelines.
- Scripts compute everything computable (run ids, hashes, counters, versions from
  frontmatter); the agent supplies only what code cannot: model id, rationale, judgement.
- No script installs packages, phones home, or widens permissions. Network-touching code
  carries one honest identity, respects registry rate limits, and never bypasses a paywall
  or a technical protection measure (record as unavailable). It reads `robots.txt` to set
  **retention**, not access — the rule and its two rows live in
  `skills/collect/references/fetch-extract.md` §1.4.

## Rules of the game

1. **Harness-neutral.** Plain Markdown + POSIX-runnable scripts. Claude Code discovers
   skills via the `.claude/skills` symlink; other agents are pointed at `SKILL.md`.
2. **One stage = one artifact boundary, not one required subagent.** The executing agent
   may work directly, delegate, shard, or skip the LLM. A delegated worker gets
   `SKILL.md` + explicit input paths + output path + self-check + stop condition —
   nothing else. Stages hand off only through artifacts on disk. Model choice follows
   [`docs/subagent_model_routing.md`](../docs/subagent_model_routing.md) at runtime;
   skills never name vendors or models.
3. **Deterministic work belongs in `scripts/`.** Anything checkable by code — ids,
   verbatim match, schema validity, counts, thresholds — is a script call, not an
   instruction the model is trusted to follow.
4. **Evidence is bound at generation time.** No stage emits a statement whose evidence is
   filled in afterwards.
5. **Self-describing outputs.** Every artifact carries
   `provenance{skill_version, model_id, run_id, timestamp}`; every run appends a manifest
   entry. Artifacts are immutable; re-runs mint a new `run_id`.
6. **Local language discipline.** A `source-local` skill writes free text in the source's
   language; field names and enums stay English.

## Registry

The eight stages of [`docs/value_chain.md`](../docs/value_chain.md), and what runs each:

| # | Stage | Runs as | Notes |
|---|---|---|---|
| 1 | scope | `scope` | touchpoint #1 — one sitting; user present or explicitly recorded AI stand-in with limited question authority |
| 2 | collect | `collect` | new corpus or append-only extension |
| 3 | annotate | `annotate` | Q×A: question set + per-cluster answers, source language |
| 3.5 | normalize | `normalize` | category merge map, frozen versioned artifact; analyze applies it |
| 4 | analyze | `analyze` → `python -m newsab_a1 qa` | code only, no model; one-page wrapper |
| 5 | write | `write` | the data journalist; `packages/editorial` carries the claim machinery |
| 6 | render + localize | `render-localize` | mechanical checks + spot check + localization + preview |
| 7 | review | — human | user reads the localized preview; no skill, by design |
| 8 | publish | `publish` | deterministic wrapper over the exact approved page bytes; immutable publication + append-only event + derived selector/catalog |

The private operating repository may retain retired skills one level deeper so no harness
discovers them and old run identifiers stay interpretable. They are historical state, not
part of the standalone toolkit export; every surviving rule is routed from an active skill.

**Starting a new skill:**
`cp -r skills/_template skills/<stage> && mv skills/<stage>/SKILL.md.template skills/<stage>/SKILL.md`
(the template is suffixed so harnesses do not load it as a real skill), then make
`python tools/skills_check.py skills/<stage> --strict` pass.
