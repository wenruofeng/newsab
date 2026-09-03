# Artifact versioning — the write protocol

How every stage writes its outputs: content is append-only, runs pin the content set they
saw, and a publication pins the full reviewed run closure (value_chain non-negotiable 6).
`topics/README.md` describes what the directories are; this file defines how they are written to. The single
implementation entry points are `newsab_schema.artifacts` and `newsab_schema.store` — no
stage assembles version directories or appends to the manifest on its own.

---

## 1. Three kinds of thing, three lifetimes

| | what it is | lifetime |
|---|---|---|
| **article store** `corpus/articles/` | every article this topic has *ever* ingested, keyed by content-addressed `article_id` | append-only: grows, never edited. Never leaves the private tree (D14) |
| **run record** `<stage>/versions/<run_id>/` | the content set one run saw / produced | immutable once written, never reused |
| **active pointer** `manifest/active.json` | which run each stage currently selects | mutable routing — **not an artifact, enters no hash check** |

What is immutable is **the content set a run referenced**, not the state of a directory:
the store only grows, each run records which members it saw and what each contained, and a
published version pins one run. That is why later, legitimate growth of the corpus never
looks like tampering.

### 1.1 `article_id` is a content address

`{GROUP}_{first 8 hex of sha256(canonical_url)}`, e.g. `CN_a1f39c02`. Not a build-order
serial: serials shift wholesale when a mid-list article is removed, and sentence IDs are
`{article_id}:P{para}:S{sent}` — one shift misaligns every downstream evidence anchor.
Under content addressing the same article gets the same ID whenever it is ingested and
whatever sits next to it; re-collection deduplicates naturally. Legacy `CN_028`-style IDs
still resolve (for reading old records) but are never minted again.

`canonical_url` normalization does only what provably cannot change which article the URL
points to: lowercase scheme/host, drop default ports, fragments, tracking params and
trailing slashes, sort the query, collapse duplicate slashes. It does **not** unify mobile
vs desktop domains and does not resolve redirects — those are collection-time judgements
made with evidence, not something to hide inside a hash function.

### 1.2 How the store changes

| case | action |
|---|---|
| new article | write `corpus/articles/{article_id}.json` |
| re-collected, body identical | **do not touch the file**. Same bytes ⇒ same content hash ⇒ every existing annotation anchor stays valid |
| re-collected, body changed | archive the old bytes as `corpus/articles/_superseded/{article_id}.{hash8}.json`, then write the new version. Runs pinning the old hash can still restore it |
| remove an article from the sample | `python -m newsab_corpus withdraw <topics_root> <topic_id> <article_id> --reason "…"`, recorded in `corpus/withdrawn.jsonl`. **Never delete the file** — deletion makes historical runs unrestorable |

Retiring a stage's current version likewise only removes routing, never runs:
`python -m newsab_schema deactivate-stage <topics_root> <topic_id> <stage>` atomically
drops the stage from `manifest/active.json`; manifest lines and version directories stay,
so historical runs remain restorable.

### 1.3 What a run record holds

The corpus run record is `corpus/versions/<run_id>/corpus_run.json` (`CorpusRun`):

```
run_id, topic_id
articles[{article_id, source_id, content_hash, reporting_cluster_id}]   # members this run saw
withdrawn[{article_id, reason, at}]                                     # in the store but excluded here
set_hash                    # sha256 over sorted [[article_id, content_hash], ...]
splitter_version, cluster_threshold, cluster_shingle_n
backfill_debt[{source_id, cell, reason}]                                # unsearched query-matrix cells
build_report{cluster_members, stats, sources_covered, ...}
warnings[]
```

Two points worth stating separately:

- **`reporting_cluster_id` belongs to the run, not the article.** Adding one wire reprint
  can merge two clusters into one, so cluster membership cannot live in an immutable
  article record. The copy inside the article file is a provisional build-time singleton;
  `restore_set()` overrides it with the run's assignment.
- **`sources_covered` is a derived fact.** "Which sources this version actually covered"
  is computed from the run, not approved in advance (R-3). It is what the page should show.

Other stages (questions / answers / analysis / page) still "write files into a run
directory"; their set fingerprint is a digest over the directory's file hashes. A1 already
has `analysis/<a1_run_id>` and gets no extra layer.

## 2. Commit order

A successful run commits strictly in this order:

1. New articles into the append-only store; existing identical ones are **not rewritten**.
2. The run's outputs into a run directory that does not exist yet; an existing directory
   is a failure, never overwritten.
3. The stage's deterministic checks. A failing working directory must not reach the
   manifest or the active selector. **Run every check the pre-publication verifier would
   run — as a dry-run against the working tree, before step 2 writes the immutable
   directory**: run directories are write-once, so a check that can only fire after the
   fact costs one burned run id every time it fires.
4. Compute `output_set_hash` (corpus: `CorpusRun.set_hash`; other stages: the digest over
   run-directory file hashes).
5. One append to `manifest/manifest.jsonl`. Inside the lock, before writing: validate the
   whole existing chain, reject a duplicate `run_id`, reject `inputs` naming unknown
   upstream runs, and **recompute** `output_set_hash` to confirm it matches the claim.
6. Atomically replace `manifest/active.json`.

An aborted run writes the manifest with `status=stopped` and must carry `escalations`; a
run that produced nothing new uses `status=no_op`. Neither updates the active selector.
Re-running the same inputs still mints a new `run_id`.

## 3. What the manifest records

```
{skill_id, skill_version, model_id, run_id, topic_id,
 stage,             # which versioned stage this run wrote (null if none)
 inputs,            # upstream run_ids — the real dependency edges
 output_set_hash,   # fingerprint of the content set this run produced
 input_hashes, output_hashes,   # byte hashes: historical evidence
 status, counters, metadata, escalations, gates, timestamp}
```

**`inputs` are upstream `run_id`s, not paths.** "A1 run X analyzed corpus run Y" is a
stable dependency fact; "A1 read these bytes at these paths" is not — paths change when
content legitimately grows.

**`input_hashes` / `output_hashes` are historical evidence; `manifest-check` does not
re-verify them.** They record what a run touched, which stays true forever; they do **not**
promise that a path keeps those bytes forever — that promise would make every legitimate
addition look like tampering.

**What `manifest-check` verifies:**

1. every run that declares an `output_set_hash` still has a **restorable** set with a
   matching fingerprint — for a corpus run, every article it references can still be found
   in the store (current version or `_superseded/`) under the pinned content hash, **even
   after the store has grown**;
2. every `inputs` edge points at a run this manifest knows;
3. the active selector points at runs that exist.

Tampering is still caught: editing any file in a run directory, or changing a pinned
article's content without archiving the old bytes, makes the recomputed fingerprint
mismatch.

## 4. Correction mappings

Wrong records are never edited in place. Produce the replacement in a new run, then append
a `CorrectionMapping` to `manifest/corrections.jsonl`:

- `superseded` and `replacement` each bind a `run_id`, a topic-relative path, the file's
  SHA-256, and — for streamed artifacts — the `record_id` (omit for whole-file
  replacement);
- `reason` carries a language tag;
- the replacement run must already exist in the manifest, and both files' current hashes
  must match the mapping;
- one old reference gets at most one direct correction; a further correction points at the
  previous replacement, forming a walkable chain.

A correction changes only which version is *interpreted* as valid. It never deletes or
rewrites old artifacts or old manifest lines.

## 5. Incremental extension is the standard move

Routine operation, not an exception (D20):

```bash
# 1. put the new staged articles in staging, then
python -m newsab_corpus build topics <topic_id>
#    the output names exactly which articles are new:
#    incremental  3 new article(s) need annotation; the rest carry over unchanged: CN_… CN_… CN_…

# 2. annotate only those, assembling a new answers run (existing answer lines untouched)
# 3. re-run analyze (pure Python, seconds) — it pins the new corpus run
python -m newsab_a1 qa topics <topic_id>
```

A published page keeps pinning its old analysis run; its numbers do not move. Switching a
page to a newer run is an explicit act.

## 6. Site-level publication root

**Specified reader:** the stage 8 `publish` agent and any agent changing production
selection, catalog generation, curation or site-level artifact storage must read this
section.

Publication, lifecycle events and catalogs span topics, so they do not live in any one
`topics/<topic_id>/` tree and do not extend that topic's active selector. The second typed
root is `SitePaths.at("site")`, a sibling of `topics/`:

```text
site/
  publications/<publication_id>/publication.json   immutable, public-safe record
  events/publication_events.jsonl                  append-only internal hash chain
  catalog/<locale>.jsonl                           derived, public-safe cache
  production/selector.json                         derived atomic cache
  curation/                                        reserved site-operation root
  submissions/                                     private, never deployed, never committed
  audit/<publication_id>/                          never deployed; holds only the
                                                   display-cleared render-input archives a
                                                   candidate re-verification needs, so it
                                                   is versioned — anything not already
                                                   cleared for page display belongs in
                                                   submissions/ or private/ instead
  private/                                         private credentials/operations, never committed
```

There is deliberately **no second generic manifest** beside these files. A site manifest
would repeat the same semantic history while making disagreement possible. Instead:

1. `PublicationRecord` itself carries deterministic producer provenance, the full set of
   topic-run pins and their output fingerprints, the exact reviewed page hash and public
   bundle fingerprint. It also pins the content-addressed data-island assets
   the page bytes reference (`data_assets`: filename, URL, byte hash) — a content
   document is several files, all content (`value_chain.md`, "Content document and site
   chrome"): the islands sit in the bundle's closed file list at
   `topics/<topic_id>/data/<island>.<hash>.json`, shared across locales, and
   `verify-candidate` re-derives them for a current-producer candidate.
   `newsab_schema.store.write_publication()` creates its directory and
   refuses any overwrite.
2. `PublicationEvent` binds the byte hash of that record and the prior event hash.
   `append_publication_event()` validates the complete existing chain and state transition
   under a lock, fsyncs one event, then atomically replaces the derived selector.
3. Catalog records bind the publication hash and bundle fingerprint. They are discarded
   and rebuilt when the publication set or versioned site metadata changes.
4. **Site chrome is a release fact, not a publication fact.** The shared stylesheet, the
   behaviour script and the palette behind each theme token are written once per release
   at stable URLs (`/assets/…`) that content documents link, and `production/release.json`
   records their version and per-asset hash. No `PublicationRecord` names them, no
   candidate bundle contains them, and `verify-site` re-checks the deployed bytes against
   that record. This is what lets the site be restyled without invalidating a single
   human approval (`value_chain.md`, "Content document and site chrome"); a publication
   still pins the theme *registry bytes* it was prepared against, as audit provenance.
   The site's PNG social card is one of these release assets.
5. **The origin is a release fact too, so a deployed page is not byte-identical to its
   bundle**. Approved bytes are root-relative; the build resolves the crawler
   metadata a social platform cannot resolve itself — absolute `og:url` / `og:image`,
   pointed at the release's PNG card — into the deployed copy. Nothing else moves, and
   `verify-site` re-derives every deployed page as `crawler_meta.resolve(bundle bytes,
   base_url)` and compares bytes, so the difference is audited rather than trusted. The
   bundle stays the approved artifact and the thing every hash in the record binds.

This is still the same append-only protocol, with site-shaped facts rather than a duplicate
run ledger. A reviewed `PublicationRecord` with no event is “approved but not published.” A
`publish` event (or the replacement side of `supersede`) makes it live; its event timestamp
is the sole `published_at`. Mutable status never enters the record. `withdraw`, `restore`
and `audit_delete` are later events, not correction mappings; a content correction is a new
topic run closure, new review, new publication and `supersede` event. `audit_delete`
removes a publication from every derived and deployed surface, **not** its record file:
every later append re-verifies the whole chain's hash bindings against the on-disk
records, so deleting or editing any `publication.json` — even an audit-deleted one —
permanently blocks all further lifecycle events. A legal takedown that must destroy the
record bytes themselves needs a tombstone mechanism that does not exist yet; design it
before executing one, do not improvise by deleting files.

Cross-root dependency edges are always qualified as
`{topic_id, stage, run_id, artifact_fingerprint}`. For a versioned stage this is its
`output_set_hash`; for a scope run that predates version directories it is the canonical
fingerprint of the signed scope artifact. A bare run id is insufficient at site level, and
`manifest/active.json` is never consulted to interpret a publication. The required closure
is scope, corpus, questions, answers, normalization, analysis and final page.

`SitePaths.visibility()` uses three classes. Only `publications/` and `catalog/` are
`public_source`; `events/`, `production/` and `curation/` are internal; `submissions/`,
`audit/` and `private/` are private. “Public source” only permits the bundle builder to read
the typed record. Deployment still assembles a closed file list and scans its final bytes;
the `site/` tree is never copied wholesale. The renderer may resolve quotes from the private
topic corpus during the build, but the built HTML and public-safe records are sufficient at
runtime and never point the browser back into that corpus.

---

## 7. Which bytes git carries, and which it does not

**Specified reader:** every agent that writes, reads, verifies or moves an artifact —
because "recoverable" and "committed" are not the same promise, and this section is where
the difference is defined.

Append-only requires that an artifact be **recoverable and provably untampered**. It does
not require that it be in git. Three classes of large bytes are therefore gitignored while
staying exactly where they always were on disk (product decision):

| Path | What it is |
|---|---|
| `site/public/**` | the derived production tree — rebuildable from records |
| `site/publications/<id>/bundle/**` | the immutable candidate/publication page bytes |
| `topics/<topic_id>/editorial/versions/<run>/preview.*.html` | stage-6 reviewer previews |
| `topics/<topic_id>/corpus/{articles,staging}/**` | full source text (also *private*) |

They grow as topics × versions × locales — a thousand topics extrapolates past 4.5 GB —
and git history only ever grows. The corpus store was already gitignored for the private
reason; these three join it for the size reason.

One class of small bytes moves the other way — `site/audit/cost/**`, the per-topic
production cost reports — and is carried by git precisely *because* nothing verifies it:
it is telemetry about how an artifact was produced, freely recomputable and backfillable,
so it is cheap to keep and it can never invalidate a byte. Do not confuse it with the four
archived render inputs one level up in `site/audit/<publication_id>/`, which
`verify-candidate` reads by name on a fresh clone.

What git keeps is the **small record that proves them**: `publication.json` (bundle
fingerprint + reviewed page hash), `manifest/manifest.jsonl` and each run record
(`output_set_hash` over the run's outputs), `production/release.json` (per-asset chrome
hashes), `catalog/<locale>.jsonl`. Every verifier — `manifest-check`, `verify-candidate`,
`verify-site`, `web-gate`, `dev-serve` — hashes the bytes **on disk** and compares them to
those records. None of them asks git anything, so untracking changed no verdict.

Three rules follow, and they are not negotiable:

1. **Paths never move.** Untracking is not relocation. Every skill, script and agent reads
   these files exactly where it always did; a change that moves them is a different,
   larger change that must update every reader in the same commit.
2. **Never delete them.** Disk is the authoritative copy. Deleting a gitignored artifact
   destroys it — `git checkout` will not bring it back. This includes "cleaning up" an old
   run directory, an old bundle, or a superseded preview. (The one deliberate rebuild is
   `site/public`, per `packages/publish/README.md`; even that reuses the recorded
   `base_url` and `build_date` and is re-verified against `release.json` afterwards.)
3. **Off-machine backup is owed before production.** Until then this machine's disk is the
   only copy, which is an accepted, recorded risk — not an invitation to treat the bytes
   as disposable. `TODO.md`'s icebox holds the open item.

A tracked artifact that turns out to belong to one of these classes is untracked with
`git rm --cached` plus a `.gitignore` line, never with `rm`.
