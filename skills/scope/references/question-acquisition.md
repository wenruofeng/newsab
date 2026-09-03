# Bounded reader-question acquisition

Read this only for scope core-loop step 4. The outcome is a small, reviewable candidate
set, not a dossier and not a measurement of public opinion.

## Reconnaissance budget

Use the issue's native names in each comparison side's likely reader/search language.
Cover at least two of these surfaces per language when public results exist:

- search suggestions or "people also ask"-style questions;
- open social, forum or Q&A discussions;
- audience-shaped FAQ/explainer pages whose headings answer recurring questions.

Run at most 12 web queries total, retain at most 8 distinct candidates, and keep at most
two links per candidate. Stop after two consecutive queries add no new semantic question.
Do not log result pages exhaustively, quote usernames, enter private groups, or spend
tokens summarizing discussion. Search rank, likes and reposts are weak discovery signals,
never prevalence estimates.

Use native wording on every side. A zero found with a translated query says nothing about
reader interest. Platform availability will be asymmetric; record an unavailable surface
in one short note rather than compensating with many searches on the reachable side.

## Candidate admission

**Draft each candidate as one question asking one thing.** A candidate that joins two
halves ("…, and how much?", "…, and what happened to them?") survives touchpoint one,
reaches annotate as a seed, and there becomes either a question whose second half nobody
codes or a category vocabulary mixing two axes. Annotate is required to split it, but a
compound candidate makes that a repair rather than a design. Measured,
`aabb-steppe-stone-2025`: five of eight approved seeds were compound, and two of them reached
the reader page still carrying an uncoded half.

Keep a question when it is in scope, a half-informed reader could reasonably care about
the answer, and the two media samples could in principle be asked it. Deduplicate by
meaning. Include useful agent-authored candidates and user-authored questions in the
same list: source must not influence annotate later.

This reconnaissance discovers questions only. Its pages are not evidence, do not enter
the news corpus, and do not contribute terms or outlets to collect's query matrix.

## Scope-only review artifact

Write `topics/<topic_id>/scope/question_candidates.yaml` in this compact shape:

```yaml
candidates:
- candidate_id: SQ-001
  text:
    values:
      en: What would happen to students already enrolled?
      zh-CN: 已经入学的学生会受到什么影响？
  why: Recurs across search questions and one open student forum.
  signals:
  - lang: en
    url: https://example.org/public-page
    wording: What happens to current students?
  review:
    approved: false
    required: false
review_record: null
```

`why` is one sentence; `signals` holds zero to two short public examples. A user-authored
or agent-authored question may have no signals. Never put origin labels or URLs into
`text`; `apply-question-review` copies only `candidate_id`, `text` and the resulting
mandate to the manifest.

Present the list in the user's language with two checkboxes per item:

- **approve** unchecked: rejected; it stays only in this file;
- **approve** checked, **required** unchecked: `reference`; annotate may use or discard it;
- both checked: `required`; annotate must include one semantically equivalent question.

Only a directly participating human may check **required**. Under an explicitly requested
AI stand-in, leave every required box false even when the agent strongly recommends the
question. Run `apply-question-review`; do not hand-copy approved questions into the
manifest.
