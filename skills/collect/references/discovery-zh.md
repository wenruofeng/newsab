# Collecting Chinese-language media — the durable judgement calls

Read this before the first query against a Chinese-language group. It keeps only what
does not rot: how to tell boundary cases apart and how to triage a channel that goes
dark. **Per-outlet mechanics — URL templates, parameter quirks, parse targets, observed
rate limits, the field that settles reporting origin — are registry channel fields**,
read with `python -m newsab_corpus registry find --lang zh-CN --has-channel` and written
back with `registry set-channel` the moment you re-measure. Site behaviour drifts;
re-measure rather than trusting any claim here that contradicts what you see.

## 1. Search-engine behaviour patterns (measured 2026-08; the pattern is durable, the
   thresholds are not)

- **In-page `fetch()` of search URLs** draws an immediate captcha redirect (surfacing in
  the console as a CORS error) while normal navigation to the identical URL is fine.
  Engines score request *patterns*, not browser identity — which is also why stealth
  tooling is never the answer.
- **The `site:` operator** can land straight on the engine's verification wall, or —
  worse — be silently ignored and return unrelated results that look like an answer. To
  restrict to one outlet, first try DuckDuckGo's html endpoint via
  `skills/collect/scripts/ddg_search.py --site <host> '<terms>'` — not a Chinese engine,
  it honoured `site:` on a zh domain (measured 2026-08-29;
  `references/search-strategy.md` §1b), and the script needs no shared browser session —
  then the outlet's own search, or distinctive title wording with results filtered by
  host.
- **Sustained querying gets the whole IP blocked**, and that block can outlive the
  browser profile. Treat an engine as a **budget, not a faucet**: decide the query list
  before starting, keep a session's queries few and spaced. Burning the budget on
  exploratory phrasing loses the channel for the session — and the log then cannot
  distinguish "not covered" from "could not search".
- Expected in-period yield per query is low and deeper pages fall out of a short period
  quickly: budget several differently-phrased queries per grid cell rather than deep
  pagination.

## 2. Two channel traps that return plausible-looking wrong answers

- **A silently misnamed parameter** (e.g. singular where the API wants plural) can return
  the site's default feed with a believable count — a successful-looking search that
  searched nothing. Verify a new channel with a query whose answer you already know.
- **AND-matching site search** returns zero for almost any three-term query. A zero-result
  multi-term query is a property of the query, not evidence of silence; log it as such
  and re-run with fewer terms.

## 3. Origin labelling in Chinese copy

The lead sentence usually tells you, and getting it wrong breaks the cluster denominator:

- `据央视新闻，…` / `据新华社，…` → `domestic_wire`, `wire_source` = that outlet. If the
  original was not collected, say so explicitly — the build warns that the article matched
  no sibling, and an unexplained warning is worse than an explained gap.
- An editorial republished by another outlet → the republisher is `syndication` with the
  originating outlet as `wire_source`; the original is `original`. Collecting both is
  correct; they belong to one cluster.
- `据中国有色金属工业协会消息，…` / a ministry, regulator, association or company
  statement that several outlets rewrote → `press_release`, `wire_source` = **the issuing
  body**, not the outlet you took it from. A wire agency is a newsroom that reported; an
  issuer is an interested party that published — "six outlets carried the association's
  statement" and "six outlets carried the wire's story" are different facts to a reader.
  The build does not warn when a press-release rewrite matches no sibling: the statement
  itself is never an article in the corpus, so a lone rewrite is the normal case.
  - The test is **who wrote the words**, not who is quoted: interviewing the association
    is `original`; reprinting its notice is `press_release`.
  - A statement republished by a wire and then picked up (`据新华社报道，协会发布公告称…`)
    stays `domestic_wire` with the wire as `wire_source` — that is the chain the reader
    sees on the page.
- Two articles in one cluster both claiming `original` **fails the build** — intended
  behaviour, not an obstacle.

## 4. Aggregator-hosted copies

A large share of in-period Chinese results are not on the publisher's domain: platform
hostings of an outlet's own account (baijiahao and its kin — the real publisher is named
on the page, not in the URL) and finance portals republishing wire copy. Bodies never
come from these (`references/fetch-extract.md` §7); resolving one costs a browser visit
just to read who published it, so prefer results already on a publisher domain, and log
`kind: excluded` for what you cannot resolve. Watch equally for real newsrooms hosting
other institutions' accounts — the hosted-account channel name and author fields on the
page are authoritative, and belong in the registry's `channel.origin_field`.

## 5. Result pollution: what is not media

Chinese results carry a heavy layer of study-abroad-agency and education-marketing SEO,
plus self-media accounts on discovery platforms. Neither is a media organisation; both
are out of frame. Log a recurring host once as `kind: excluded` with the reason rather
than dropping it silently — the next collector otherwise cannot tell "seen and rejected"
from "never searched".

## 6. Dates

Result lists mix three formats and only one is unambiguous: relative (`3天前` — resolve
immediately, it rots), month-day with the current year implied (`8月4日` — the dangerous
one, sitting next to explicit-year rows in the same list), and explicit-year. **Confirm
the date on the article page** before staging anything near a period boundary.

## 7. Site-search recall is poor — zero hits is not silence

Measured repeatedly: an outlet's own site search returned nothing for queries whose
answers were already in the corpus from that very outlet, and some site searches pad the
tail of the result list with the day's homepage items (unrelated tail rows are filler,
not hits). *Zero site-search hits from an outlet is never evidence the outlet was
silent* — cross-check through another channel before writing any note.

## 8. The period-mismatch failure mode

The most expensive error measured was not a blocked site: coverage of the *previous*
policy round was dense just outside the period, every query phrased in that round's
vocabulary returned it, and the in-period round looked like press silence. Vocabulary is
time-indexed (`references/search-strategy.md` §2); before writing a thin-side note,
re-run the cells in the in-period round's own phrasing. If the period itself looks
misaligned with when coverage actually happened, that is a scope decision — return it to
the user, never widen the window yourself. When the user keeps a period knowing a
side runs thin, the log must say the shortfall is by scope decision, in those words.

## 9. Paywalls

A paywalled outlet serving lead-only pages → `access_level: partial`, stage title + lead
only. Do not attempt to defeat it.

## 10. Post-block triage — write the note before moving on

The distinction is invisible an hour later and impossible to reconstruct from the corpus.
Two failures get called "anti-bot" and need opposite responses:

| | Discovery failure | IP-level block |
|---|---|---|
| Symptom | article pages fetch fine; site search refuses HTTP **and** browser | a working channel, then the **whole host** refuses every path |
| Why a browser does not help | the problem is not opening a page, it is **not knowing which page to open** | the block is below the UA layer; looking human is irrelevant |
| Correct response | find another way to turn keywords into URLs (a discovery-only platform that names outlet + date, then fetch direct) | throttle to minutes per request, split across sessions, log unsearched cells as `backfill_debt` |
| Registry `channel.status` | `discovery_blocked` | `ip_blocked` |

While the triage is still pending (you cannot yet tell whether article pages fetch),
record `--status unknown` with a dated fetch note rather than guessing a state.

The symptom table, none of which is evidence about the media:

| Symptom | What it is | What the log must say |
|---|---|---|
| Empty results, verification-wall page title | anti-bot | blocked, not zero hits |
| Search refuses but article pages fetch | discovery failure | no channel, not zero hits |
| Whole host refuses every path | IP rate limit | blocked, not zero hits |
| Well-formed results, none in period | real | in-period yield, with the query |
| Zero results for a multi-term AND query | query artefact | re-run with fewer terms |
