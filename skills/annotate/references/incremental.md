# Incremental annotation — new clusters, new questions, same guarantees

Read this only when the topic already has an active answers run. Incremental is the
normal case, not an exception: a collect extension or a mid-run question addition never
triggers a full re-annotation.

## The shape of every incremental pass

1. **Dump what stands.** `dump-answers` re-emits the active run as batch lines;
   `dump-questions` does the same for the question set. The dump carries each legacy
   record's own `model_id` and `summary_lang`.
2. **Cover only what is new.**
   - *New articles*: answer **all** active questions for the new or changed clusters
     only (the collect build printed exactly which those are).
   - *New questions*: mint a new questions run carrying every old question plus the new
     ones, then answer **only** the new questions across **all** clusters.
3. **Assemble a complete run** from old + new batches — coverage is every active
   question × every cluster of the active corpus run, exactly once, and the assembler
   rejects holes.

A *new-questions* shard checks itself with `--scope-questions QST-…,QST-…` alongside
`--scope-clusters`. Coverage otherwise measures the shard against every active question,
so the carried ones read as holes, the check can never exit 0, and each worker ends up
inventing its own way of reading past the noise. The integrator still runs the unscoped
check over old + new together before assembling — that is the one that must be clean.

## What must survive the pass untouched

- **Provenance is never laundered.** The assembler keeps each carried answer attributed
  to the model that actually wrote it; only genuinely new answers get this run's
  `model_id`. (Before this rule, two or three reruns left the whole topic claiming
  whichever model touched it last.)
- **Old text is never silently relabelled.** An extension adds records; it does not
  "improve" carried summaries or categories. A category that needs merging is the
  normalize stage's decision, on the record.
- **A `retexted_anchor` is refused**, by `check` and `assemble` both: an anchor a corpus
  rebuild rewrote in place still resolves, so this refusal is the only thing standing
  between the reader and a quote that changed under its citation. The collect build's
  store line lists these IDs — bring that list with you.

## Splitting and finalizing

Sharding follows the entry's "Sharding to subagents" contract unchanged — the carried
lines are never sharded: the integrator dumps them itself and concatenates. When
finalizing, cite the **current active** corpus and questions runs as `--input-run`
(matching every prior answers run); the collect build's report already records what the
extension added.
