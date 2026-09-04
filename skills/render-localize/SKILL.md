---
name: render-localize
description: Take the English-pivot reader page through every mechanical refusal, an independent spot check and full localization, then render the reviewer's own-language preview and stop at the user's review — run after write (value chain stage 6), before publish.
compatibility: Requires this repository and Python 3. No network.
metadata:
  newsab-stage: "render-localize"
  newsab-version: "0.23.1"
  newsab-inputs: "page,qa_analysis,corpus,topic_manifest"
  newsab-outputs: "page,preview"
  newsab-language: "reader-local"
  newsab-counters: |
    angles: number of angle cards covered by this run's page
    languages: number of languages present in this run's page.json
    judge_panel_size: number of L1 judge-panel members in the final round
    judge_rounds: number of L1 judge-panel rounds run (1 if no fix pass, 2+ if fixed)
    judge_min_score: the final L1 panel's merged minimum score (worst score any member gave)
    locales_added: number of site languages backfilled beyond pivot + reviewer locale, in a backfill-locales expansion run
    localization_judges: number of L2 localization-judge runs dispatched (one per locale judged)
    localization_judge_reruns: number of L2 judge reruns triggered by unparseable/invalid judge output (exit 2), not a scoring rejection
    localization_judge_min_score: lowest score any L2 localization judge gave across all locales judged in this run
---

# render-localize

Everything between a written page and a human reading it, four segments in order, each
loading its material only after the one before succeeded: **mechanical check** (deterministic)
→ **independent judge panel** (N × `standard`-class, in parallel) → **localize** (`standard`)
→ **render preview** (deterministic). The stage stops at the user's review — it never
publishes, never rules on its own output, and never hand-writes a renderer-computed field
(whose field is it: `references/renderer-owned.md`).

## Start here

Working directory: repo root. Inputs: the active `editorial` run's `page.json`
(`manifest/active.json` → `editorial`), the analyze run it pins (`how_we_counted.qa_run_id`),
the active corpus run **with its article store present** (quote text resolves from stored
bytes at render time, never from a copy in the page), and the topic manifest.

    export PYTHONPATH=packages/schema:packages/corpus:packages/a1:packages/editorial
    python -m newsab_schema validate-topic <topics_root> <topic_id>   # must be clean
    run_id=$(python -m newsab_schema mint-run-id rl)   # rl-<yyyymmddHHMMssffffff>-<8hex>
    python -m newsab_schema prepare-run <topics_root> <topic_id> editorial <run_id>

Prepare that directory **now**; every artifact this stage produces goes in it — both
previews, their shared `data/` islands, the bilingual page, every judge member file and
merged panel record. The write run you read is finalized and hashed — a file dropped beside
its `page.json` fails `manifest-check`; a run directory is append-only until finalized,
immutable after. Restamp `provenance` for this run the moment `page.json` lands in it — `page-check` enforces the match.

## Segment 1 — mechanical checks, before reading the page

Reading the page first is how a reviewer talks themselves into a finding being acceptable.

    python -m newsab_editorial page-check <topics_root> <topic_id> \
        --page <page.json> --qa-run topics/<topic_id>/analysis/<qa-run-id> --langs en
    python -m newsab_editorial page-render <topics_root> <topic_id> \
        --page <page.json> --qa-run <qa-run-dir> --lang en \
        -o <run dir>/preview.en.html --data-assets data

This path has no end-to-end test coverage. `--data-assets data` externalizes the language-neutral data islands as content-hash-named
files in `<run dir>/data/`, reused by the candidate render. Both language renders must yield
the **same** names — a "replaced stale data asset" line on the *second* language's render
means localization leaked into shared data: a defect, not housekeeping. Exit 1 sends the
page back to write with the error list — a wrong rule is changed in its own task with a
reason, never waved past for one page; warnings are not waivers, answer each in the run report.

## Segment 2 — the independent spot check, as a parallel panel

Build the judge's input once (the rendered HTML is not it — it embeds the whole corpus),
then send that one packet to **three judges in parallel, dispatched together** — not one
judge five times. Composition, member input isolation, model routing, merge semantics,
exit codes, the fix pass, the churn taxonomy and the round budget are
`references/panel.md`'s contract: read it before spawning anyone.

    python skills/render-localize/scripts/judge_packet.py <topics_root> <topic_id> \
        --page <page.json> --qa-run topics/<topic_id>/analysis/<qa-run-id> \
        -o <scratch>/judge_packet.md
    python skills/render-localize/scripts/check_judge.py \
        --judge <run dir>/judge.1.1.json --judge <run dir>/judge.1.2.json \
        --judge <run dir>/judge.1.3.json --judge-model <id> --writer-model <id> \
        --page <page.json> --out <run dir>/judge.panel.1.json

This path has no end-to-end test coverage as a whole (`check_judge.py` alone is subprocess-tested; `judge_packet.py` is not). On exit 1, run write's `fix-page` on the union and nothing else, then dispatch the
confirmation panel on a **fresh packet** — the same `check_judge.py` call with the round-2
member files, the fixed page, a new `--out` and `--previous <run dir>/judge.panel.1.json`,
which turns on the churn check. Exit 0 proceeds to localization; exit 3 is a human's.

## Segment 3 — localize into the reviewer's language (`<reviewer_locale>` below)

`<reviewer_locale>` is the manifest's **`review_locale`**, read there and nowhere else — never the language you happen to be speaking, and a manifest that names none stops the stage. The invariants — lexicon maps, quantity and provenance, anchors, quotes, side names, Q–A–explain as reader logic — are in `references/localize.md`, none optional. Read the rendered frame in its order (question → labels/counts → relation → explanations). Translate labels first, then explanations; pair-read the complete `<reviewer_locale>` frame.

Extract the work list, translate it, merge it back — one command each way, whole page, same for any further site language. Never hand-assemble the field list or hand-write a merge; what each command guarantees is in that same reference:

    python skills/render-localize/scripts/localization_units.py --page <page.json> \
        --lang <target> --topics-root <topics_root> --topic-id <topic_id> \
        -o <scratch>/units.<target>.json
    python skills/render-localize/scripts/apply_localization.py --page <page.json> \
        --translations <scratch>/<target>.json --lang <target> \
        --topics-root <topics_root> --topic-id <topic_id> \
        --run-id <this run_id> --model-id <localizer model> -o <run dir>/page.json

The translator returns `{unit key: text}`; the key is the page's own JSON path, and the merge refuses to overwrite a language the page already carries. Quote the printed per-kind gap table in the run report. `page-check --langs en,<reviewer_locale>` stays the refusal that decides whether the page is complete.

**The localization judge (L2) — mandatory for every language no human reads**, one judge
per locale before finalize (protocol, and why not a panel: `references/localize.md`); its
entire input is `references/localization-judge.md` plus its packet. Exit 1 blocks that
locale — fix, rebuild the packet, re-judge; exit 2 means re-run it, never hand-fix its JSON.

When localizing several locales in parallel, **pipeline localization with judging instead of gating them into two serial waves**: dispatch a locale's judge the moment that locale's page bytes land, not after every localizer has returned. Measured: waiting for all 7 localizers before dispatching the first judge spent about 25 of 39 minutes idle; running the judge as each locale finished would have saved roughly 8–10 minutes.

    python skills/render-localize/scripts/localization_packet.py \
        --page <page.json> --locale <target> -o <scratch>/localization_packet.<target>.md
    python skills/render-localize/scripts/check_localization_judge.py \
        --judge <run dir>/locjudge.<target>.json --judge-model <id> --localizer-model <id>

This path has no end-to-end test coverage.

## Segment 4 — render the reviewer's preview and stop

The reviewer reads their own language *before* review, never an English page with a
translation promised later; further site languages are localized here too and never reach
them — one own-language approval covers every localization of the same bytes
(`skills/publish/references/localization.md`):

    python -m newsab_editorial page-render <topics_root> <topic_id> \
        --page <page.json> --qa-run <qa-run-dir> --lang <reviewer_locale> \
        -o <run dir>/preview.<reviewer_locale>.html --data-assets data

The `--concept-cloud` switch and the public sentence budget are renderer-owned mechanics
(`references/renderer-owned.md`): use one concept-cloud value for both languages and name
it in the run report; quote the render's printed budget line in the run report and name the
heaviest article and why — a *full* article at or near 100% is a defect, not a footnote.
`page-render` writes the preview plus its `data/` islands and nothing else; both must be in
place **before** finalize — the output set hash covers the whole tree. Finalize with
`judge_min_score` = the final panel's **merged** minimum (the worst score any member gave)
and every member's `judge.<round>.<member>.json` as an `--output` beside the merged records:

    python -m newsab_schema finalize-run <topics_root> <topic_id> --run-id <run_id> \
        --activate editorial --skill-id render-localize \
        --model-id <model> --status completed --input-run <write run> --input-run <qa run> \
        --input-run <corpus run> --output <run dir>/page.json \
        --output <run dir>/preview.<reviewer_locale>.html --output <run dir>/judge.panel.<last>.json \
        --counters-json '{"angles": N, "languages": 2, "judge_panel_size": N, "judge_rounds": N, "judge_min_score": N}'

`--skill-version` defaults to frontmatter `newsab-version`; its `newsab-counters` also covers a `backfill-locales` expansion run (`locales_added`, `localization_judge*`).

Then **stop**. These previews are intermediate artifacts, not the review surface: touchpoint two is taken on the publish stage's candidate. Render one from this run (`review-preview … --page-run <this run> --categories <site categories> -o <dir>`) into a fresh `site/private/review-<task>-<topic>-<date>/`, never a temp dir (`/tmp` can vanish under an open review). Serve it (`dev-serve --preview <that dir>`), and hand the user
that `http://127.0.0.1:8787/` link, this run's id and the judge's overall-impression paragraph. Never a file path. Never wrap `dev-serve` in a `timeout` — it exists to keep running past the end of your turn; measured: one run wrapped it in `timeout 900` and the review server was killed before the reviewer ever opened it.

**Propose the site categories here, do not ask for them later.** `--categories` puts your proposal on the review card, so the one touchpoint-two confirmation settles the taxonomy with the bytes and the user objects in the review if it is wrong; published without them, `publish` demands a separate approval for something the user was never shown — a second decision, not a safeguard. The vocabulary is **closed**: pick 1–2 `category_id`s from `packages/publish/newsab_publish/data/site_metadata.v1.json` → `categories` (the same ids the home page filters by). Never invent a category or a free tag — `review-preview` refuses ids outside the file, and adding one to the file is the site operator's own metadata edit, not a pipeline step. This run's page carries only the pivot and the reviewer's own language; the user can authorize more of the site's languages at touchpoint two with no second review, and a later expansion run comes back through this same segment for each added locale (`skills/publish/references/localization.md`).

## Done

`page-check --langs en,<reviewer_locale>` and post-activation `validate-topic` exit 0; the last
`check_judge.py` panel exits 0, or its escalation is ruled on by a human; every localized
language beyond the pivot and the reviewer's own has `check_localization_judge.py` exit 0.
The run holds the multilingual `page.json`, both previews, their `data/` islands, every
member and merged panel record, and each extra locale's `locjudge.<locale>.json` — all
covering the **final** text.

## Stop and hand to a human when

- `check_judge.py` exits 3, or the escalation is a rule conflict or an upstream fix; a
  human sees it before touchpoint two, which is for reading a finished page.
- A translation changes a claim (back to write), or a stored quote contradicts its use
  (back to annotate/write).
- Anyone stands in for the user without explicit, recorded delegation — touchpoint two
  included, which the manifest's `review_stand_in_model_id` must already name, because the
  page record states who reviews it and nothing may be injected afterwards.
