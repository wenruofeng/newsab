---
name: collect
description: Find, fetch and stage one topic's news coverage verbatim from publisher pages, then build it into a sentence-segmented corpus with independent reporting clusters — run after the topic manifest is approved, before annotate. Use it equally for a new corpus, an append-only extension, or a withdrawal.
compatibility: Requires this repository, Python 3, and permitted web/browser access for discovery and fetching.
metadata:
  newsab-stage: "collect"
  newsab-version: "0.20.0"
  newsab-inputs: "topic_manifest,source_registry"
  newsab-outputs: "collection_log,staging,topics_raised,corpus"
  newsab-language: "source-local"
---

# collect

Turns an approved topic scope plus the cross-topic outlet registry into a corpus whose
**independent reporting clusters** are the denominator of every downstream statistic. The
deterministic half (segmentation, sentence IDs, clustering, origin cross-check) is
`packages/corpus`; this skill is the judgement half — what to search, what counts as
in-scope, what the body of an article actually is, and what to record when something
cannot be had. It does not design questions (annotate) or compute statistics (analyze). Ignore the manifest's `question_seeds` when building the query matrix: reader-question acquisition and news discovery are separate samples with separate purposes.

## Start here

Working directory: repo root.

    export PYTHONPATH=packages/schema:packages/corpus:packages/a1:packages/editorial
    python skills/collect/scripts/preflight.py <topics_root> <topic_id>

Preflight refuses to start without user approval matching the current scope hash, and
prints the groups, period, targets and current corpus state. Then query your slice of the
registry — it answers "how do I even search this outlet"; never read the whole file:

    python -m newsab_corpus registry find --country CN --lang zh-CN
    python -m newsab_corpus registry find --host <host>          # is this outlet known?

## Choose a mode

- **new** — first corpus for the topic: the core loop below.
- **extend / repair** — the corpus exists (usually annotated): same loop, but read `references/incremental.md`
  first — append-only mechanics, the store-line reading, debt roll-forward, what needs re-annotating.
- **withdraw** — removing an article: `references/incremental.md` §3. Never `rm`.

Per-material routing inside any mode: `references/search-strategy.md` before the first
query of a group and whenever a group looks thin; `references/fetch-extract.md` when URLs
are in hand; `references/source-registration.md` when the registry does not know an outlet;
`references/discovery-zh.md` before the first query against a Chinese-language group.

## Core loop

1. *(judgement)* **Plan the query matrix** — `term_variant × group`, both sides' own
   namings, vocabulary of the round inside the period (`references/search-strategy.md`).
   No cell may stay unsearched; searching the other side's media with only your own
   side's vocabulary is the largest single source of sampling bias.
2. *(judgement + commands)* **Discover in a browser, and log every query as it runs**:

       python skills/collect/scripts/log_query.py <topics_root> <topic_id> query \
           --group <g> --query "…" --term-variant <cell> --engine-or-site <where> \
           --results-seen N --results-staged M

   Never reconstruct the log afterwards; it alone answers "what would you have found if you had searched
   differently?", and `--results-staged` — required on every query line, `0` included — is reconciled
   against the corpus (`references/search-strategy.md` §6): an article no query claims fails the round.
3. *(commands)* **Fetch with the fetcher, then extract the body verbatim**, scoped to the
   body container: `python -m newsab_corpus fetch <url> … --out <topic>/corpus/raw`. It
   sends the one honest identity in both layers, retries every refusal — a non-2xx *or* an
   implausibly thin 200 — in the browser, reports the deciding layer, and reads our robots
   group to set **retention, never access** (`references/fetch-extract.md` §1.4). Never
   hand-roll a fetch around it — that re-decides all three, each already broken once.
   **Read `references/fetch-extract.md` §1 first** anyway — it is the judgement the command
   cannot make. Log every miss: `fetch_failure` (only at `layer: browser`), `excluded`
   otherwise — an unlogged miss is a fake gap.
4. *(judgement)* **Judge each candidate article**: in scope (the deletion test against
   the manifest's `include`/`exclude` — `references/search-strategy.md` §3); `group_id`
   against the groups' natural-language definitions (never inferred from country or
   language); `origin` from the page's own attribution (`references/discovery-zh.md` §3
   for Chinese copy). A candidate failing the deletion test or the period is logged
   `kind: excluded` with the reason, never staged. An outlet the registry has never seen
   gets its complete registration block now (`references/source-registration.md`) — the
   build refuses a half-filled one. While the full text is still in context, write the
   article's `topics_raised` record — read
   [references/topics-raised.md](references/topics-raised.md) before the first one, and
   note `pivot_en` is a shared topic vocabulary, not a per-article summary. Interleave
   with step 5 per article — stage-everything-first loses the context the phrases need.
5. *(commands)* **Stage, build, check.** One YAML per article in `corpus/staging/`
   (annotated example: [references/staging.example.yaml](references/staging.example.yaml);
   filenames append-only), then:

       python -m newsab_corpus build <topics_root> <topic_id>

   (`--registry` when your topics_root is not the repo's own `topics/`.) The build
   cross-checks your origin calls (two `original`s in one cluster fail it), registers
   complete new outlets, strips known chrome, reports each group's observed per-language
   instance/cluster composition, and checks staged body sentences against matching raw
   snapshots. The language and raw-verbatim diagnostics are report-only: they infer no
   language quota and do not gate the build.

   If this topic brings a language the repo has not built before, prove the splitter on it
   before staging the rest: run `python -m newsab_corpus segment` on two or three articles —
   sentences coming back one-per-paragraph mean the fallback rule, not segmentation.
   `newsab-corpus segment --help` lists the languages with real rules; anything else needs
   one written before its first build.

## Artifacts, and the traps the schemas cannot state

Definitions live in `packages/schema` / `packages/corpus`, generated to `packages/schema/dist/` — never restate a field list. What bites in practice:

- `collection_log.jsonl` rejects invented fields, unknown kinds and a `fetch_failure`
  without `layer: browser`; corrections are new lines carrying `corrects`, never edits.
  `log_query.py` validates through the real model — use it, do not hand-write JSONL.
- Article and sentence IDs are content-addressed from the canonical URL — re-collection
  deduplicates for free, and nothing ever hand-writes or renumbers an ID.
- A corpus **run** records the set one analysis saw; `reporting_cluster_id` belongs to
  the run, not the article (one wire reprint can merge two clusters).
- Full text lives only in the article store and never ships publicly.

## Done

All of these, from repo root, exit 0 — and their printed warnings are read, not skimmed:

    python skills/collect/scripts/check_collection_log.py <topics_root> <topic_id>
    python skills/collect/scripts/check_topics_raised.py <topics_root> <topic_id> \
        <topics_root>/<topic_id>/corpus/topics_raised.jsonl
    python -m newsab_corpus registry check

plus the build itself. **Backfill debt is a refusal budget**: while any `backfill_debt`
entry has retry budget left, collect is not Done — retry **only the debt cells** (`site:`
routing, `references/search-strategy.md` §1b; at most 2 rounds, ordinary query lines),
then rebuild with the debt flags (`references/incremental.md` §1). Annotate's preflight
refuses the corpus until every budget is spent; the residue rides the run report to
touchpoint two. Read the build's **beat-composition warning** (the two sides are made of
different kinds of newsroom — answered by collecting the missing kind, never by
relabelling) and its **store line** (`references/incremental.md` §2 — the only warning
anyone gets about anchors whose text moved); every `thin:` / `thin-language:` / `silence:`
line must be
explainable from the log. Extending a corpus that predates `topics_raised`:
`references/topics-raised.md`, last section.

## Stop and return upstream when

- A group cannot reach `target_clusters_per_group` and the log cannot show whether the
  shortfall is about the media or about your searching. **Never resolve this by guessing**
  — "we could not reach it" and "they did not publish it" produce opposite findings, and
  telling them apart is this stage's whole value. Escalate: a `kind: note` line naming
  causes ruled out and what would settle it, unsearched cells as backfill debt, the open
  question in the run report — the corpus is not handed on as if complete.
- The period looks misaligned with when coverage actually happened — period is topic
  scope: the user's call, never a quiet widening.
- A source was added but its full-grid backfill cannot happen this run — add it, record `backfill_debt`, say so in the report.
