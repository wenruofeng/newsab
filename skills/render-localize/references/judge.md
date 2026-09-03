# The spot-check judge rubric (render-localize L1)

Public on purpose: an outside reviewer must be able to re-run this standard, and whoever
wrote the page must be able to read what they will be held to.

The judge runs as its own agent with its own context. What makes it independent is its
**input**, not its vendor: it may run on the writer's model, and a `standard`-class model
is the recommendation (routing responsibility 13) — this is a read of published sentences
against their anchors, which a bottom-tier model does badly. Its entire input is this
rubric plus the ~10 KB judge packet that `scripts/judge_packet.py` derives from the
artifacts — the page's reader-facing text in reading order, every anchored sentence
verbatim, and the pinned findings with each side's counts. It never sees the rendered
HTML (which embeds the whole corpus), the writer's reasoning, this repo's docs, or this
file's sibling `SKILL.md`.

**You are one of several independent reads of the identical packet, and the panel's
findings are unioned, never voted on.** One pass of this rubric has measurably low recall —
later serial passes kept surfacing true defects the first pass had missed — which is why
the reads happen in parallel instead of in rounds. Two consequences for how you
write: report everything you actually see, including what seems too obvious to be worth
saying — a defect only you notice still counts, and one you skip because someone else will
surely catch it is simply lost. And **name where, in the note itself**: every score below
2 must locate its fault on the page (`angle 3`, `intro`, `title`, `lexicon`, or a
`QST-…`/`FND-…` id the packet shows), because the merge is what decides afterwards
whether a fix pass introduced your finding or merely failed to notice it. The note's own
loci are authoritative; `refs` locate the fault only when the note locates nothing *and*
they name exactly one place — a refs list of everything you read under a non-locating
note is treated as unlocated, not as N faults. Keep the note about the faulted locus
only: a locus the note merely praises in passing still parses as that locus. A finding
with no location cannot be classified and has to be triaged by hand.

It is a **spot check**, deliberately lighter than the retired S8 L1: the mechanical layer
(`page-check`) has already refused everything recomputable, so the judge only looks at what
code cannot see. Five axes, each scored 0/1/2, naming the angle or claim behind every score
below 2.

## 1. Evidence entailment

Does the anchored sentence actually support the sentence we published?

| score | meaning |
|---|---|
| 2 | every anchor supports its claim; nothing is stretched |
| 1 | an anchor is topically related but does not carry the specific assertion |
| 0 | an anchor contradicts the claim, or is about something else |

A `source_claim` must be supported by its own anchor alone. A `corpus_aggregate`'s anchors
are illustrations — judge whether they illustrate the stated direction, not the magnitude
(the magnitude is `page-check`'s job). A `corpus_reading` must hold *as a
characterisation*: would a reader who read only the anchors arrive at this reading? Anchors
from one side only is a 1 at best.

## 2. Symmetry under label swap

Re-read the page with the two sides' labels exchanged. Would any sentence now read as
unfair, or as praise, that did not before?

| score | meaning |
|---|---|
| 2 | the page reads identically under swap |
| 1 | wording asymmetry (one side "acknowledges", the other "claims") without a stated basis |
| 0 | the page carries an evaluative stance toward one side |

Report the exact phrase, not a judgement of intent.

## 3. Silence and strength

- Is every silence presented as the *kind* of silence it is: "no cluster was annotated as
  answering this" versus "the coverage contains none"? Presenting the first as the second
  is a 0 (non-negotiable 5).
- Does a `weak` finding's angle read as weak? **The weak label is not the writer's job and
  its absence from the prose is never a deduction.** The renderer prints a `weak` badge on
  the card itself, in the same words on every page, with the pinned thresholds behind it;
  the packet tells you which cards carry it. A writer who also hedges in the sentence ships
  the same caveat twice, which reads as an apology — do not ask for that, and do not score
  it down for missing. What *is* scored here is **overstatement**: prose on a `weak` card
  that asserts a certainty, a direction or a magnitude the finding does not carry — a bare
  point estimate, "shows that", "because", a comparative stated as settled. An angle whose
  sentences stay inside what the finding supports scores 2 with no hedge in sight.
- Do adjacent sentences or a visual let a reader draw a contrast no finding asserts?
  Insinuation is scored as assertion.

## 4. Scope discipline

Every reader-facing claim's subject is the sampled coverage of one side. A country, a
government, a people, or "the media" as the subject of a comparative claim is a 0 — no
matter how obviously true the sentence seems. Interval language must describe robustness of
*this sample*, never inference about a population.

Note the direction this axis does **not** run: repeating "in the sampled X-language
coverage" in every sentence is not a higher score. Scope lives in what the claim asserts,
not in its cadence.

## 5. Overall impression (the reviewer's question, pre-answered)

Reading only the overview layer — what a reader sees before clicking anything — what
impression does the page leave? Write it in two sentences, then say whether the artifacts
support it. A page where every sentence is true and the overview layer is collectively
misleading is the most expensive defect this format has, and the one no script can see.

Read each angle in rendered order: question → answer cards → relation → explanation pair.
The prose must justify why the counted reports reached the answers already on the cards;
card restatement, mirrored filler, abstract viewpoint language, or one substantive column
beside one empty column lowers this axis. Judge the sequence, not the paragraphs in
isolation.

## Output

```json
{"rubric_version": "rl-judge-0.4",
 "scores": {"evidence_entailment":  {"score": 2, "note": "...", "refs": []},
            "symmetry":             {"score": 2, "note": "...", "refs": []},
            "silence_and_strength": {"score": 1, "note": "...", "refs": ["angle 3"]},
            "scope_discipline":     {"score": 2, "note": "...", "refs": []},
            "overall_impression":   {"score": 2, "note": "two sentences, then whether the artifacts support it"}},
 "unverified_readings": [],
 "contradicted_notes": []}
```

## Escalation triggers (evaluated by `check_judge.py` on the merged panel, never by a judge)

The panel merges first: each axis takes the **worst** score any member gave it, and
`unverified_readings` / `contradicted_notes` are unioned across members. Then, on that
merged record:

- any score of 0;
- two or more scores of 1;
- a `corpus_reading` claim any member could not verify from its anchors;
- an appendix note any member believes contradicts the page's own claims.

A fired trigger means **one fix pass on exactly what fired**, then a confirmation panel.
It reaches a human when the fix cannot be made inside this stage's rules — a finding, a
count or an annotation would have to move (upstream's call); the rubric asks for something
this repo's writing rules forbid (a rule conflict — name the rule and the rubric line); or
the confirmation panel finds a **new** fault on text the fix pass rewrote, which is the fix
making the page worse. Whatever the route, the human sees it **before** the localized
preview goes to the user: touchpoint two is for reading a finished page, not for
catching defects.

A new fault on text the fix pass did *not* touch is not that. It is this rubric's known
recall variance — the panel still finding what was always there — and it is verified and
fixed like any other finding, never used as a reason to stop.
