# The Value Chain — canonical spec

## Mission

Show a reader what they cannot find out on their own: how two groups of media — usually
two countries reporting in their own languages — tell the same story differently. What
both cover, where their answers diverge, and what one side never says. Every statement
on a published page traces back to verbatim source sentences the reader can check.

Topics will be diverse: breaking policy news (US student-visa rules), industry disputes
(China–Indonesia nickel), but also historical/cultural narrative gaps (the giraffe that
became the qilin; Zheng He "descendants" in East Africa). The engine is a **narrative
diff**: collect both sides, sentence-ize, design the same questions of interests, ask both,
count the answers, tell the difference. 

## The product: what a reader sees

The localized homepage has one site-owned participation entrance: a circular ``+``
immediately left of the ``?`` control. It appears on the homepage only. Its modal keeps
two paths distinct: a reader may suggest a topic for this site to consider, with no
promise of adoption, processing or reply; or may give the public toolkit to their own AI
agent and produce a report locally. The separate full-report upload control stays visibly
unavailable until the invitation/upload infrastructure exists. A suggestion never starts
the pipeline, fetches a supplied URL, or invokes a model.

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

The storyline always sits on top; the appendix never competes with it. No single render
shows more than half of any one article's sentences — past that budget an anchor is listed
by address, with the publisher's page as the place to read it (non-negotiable 7).

What never appears in the reader's flow: run IDs, threshold names, internal jargon, or 
defensive per-sentence hedging. **Traceability is a click, not a writing style.** 

## The Q×A model (the semantic core)

The unit of comparison is a **question × answer** pair, not a topic mention.

- **Question set** per topic, two tiers:
  - *Template tier* — comparative-journalism standards, asked of every topic: what is
    the problem, who is blamed, what consequences are foreseen, what should be done,
    who gets quoted, what language is loaded.
  - *Reader tier* — topic-specific questions an interested reader would actually ask,
    generated by the agent from the scope brief and the corpus itself.
  Before collection, scope runs a small public-web reconnaissance in the relevant reader
  languages and puts those candidates, agent-authored candidates and user-authored
  candidates into one compact review list. Touchpoint one approves each candidate as
  either **reference** (annotate may keep or discard it) or **required** (annotate must ask
  one semantically equivalent question). Unapproved candidates never enter annotate's
  context. Only a human may mark a seed required; an explicitly requested AI stand-in may
  approve reference seeds only. Discovery origin never travels with an approved seed.
  Required means *must be annotated*, not *must become an angle*: the mandate is removed
  from the versioned question set before analyze. The writer does not inspect seed
  mandates while selecting angles, so neither statistics nor editorial selection gives
  it any preference.
  Questions can be added mid-run (analysis discovers a pattern → new question →
  incremental re-annotation). The set is an artifact (`questions`), versioned like
  everything else.
- **Annotation** per reporting cluster per question: `addressed?` (yes/no), and if yes an
  **answer**: a short English-pivot summary, a normalized answer category (so answers are
  countable across clusters), and source-language anchoring sentence IDs.
- **Findings** then come in the three shapes a reader actually cares about (each finding
  is one concrete assertion):
  - **Consensus** — both sides address the question *and* their most common answer is
    the same one.
  - **Divergence** — both sides address it, their most common answers differ. This is
    the headline case: not "how often blame is assigned" but *who gets blamed*.
  - **Attention gap** — one side barely takes the question up (addressed rate below the
    near-silence threshold) while the other side addresses it substantially more
    (qa-0.4.0, user decision). The blindspot-like reading: a mere rate difference
    between two sides that both plainly speak is *not* a finding. First-class (it can
    carry an angle), and its angle always lays the quiet side out as the silent block —
    no answer is asserted for a side whose attention is statistically indistinguishable
    from silence, though its one or two mentions stay listed. When the quiet side has
    *zero* addressed clusters the finding is worded as annotation-layer silence ("we
    found no cluster that…"), never as proof the words don't exist somewhere — the old
    **blindspot** is this special case.

  A question emits at most one finding: the three kinds are disjoint readings, and a
  firing attention gap owns its question (a modal assertion riding on the quiet side's
  one or two answers is suppressed).

## The chain

| # | Stage | Actor | In → Out |
|---|-------|-------|----------|
| 1 | **scope** | human + agent, one sitting | User writes one sentence: the issue, the A/B split, a rough window. Agent enriches it into a collection plan and runs bounded reader-question reconnaissance. At the same sitting the user edits the scope and gives candidate questions the two-level review above. If the user explicitly delegates this touchpoint to an AI stand-in, the record says so and `required` is unavailable. **Human touchpoint #1 when exercised by the user.** |
| 2 | **collect** | agent per side + code | Independent per-side collection through per-side channels; balance check over outlet `category × beat_scope`, targeted re-collection to fill the thin cells; sentence-segmented corpus; independent-reporting clusters (the denominator); append-only article store, run snapshot. Reader-question seeds do not feed its query matrix. |
| 3 | **annotate** | agent | Build/extend the question set from the frozen corpus plus approved source-blind seeds; reference seeds remain optional, while every required seed gets one meaning-equivalent question. Then annotate every cluster per question (addressed? English-pivot answer? source-language anchors). Iterative with stage 4. |
| 3.5 | **normalize** | agent → versioned artifact | Judge which answer categories are the same concept and freeze the merges into a versioned, merge-only category map (per question, with rationales). All agent judgement lives in the artifact; stage 4 applies it deterministically. |
| 4 | **analyze** | code only | Posterior machine over the (map-projected) counts: each finding is one assertion — consensus / divergence / attention gap — whose **stability** is the probability the assertion is true under a pseudo-vote prior, with its effect size and interval. Output: the writer's candidate pool, ordered mechanically (significance gate → kind rotation → effect size), each finding marked **supported / weak / unsupported**. "Interesting" is not computed here — it is stage 5's judgement. No LLM anywhere in this stage. |
| 5 | **write** | agent ("the data journalist") | Storyline brief → page content as claim objects. May not state or visually imply any contrast marked unsupported; every sentence binds to sentence IDs or computed values at generation time; no computed number in the English master is ever retyped by hand. A scope mandate gives no angle-selection preference. English master + per-side verbatim quotes. |
| 6 | **render + localize** | code + agent | Build the page, then localize into the **reviewer's own language** *before* review — whichever language the scope names the reviewer as reading, not fixed to any one language — so the reviewer reads everything, editorial included, as a reader would. Localized notation and units may be converted naturally while preserving the master's quantity and provenance. |
| 7 | **review** | human | User reads the localized page in a browser like a reader. Two questions only: does anything mislead, and is the story worth telling? All mechanical verification (verbatim quotes, count recomputation, citation coverage, independent spot check) ran as code/agent *before* this point. What is approved is the **content document** (below), not the site's typography. **Human touchpoint #2, the last one.** |
| 8 | **publish** | code | From the exact page bytes approved at review, create an immutable, public-safe publication that pins the full topic-run closure; append the lifecycle event; derive the production selector and per-locale catalog; ship the page, per-angle share landings and methodology appendix in every reader language the topic is localized into. That set is always at least the English pivot and the reviewer's own language; touchpoint two's same confirmation may also authorize a wider target set (any of the site's other supported languages) to be localized after the fact, with no second review — the localization judge (stage 6) is what gates each added language, not a second human read. |

There are only two slots where human judgement may enter. The user may explicitly
delegate touchpoint one to a recorded AI stand-in, but delegation does not silently grant
human-only authority. Everything after the scope handoff and before review is agents and
code, and may loop (collect ↔ annotate ↔ analyze) without asking anyone.

The two-touchpoint rule governs the **content judgement of one topic**. Site operations do
not create a hidden third editorial pass: curation may select an already published
publication for a labelled site placement, and lifecycle operations may withdraw or
restore it, but neither may change its findings, prose, evidence, locale bytes or topic
metadata. Any such change is a new topic revision through the ordinary chain and a new
reviewed publication. New-topic taxonomy is fixed at scope sign-off; backfilling legacy
topics is an explicit, reviewer-visible migration, not an inference made at publish time.

## Publication and site artifacts

Stage 8 crosses from per-topic work into a separate site-level artifact root. It is
deterministic: models may be credited as workers for the upstream runs they actually
performed, but no model selects a production version, changes a lifecycle state or writes
catalog facts by judgement.

- A `PublicationRecord` is an immutable **reviewed release candidate**. It binds one topic,
  the complete qualified run closure (`topic_id` + stage + `run_id` + artifact fingerprint),
  the exact locale bytes approved at touchpoint two, every shipped locale and public-bundle
  fingerprint, plus sponsor/worker/reviewer facts. It has no mutable `status` and no
  `published_at`: before an event it means “approved but not published.”
- A `PublicationEvent` is the only lifecycle fact: `publish`, `supersede`, `withdraw`,
  `restore` or `audit_delete`. Events form an append-only hash chain, bind the exact
  publication-record bytes and record the human authorization. The event time is the
  publication time. A revision is a new record and a `supersede` event, never an edit.
- The production selector is an atomic cache mechanically rebuilt from that event stream.
  It maps each topic to at most one live publication and is neither history nor authority.
- `CatalogRecord` is one small, localized, public-safe row per publication locale. It is
  derived from the pinned publication/page plus versioned site metadata; it contains no
  article body and cannot become a second hand-written source for questions, answers,
  counts or group definitions. Site search reads only this catalog.

Publication never follows `manifest/active.json`: active pointers route work in progress
and can move. It follows only the immutable qualified pins the human-reviewed publication
names. The public bundle is built from a closed output list, not by copying a topic or site
tree. Private corpus text may be read inside the build/audit boundary to resolve and check
verbatim quotes, but neither the corpus store, submissions, control credentials, audit
packets nor event-internal details may enter the deployed bundle.

### Content document and site chrome

Touchpoint two approves **what a page states**, not how the site is dressed. Those are two
artifacts with two different authorities, and the page bytes are split accordingly
(product decision).

- The **content document** is the reviewed artifact and is verified byte for byte: claims,
  order, counts, quotes, anchors, labels, locale/canonical metadata, and the *name* of the
  theme it asks for (`data-theme-token`). Anything that can change what the page states
  stays here. Approval binds these bytes and nothing else.
- The **site chrome** — stylesheet, fonts, behaviour script, and the palette each theme
  token stands for — is site-owned, shipped once per release at stable URLs the content
  document links, and versioned in the site release record. It is not part of any
  publication's bundle or of any human approval.

A content document may consist of **several files** (product decision): the
page markup plus the language-neutral **data islands** it references as content-addressed
asset files (`topics/<topic_id>/data/<island>.<hash>.json`, shared by every locale of the
page), with a small per-language overlay riding inline in the markup. These islands are
content, not chrome: they enter the candidate bundle's closed file list, the bundle
fingerprint covers their bytes, and the publication record pins them (`data_assets`).
Approval still binds the reviewed page bytes — which name every referenced asset by its
own content hash, so the approval binds the asset bytes transitively. Identical content
yields the identical filename across locales and page versions, which is what lets eight
locales ship eight small markups over one shared dataset. The hash in the asset path is
the deliberate opposite of the chrome rule ("stable URL, no content hash"): an asset is
approved content that must never change underneath a page, while chrome must be
replaceable underneath every page at once.

A content document also **never names the site's origin** (product decision). Every
URL it states is root-relative — a browser resolves those against whatever origin served
the page, which is what keeps an approval origin-free: moving the domain is a rebuild, and
it must not invalidate a single approval. A social crawler resolves nothing, so the two
facts it needs are release-owned rather than approved, and the site build writes them into
the deployed copy of the page: an absolute `og:url` / `og:image`, and a card image a
platform will actually render (none renders SVG, so the release points at the site's PNG
card, which is chrome). Canonical and alternate links stay root-relative as approved. The
per-angle facts still travel in `og:title` / `og:description`, which the share landing
pages state per angle. The relation is stated as a check, not assumed: `verify-site`
re-derives every deployed page as `resolve(approved bundle bytes, base_url)` and compares
bytes, so **deployed = approved ⊕ release origin** is audited on every run.

A chrome release therefore does **not** need a new review of every topic. It must instead
pass, all three: the theme contrast gate (4.5:1, refused at assembly, not merely at load),
the browser gate — which additionally proves the chrome loaded, resolved the page's theme
token, and hid neither side of the comparison — and a commit by the site operator.

This deliberately moves one trust boundary. CSS can in principle conceal or distort
approved content, and that risk now rests on those automated gates plus the site operator
rather than on per-topic human review. It does not widen the submission threat model: a
submission still carries only an opaque `theme_token` and can never reach the chrome layer.
Changing what a page *says* remains a new topic revision, a new review and a `supersede`.

## What statistics are here

Statistics are the **writer's discipline, not the reader's promise**.

- The analyze stage ranks findings and marks each supported / weak / unsupported. These
  marks are computed by plain Python against versioned thresholds; the writer cannot
  move them.
- The writer must not assert — in prose *or* in a chart — a contrast marked unsupported,
  and must show magnitudes with their intervals.
- What we promise the reader is not p-values but: **every claim is counted, and every
  count is clickable down to the source sentences.** Where the corpus is too small to
  support a comparison, the page says so in reader words.

## Non-negotiables 

1. **Present, never adjudicate.** Subjects are "the sampled X-language coverage" — never
   a country, never this site. This constrains what we claim, not every sentence's style.
2. **Sentence-level traceability at generation time.** Claims bind to sentence IDs
   (`{article_id}:P{n}:S{n}`) when written, never retro-fitted.
3. **Independent reporting clusters are the denominator** of every prevalence statement.
4. **Deterministic work stays deterministic.** Counting, diffing, ranking, checking =
   plain Python. LLMs do language, semantics, categorization, storytelling. Numeric
   extraction/recomputation governs the English master; localization may convert notation
   or units while preserving the same quantity and provenance. Translation equivalence is
   reviewed, not parsed by a second numeric system.
5. **Silence and wire homogeneity are data.** Annotation-layer silence is stated as such.
6. **Append-only content; runs pin content sets; publications pin the complete run closure.**
   Protocol: `docs/artifact_versioning.md`. Withdrawals are marked, never deleted.
7. **Full article text never ships publicly.** Quotes = URL + verbatim sentence. Public
   packaging uses an allowlist and a closed output list; absence from a private-path
   blacklist is never sufficient permission to ship a file.
8. **Statistical discipline precedes editorial.** A better story never lowers the
   evidence bar, and collection/analysis failures are never read as media behavior.
9. **Human question authority stops at annotation coverage.** A required scope seed is
   guaranteed one semantically equivalent question and nothing more: it changes no
   threshold, rank, finding strength or editorial obligation.
