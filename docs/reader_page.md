# The reader page — layout and interaction contract

> Designated readers: whoever changes what the published page shows — the renderer and
> page schema (`packages/editorial`, `packages/schema/.../models/page.py`), the page
> checks, and the `write` / `render-localize` stages when an output must fit a specific
> module. Everyone else needs only the summary in
> [`value_chain.md`](value_chain.md) "The product". This file is part of the canonical
> spec: it wins over code the same way, and the summary there wins over this file.

## The topic page, top to bottom

One topic = one page. Top to bottom:

0. **No top bar.** The light/dark switch is one floating circular icon in the upper-right;
   original/translation controls stay beside the quote they affect. Scope belongs to the
   timeline and angle navigation belongs to the storyline, so neither consumes a fixed bar.
1. **Intro** — background for a half-informed reader: what happened, what it replaces,
   when it was decided and when it takes effect. One separately anchored fact per claim,
   so past two claims it is set as a visually separated list, in chronological order when
   the claims carry dates. Its reading column is narrower than the page's data modules,
   centred while the prose remains left-aligned. Section-pointer numerals (01 / 02 / 03)
   never appear.
2. **The reporting timeline**, between the briefing and the storyline, because it is the
   overview: one dot per independent report on the day its original or earliest captured
   version ran, each side on its own side of the axis and named beside it, so density and
   lag are visible rather than asserted. It is drawn
   in the reader's browser, because bucket width, tick density, dot size and lane height
   all depend on how wide their window is: the two lanes are always the same height, a
   busy bucket spreads sideways rather than growing upwards, and the picture stays flat so
   the storyline keeps the first screen. Clicking a dot opens our record of that article.
   The module also carries the sampled window and each side's report count in reader words,
   and one click through to **the scope this topic was signed off on** — what we said we
   would and would not collect. All of it computed from the pinned corpus and manifest.
   Browser layout chooses an odd-numbered bucket width (1 / 3 / 5 / 7 / 9 / … days), draws
   dots at a comfortably clickable desktop size with no more than two columns per bucket,
   and may grow the equal-height lanes rather than shrink hit targets. Hover always shades
   the bucket; its date or date range sits in a label gutter above the shaded lanes.
3. **The storyline** — 2–6 angles, in **three tabs by kind: agreement / divergence /
   silence, each showing how many angles it holds**. A kind with none keeps its tab and
   says so: "this topic produced no divergence at all" is often the loudest thing the data
   has to say, and a tab that vanished when empty would hide it. It is labelled
   **Angles** in English / **视角分析** in Chinese and led by the framed open/solid dual-view
   mark; the section sits on a very light accent-tinted surface, so the core editorial
   reading is immediately distinct from the annotation appendix below without introducing
   another page-wide divider. The reader lands on the tab holding the highest-ranked angle.
   Each angle is:
   - a **question** a reader would ask, in a reader's words and prefixed `Q:` — the
     annotation wording, with the qualifiers an annotator needs, is a different sentence
     and stays in the annotation layer,
   - **two answer cards with the relation between them drawn in the middle**, using the
     project's own **meet / part / fade symbols** when both sides answer the same thing,
     answer differently, or one side is near-silent. The same three symbols lead the
     storyline tabs. In each angle, a green solid or subdued amber dotted ring around the relation
     carries the finding's generated statistical strength and threshold tooltip. The
     relation is the finding, so the relation is what is drawn.
   - inside each card, centred, that side's **tag**; its compact **count badge** (`13/17`)
     and evidence control sit together in the upper-right in the same neutral furniture
     style as other compact badges.
     The badge explains the fraction but is not a control. A separate evidence icon in the
     card's upper-right opens one shared two-side modal, initially on the side clicked,
     with one row per counted independent report and the columns report / quoted text /
     original sentence address — so a badge saying `9/17` can show nine,
   - **the writer's two explanations** and nothing else, tight under the cards — one per
     side, or one for both when the angle is genuinely one thought. They complete a
     Q–A–explain sequence: after the card states the modal answer, the prose concisely
     justifies why that side's supporting reports arrived there. Caveats and extra beats
     are numbered footnotes inserted at the point they qualify.
   - the question's whole **data card**, folded, for a reader who wants the numbers.
   A quote's source link opens **our own record of that sentence first** — outlet, date,
   article, reporting cluster, position, when we collected it, what the article is about —
   and offers the publisher's page from there. Every reporting-cluster id on the page is
   itself a way in: a cluster of one opens that article, a cluster of several lists its
   members with the original reporting first, so a reader can see the shape of wire
   syndication rather than be told about it.
   Each side is named by a **short tag** ("中方" / "美方") whose tooltip carries the group's
   full definition; the tag is the only place a side is named, and its wording is fixed at
   scope sign-off. Every statistical judgement is **generated** — the kind, the strength,
   "tied lead", "#3" — and states the rule and the pinned run's thresholds. No writer ever
   hand-writes a hedge about sample size.
   **Everything that is not self-evidently clickable explains itself on hover or tap**, and
   nothing that is (a button, a link) does — because a button already says what it is by
   being one.
4. **Data visuals** where they carry the story, never as decoration. Charts obey the same
   statistical discipline as sentences (§ below).
   Any outlet name anywhere on the page opens **its media card**: country, language, what
   kind of outlet it is and what it covers, plus one sentence from the registry saying what
   the institution is — who runs it, what to discount. A byline a reader cannot place is a
   byline they cannot weigh.
5. **The annotation appendix** — a framed module sharing the Angles section's light
   accent tint, because both are views of the same Q×A data; its collapsed rows and white
   expanded data cards keep it structurally subordinate. Every question in the set appears
   as a collapsed question row so the list is scannable; opening one gives that question's data card: both sides' answer
   distributions drawn as one shared axis of answers (each side's bars growing outward from
   the answer, the way the two cards above sit left and right), plus two panels on demand —
   **every individual report's annotated answer with its anchors**, and **how the statistics
   judged this question**, generated from the finding in words rather than in code names. A
   question the statistics assert nothing about gets no such panel: there is no hypothesis
   to explain. No writing in any of it: it is the record the storyline was chosen *from*, so
   a reader (and the reviewer at touchpoint two) can see what was left out and check that
   the choosing was honest.
6. **The concept cloud**, after the appendix, because it is the one section that asserts nothing: both
   sides' vocabularies side by side, each column ranked by its own share.
7. **Search**, below the concept cloud: one fast local search over the report
   information this page already exposes — headline, outlet, dates, reporting metadata,
   collect-stage concept phrases, questions, answer labels, annotation summaries and
   notes. It is a static, short-debounce index whose results open the existing article
   record and publisher link. **It never indexes article body text**, including body text
   retained in the private corpus; search must not become a second way to ship what the
   page does not display.
8. **Footer** — two panels, and they are not the same panel. **"Method"** is the
   method, in the same words on every page there will ever be: the counting unit, the Q×A
   model, what "supported" means, why silence in the data is not silence in the world.
   **"Page record"** is a pure machine-generated provenance ledger: the topic's
   contributors, then the signed scope, pinned corpus, questions, annotations, category
   map, analysis, the run that wrote the sentences and the page snapshot — each with its
   run identifier, timestamp, producer version, the model that did its judging (nothing
   at all for a deterministic step) and its own output counts. Two steps also name who is
   accountable: the scope signer and who takes touchpoint two, marked as a stand-in when
   a model does either. Artifact fingerprints are not shown: a run id already identifies
   a step, and a hash only earns its row once a reader can re-verify what it names. It
   contains no writer-authored disclosure or caveat.

## Page-wide rules

The storyline always sits on top; the appendix never competes with it. No single render
shows more than half of any one article's sentences — past that budget an anchor is listed
by address, with the publisher's page as the place to read it (non-negotiable 7).

What never appears in the reader's flow: run IDs, threshold names, internal jargon, or 
defensive per-sentence hedging. **Traceability is a click, not a writing style.**

## The homepage participation entrance

The localized homepage has one site-owned participation entrance: a circular ``+``
immediately left of the ``?`` control. It appears on the homepage only. Its modal keeps
two paths distinct: a reader may suggest a topic for this site to consider, with no
promise of adoption, processing or reply; or may give the public toolkit to their own AI
agent and produce a report locally. The separate full-report upload control stays visibly
unavailable until the invitation/upload infrastructure exists. A suggestion never starts
the pipeline, fetches a supplied URL, or invokes a model.
