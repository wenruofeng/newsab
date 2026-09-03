# `topics/` — one directory per topic, and the artifact contract

The stages are the value chain's ([`docs/value_chain.md`](../docs/value_chain.md)). Every
stage reads and writes through `newsab_schema.paths.TopicPaths`, so this table is the
only place the layout is described in prose — if you need a path, ask `TopicPaths` for it
rather than joining strings.

```
topics/<topic_id>/
  topic_manifest.yaml        scope output; what touchpoint one signs
                             (scope + risk, never a conclusion); pins cluster_threshold
  scope/
    collection_plan.md       the collection plan touchpoint one signed off with
  corpus/
    staging/*.yaml           staged article records, one per fetched article
                                                                       [PRIVATE, gitignored]
    articles/<ID>.json       THE append-only article store: everything ever ingested for
                             this topic, keyed by content-addressed article_id
                                                                       [PRIVATE, gitignored]
    articles/_superseded/    prior bytes of any re-collected article, so older runs stay
                             restorable                                [PRIVATE, gitignored]
    withdrawn.jsonl          articles held in the store but excluded from new runs, + why
    versions/<s2s_run_id>/
      corpus_run.json        THE set snapshot: which members this run saw, each one's
                             content hash, the cluster assignment, set_hash, build report
      index.jsonl            public-safe article index (no body text)
    collection_log.jsonl     every query with results_staged, failures, corrections, notes
    topics_raised.jsonl      per-article extractive topic phrases + English pivots;
                             derived, model-attributed, never evidence or reader output
  questions/versions/<qst_run_id>/questions.yaml
                             annotate: the question set
  answers/versions/<ans_run_id>/answers.jsonl
                             annotate: every question × every cluster, English pivot,
                             source-language sentence anchors
  normalization/versions/<nrm_run_id>/category_map.json
                             normalize: the frozen merge-only category map
  analysis/qa-<run_id>/      analyze (`python -m newsab_a1 qa`): question_stats.json,
                             findings.jsonl, run.json
  editorial/
    page.json                write's working draft; the reader lexicon inherits here
    versions/<edt_run_id>/   write: page.json (ranked findings → reader page)
    versions/<rl_run_id>/    render-localize: page.json, judge panel records, and
                             preview.<locale>.html — intermediate, never the review
                             surface                       [previews on disk, gitignored]
  manifest/manifest.jsonl    one entry per stage run
  manifest/corrections.jsonl immutable correction links
  manifest/active.json       mutable run selector; never the sole copy of an artifact
```

Topics created before the 2026-08 value-chain redirect may also carry the retired
S0–S8 layout (`observations/`, `ontology/`, `angles/`, `cards/`, `dossier/`, `qa/`,
`gold/`, `hypotheses.jsonl`). `TopicPaths` keeps accessors for reading them and
`gold/worksheet.json` stays private where it exists, but `init-topic` no longer
scaffolds any of it — a new topic gets only the directories above.

The cross-topic source registry lives *outside* this tree, at `sources/registry.yaml`
(R-3): what an outlet is and how to search it outlive any one topic, and which sources a
version actually covered is derived from its corpus run rather than approved in advance.
Query it with `python -m newsab_corpus registry find …` rather than reading it whole.

## What may be published

`topics/.gitignore` keeps `corpus/articles/`, `corpus/staging/`, and the full-text gold
worksheet out of git. That is not a convenience — D14 and §1.3(2) forbid republishing
scraped text, and a submission package is built from everything except those paths.
`TopicPaths.is_private()` is the programmatic form of the same rule, including versioned
article directories; use it in any
packaging code rather than re-listing paths.

The exact write/commit/correction protocol is
[`docs/artifact_versioning.md`](../docs/artifact_versioning.md). What is immutable is **the
content set a run referenced**, not the state of a directory: the article store only grows,
and each run pins which members it saw and what each contained.

## Naming a topic

`topic_id` is `<sides>-<subject>-<year>`, and the schema only enforces that it is a
lower-case hyphen slug — the meaning of the first segment is this convention, not a
validator:

- **`<sides>`** is the two compared groups' abbreviations *concatenated*, in the order
  the manifest lists them: `cnjp` (China ↔ Japan), `jpkr`, `detr`, `inpk`, `mnfr`.
  Each side is normally its ISO 3166-1 alpha-2 country code; `intl` stands in for a side
  that is not one country, so Chinese outlets against the international press is
  `cnintl-…`. It is not a country claim — it names the two *media groups* the manifest
  defines, which is why it is written from the groups and not from where an event
  happened.
- **`<subject>`** is one or two words a human recognizes: `visa`, `tourism`, `nickel`,
  `bronzes`.
- **`<year>`** is the year of the events compared, not the year of the run: a comparison
  written this year of how each side told a 1415 story ends in `-1415`.

**`aabb` is reserved for test fixtures** — it is literally "side A + side B" and appears
throughout `packages/*/tests` and this repo's synthetic topics. A real topic never uses
it: a slug starting `aabb` in a production tree means someone copied a fixture id instead
of naming the two sides (it has happened — a submission arrived as
`aabb-steel-share-2025` where `jpus-steel-2025` was meant, and the id is pinned into the
run closure by then, so it cannot be renamed afterwards).

## Creating a topic

```sh
python -m newsab_schema init-topic topics <topic_id>       # directory skeleton
$EDITOR topics/<topic_id>/topic_manifest.yaml              # scope, then touchpoint one
# drop staged articles into corpus/staging/, then:
python -m newsab_corpus build topics <topic_id>
```

`build` is reproducible: same URL, same `article_id`, same sentence IDs, whatever else is in
the corpus and whenever it was ingested. `article_id` is `{GROUP}_{sha256(canonical_url)[:8]}`
(R-1), so adding or removing a staged file no longer renumbers anything — staging filenames
are now just human-readable ordering.

Extending an already-annotated corpus, withdrawing an article, and the exact
commit/correction sequence are all the write protocol's territory —
[`docs/artifact_versioning.md`](../docs/artifact_versioning.md) §1.2/§2/§5. The one rule
worth repeating here: **never `rm` an article file** — withdraw it, so earlier runs stay
restorable.
