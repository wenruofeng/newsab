# topics_raised — the per-article agenda index

Write one record per staged article **while its full text is still in context**,
following the line format in `topics_raised.example.jsonl`: 3–6 short extractive
`source_phrase` values (each Ctrl-F-exact in the staged text) with an English `pivot_en`
each. The record is a model-derived agenda index carrying its own provenance. It is
**never evidence** — no claim anchors to one — but it **is** reader-facing: the page
shows an article's phrases as its keywords, so make each `source_phrase` a short
fragment fit to be seen.

## `pivot_en` is a shared vocabulary for the topic, not a per-article summary

Its only consumer is the whole-topic tally `check_topics_raised.py` prints, which the
question designer reads down looking for a topic one side raises and the other never
does — joined by *exact string*. One `layoffs at nickel smelters` used nine times shows
an asymmetry; nine restatements of it are nine rows of 1 and the asymmetry is gone
(measured: `aabb-harbor-bell-2026`, written one-pivot-per-fact, validates and tells the next
stage nothing). Keep specifics in `source_phrase`, where they are evidence; reuse a
pivot the moment its topic recurs.

**Sharded across workers this needs an owner.** Three workers, each perfectly consistent
inside its own shard, produced 165 pivots for 102 articles with only six shared. Give
every worker the same starting vocabulary, or have the integrator merge labels across
shards — touching `pivot_en` only, never the evidence side.

## Extending a corpus that predates `topics_raised`

Write records for the newly staged articles only, scoped with
`--articles <new-staging-file>…`; a full backfill is a deliberate parity pass, not part
of an extension.
