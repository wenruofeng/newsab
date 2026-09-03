# Which languages a publication ships

Read this with the core loop whenever a publication's locale set is decided or changed.

## What one approval covers

**The user reviews in exactly one language, because that is the only language they
read. Their approval is of the page, not of that one rendering of it.** It therefore
carries to every localization of the same approved bytes. Full localization belongs to
the publish stage: the reviewer's own-language page is the touchpoint, and every other
language follows from it without going back to a human.

## One file names the shipped languages

`packages/publish/newsab_publish/data/site_metadata.v1.json` → `locales`. That list is
the default locale set for both `review-preview` and `prepare` — do not retype it on the
command line. `--locales` remains only as a deliberate narrowing, and
`resolve_publication_locales` refuses any set below the floor:

- the **English pivot**, which the page was written in and every other language is a
  localization of; and
- the **reviewer's own language**, whose bytes they signed.

Narrowing below that floor is not a smaller publication — it is a missing one. A site
locale a publication does not ship gets a site-owned whole-page fallback shell (`noindex`,
the article in another language inside an iframe, its nested article staying in one
declared content language — never localized field by field), and the reader-facing
language switcher lists only what shipped. `PUB-aabb-market-meal-2024-6622bb9886bc` and
`PUB-aabb-island-dance-2024-9c3f2b02f854` went live that way, English-less, from a stray
`--locales zh-CN` copied off a `review-preview` command; both English pages had been
rendered at stage 6 all along. The floor is enforced in code, not here.

## Why a wider locale set does not invalidate a review

A page states which other languages it exists in, so the locale set is inside its bytes:
adding a language changes the `hreflang` alternates and the language switcher on *every*
other language's page. Taken literally that would invalidate every existing
`PublicationReview` each time the site learns a language — and force a human to
re-approve an article they already read, in a language they cannot check.

So `PublicationReview.reviewed_locales` records the set the reviewed bytes were rendered
under. When `prepare` ships a different set, it renders the reviewed set as well and
requires the reviewed locale's bytes to reproduce exactly. Nothing is weakened: both
renders come from the same pinned closure, so content drift still fails byte-for-byte.
Records written before this field omit it; supply the set with `prepare
--reviewed-locales`, taking it from the `locales` of the publication that review was
bound into, never from memory.

**This byte re-prove is the only thing that passes on every touchpoint-two path.** The
site-wide backfill below is the single exception, and it does not loosen this check —
it proves the same thing a different way. Read that section before assuming otherwise.

## Expanding one topic ahead of the site (the locale-plan)

The localization floor above is per-publication and site-wide: English pivot plus
**whichever language the reviewer happens to read**, never assumed to be `zh-CN` — the
scope record names the reviewer and their language in `topic_manifest.review_locale`,
which is where the dev shell reads it to key that topic's approval hash, and where
`prepare` reads it for the publication's default locale. There is no site-wide reviewer
constant to fall back to: a topic whose manifest never named one takes no approval at
all — the release card says what is missing instead of offering a confirmation. Beyond that floor, the user can authorize one topic's page to reach more
of the halo's nine **without waiting for
`site_metadata.v1.json`'s `locales` to grow and without a second review** — that
authorization is what touchpoint two's dev-serve card now also takes, in the same
confirmation as the content review itself.

Approving a release on the dashboard writes three records from one confirmation, not
two: the per-locale `PublicationReview`s, the lifecycle `HumanApproval`, and a
`LocalePlan` at `site/private/approvals/locale-plan-<topic_id>-<hash8>.json` (same
`<hash8>` suffix convention as the sibling review files — the trailing 8 hex of the
reviewed page hash). It records `included_locales` (exactly what the approved candidate
already ships — English pivot and the reviewer's language, read-only on the card),
`target_locales` (that set plus whatever else the user checked, a non-strict
superset), and `reason` — the user's own click, not a second sitting. Checking
nothing is still a decision and is still recorded: "ship only what is already here" is
what an unchecked box means, not silence to be inferred later.

A render-localize expansion run for that topic reads the still-pending plan instead of
asking again:

    python -c "
    from newsab_schema.paths import SitePaths
    from newsab_publish.dev_shell import pending_locale_plan
    plan = pending_locale_plan(SitePaths.at('site'),
        topic_id='<topic_id>', reviewed_hash='<the review's page_hash>')
    print(plan.target_locales if plan else 'no pending plan')
    "

Localize the topic's `page.json` into each locale in `target_locales` beyond what
already exists (`references/localize.md`'s bulk tools —
`scripts/prepare_localized_page.py --locale <l>` for lexicon maps,
`scripts/apply_angle_localizations.py --lang <l>` for angle prose), gate each new locale
through its own L2 `check_localization_judge.py` pass exactly as any other language —
**a locale-plan authorizes shipping a language, it does not exempt it from the judge**.
Then prepare and activate the wider candidate, citing the plan as the human
authorization behind it:

    python -m newsab_publish prepare <topics_root> <site_root> <topic_id> \
      --page-run <the expansion rl run> --review <path to the PublicationReview> \
      --site-metadata <metadata.json> --locales <target_locales, comma-separated> \
      --reviewed-locales <the review's original locale set>
    python -m newsab_publish activate <topics_root> <site_root> <publication_id> \
      --approval <a HumanApproval citing the locale-plan file> \
      --site-metadata <metadata.json> --production <public_dir> \
      --base-url <https://origin> --reason "expanding <topic_id> per locale-plan-<topic_id>-<hash8>.json"

`--reviewed-locales` is required whenever the original review predates that field or
shipped a narrower set than `target_locales` — read it off the review record, never from
memory (same rule as the site-wide backfill below). Finally mark the plan spent so a
resumed or repeated expansion run does not silently replay it:

    python -c "
    from newsab_schema.paths import SitePaths
    from newsab_publish.dev_shell import consume_locale_plan
    consume_locale_plan(SitePaths.at('site'), topic_id='<topic_id>',
        reviewed_hash='<the review's page_hash>', consumer='<new publication_id>')
    "

This is a **per-topic, ad hoc** path — one plan, one topic, whatever subset of the halo
the user checked. It is independent of and does not substitute for the site-wide
switch below: a topic can carry an unconsumed locale-plan indefinitely (no deadline,
no expiry), and `backfill-locales` never reads it — the two mechanisms happen to reuse
the same `prepare --locales` / `activate` primitives underneath, nothing more.

## When the site adds a language

The user edits `locales` in that file. Two things then follow, neither needing a human
reviewer:

1. **Backfill.** Every live publication is re-prepared and superseded so it ships the new
   language, reusing the existing `PublicationReview` — the approved bytes are unchanged,
   so the approval still holds. One command runs the whole batch:

       python -m newsab_publish backfill-locales <topics_root> <site_root> \
         --site-metadata <metadata.json> --production <public_dir> \
         --base-url <https://origin> --reason "<why the set changed>"

   Per live publication it re-prepares against the topic's active editorial run (override
   per topic with `--page-run topic=run`), reuses the record's `PublicationReview` with
   the locale set it was bound into, and supersedes. Each supersede gets its **own**
   `HumanApproval`, minted from the command's `--reason` — running the backfill is the
   human act that authorizes the batch; a spent `activate-intent` authorizes nothing.
   A topic whose page run is not yet localized into the new language fails
   `prepare`'s `required_langs` refusal and is reported for stage-6 localization; a topic
   whose active run drifted in content fails and is reported for the ordinary review
   path. The command is resumable: current publications are skipped, prepared candidates
   reused, approvals reread.

   **How the approval is re-proved here, and why it is not the byte re-prove.** A
   backfill runs long after the review, against the topic's active editorial run and with
   whatever renderer the repository now has. Two things have moved that the reviewer never
   saw: the run's self-description (the disclosure panel prints the editorial run's
   own `run_id`/timestamp/producer/`model_id`, and an expansion run is a new run — records
   are never edited in place), and renderer-owned chrome (`dir=`, the hreflang alternates
   and language switcher, the wording of the stat tooltips). The strict byte re-prove
   refuses every publication on those grounds alone — it did, for every live publication,
   the first time this was tried — so this path hands `prepare` a *baseline* to measure
   against and proves equivalence in two mechanical layers
   (`newsab_publish.reviewed_equivalence`):

   1. **Content.** The signed run's `page.json` and the candidate run's, both projected
      onto the reviewed languages, must be identical — same angles, prose, quotes, badge
      numerators and denominators, lexicon. Other languages are ignored; that is what an
      expansion run adds. The pinned upstream closure and the language-neutral data
      islands must match too. This is *stronger* than the byte re-prove: it compares the
      artifact the writer produced rather than one rendering of it.
   2. **Bytes.** Both renders go through a closed, code-owned whitelist (`RULES`) and the
      remainder must be byte-identical. The whitelist covers only: hreflang alternates,
      the language switcher and fallback notice, the root `dir=`, the provenance rows'
      run id / timestamp / producer / model, the page row's "N languages" counter, and the
      stat tooltip's *wording* — whose numbers stay in the comparison. Anything else is a
      refusal.

   The baseline is the reviewed bytes themselves the first time — read back out of the live
   publication's stored bundle and re-hashed against `review.page_hash`, never trusted
   from a hash — and the standing publication's own proof every time after, because by
   the second language the site learns, the record holding those bytes is superseded.
   Chaining is exact, not a hand-off: Layer 2 is a digest equality, so reproducing the
   standing digest reproduces equivalence to the signed bytes.

   The proof is written into the new `PublicationRecord` as `reviewed_equivalence`
   (the approved page hash, the baseline run, the digest of the redacted bytes, which rules
   actually fired), and `verify-candidate` replays it by re-rendering and re-deriving that
   digest — so the claim survives without any superseded bundle. A publication that
   reproduces the signed bytes exactly carries no such record; its presence *is* the audit
   flag. Widening `RULES` widens what ships without a human, so treat it as the user's
   decision, not a fix for a stubborn topic.
2. **Every later publish** localizes into the full set automatically.

A human cannot audit a language they do not read, so **never route added languages to
touchpoint two.** Put the quality gate where it can actually work: the localization judge
(L2) inside render-localize, which scores every English-pivot↔target pair per locale —
`scripts/localization_packet.py` → an isolated judge on
`references/localization-judge.md` → `scripts/check_localization_judge.py`, whose exit 1
refuses the locale outright. The mechanical refusals (`page-check`'s `required_langs`)
already fail a locale whose page is not fully localized, so a half-translated language
cannot ship silently.

Adding a language is two halves. `locales` covers the article; the chrome around it is
renderer-owned (`newsab_publish.site_strings`) and must learn the same language.
`resolve_publication_locales` names the missing half rather than failing mid-render.
