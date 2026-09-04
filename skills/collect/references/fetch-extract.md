# Fetch & extract — from a discovered URL to a verbatim staged body

Read this when URLs are in hand and bodies need taking. The product promises a reader can
Ctrl-F any quoted sentence on the original page, and the pre-publication checks re-verify
quotes character by character weeks later — so extraction is not "get the gist", it is
"get exactly those characters".

## 1. Identity, layers, and the one rule you may never break

**Discover in a browser. Fetch over HTTP. When HTTP is refused, go back to the browser.**
Search engines and outlet site search actively block scripted access; publisher article
pages usually do not — and when one does, that refusal is an artifact of the transport,
not the publisher's answer about who may read the page.

### 1.1 The identity you send

You are a **named research fetcher operated by a human**, and you say so, in both layers:

    newsab-collect/0.1 (+<operator-url>; human-operated news-comparison research; contact: <operator-email>)

Truthful, specific, contactable. That is the strongest position available: it lets a
publisher rate-limit you, mail you, or ask you to stop — which is what good faith looks
like from the other end of the socket.

In a public clone, configure `.newsab/operator_identity.json` with the human operator's
real, contactable URL and email, following the schema in
`packages/corpus/newsab_corpus/data/operator_identity.v1.json`. The starter package data is
intentionally unconfigured and network access fails closed until this local file exists.
**Do not type the resulting UA. Send it by using the fetcher**, which carries the same
configured identity in both layers:

    python -m newsab_corpus fetch <url> [<url> …] --out corpus/raw
    python -m newsab_corpus fetch --show-identity     # the exact string, for a plan or a note

`newsab_corpus.fetch` is the one definition site of the identity, of the robots reading in
§1.2 and of the retry in §1.3. A hand-rolled fetch re-decides all three, which is how each
of them got broken the first time.

Two identities are forbidden, because both are false statements:

- **Never send `ClaudeBot`, `anthropic-ai`, `Claude-Web`, `GPTBot`, `CCBot` or any other
  vendor crawler token.** This fetcher is not that crawler. `ClaudeBot` is a vendor's
  bulk crawler; a publisher disallowing it is refusing corpus-scale harvesting by that
  vendor's infrastructure, not answering a question about a script a researcher runs on
  their own machine for one topic. Borrowing the name is impersonation — and it silently
  rewrites which robots group applies to you.
- **Never send a bare browser UA over HTTP to look human.** The same lie pointed the
  other way, and it is the stealth this skill has always banned.

### 1.2 Which robots group applies — and the absolute prohibition

RFC 9309: exactly one group applies — the most specific `User-agent` that names you, and
`*` when nothing does. Nothing in the wild names `newsab-collect`, so in practice **`*` is
your group. Honour it, and only it.** (A host that ever does write `User-agent:
newsab-collect` is addressing us, and that group then wins over `*` — the fetcher picks
this correctly; nothing else may.)

> **ABSOLUTE PROHIBITION — never bind yourself to a rule that was not addressed to you.**
> Do not adopt a vendor crawler's name. Do not "read it the strict way to be safe". Do
> not apply a `Disallow` written for `GPTBot`, `CCBot` or `ClaudeBot`. Do not invent a
> caution the collection plan does not contain. This is not a style preference and not a
> tie-break in favour of restraint: **extra caution here is a sampling decision, taken
> silently, at fetch time, by an agent with no mandate to take it.** It belongs to the
> same family of errors as inventing a source.

Measured, 2026-08-27, `aabb-market-meal-2024`: a collector volunteered `ClaudeBot` as its user
agent, which made the `ClaudeBot` group the most specific match, which disallowed it —
and it then obeyed the instruction it had just issued to itself. Result: 15 of 50 German
hosts reachable, with *Spiegel*, *SZ*, *FAZ*, *Zeit*, *Welt*, *Focus*, *Tagesspiegel* and
every public broadcaster out of the sample, while the Turkish side kept its national
agency and most large dailies. The German press opted out of AI crawling collectively in
2023–24; the Turkish press largely did not. Reading robots by crawler identity therefore
does not sample media — it samples **national copyright-lobby posture**, and the reader
meets that as "the German press covered this less". A false finding, manufactured
entirely by self-applied restraint.

`robots.txt` status codes, per RFC 9309 §2.3.1: **4xx — 403 included — means
*unavailable*, and no restrictions apply**; 5xx means *unreachable*, and the host is
treated as disallowed until it answers. A 403 on `robots.txt` is not evidence that a rule
exists and you should assume the worst. Note the signal, though: a host that 403s your
`robots.txt` request but serves it to a browser is telling you which layer to use next.

### 1.3 When a fetch is refused, retry in the browser. Always.

Any host that refuses the HTTP fetcher — 403, WAF interstitial, JS challenge, empty body,
"unsupported browser", a redirect loop — **must be retried through the Playwright browser
before anything is written down about it.** A bot-score heuristic is a guess about
transport, not a statement about who may read the article; the publisher serves that page
to anyone who opens it, and you are opening it for the human who delegated this run.

- A failure is only real if it survives **both** layers. `fetch_failure` entries record
  `layer: browser`; `CollectionLogEntry` refuses one that does not, so an HTTP-only
  refusal cannot reach the log as a finding. `newsab_corpus fetch` does both retries for
  you and prints the layer each outcome was decided at — including which URLs are
  loggable as `fetch_failure --layer browser` and which are not. It keeps the refusing
  page as `*.refused.html` so you can see what the browser actually got before you write
  a failure down, and it raises rather than reporting a both-layer failure when the
  browser could not start: a missing tool must never be recorded as media silence.
- A host that needs the browser is `status: ok` in the registry, with
  `channel.fetch_notes` saying a browser is required. It is not a block, and it must never
  become one downstream.
- **Never write down a retrieval limit you have only tested at one layer**, and state the
  layer you tested. A run that concluded "this environment refuses programmatic queries"
  from HTTP alone was one step from publishing a tool ceiling as *media silence*.

**A page that fetches but does not extract is also a refusal.** A JS-rendered site answers
200 with a shell and a nav menu, then yields four words of body — so the retry fires on
**either** signal: a non-2xx status *or* an implausibly thin extraction (the fetcher's
`--min-chars`, default 600), before anything is written down. Measured,
`aabb-steppe-stone-2025`: six Mongolian pages fetched 200 over HTTP and extracted to 11–448
characters; rendered in the browser, four came back with 650–6,200 characters of real
article. Had the run stopped at the HTTP status, those would have entered the corpus as
near-empty articles or been dropped as thin coverage.

### 1.4 The hard floor — where "never bypass" actually lives

Never, under any collection plan, on either side:

1. **Paywalls, metered walls, registration walls, logins.** Not defeated, not worked
   around, not read out of a cache that exists to defeat them. → `access_level: partial`,
   title and lead only (§8).
2. **Technical protection measures.** Circumventing them is unlawful in most jurisdictions
   this repo collects from (§95a UrhG, DMCA §1201).
3. **Disguised or rotating identity** — UA rotation, IP or proxy pools, stealth plugins,
   cookie and consent-wall tricks. Both layers carry the one honest identity of §1.1.
4. **Bulk traversal, in either layer** — pagination sweeps, site-wide enumeration,
   walking a result set page after page, anything that turns retrieval into a crawl. What
   makes something crawling is the volume and the pattern, not the client: driving it from
   the Playwright browser instead of the fetcher changes nothing about it. Opening the
   pages a query actually named, at human pace, is not this.
5. **Rate.** Same-host requests serially, under the registry's `rate_limit`. Human pace,
   never crawl pace. The fetcher paces itself per host (`--delay`, default 2s); raise it
   when the registry entry asks for more, never lower it to go faster.

**What is deliberately *not* on this floor: `robots.txt`.** A `Disallow` in the `*` group
is a crawling convention, not an access control and not a rights reservation, and it binds
**retention, not reading** (§1.5 — that is where the legal weight is). Product ruling,
2026-08-29 — it turns on **which path** the rule names, never on which country the
publisher sits in:

| what the `*` group disallows | may you open it | what may be kept |
|---|---|---|
| a utility path — `/suche/`, `/search/`, `/tag/`, `/print/`, `/amp/` | yes, either layer | nothing is staged *from* it; the articles it names are ordinary allowed URLs, staged in full |
| the article path itself | yes, human pace | title + lead — `access_level: partial`, chosen at the scope sitting and applied to **both** groups |

Neither row licenses a sweep: item 4 holds over both of them.

Row 1 is the ordinary case and the one that was getting mishandled: search and tag paths
are disallowed almost everywhere for crawl-budget and duplicate-content reasons, and
reading that as "this publisher refuses us" is §1.2's failure wearing different clothes.
Row 2 is real: EU law does recognise a machine-readable reservation, so an article-path
`Disallow` is treated exactly like a purpose-addressed reservation (§1.5 row 3).

**The two layers are one regime.** The browser is not a loophole and not a stricter court:
`newsab_corpus fetch` reads `robots.txt` and returns `retention: full` or
`retention: reserved` without ever refusing to fetch, and opening the same page in the
Playwright browser sits under the same two rows. Measured, `aabb-museum-metal-2026`: the
fetcher refused n-tv's `/suche/` outright while the browser opened it with no check at all
— one behaviour was too strict, the other unwritten, and the gap between them was being
resolved by whichever agent happened to be reading.

### 1.5 Retention — what may be kept, which is the part with legal weight

The exposure of this project is not *reading*; it is *keeping*. EU DSM Art. 4 (in Germany
§44b UrhG) lets a rightsholder reserve text-and-data-mining rights **in machine-readable
form**. Three kinds of signal must not be confused:

- **Addressed by name** — a robots group naming `GPTBot`, `ClaudeBot`, `CCBot`. Addressed
  to those crawlers, not to `newsab-collect`. §1.2 applies: not yours, do not adopt it.
- **Addressed by purpose** — `tdmrep` (`/.well-known/tdmrep.json`, `tdm-reservation`
  headers or meta), `ai.txt`, a `noai` meta directive. These reserve *mining*, whoever is
  doing it. Treat them as addressed to the corpus store.
- **Addressed by path** — a `*` group `Disallow`: a utility path is an indexing measure,
  an article path is treated as a machine-readable reservation. §1.4 has the two rows;
  neither stops the fetch.

| what the host publishes | fetch | keep |
|---|---|---|
| nothing, or a `*` group that allows the path | yes | full body |
| a robots group naming vendor AI crawlers | yes, human pace, honest UA | full body |
| a purpose-addressed reservation (`tdmrep` / `ai.txt` / `noai`) | yes, human pace | title + lead only — `access_level: partial`, reason logged |
| a `*` group disallowing a **utility** path (`/suche/`, `/tag/`, …) | yes — it is not addressed to reading | nothing is staged from that page; articles found through it are ordinary full-body sources |
| a `*` group disallowing the **article** path | yes, human pace | title + lead only — `access_level: partial`, reason logged (same as row 3) |

What the project *publishes* is short verbatim quotation, attributed and linked back to
the publisher's own page; the corpus store that feeds it is local, gitignored and never
redistributed. Rows 3 and 5 are the deliberate concession: they cost the outlet's answers
but keep it visible in the sample rather than deleting it, and they are the rows to revisit
with a lawyer before this repo publishes at scale.

The retention row for a topic is chosen **at the scope sitting**, written into the
collection plan, and applied identically to both groups — never per outlet, never at fetch
time.

## 2. Browser mechanics that save sessions

- **Extract a result page in one JS evaluation** over the result nodes (title, href, date
  text, outlet) — an order of magnitude cheaper than paging through accessibility
  snapshots.
- **Do not batch-`fetch` search URLs from inside the page context.** It inherits cookies
  and looks attractive; engines score the request pattern and answer with a captcha while
  the same URL opened by normal navigation is fine.
- **SPA site search**: a deep link is not a search — the hash route renders an
  empty-results shell; put text in the box and press Enter. React-controlled inputs
  ignore assigned values; use real keystrokes (type/fill + press), not `input.value =`.

## 3. Scope to the body container. Never all `<p>`.

Taking every `<p>` on the page is the most common way to poison a corpus, and the poison
is invisible until annotate meets it: page-wide extraction has brought along AI-summary
disclaimers, share instructions and paragraphs of unrelated recommended stories; in one
measured case, un-stripped subscription boilerplate made 13 newsletters similar enough to
collapse into **one** reporting cluster, directly corrupting the denominator.

Procedure: find the node containing the first real body sentence, walk up to its
container, extract only within it. Container selectors drift — verify on the page, and
record what you used in the outlet's `channel.fetch_notes`.

### 3.1 JSON-LD `articleBody` is a shortcut with a trap

Many sites ship the article as a string in a JSON-LD `<script>`, which looks like the
cleanest possible extraction — no container hunting, publisher's own paragraph breaks.
It is, right up to the case that matters: **a paywalled page routinely puts the WHOLE
article in JSON-LD while rendering only a teaser.** Taking that string then breaks §2.5
(the reader cannot Ctrl-F a sentence that is not on the page) and takes text the wall was
withholding, which §1.4 refuses on both sides of every topic.

The rule, therefore: **JSON-LD text may only be kept when it is actually present in the
rendered page.** Build the visible text once, keep the JSON-LD blocks it contains, drop
the ones it does not — and if anything was dropped, the article is `access_level: partial`.
Measured, `aabb-steppe-stone-2025`: of 35 French pages, 9 shipped a JSON-LD body whose text was
partly or wholly absent from the rendered page (Le Figaro and Challenges: absent entirely;
La Croix: 16 of 23 blocks visible). Under the check, 16 of 35 articles came out `partial`,
which is what the French press actually gave us.

The same check is the cheapest paywall detector you have — cheaper and more reliable than
looking for a subscription banner, because it asks the only question that matters: can a
reader see this sentence?

### 3.2 The standfirst is part of the article

On most French and many other sites the standfirst (`chapo`, lede, standfirst, excerpt)
sits *outside* the body container. On a wire-carrying page it is the dispatch's lede — the
single most quotable sentence in the article — and a container-scoped extraction drops it
silently. Take it, and prepend it as the body's first paragraph when it is not already
there. Measured on the same corpus: 9 of 35 pages lost their lede before this was added.

### 3.3 A class blocklist must be guarded by text share

Dropping nodes whose `id`/`class` mentions `sidebar`, `header`, `nav`, `promo` and friends
is necessary and is also how you delete the article: france24 and rfi wrap the body in
`t-content__beside-sidebar`, so a naive blocklist removed 100% of the text and reported an
empty page. **Never drop a node holding a large share (≥30%) of its parent's `<p>` text**,
whatever its class says. A blocklist is a hint about intent; the text share is evidence.

## 4. Allowed normalisation — only what a browser itself does

Resolve HTML entities; `<br>` → newline; fold runs of **ASCII** whitespace to one space;
strip Unicode spaces at block edges. Everything else is preserved exactly — punctuation,
full-width vs half-width, spacing, typos. Do not tidy: a prettified quote fails the
verbatim re-check weeks later with no context. This is why trafilatura / newspaper3k /
news-please are not used here despite being the obvious tools — they normalise for
readability, the opposite of this guarantee. Borrow their idea (scope to the container);
never their output.

Chinese pages declaring `charset=gb2312` routinely contain GBK-only characters; decoding
as declared silently replaces them and the quote is no longer verbatim. `newsab_corpus.fetch`
handles this for you: `http_get` reads the HTTP header charset, then a `<meta charset=…>` /
`http-equiv="Content-Type"` declaration in the first 2048 bytes, then falls back to utf-8 —
and decodes `gb2312`/`gbk` (any spelling) as **`gb18030`**, always, since it is a strict
superset of both. A hand-rolled fetch that bypasses this (see §1.1's warning against one)
re-decides it and is how this broke the first time; nothing else needs to re-decode.

## 5. Site chrome, and what the build already catches

Strip subscription prompts, share widgets, navigation, ad markers, copyright footers,
recommendation rails — not cosmetics: shared boilerplate inflates similarity between
unrelated articles and merges clusters. `strip_residue` catches the known shapes at build
time and prints every removal into `build_report`; a survivor it does not know is **not**
something to hand-edit out of the body — leave the text verbatim, never anchor on the
residue sentence, and report the shape so it becomes a rule. Chrome-stripping is not a
licence to remove *content* you find repetitive; when unsure, keep it and say so in the
staging `note`.

## 6. Declare how the body marks paragraphs

Staging carries `paragraph_break: blank_line | single_newline` and the builder never
guesses. Both readings produce valid sentence IDs, so a wrong guess is silent until every
"which paragraph" answer is wrong. A body copied from the rendered page is `blank_line`;
a body from a JSON-LD `articleBody` (or any API field shipping the article as one string)
is almost always `single_newline` — its paragraph breaks survive as lone `\n`. Check
before staging: no blank lines but plainly multiple paragraphs answers it.

## 7. Aggregators — including ones wearing a newsroom's domain

Bodies never come from an aggregator: the Ctrl-F promise is about the publisher's own
page. An aggregator copy that cannot be resolved to its publisher is logged
`kind: excluded` with the reason, never staged.

The expensive case is a platform that is *itself* a real newsroom hosting other
institutions' accounts: an article staged as the host outlet's own reporting inflates its
prevalence and puts a copy into the cluster denominator as though it were independent.
Before staging from any platform that hosts institutional accounts, find the page field
that names the actual author — hosted-account channels vs the outlet's own desks, an
`isOrigin`-style flag, a named source field. **Where the outlet's own page distinguishes
its reporting from what it hosts, that field is authoritative and cheaper than your
judgement**; record where it lives in the registry's `channel.origin_field`.

## 8. Partial and blocked sources

Paywalled, or carrying a purpose-addressed TDM reservation (§1.5 row 3) →
`access_level: partial`, stage title + lead only, marked in the source snapshot too. A
fully blocked source produces **no article record at all** — only a `collection_log`
entry; the schema enforces this. "Blocked" means **both** retrieval layers failed (§1.3),
and nothing else: an HTTP-only refusal is not a blocked source, and neither is a robots
`Disallow` — that one sets retention, not reachability (§1.4), so it produces a `partial`
record, never a missing one.

## 9. Before you stage — the last look

- The URL is the publisher's own page (§7 — check even when the domain is a real
  newsroom's).
- The publish date is confirmed **on the page**, never inferred from a search-result
  snippet — result lists mix relative dates, year-implied dates and explicit years in one
  column.
- `origin` reflects the lead's attribution (`references/discovery-zh.md` §3 for Chinese
  copy); the build cross-checks and fails when two articles in one cluster both claim
  `original`.
- Filenames are append-only working labels (`<group>-<serial>-<outlet>.yaml`); article
  and sentence IDs are content-addressed from the canonical URL, so adding a neighbour
  never renumbers them.
