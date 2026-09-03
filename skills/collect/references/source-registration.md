# Registering an outlet the registry has never seen

Read this when a search surfaces an outlet that
`python -m newsab_corpus registry find --host <host>` does not know. Meeting a new outlet
is the *normal* result of an open source frame, not an incident — you add it rather than
excluding it because "the list was already approved". What is not negotiable is doing it
completely: **you are the annotator of record; nobody reviews this file later.**

## 1. The registration block — all or nothing

The first staged article from a new outlet carries the full block; the build refuses a
half-filled one rather than completing it with placeholders (placeholders behind a
"human will review later" flag are exactly what this rule replaced):

```yaml
source_id: kendari_pos_id
source_country: ID                      # ISO alpha-2, upper case
source_url: https://kendaripos.fajar.co.id/    # the FRONT PAGE — a reader clicks this
source_name_en: Kendari Pos             # the masthead, not the slug
source_name_zh: Kendari Pos
source_name_native: Kendari Pos         # the outlet's own language, when neither en nor zh
source_category: serious
source_beat_scope: general
source_notes_en: >
  The regional daily of Kendari in Southeast Sulawesi, part of the Fajar group, close to
  Indonesia's nickel-producing areas.
source_notes_zh: 东南苏拉威西肯达里市的区域日报，属 Fajar 报业集团，地处印尼镍矿产区。
```

`source_notes_*` is **one sentence, for a reader**: who runs it, what it covers, what to
discount. It doubles as the record of why `source_category` reads the way it does.
Nothing addressed to an agent goes here — fetch mechanics belong in
`channel.fetch_notes`, this topic's sampling debt in its collection log.
`registry check` greps for the giveaway phrases.

## 2. Which `category` — the only cut it must support

Two values, supporting exactly one cut: "serious press only" versus "everything we
collected".

- **`serious`** — a newsroom that reports under its own byline and answers for the facts:
  named reporters, its own desks, reported rather than aggregated copy. Wires, national
  and metro dailies, public broadcasters, party organs, staffed business newsrooms.
- **`other`** — everything else we still collect and still count in the all-sources view:
  tabloids, special-interest magazines, trade information services, aggregating portals.

**Ownership is not the test** — state, public and private newsrooms are all `serious`
when they report under their own byline; the notes sentence is where the institutional
difference is recorded, in words, for a reader. Recurring lines: a general-news magazine
with a news desk is `serious`; a special-interest magazine is `other` however good it is;
a portal whose news pages are mostly attributed republication is `other` — not a quality
verdict, but what keeps the same wire copy from counting as independent serious coverage.
`other` is a real answer, not a place to park an undecided call: say in notes what the
outlet is, and the category follows.

## 3. `beat_scope: general | vertical` — what kind of newsroom

Orthogonal to `category`: register vs **remit**. `general` = the remit is all news, even
with a heavy business emphasis; `vertical` = one industry, sector or domain (metals trade
press, an education chronicle, an energy desk). The axis exists because verticals fall on
both sides of the serious/other line, so a balance check reading `category` alone calls
two samples comparable when one is entirely trade press — the worst composition bias
measured in the first topic. The build compares the two sides' vertical share and warns;
**the fix is to top up the kind of outlet the other side is missing, never to relabel.**

## 4. Channel knowledge — write it back the moment you measure it

The registry is also where "how do I even search this outlet" lives:
`channel.search_channel`, `fetch_notes`, `rate_limit`, `origin_field`, `status`.

```sh
python -m newsab_corpus registry set-channel <source_id> \
    --search-channel 'https://…/search?keywords={query}&page={page}' \
    --rate-limit 'none observed' --status ok
```

Write it mid-run, not at the end; `checked_at` is stamped for you, because an undated
channel note is a claim about a website that may have been redesigned twice since.
`--fetch-notes` **appends** a dated line to whatever earlier workers measured — the
accumulation is the value (huanqiu's entry holds seven facts: a 403 subdomain trap, a
list-API shape, a body-selector…), and one overwrite nearly destroyed it once. Replace
only with `--replace-fetch-notes`, and only when the old notes are measured to be wrong,
not merely old. An
empty `channel` is a gap, not a defect — most outlets enter through a search engine and
nobody ever needed their site search. `status` distinguishes `discovery_blocked` (article
pages fetch, search does not — find another way to turn keywords into URLs) from
`ip_blocked` (the whole host throttles — pace in minutes and split across sessions).

## 5. Registry traps

- **Read it through `registry find`, never with `cat`** — it spans every topic ever
  collected and is knowledge, not a gate: never hashed, never frozen, never approved.
- It has no `group_id`: which side an article falls on is a per-topic judgement against
  the manifest's group definitions, stored explicitly in staging.
- "Which sources this corpus covered" is derived from the corpus run's `source_ids`,
  never read off a list.
- Audit before finishing: `python -m newsab_corpus registry check` must exit 0 — it
  catches what a schema cannot (a media card written at an agent instead of a reader, an
  article URL where the front page goes, undated channel knowledge).
