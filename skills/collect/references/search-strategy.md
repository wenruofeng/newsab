# Search strategy — planning queries and reading their results

Read this before the first query of a new group, and again whenever a group looks thin.
Retrieval bias is the largest error source of this stage, and it enters through the
queries, not the fetching.

## 1. The query matrix — no empty cells

Discovery runs on a grid: **term_variant × group**, where the variants cover *both* sides'
namings of the issue — policy name, each side's framings, affected parties, official
responses. The scope's collection plan drafts them; extend the grid when the corpus
teaches you new namings. Searching the other side's media with only your own side's
vocabulary is systematic under-sampling.

- Every executed query is logged **as it runs** — one `kind: query` line carrying its
  `term_variant` (use `python skills/collect/scripts/log_query.py`, which validates the
  line for you). Never reconstructed afterwards from memory: the log is the only artifact
  that answers "what would you have found if you had searched differently?".
- **A cell left unsearched in any group means the collection is not done.** Over-searching
  is cheap — irrelevant hits become `excluded` lines. An empty cell is invisible
  under-sampling that surfaces downstream as a fake attention-gap angle, the worst failure
  this stage can produce.
- `python skills/collect/scripts/check_collection_log.py topics/<topic_id>` prints the
  variant-coverage table. Cells that genuinely could not be searched this run are recorded
  on the corpus run, never left implicit:
  `python -m newsab_corpus build … --backfill-debt "<source_id>:<cell>:<reason>"`
  (repeatable).

## 1a. The grid has a third axis the log does not print: the outlet

`term_variant × group` is where retrieval bias is planned, but it is not where it has
actually been leaking. Four topics were re-searched under this document after being
collected without it; **none** had an empty cell, and every gap that turned up was an
outlet the grid never reached:

- **A registered outlet nobody has queried is an unsearched cell in disguise.** One topic
  found two articles the moment someone ran its existing, period-correct vocabulary against
  nine registry outlets that had never appeared in a single query line. Check coverage by
  outlet as well as by variant; `registry find --missing-channel` names the ones nobody yet
  knows how to search, and an outlet with no recorded channel is the one that will be
  skipped again.
- **The corpus names its own missing sources — read them back.** A staged republication
  crediting an origin you never recovered, and a `kind: note` line saying so, are a search
  plan. One topic's log had listed five such origins for months; searching them directly
  recovered none of the five but surfaced two outlets nobody had thought of.
- **An unclosed `backfill_debt` is the expensive one.** A debt reads as "handled" in every
  later run unless something forces it closed: one topic's five unreachable Indonesian
  outlets survived every subsequent pass, and closing the debt a run later cost roughly
  twenty-five articles — enough to move one side's denominator. The pipeline now enforces
  closure: the build rolls every unclosed debt forward (`--close-debt` / `--retry-debt` /
  `--futile-debt` are the only exits), and annotate's preflight refuses a corpus while any
  debt still has retry budget (2 targeted rounds, §1b routing). Still put a recorded debt
  in the run report as work owed, not just on the run record.

Costing this out: the same re-search found 2, 2, 0 and ~25 new articles across four topics.
The variance is not about how hard anyone searched — it is about which outlets each run
happened to point at.

## 1b. Where to run a cell — the external index first, site search second

For any given `term_variant × outlet` cell there are usually two ways to turn keywords
into URLs, and they are not equivalent. **Prefer the external index:**

    site:n-tv.de <term_variant>          # general engine, scoped to one outlet
    site:n-tv.de <term_variant> after:YYYY-MM-DD before:YYYY-MM-DD

- It is better retrieval. A general engine has crawled the outlet's whole archive under
  its own arrangement with the publisher; the outlet's own search box is frequently
  date-blind, drops older rounds, ranks by recency, or covers only one desk.
- It reaches outlets with no findable site search at all — the `discovery_blocked` case in
  `references/source-registration.md`, which is a channel gap and never a finding about
  the media.
- It sidesteps the whole question the site search raises: most publishers `Disallow` their
  `/suche/` or `/search/` path, which changes nothing about whether you may open it
  (`references/fetch-extract.md` §1.4) but is a decision nobody needs to make twice a day.

Site search is the fallback, and a real one — an outlet's own search often finds the
local naming a general engine ranks away (§5 case 2 is where the thin side usually
hides). Open it in the browser at human pace, never walking its result pages in bulk
(`references/fetch-extract.md` §1.4 item 4). Whichever channel you used goes in the query
line's `--engine-or-site`.

**"The external index" means an engine that actually honours `site:` — check the result
hosts, because the failure is silent.** The universal test: whenever a `site:` cell
returns results that do not belong to the host you scoped it to, the operator was dropped
and the cell has not been searched — it silently became an unscoped query wearing a
scoped label, and downstream that reads as a fake attention gap. Measured routing
(2026-08-29, re-confirmed same day):

- **A harness's built-in web-search tool drops `site:` silently.** Claude Code's
  `WebSearch` given `site:theguardian.com <terms>` returned eight results, none on the
  host, with no error. Use such a tool for **unscoped broad queries only** — the wide
  sweep before the grid, never a `term_variant × outlet` cell.
- Where the harness tool takes an explicit domain filter, it at least fails loudly: the
  same tool's domain parameter refused theguardian.com outright because the publisher
  blocks the vendor's crawler (and worked on dawn.com). The refusal is a channel gap,
  never a finding — and since much of the major press blocks AI crawlers, the filter
  cannot be the default route even where it works.
- **The route that honoured the scope in both scripts: DuckDuckGo's html endpoint** —
  `https://html.duckduckgo.com/html/?q=site%3A<host>+<terms>`. Measured 10/10 on-host on
  theguardian.com and 10/10 on thepaper.cn (dates shown, no verification wall), and
  re-measured 10/10 per cell through the fetcher route below (2026-09-01). Run `site:`
  cells here by default, on either side's domains, and log it as the `--engine-or-site`.
  **Default tool: `skills/collect/scripts/ddg_search.py --site <host> '<terms>'`** — it
  walks the endpoint through `newsab_corpus`'s honest fetcher (identity, robots,
  pacing, browser retry all kept) and prints the resolved results with the on/off-host
  split, so the silent-drop test above is a number you read, not a spot check. It also
  needs no shared Playwright session, so parallel collect workers can each search their
  own cells — the browser route serialized them behind one session. Open the endpoint in
  the browser only when the script's page comes back walled. It is still an engine — a
  budget, not a faucet (`references/discovery-zh.md` §1). Two shapes to know: the result
  tail can pad with on-host but off-topic rows — that is the end of the results, not more
  hits (the filler pattern of `references/discovery-zh.md` §7); and for some outlets the
  `site:` index is **heavily stale**, returning pre-window archives while the outlet
  publishes daily inside the window (measured on huanqiu.com and bworldonline.com,
  2026-09-01 — one recovered by adding dated phrasing to the query, the other by an
  engine with a domain filter). A thin or old-only grid is a channel symptom to route
  around, never this outlet's silence.

**Chinese-language *engines* still reverse the general-engine preference**
(`references/discovery-zh.md` §1): their `site:` lands on the verification wall, or is
silently ignored and returns unrelated results that read like an answer — the worse
failure of the two. The DuckDuckGo html route above is not a Chinese engine and honoured
`site:` on a zh domain, so try it first for Chinese outlets too; when its index runs thin
for an outlet, fall back to the outlet's own search, or query distinctive title wording
and filter by host.

## 2. Vocabulary is time-indexed

The same issue gets renamed between policy rounds, so a query written in an old round's
vocabulary silently returns the old round's months — which reads exactly like "this side's
press went quiet". Worked example (`aabb-river-light-2026`, period opens 2026-05-01): the query
phrased in the previous year's episode vocabulary returned only May-2025 coverage; the
in-period round's own phrasing returned several publishers at once. Same engine, same day.
Before concluding a group is quiet, re-run its cells in **the vocabulary of the round
inside your period**, and log both attempts.

## 3. Is this article in scope? — the inclusion decision

Relevance is a **binary inclusion decision**: related → collect it; collected → it counts
in every denominator. There is no second label that quietly removes an article after
collection.

The test, applied before taking an article: delete every sentence about this topic —
would the article still be a coherent piece? If yes (a market wrap listing our event among
six factors, a profile with one paragraph on the policy), do **not** collect it. If it
would collapse, collect it. Borderline but substantial → take it and say so in `note`; an
included borderline costs a little precision, an excluded one silently removes a voice
from every denominator.

**Judge against the manifest's `include` / `exclude` clauses in their own words, never
against the topic title.** A topic title is written from somewhere; the deletion test
applied to it silently adopts one side's framing as the definition of the topic — and how
differently the two sides frame the story *is the product*. Measured case: a relevance
pass judged against "Sharifu's China story" would have excluded all six Africa-side
articles (they tell the story as village ancestry history, not as a personal profile) and
published a zero denominator; re-judged against the manifest's actual `include` list, five
of six came back in. Also:

- "this article is also about something broader" is not exclusion grounds when the broader
  thing is what that side's coverage of this topic looks like;
- subjects appear under variant names and spellings — a name search is not the test;
- a decision that would empty one side of the corpus is a scope question for the manifest,
  never a relevance judgement made quietly at the staging table.

## 4. Adding a source mid-run

The source frame is **open**: meeting an outlet that plainly belongs is the normal result
of searching. Add it (registration itself: `references/source-registration.md`) — but a
source added carelessly biases the sample worse than not collecting it:

- **Backfill the full grid.** Re-search the new source with *every* term-variant cell, not
  just the query that surfaced it. Otherwise the source enters only in its
  "covered-this-topic" posture and both the cluster denominator and any silence claim are
  polluted.
- **Leave a trace.** One `kind: source_added` line naming the `source_id`, the query that
  found it, and why it fits the frame. If the backfill cannot happen this run, add the
  source anyway and record the unsearched cells as `backfill_debt`.
- If a build has already run, adding a source means **rebuilding**: the cluster
  denominator changed, so every previously computed prevalence is void.

## 5. Reading an empty result set honestly

An empty result set has **three** same-shaped causes, falsified in this order:

1. **Your own call is wrong** — pagination base, date format, parameter name, wrong-round
   vocabulary (§2). A search-API off-by-one once impersonated a site-wide ban; a silently
   misnamed parameter once returned a believable default feed that had searched nothing.
2. **The channel is missing or limited** — an outlet whose article pages fetch fine may
   have no findable site search, and general engines index trade press badly. When one
   side's sample is thin, the first hypothesis to kill is always "we have not found this
   group's home channel yet": one topic's thin side went from 14 to 23 clusters when the
   right trade-press search was found.
3. **The outlet really published nothing in period** — the only one of the three that is a
   finding, and it may be read only after 1–2 are ruled out for every cell of the matrix.

**No collection failure is ever written up as a conclusion about the media.** Write
measured channel details back to the registry (`registry set-channel`); when you cannot
rule causes 1–2 out, say so in a `kind: note` line and say what would settle it.

## 6. `results_staged`, and why the log is reconciled against the corpus

Log the count you actually staged off *that* query, as it runs — **`results_staged` is
required on every query line** (`CollectionLogEntry` refuses one without it from
2026-08-30), and `0` is a real answer to write, not omit. When the staging decision has
to wait for the article page (a date only the page confirms), logging `0` now and
appending a `--corrects` line after is the intended flow, not a workaround — a run that
produces a dozen correction lines is a normal run; corrections are new lines, never
edits. `check_collection_log.py` adds
up `results_staged` per group and compares it against what the round put in the corpus
(the newest build's members; `corpus/staging` before the first build), so:

- **over-counting across queries is fine** — one article surfaced by three queries is
  staged once and claimed three times, and the check is one-sided on purpose;
- **an article no query claims fails the round.** `aabb-island-dance-2024` round one logged 76
  queries every one of which read `results_staged: 0`, built 41 articles, and passed every
  check of the day. A log that explains none of the corpus still looks complete, and it is
  the only evidence anyone has of what a different search would have found — the reader
  who is told a side "barely covered this" is entitled to it.

Only the round matters: articles inherited from earlier builds are the baseline, so an
extension is judged on what it added. A count already written is corrected by a new query
line carrying `--corrects` (`log_query.py`), never by editing the old one. Rounds that
predate the rule (2026-08-29) are reported and not enforced; `--reconcile-since <date>`
audits them on purpose.
