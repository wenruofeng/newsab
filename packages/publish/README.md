# Stage 8 production builder

**Specified reader:** the stage 8 `publish` operator and the agent configuring a
Cloudflare Pages deployment must read this file.

`newsab_publish` builds immutable topic candidates and derives the public static site from
the append-only lifecycle event stream. It never follows a topic's active editorial
pointer and never accepts an approval that names only a topic. Read
[`skills/publish/SKILL.md`](../../skills/publish/SKILL.md) and its threat model before
crossing the public/private boundary.

## The review shell

One command puts every human touchpoint in a browser and indexes what is waiting:

```sh
uv run python -m newsab_publish dev-serve [--preview <private_review_dir>]
```

(`uv run` uses this checkout's own `.venv`, created by `uv sync` — see AGENTS.md §4. Every
`python -m newsab_publish …` below assumes the same prefix.)

It prints a map and holds until Ctrl+C. The dashboard tries `http://127.0.0.1:8787/`
first; if that port is already busy (two review sessions — touchpoint one and touchpoint
two — now run side by side routinely) it auto-probes upward and prints whichever port it
actually bound, so a second session never crashes or needs a hand-typed offset. Pass
`--port <N>` to pin an exact port instead — that choice is never moved: it fails loudly if
occupied. Each servable tree gets its own loopback port, because production pages use
root-relative URLs and are only correct when served *as a root*. The dashboard indexes the live
production site, every undecided candidate, any registered review preview and touchpoint-one
sign-off state — nothing else; the style panel itself is still served at
`<style origin>/__panel__/`, whose URL dev-serve prints. One data-driven exception: if
`site/private/panels/*.html` exists — static operator panels a private script generated, such as the suggestion-review
projection — the dashboard lists and serves them at `/panels/<name>.html`, so a step that
ends in human review still ends in a clickable link. A panel's buttons may POST to the
generic `/api/panel-decision`, which appends `{item_id, decision, reason}` to
`site/private/panels/<name>.decisions.jsonl` — the dashboard records the choice and
executes nothing; the consequential work stays with the private script that generated the
panel, run with its own credentials. The dashboard knows no specific panel; a checkout
that generates none (a public clone, a fresh machine) has no such section.

What it may do: write a `PublicationReview` bound to the exact bytes it served
(touchpoint two), write a `HumanApproval` authorizing a lifecycle operation, write review
notes, sign touchpoint one through `skills/scope/scripts/scope_tool.py`, and export a
theme-token change proposal from the style panel. Everything lands under `site/private/`.

**Touchpoint two and the replacement authorization are one decision.** They used to be two
clicks, which asked a question the first click had already answered: a user who has read
the exact bytes and approved them holds no further information about whether those bytes may
replace the ones they just compared against on screen. What actually guards the bytes is
mechanical and unchanged — `verify-candidate` re-renders from the pinned artifacts and
refuses on any difference, and no click can wave that past. So one confirmation writes a
`PublicationReview` per locale plus one `HumanApproval` for the lifecycle move, and it
requires a reason, because the reason outlives the click in the event log.

Touchpoint two happens on preview bytes, and `prepare` is what mints a publication id. A
decision taken before `prepare` is therefore filed as `activate-intent-<topic>-<hash8>.json`,
keyed by the page hash the user signed; `prepare` promotes it to the ordinary
`activate-<publication_id>.json` only when the candidate it just built pins that exact hash
as reviewed. The dashboard writes the final name directly when the candidate already exists.

The intent authorizes **one** lifecycle move, not every future operation on the same bytes,
so promotion is single-use: it first writes `activate-intent-….consumed.json` beside the
intent, recording which publication spent it and when, and a consumed intent promotes
nothing — `prepare` says so, and the later `activate` needs an authorization recorded
against the new publication id. The signed intent file itself is never edited or deleted.
(Before this rule a locale-set re-`prepare` of already-approved bytes silently re-promoted
the previous release's signature.)

What it must never do, and does not: inject anything into a page under review, or run
`activate`, `supersede` or `lifecycle`. Those stay explicit commands; the dashboard only
shows them.

### Adopting a touchpoint-two category decision

The dashboard's release confirmation writes the reviewer's proposed categories to
`site/private/approvals/topic-categories-<topic_id>-<hash8>.json` (a
`TopicCategoryApproval`) alongside the `PublicationReview`s and the `HumanApproval` —
but `prepare` reads `SiteMetadata.topic_categories`, a different file, and refuses a
topic's first `prepare` with `site metadata has no approved taxonomy mapping for
<topic_id>` until that mapping exists there too, with a matching entry in
`topic_category_approvals` (`SiteMetadata._controlled_taxonomy` checks `category_ids`
equal in order). Getting the approval file into that shape used to be a hand transcription
with zero judgement content — the file already says everything — so it is a command:

    python -m newsab_publish adopt-taxonomy <site_root> <topic_id> \
      [--approval <topic-categories-....json>] [--site-metadata <metadata.json>]

`--approval` defaults to the sole matching file under `site/private/approvals/`; more than
one match requires it explicit. `--site-metadata` defaults to the checked-in
`site_metadata.v1.json`. Adopting the same approval file twice is a no-op (reported as
`already-adopted`, nothing rewritten); a *different* approval for a topic that already
carries one — a re-review under a different page hash, say — is refused rather than
silently replacing a recorded human decision, and so is a topic already named in the
one-time `taxonomy_backfill_approval` (the schema forbids it from also carrying a
per-topic record). Either refusal names both records so an operator can reconcile them by
hand.

## Content documents and site chrome

A production page carries no stylesheet, font link or behaviour script of its own. It
links `/assets/site.css` and `/assets/site.js` at stable, unhashed URLs, and states its
theme as `data-theme-token`. The chrome is generated once per release from
`newsab_publish/chrome.py` plus the theme registry, and `site/production/release.json`
records its version and per-asset hashes, which `verify-site` re-checks.

The consequence worth stating plainly: **a chrome change does not require re-approving a
single topic.** It requires the 4.5:1 contrast gate (enforced when the stylesheet is
assembled), `web-gate`, and a site-operator commit. Changing what a page *says* is still a
new review and a `supersede`.

Site-level controls follow the same line. A content document states *that* there is a way
home, a set of locale links and a theme control; chrome decides they are one row of
identical icon buttons above the title, and assembles that row at runtime
(`buildToolbar` in the M2 script). Every label the document wrote survives as the
control's accessible name, and with JavaScript off the row degrades to the plain links
the document itself carries. Restyling site furniture therefore never costs a page
re-approval — which is the whole reason the relocation lives in chrome rather than in the
renderer.

One page is deliberately outside this split: the **home page**. It is derived from the
catalogue by `newsab_publish/home.py`, no human ever approves its bytes, and it is
rebuilt whenever the catalogue or the build date changes — so it carries its own
stylesheet, font link and behaviour instead of linking the chrome. It still speaks the
chrome's design language, and changing it costs no topic re-approval, because no topic's
bytes are involved.

Because a candidate bundle deliberately contains no chrome, anything that serves candidate
bytes supplies it: `review-preview` writes the assets into its output directory, and
`web-gate` and `dev-serve` overlay them in memory without touching the immutable bundle.

### Crawler metadata and the browser icon are resolved by the release

An approved page states only root-relative URLs — that is what keeps an approval free of
the site's origin, so moving the domain stays a rebuild rather than a re-review. A social
crawler resolves nothing and renders no SVG, so `newsab_publish/crawler_meta.py` writes
two release-owned facts into the *deployed* copy of every page: an absolute `og:url`, and
an `og:image` pointing at `/assets/share-card.png` — the site's PNG card, a chrome asset
drawn from flat geometry in `social_card.py` and checked in beside it so every host ships
identical bytes. Nothing else in the page moves, and `verify-site` re-derives each
deployed page as `resolve(bundle bytes, base_url)` and compares, so *deployed = approved ⊕
release origin* is checked, not assumed.

The per-angle SVG cards a publication ships stay in its bundle and are not what a platform
sees. What travels instead is the share **landing** page's `og:title` / `og:description`,
which state that angle's question and both sides' counts — the text every platform renders
beside the image.

The reusable vector brand mark follows the same authority boundary. It ships once at
`/assets/favicon.svg`, is hashed in `site/production/release.json`, and the release resolver
adds that stable link to deployed topic and auxiliary pages. The home renderer links it
directly because home bytes are derived site chrome, not reviewed topic content. This keeps
already-approved topic documents byte-identical while giving every deployed HTML entry
point the same favicon; the asset can also be reused by future chrome surfaces such as the
About modal without duplicating its paths.

## M2 review, themes and browser gate

M2 topic bytes are a new reviewed candidate; the publisher never patches an existing M1
publication in place. Render an explicit pinned page run, inspect the locale pages and
angle share landings, then approve the exact reviewer-locale hash through the ordinary
touchpoint-two record:

```sh
python -m newsab_publish review-preview topics <topic_id> \
  --page-run <render-localize_run_id> -o <empty_private_review_dir> \
  --theme-token ember
python -m newsab_publish web-gate <empty_private_review_dir> \
  --screenshots <private_audit_screenshot_dir>
```

`review-preview` prints (and records in `review_manifest.json`) the
`candidate_fingerprint` of the bundle it just wrote — the same value
`directory_fingerprint` gives for a bundle rendered alone into an empty directory, with
the site chrome and the review manifest deliberately outside it. On the submission path
that value is not just reported: `--expect-candidate <imported>/verification.json` makes
the render refuse unless it reproduces the archive verifier's own G2 recomputation, and
`--hash-only` without `--expect-candidate` is refused outright, so bytes no independent
gate recomputed can never reach a human reviewer.

The controlled theme registry is
`newsab_publish/data/theme_tokens.v1.json`. A local chooser can be regenerated with
`python -m newsab_publish theme-panel -o site/theme_panel.html`; its output is only
`{"theme_token": "..."}`, never arbitrary colours or CSS. `web-gate` requires Python
Playwright plus an installed Chromium. It starts a loopback-only server and makes no
external request; on the topic-page profiles font requests are aborted so screenshots
exercise the offline fallback stack, while the home profiles deliberately keep web fonts
loading because the card-containment check measures the real typeface's line breaking.

### What a `web-gate` run actually opens a browser for

A run reports **every** failure it found, not the first: a whole-tree round costs minutes,
and fail-fast used to make each round surface exactly one defect (an `/ar/` RTL
assertion hid an unrelated `/ru/` card overflow). Checks are grouped into named steps; a
failed assertion ends its own step and the run carries on.

It also refuses to re-prove what is already proved. A page's browser behaviour is a
function of its own bytes, the chrome served beside it, and this gate's source — all three
are hashed, and `.newsab/web_gate_verified.json` (machine-local, gitignored, not
provenance) records which triples passed. Pages then fall in three groups, reported in the
command's own JSON:

| group | meaning | what happens |
|---|---|---|
| new | these bytes have never passed | **always checked in full** |
| cached | same bytes, same chrome, same gate source | skipped |
| stale | passed before, but the chrome or the gate source has since moved | sampled |

A chrome revision invalidates every page at once, so a byte cache buys nothing there and
re-running all of them buys little: what a global CSS change can break is typography. The
stale group is therefore sampled one page per (page shape × typography stratum) — RTL,
unspaced CJK, Hangul, Indic, long-word Cyrillic, Latin, and a stratum of its own for any
language nobody has classified — with the representative rotating on the chrome
fingerprint so successive revisions land on different pages. Anything not sampled keeps
its older verdict and the run says so in a `note` field.

**A candidate bundle at touchpoint two is entirely new bytes, so none of this relaxes the
publish path.** Before a release, run the whole tree:

```sh
python -m newsab_publish web-gate site/public --full
```

`--workers N` sets the browser shards run in parallel (default: half the cores, capped at
8), `--sample N` widens each stratum, and `--no-cache` ignores and does not write the
cache. On this repo's 110 pages: `--full` ~1m10s, a run after a chrome change ~13s, a run
with nothing changed ~2s.

New M2 candidates include root-relative canonical/real-locale alternate metadata, one
share landing page per angle and locale (the page and every landing name the site's PNG
card as `og:image`; the per-angle SVG cards were retired and survive only in
bundles minted up to `publish-0.7.0`), native-share/copy-link progressive enhancement, and
the mobile/keyboard/touch layer. A missing topic locale is a site-owned fallback shell around
one intact default-locale page, not a field-by-field mixed translation.

Since `publish-0.4.0` a candidate page externalizes its language-neutral data
islands into content-hash-named files at `topics/<topic_id>/data/<island>.<hash16>.json`,
shared by every locale and pinned in `PublicationRecord.data_assets`; a few-KB
per-language overlay stays inline and the chrome script hydrates the fetched data back
into the legacy structures. The islands are content, not chrome — they live inside the
candidate bundle and its fingerprint. Older publications keep their inline islands and
verify unchanged.

## Producer versions and verification tiers

`prepare` stamps the current producer version into each record. Verification is tiered:
only a publication that is **still live** for its topic (or a candidate not yet
activated) *and* minted by the **current** producer is re-rendered and must reproduce
its bytes exactly (including the pinned outlet-registry, theme and `topics_by_article`
archives under `site/audit/<publication_id>/`). A **superseded or withdrawn**
publication — whatever version stamped it — and any publication from an **older
supported producer** is verified against its immutable stored bundle, its pinned
archives and the event hash chain — never by re-rendering with today's code, so neither
renderer evolution nor a supersede can brick bytes a human already approved.
The same rule applies to the release record: an old-producer release verifies by
fingerprint and scan only. Replacing old bytes always means a newly reviewed record and
a `supersede` event, never an in-place rewrite.

One schema migration has an explicit compatibility ledger: `cluster_threshold` moved
out of the user-signed scope hash. The migration first
verified every stored topic's legacy hash against its signed manifest, then recorded the
exact old→new fingerprint pairs in `newsab_publish.builder`. Release assembly accepts
only those named scope pairs, with the same topic and scope run id; an unknown scope
mismatch, any other changed pin, or a different run id still fails closed. This preserves
immutable pre-migration publications without turning a hash-algorithm migration into a
general scope waiver.

The cross-topic outlet registry (`sources/registry.yaml`) is append-only and mutable, so
`prepare` archives the exact registry bytes it rendered with and pins their hash in
`render_input_hashes`; a later registry edit changes future candidates, not the
verifiability of published ones. Records prepared before this pin existed fall back to
the live registry.

## Local production preview

To browse the existing approved production tree, serve it directly — do not rebuild it.
`dev-serve` does this and more; a bare server is the fallback when only the public tree
matters:

```sh
python -m http.server 8000 --directory site/public
```

To preview a rebuild, point `--production` at a scratch directory. Only a rebuild whose
target is exactly `site/public` updates the authority records (`site/production/release.json`
and `site/catalog/`); any other target builds a throwaway tree and leaves them untouched.
Rebuilding `site/public` itself must reuse the `base_url` and `build_date` recorded in
`site/production/release.json`, otherwise the approved fingerprint changes.

```sh
uv run python -m newsab_publish rebuild topics site \
  --site-metadata packages/publish/newsab_publish/data/site_metadata.v1.json \
  --production /tmp/newsab-preview --base-url https://example.invalid \
  --build-date 2026-08-25
python -m http.server 8000 --directory /tmp/newsab-preview
```

Open `http://localhost:8000/`. `https://example.invalid` affects only absolute sitemap
entries; page and home navigation remain root-relative. Code embedding a home page in a
different directory can call `render_home(..., url_mode="relative", home_path="/path/")`
to produce relocatable links.

## Cloudflare Pages

The production rebuild and `verify-site` must run on the machine that holds the pinned
topic artifacts — including the gitignored private corpus stores under
`topics/*/corpus/`, which catalog derivation and closure verification restore from.  A
bare repository checkout cannot run them, and the private corpus must never be exported
into a hosting provider's build environment.  Cloudflare Pages therefore deploys the
already-built, already-verified `site/public` directory (direct upload / no build step);
it is only a static host and has no authority to prepare, activate or rebuild
publications.

On the build machine:

```sh
uv run python -m newsab_publish rebuild topics site \
  --site-metadata packages/publish/newsab_publish/data/site_metadata.v1.json \
  --production site/public --base-url "$NEWSAB_BASE_URL" \
  --build-date "$NEWSAB_BUILD_DATE"
uv run python -m newsab_publish verify-site topics site \
  --site-metadata packages/publish/newsab_publish/data/site_metadata.v1.json \
  --production site/public
```

Set `NEWSAB_BASE_URL` to the canonical HTTPS origin with no path, query or fragment. Set
`NEWSAB_BUILD_DATE` explicitly as `YYYY-MM-DD`; a rebuild of the same event stream,
metadata revision, origin and day must produce the exact fingerprint recorded at
`site/production/release.json`.

## Production cost reports

**Specified reader:** the stage 8 operator, and anyone comparing what topics cost.

    python -m newsab_publish cost-report <site_root> <publication_id>
    python -m newsab_publish cost-report <site_root> --topic-id <topic_id>
    python -m newsab_publish cost-report <site_root> --topic-id <topic_id> --run-id <run_id> [--run-id <run_id> ...]

Writes `site/audit/cost/<topic_id>.{csv,json}` and refreshes `site/audit/cost/index.csv`:
agent wall clock and token spend for the topic that publication belongs to. Run it after
`activate`, or over any topic at any later time — it reads harness transcripts, never the
publication, so it can be recomputed and backfilled freely. Pass exactly one of
`PUBLICATION_ID` (sums every run id the topic's artifacts mention) or `--topic-id` (works
before activation — before touchpoint two ever runs — and defaults to the topic's
currently active run per stage, `manifest/active.json`); `--run-id` (repeatable) scopes
either form to an explicit set of run ids instead, e.g. to look at one run in isolation.

**It is telemetry, not provenance.** Nothing reads it back: not `verify-candidate`, not
`verify-site`, not a bundle, catalog row or event. It is written outside the production
tree and outside the four archived render inputs in `site/audit/<publication_id>/`, and a
test pins that (`tests/test_cost.py`). A wrong or missing cost report can never invalidate
approved bytes — which is exactly why backfilling one disturbs no review.

Reports are keyed by **topic**, not publication, and name the publication they were
generated for. A republished topic is one production history, not two.

### What the numbers mean, and what they do not

- **Observed usage and projected price are separate.** Prices are data
  (`newsab_publish/data/model_rates.v1.json`), and each report pins the table's version and
  fingerprint so an old report stays readable after prices move. Claude and Codex are both
  reported as API-list-price equivalents, not subscription invoices. The OpenAI rows price
  each request before aggregation so the documented >272K-input multiplier is never applied
  to a sum of ordinary requests; GPT-5.6 cache writes use the published 1.25x input rate.
  An unpriced model keeps all observed token/time values, makes `total_usd` null and sets
  `pricing_status` to `partial` or `unavailable`; it is never counted as free or guessed.
- **The per-topic CSV is one row per session with no TOTAL row**, so summing it is always
  correct. Totals live in `index.csv`, one row per topic, with explicit Claude, Codex and
  combined time/token/USD columns. `total_tokens` means context plus output; reasoning
  output is already a subset of output and is not added again.
- **Wall clock is the union of session spans, not their sum** — a subagent pool runs inside
  its parent, and adding the two would bill those minutes twice. It also excludes the
  user's own reading time and any wait between touchpoints. Each harness has its own
  union; the combined wall clock is the union across both, so it can be smaller than the
  sum of the Claude and Codex columns when they overlapped.
- **Attribution is per session, and a session is not divisible.** Claude Code and Codex
  qualify a session from structured tool/function-call arguments that touched
  `topics/<topic_id>/` or named at least two topic run ids. User text, inherited context and
  tool output remain visible as transcript-only evidence but never become a file-open claim.
  Parent/subagent relations are restored explicitly; every output id is namespaced as
  `<harness>:<session_id>`. Operator include/exclude overrides remain in the JSON record.
- **The early topics are not comparable to the recent ones.** `aabb-river-light-2026` draws in 74
  sessions because it was the test bed while the pipeline itself was being written, and
  session granularity cannot separate "produced the topic" from "built the machine that
  produces topics". Read the first topics as *pipeline construction*, and only a topic
  produced by a finished pipeline as the cost of a topic.
- **Coverage is part of the result.** Each report and `index.csv` say which harnesses were
  configured, observed or missing, plus `usage_coverage`, `attribution_coverage` and
  `pricing_status`. “Complete” means complete only for that declared source set.
- Codex `cached_input_tokens` is a subset of input, and `reasoning_output_tokens` a subset
  of output. The adapter sums `last_token_usage`, deduplicates repeated cumulative snapshots
  and cross-checks the final cumulative value; it never adds cached/reasoning twice.
- A session still in progress reports itself partially; re-run after it ends.
- **`by_run`/`by_skill` group cost by run_id/skill, honestly.** Each queried run_id looks
  up its `skill_id`/`model_id`/stage from the topic's own manifest (never guessed from the
  run id's kind prefix), and gets tokens/wall-clock/usd only from sessions whose tool calls
  named *exactly that one* queried run — the only case where "this session's cost belongs
  to this run" is a fact, not a split. A session naming two or more queried runs in one
  conversation cannot be divided between them, so it is reported once in `cross_stage`
  instead of being double-counted into every run it touched — this is a real limit of
  session-granularity transcripts, not a bug. A run
  with no exclusively-attributed session comes back with `coverage:
  "no_exclusive_sessions"` and `null` numeric fields — never a fabricated zero. The
  non-`--dry-run` console output prints one summary line per skill.

By default the command discovers both this repo's Claude Code directory and repo-local
`~/.codex/sessions/**/rollout-*.jsonl`; use `--dry-run` to review coverage before writing.
Any other harness can add repeatable `--usage-jsonl <path>` sources to the same report.
Every neutral row must carry `topic_id`, `harness`, `session`, `message_id`, `model` and an
explicit work-span binding. Neutral totals use `input_tokens_total` (cached input included),
`cache_read_tokens`, optional cache-write buckets, `output_tokens_total`, and optional
`reasoning_output_tokens`. Use `--no-auto-discovery` only when an explicitly bounded source
set is intentional; the resulting coverage records that configured set.
