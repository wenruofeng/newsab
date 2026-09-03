# Building a topic's question set

## Template tier — instantiate all six, worded for the topic

The template keys (`packages/schema/dist/enums.md`, `template_question_key`) are the
comparative-journalism standards asked of every topic. Instantiate each one **as a
question a reader of this topic would actually ask** — the key fixes the comparison,
the wording carries the topic:

| key | generic form | e.g. for aabb-river-light-2026 |
|---|---|---|
| `problem_definition` | What is the problem here? | What problem does the new visa rule respond to — and is the rule itself the problem? |
| `responsibility` | Who or what is blamed (or credited)? | Who is held responsible for the disruption to students? |
| `consequences` | What consequences are foreseen, for whom? | What will happen to students, universities, the US economy? |
| `proposed_response` | What should be done? | What are students/universities/governments advised or demanded to do? |
| `quoted_voices` | Who gets quoted? | Which voices (officials, students, experts…) speak in the coverage? |
| `loaded_language` | What language is loaded? | What charged terms frame the rule ("crackdown", "national security", "人才流失")? |

They are coding targets and search aids. A question the corpus does not answer simply
collects `addressed: false` records — it never manufactures answers.

## Reader tier — usually 6–9 questions, keeping the full set near 12–15

Read the whole corpus's bounded digest before drafting:

```sh
python skills/annotate/scripts/corpus_digest.py <topics_root> <topic_id>
```

The digest replaces skimming headlines plus one article. Use `topic_manifest.include`
and the collection plan as scope context. Read only the approved question texts and
mandates from `topic_manifest.question_seeds`; never the scope-only
`scope/question_candidates.yaml`, whose audience/agent/user origins must not bias this
semantic pass (pre-0.6 `seed_questions`: treat every one as `reference`).

A `reference` seed is framing input, not a draft: keep, rewrite, split or discard it on
the same semantic criteria as a question you discovered yourself. A `required` seed is
the one exception: include exactly one meaning-equivalent question (a template-tier
question that asks the same thing satisfies it), declare
`"covers_required_seeds": ["SQ-001"]` on that batch row — `qa_batch.py check-questions`
requires every human-required seed covered exactly once and deliberately drops the
mapping when it assembles `QuestionSet` — and write the `rationale` from reader value and
corpus semantics, never "the user required this". The script refuses a rationale or
category guidance that names the user, a mandate or a seed id (a run leaked six).

Then follow hypotheses with the audited probe
(`python skills/annotate/scripts/corpus_probe.py --help`); the script enforces the budget
(at most 10 searches, 5 full-cluster reads per corpus run) and refuses a search without
one native term per side (`--term <group>=<native wording>`) — a Chinese term plus a
literal translation can create a clean-looking 0-versus-N artifact that says only that
the query was wrong. Stop probing after two consecutive searches yield no new candidate
question, and record that judgement beside the mechanical log in the run report.

**One question asks one thing.** A question with two halves — "…, and how much?", "…,
and what happened to them?" — is the most common way a question set goes wrong, and it
fails in two directions at once: either only one half is ever coded and the other reaches
the reader as a question the page visibly never answers, or both halves are coded into
**one** category vocabulary that mixes two axes and the counts stop meaning anything
(`herders_and_local_residents` beside `criminal_case_reported` answers "who" and "what
happened" in the same column). Measured, `aabb-steppe-stone-2025`: five of fourteen questions
shipped compound; on one, every category was a date, the "and how much?" half was never
coded, and the user met it at touchpoint two as a question with half an answer.

Write the second half as its own question or drop it. **A `required` seed does not
override this**: the mandate is one *semantically equivalent* question, and a seed asking
two things is satisfied by the half that carries its meaning — splitting or narrowing a
compound seed is the annotator's job, not a liberty. Likewise a template instantiation:
sharpen it to one axis rather than bolting a clause on.

Good reader-tier questions:

- can be **put to** both sides, without assuming both will answer ("Which number does the
  coverage give for the 2026 RKAB quota?" works; "How does detik cover Tsingshan?" does
  not). One side having no answer is a possible finding, not a reason to reject the
  question;
- have **countable** answers (an actor, a number, a yes/no/conditional, a named cause);
- would change what a half-informed reader believes ("Is the rule about all foreign
  students or Chinese students specifically?");
- are *not* re-wordings of a template question. If the interesting part is "who is
  blamed", sharpen the template instantiation instead of duplicating it.

Actively look for asymmetric agendas: compare the two sides' digest topics and the English
pivots in `corpus/topics_raised.jsonl` (`check_topics_raised.py` prints the per-side tally).
When a topic recurs on one side and never appears on the other, turn it into one question
asked of **both** sides. That is how annotation can distinguish an attention gap from a
question nobody thought to ask. Absence discovered through a one-sided term probe is not
eligible.

**Read that tally as rates, and treat every asymmetric row as a hypothesis, not a finding.**
Two independent design passes were nearly misled by it in the same week:

- **Normalize by each side's denominator first.** The sides routinely differ two- or
  fourfold in cluster count, so raw counts invert. `1 cn / 5 us` on a 12-vs-42 corpus is 8%
  vs 12% — no gap at all; `4 cn / 1 ea` on an 11-vs-6 corpus is 36% vs 17%, and the row that
  looked one-sided the other way is the real one. Compute both rates before you believe a
  row.
- **A zero is a recall failure until a probe says otherwise.** The index is one pass of
  model-written labels, so a side can raise a topic under wording no worker happened to
  tag. Measured: a `0 cn / 7 us` row on PhD disruption survived normalization and still
  reversed under a two-sided probe — 博士 appears in 5 of 12 cn clusters (42%) against
  `doctoral` in 10 of 42 us (24%), so the *quiet* side was in fact the louder one. A
  question built on that row would have manufactured the attention gap it claimed to find.

So the tally's job is to nominate candidates; the audited two-sided probe decides. A row
you cannot confirm with side-native terms does not become a question.

Do not maximize the question count: analyze makes no multiple-comparisons correction, so
every added question is another chance for noise to clear the probability gates — twenty
questions roughly double ten's exposure. All six template questions plus a whole set
around 12–15 is the practical balance; the writer's 3–6-angle selection is the remaining
guardrail. A required seed is never dropped to hit that range (reduce optional
reader-tier questions instead); required status changes annotation coverage only —
analyze applies the same thresholds to an ordinary question.

Questions may be added mid-run when analysis or annotation reveals a pattern worth
asking about (incremental is the normal case, non-negotiable 9): mint a **new
questions run** carrying every old question plus the new ones (`dump-questions` gives
you the old set as a batch), then answer only the new questions across all clusters.

## `category_guidance` — write it at question time

For each question, say how answers should be bucketed, in one or two lines. The
categories themselves are emergent (a genuinely new answer mints a new category), but
the *scheme* must be decided before annotation starts, or each side drifts into its
own vocabulary and the counts stop joining. Rules:

- categories are snake_case English, entity-level, side-neutral
  (`us_government`, not `the_americans`; `quota_cut_to_200mt`, not `the_new_policy`);
- same referent ⇒ same category across sides and transliterations — 范塔·欧 and
  范塔·阿夫 and "Fanta Aw" are ONE entity (see `answer-rubric.md`);
- `unclear` is reserved: addressed but genuinely unbucketable. Use sparingly; two
  `unclear`s never count as agreement;
- for `quoted_voices`, the categories are the `speaker_category` vocabulary
  (`government_official`, `expert_academic`, …) — reuse it, do not invent a parallel
  one. Name the specific speakers in the summary and notes.

## Freezing the set

Draft the questions as a batch file (`python skills/annotate/scripts/qa_batch.py --help`
shows the line format), English pivot wording canonical plus each side's language for
annotator use, `category_guidance` written now. Reassert `covers_required_seeds` when an
incremental questions run carries an earlier required question; the marker is intentionally
not recoverable from `dump-questions`, so review the manifest before checking the new batch.
Then, from repo root:

```sh
python skills/annotate/scripts/qa_batch.py check-questions <topics_root> <topic_id> qbatch.jsonl
run_id=$(python -m newsab_schema mint-run-id qst)   # never hand-type the stamp
python -m newsab_schema prepare-run <topics_root> <topic_id> questions <run_id>
python skills/annotate/scripts/qa_batch.py assemble-questions <topics_root> <topic_id> qbatch.jsonl \
    --run-id <run_id> --model-id <model>
python -m newsab_schema finalize-run <topics_root> <topic_id> --run-id <run_id> \
    --activate questions --skill-id annotate --skill-version <SKILL.md frontmatter version> \
    --model-id <model> --status completed --input-run <corpus run id> \
    --output <run file> --counters-json '{"questions": N}'
```
