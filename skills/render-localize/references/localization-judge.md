# The localization judge rubric (render-localize L2)

Public on purpose, like its sibling `judge.md`: an outside reviewer must be able to
re-run this standard, and whoever localized the page must be able to read what they will
be held to.

**Why this check exists.** The user reviews the page in exactly one language; every
other localization of the same approved bytes ships without a human reading it
(`skills/publish/references/localization.md`). For those languages this judge is the only
gate that reads meaning — the mechanical layer (`page-check --langs`) has already refused
missing translations, so you only look at what code cannot see: whether the target text
*says what the English pivot says*.

The judge runs as its own agent with its own context. Its independence is its **input**,
not its vendor: it may run on the localizer's model, `standard`-class recommended (this is
cross-lingual meaning comparison — a bottom-tier model does it badly), both model ids
recorded. Its entire input is this rubric plus one locale's packet from
`scripts/localization_packet.py` — every English↔target pair the page carries, labelled
by where it lives. It never sees the rendered HTML, the localizer's reasoning, this
repo's docs, or this file's sibling `SKILL.md`.

**One judge per locale, not a panel.** Its sibling L1 spot check runs as three parallel
judges whose findings are unioned, because one pass of *that* rubric was measured to have
low recall. This check is not the same shape and inherits neither the measurement nor the
mechanics: the packet already enumerates every pair to be judged, so
there is no search step to miss things in; there is no fix loop to churn (a trigger is a
refusal, and the fixed text comes back on a fresh packet); and the cost multiplies by the
number of locales, which is the number this gate exists to scale to. Revisit after the
first real added language has run through it — if a member of a trial panel finds pairs a
single pass missed, the merge in `scripts/_judge_panel.py` is axis-generic and the change
is small. Until that is measured, adding judges here would be buying an unpriced thing.

Judge the target text against the English pivot only. You are not re-reviewing the
English page — its own judge (L1) and the user did that. If the English itself seems
wrong, note it in `pivot_concerns`; it does not score the localization down.

Four axes, each scored 0/1/2, naming the packet entry behind every score below 2.

## 1. Meaning fidelity

Does each target text assert what its pivot asserts — the same claim, the same subject,
the same direction, no more and no less?

| score | meaning |
|---|---|
| 2 | every pair says the same thing; recasting is idiomatic, not semantic |
| 1 | a pair drifts in emphasis or hedging without changing what is claimed |
| 0 | a pair changes a claim: subject, direction, certainty, or scope moved |

Watch the pairs where drift is expensive: answer labels (`answer_label`,
`shared_answer_label`), claim texts, and the silence wording — "no cluster was annotated
as answering this" localized as "the coverage contains none" is a 0 (non-negotiable 5),
in any language.

## 2. Quantity and provenance

Numbers, dates, units and named actors survive. Localized notation may change
(`250 juta ton` → `2.5亿吨`) but the quantity must be the same quantity; who said what,
and which side counted what, must not move between sides or from source to page voice.

| score | meaning |
|---|---|
| 2 | every quantity, date and attribution converts correctly |
| 1 | a conversion is awkward or imprecise but not wrong |
| 0 | a quantity, date or attribution is wrong, or moved to the wrong side |

List every conversion you checked in `checked_conversions` — the packet cannot verify
arithmetic, so your list is the audit trail.

## 3. Register and symmetry

The page's stance must survive translation. Re-read the target pairs with the two sides
swapped: does any wording now flatter or diminish one side in a way the pivot does not?
Loaded vocabulary that is neutral in English but evaluative in the target language (or
the reverse) belongs here.

| score | meaning |
|---|---|
| 2 | tone and side-symmetry match the pivot |
| 1 | a wording asymmetry the pivot does not have, without a stated stance |
| 0 | the target text carries an evaluative stance the pivot does not |

## 4. Reader fluency

Each target text must read as concise native news prose answering its slot on the page —
not translationese tracking English syntax (SKILL.md segment 3: preserve Q–A–explain as
reader logic, not English syntax). A literal rendering of English scaffolding
("from this position", "the logic here") is unfinished work.

| score | meaning |
|---|---|
| 2 | reads as written in the target language |
| 1 | understandable but visibly translated; scaffolding survives |
| 0 | garbled, wrong-language fragments, or unreadable in place |

## Output

```json
{"rubric_version": "rl-locjudge-0.1",
 "locale": "<target locale>",
 "scores": {"meaning_fidelity":       {"score": 2, "note": "...", "refs": []},
            "quantity_and_provenance": {"score": 2, "note": "...", "refs": []},
            "register_and_symmetry":   {"score": 1, "note": "...", "refs": ["angle 3 (QST-...) sides[0].answer.text"]},
            "reader_fluency":          {"score": 2, "note": "...", "refs": []}},
 "meaning_changes": [],
 "checked_conversions": ["250 juta ton -> 2.5亿吨 (angle 2 ...)"],
 "pivot_concerns": []}
```

`meaning_changes` lists every pair where the target asserts something the pivot does not
(each entry names the packet label and quotes both sides); it is the blocking list, so an
axis-1 drift you judged tolerable stays out of it and an axis-0 change always appears in
it. `pivot_concerns` is advisory only.

## Blocking triggers (evaluated by `check_localization_judge.py`, never by the judge)

- any score of 0;
- two or more scores of 1;
- any `meaning_changes` entry.

A fired trigger means **this locale does not ship**: fix the localization and run a fresh
judge on a fresh packet. There is no human fallback on this path — the user cannot
read the language, which is why the trigger is a refusal rather than an escalation. Only
a rule conflict (the judge demands what this repo's writing rules forbid) goes to the
user, as a rule question, not a page question.
