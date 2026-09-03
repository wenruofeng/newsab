# Extending, repairing and withdrawing — append-only mechanics

Read this for any run against a corpus that already exists (and especially one that has
already been annotated). The governing fact: articles already in the store keep their
bytes, so their sentence anchors — and every observation written against them — survive
untouched. Everything below is about not breaking that promise.

## 1. Extending is a normal collect run

Same loop, same logging, same checks; the only differences:

- **Filenames and records are append-only.** New staging files take new serials; an
  existing article's YAML is never edited to "improve" it. Corrections to the collection
  log are new lines carrying `corrects`, never edits of an existing line.
- **`build` prints exactly which articles are new** and therefore need annotating — hand
  that list to annotate's incremental mode; nothing else needs re-annotating.
- **Adding a source mid-extension carries the same grid-backfill duty** as mid-run
  (`references/search-strategy.md` §4), and once a build exists, adding any article
  changes the cluster denominator: rebuild, and every previously computed prevalence is
  void until re-analyzed.
- **The previous round's `backfill_debt` rolls forward on its own.** The build
  copies every unclosed debt onto the new run; close one with `--close-debt` only when its
  cells were actually searched this round (the query lines are the evidence), count a
  failed targeted retry with `--retry-debt`, and mark a miss no retry can change with
  `--futile-debt`. Not restating a debt does not shed it — that silence is exactly what
  made the Indonesia case expensive (`references/search-strategy.md` §1).

## 2. Read the build's store line — it is the whole safety story

The build measures drift against the corpus run the topic's *active answers* were written
on, and reports three different events that must not be conflated:

- **`revised`** — the record changed while its sentence set did not (a splitter bump, an
  `origin` relabel). No annotation needs redoing.
- **`superseded`** — the text moved. The build prints the exact sentence IDs removed,
  added, or — the dangerous list — **kept their address while their text changed**. Such
  an anchor still resolves, every downstream check passes, and the answer citing it now
  quotes a different sentence; this printout is the only warning anyone gets, and
  downstream refuses these as `retexted_anchor` only if you carry the information forward.
- **New articles** — the annotate handoff list (§1).

Never skim past this line; quote it in the run report.

## 3. Withdrawing

    python -m newsab_corpus withdraw <topics_root> <topic_id> <article_id> --reason "…"

Never `rm`: deleting store files makes every earlier run unrestorable. Withdrawal
excludes the article from *future* runs with its reason on record; historical runs still
resolve. After a withdrawal, the denominator changed — rebuild and re-analyze before any
downstream artifact is trusted again.
