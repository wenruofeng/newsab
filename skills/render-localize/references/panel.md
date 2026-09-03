# The judge panel protocol (segment 2)

**Read this if you are running the stage.** It is *not* judge input: a judge's entire
input is `judge.md` plus its packet, and nothing here — orchestration, budgets, what the
fix pass may touch — belongs in a judge's context.

## Why a panel and not rounds

One pass of the L1 rubric has low recall. On a measured topic, five serial rounds burned
96 minutes of wall clock, and on inspection the later rounds were reporting *true* defects
in paragraphs nobody had edited: the rounds were buying recall, not convergence. N reads of
the identical packet buy that recall in one round's wall clock, so the reads run in
parallel and their findings are unioned.

**Dispatch the members together, in one go.** Spawning them one after another re-buys the
wall clock the panel exists to save.

## Composition

- **Discovery panel: three judges.** Confirmation panel: at least two. `check_judge.py`
  refuses a smaller panel; `--panel-min` is the deliberate-deviation exit, and a deviation
  is named with its reason in the run report.
- Each member is its own agent whose **entire input** is `references/judge.md` plus the
  ~10 KB packet — never the writer's reasoning, never `SKILL.md`, never this file. That
  input isolation, not the vendor, is the independence.
- Routing responsibility 13 governs every member alike: `standard`-class recommended, the
  writer's own model allowed, every model id recorded. A panel where all members share one
  model buys recall across independent reads, not across vendors; the script says so.
- Members' outputs are saved in the run directory as `judge.<round>.<member>.json`, and
  each round's merged record as `judge.panel.<round>.json`.

## Merge semantics

`check_judge.py` merges before it judges: each axis takes the **worst** score any member
gave it, and the blocking lists are unioned with duplicates collapsed. **No vote.** A
defect one member saw and two missed is still a defect — filtering by agreement would give
back exactly the recall the panel was bought for. Agreement counts (`k/N`) are printed to
order the fixer's work, never to drop a finding.

Every score below 2 and every blocking-list entry becomes a finding keyed by
`(axis-or-list, page locus)`. A locus needs a defect statement behind it: the loci the
member's **note** names win; a note that locates nothing takes its locus from `refs` only
when they name exactly **one** — a list of refs under a non-locating note is a reading
list, and parsing loci out of one once manufactured a churn hard stop on an angle no
member had faulted (measured on a real run). A finding left with no locus is reported as
`unlocated`: it cannot be classified against the fix pass, so it is triaged by hand and
the conclusion goes in the run report.

Exit codes: **0** clean · **1** escalates, run one fix pass · **2** an input is unusable
(re-run *that* judge — never hand-fix a judge's JSON) · **3** stop, a human rules.

A lone member's score of 1 on one axis is recorded but does not escalate — measured score
variance (a fourth round once re-scored byte-identical text from 2 to 1).  Two or more
members scoring the **same axis** 1 is not variance and escalates (`judge_consensus_one`,
panel 0.2): a measured run shipped a 2-of-3 entailment fault through the old gap, which
fired only on two *axes* at 1 or one at 0.  Agreement raises severity; it still never
drops a finding.

## The fix pass

One pass, on the union and nothing else. It is **incremental, not a rewrite**: hand the
writer the current `page.json` and the escalation list only — one line per fired trigger,
quoting the note and the locus it names — and run write's `fix-page` mode, which changes
what an escalation names and nothing else. Rewriting a section no judge faulted is how the
confirmation panel gets a new defect to report.

Two escalation kinds are not fixed in this stage at all, and both go to a human: one that
can only be answered by changing a finding, a count or an annotation (upstream's call), and
one whose remedy this repo's writing rules forbid (a rule conflict — record which rule and
which rubric line).

## Churn: new defects on rewritten text, and nothing else

The confirmation panel judges a **fresh packet** built from the fixed page. A panel record
hashes every page locus (title, intro, hook, lexicon, visuals, appendix, one per angle),
and the hash covers the whole subtree — a swapped anchor or category rewrote that locus as
surely as a reworded sentence. `--previous` therefore lets the script diff which loci the
fix pass actually rewrote, and label every finding:

| label | what it is | what you do |
|---|---|---|
| `churn` | a **new** fault on a locus the fix pass rewrote | exit 3 — stop, a human rules |
| `persistent` | the same axis faulting the same locus as last round | the fix did not land: fix it, or refuse it with a reason. Not churn, even at a worse score |
| `recall` | a new fault on a locus nobody touched | verify it against the packet and fix it — this is **not** churn |
| `unlocated` | the member named no locus | triage by hand; answer it in the run report |

The condition this replaces ("a round reports more new defects than the last, in sections
that previously passed") pointed both ways across two measured runs: it would have
discarded one run's late findings on untouched text, which were true on inspection, and it
did not cover another run's fourth round, which re-scored byte-identical text from 2 to 1 —
score variance, correctly not acted on. So: a `recall` finding on byte-identical text that
the packet does not actually support is that same score variance — record it with the
panel's agreement count and do not rewrite for it.

## Budget

**Three panels, hard, and the script enforces it**: discovery, confirmation, and — only when
the confirmation panel's findings were all on untouched text and got their own fix — a last
confirmation. An escalation on the third exits 3, and a human rules with every panel record
in front of them.

Any semantic text change after a panel requires the next panel; there is no "the edit only
narrowed the claim" exemption.

## Does L2 work this way?

No, and deliberately: the localization judge stays one judge per locale. The reasoning, and
what would change it, is in `localization-judge.md`.
