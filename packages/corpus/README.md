# newsab-corpus

Deterministic corpus construction for Phase 0: hand-staged articles in, `Article` records
with permanent sentence IDs and independent reporting clusters out. No model calls
anywhere — this is all work D10 reserves for plain code, because a reader who disputes a
number has to be able to re-run it.

Collection criteria live in the skills (`skills/scope`, `skills/collect`). Write protocol:
[`docs/artifact_versioning.md`](../../docs/artifact_versioning.md).

## Use

```sh
python -m newsab_corpus build   topics aabb-river-light-2026     # staging -> corpus
python -m newsab_corpus stats   topics aabb-river-light-2026     # dual-unit statistics
python -m newsab_corpus similar topics aabb-river-light-2026     # tune the cluster threshold
python -m newsab_corpus segment article.txt --lang zh-CN  # eyeball sentence boundaries
python -m newsab_corpus fetch --show-identity              # verify the collector identity
python -m newsab_corpus fetch <url> --out corpus/raw       # honest HTTP + browser fallback
```

In a public clone, collection stays offline until the user's agent writes a truthful
operator URL and contact email to `.newsab/operator_identity.json`; see `AGENTS.md` and
`skills/collect/references/fetch-extract.md`.

`build` exits `1` when the corpus has a problem that changes the cluster count — currently
one case: two articles in the same text cluster both declared `origin: original`. That
number is the denominator of every prevalence claim on the site (D7), so it is not
something to warn about and carry on from.

## What is deliberately not here

- **No bulk crawler.** The fetch command retrieves URLs chosen by the collect agent under
  the two-layer access policy; `staging/*.yaml` remains the corpus builder's input.
- **No cross-language clustering.** Character shingles do not survive translation; the
  same wire story in Chinese and English will be two clusters. S2 owns that.
- **No origin *inference*.** Origin is declared in staging and cross-checked here. The
  check can prove a declaration inconsistent; it does not invent one.

## Modules

| module | what it owns |
|---|---|
| `segment.py` | `SPLITTER_VERSION`, paragraph/sentence rules for zh + ja + ko + en, conservative fallback |
| `staging.py` | the hand-filled YAML format, article ID assignment, `Article` construction |
| `cluster.py` | shingles, containment similarity, union-find, origin cross-check |

Clustering is character 5-gram shingles + **containment** similarity
(`|A∩B| / min(|A|,|B|)`), single-link within a group, per-topic threshold from
`topic_manifest.cluster_threshold`. Containment rather than Jaccard because the dominant
case is "full wire copy + three locally added paragraphs" — Jaccard reads the extra local
text as dissimilarity and splits an obvious syndication. Thresholds are provisional;
`python -m newsab_corpus similar` shows the pair distances when tuning one.
| `index.py` | public-safe `index.jsonl`, dual-unit stats, category/language composition and silence detection |
| `build_diagnostics.py` | report-only staged-body sentence checks against retained raw visible text |
| `collection_log.py` | query/failure log + `variant_coverage()` for the search-term matrix |

## The one thing that will bite you

Sentence IDs contain the article ID, which is **content-addressed** from the canonical
URL (R-1) — staging filenames are human-readable ordering only, and adding or removing
one renumbers nothing. What still bites is `SPLITTER_VERSION`: bumping it re-splits the
corpus, so it is an expensive, deliberate act. Once `observations.jsonl` exists, the build
command enforces that freeze and refuses changed content, membership, cluster assignment,
staging bytes or source-snapshot bytes. An identical post-S4 build is a no-op so it cannot
rewrite provenance. Before S4 it prunes stale derived article JSON so `load_articles()` and
`index.jsonl` cannot silently see different corpora.
