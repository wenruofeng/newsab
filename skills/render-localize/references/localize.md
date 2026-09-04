# Localization invariants (segment 3)

**Read this if you are running the stage**, before translating anything. The work list is
mechanical and comes from `scripts/localization_units.py` (below); `page-check --langs
en,<reviewer_locale>` is the refusal that decides whether it is finished. These are the
rules neither of them can state for you.

`<reviewer_locale>` is `topic_manifest.yaml`'s `review_locale` and nothing else: not the
language you are being spoken to in, not the one this checkout's other topics use, not a
guess from the group prefixes. A manifest that names none is a scope defect — the scope
stage's own `check` refuses to sign such a draft — so stop and say which topic is missing
it rather than picking a language on the reviewer's behalf; a page localized into the
wrong language reads as finished work and wastes the one human step in the chain. The
same rule is why `prepare_localized_page.py --locale` and `apply_angle_localizations.py
--lang` are required arguments with no default.

- **The whole reader-facing surface**, including all four lexicon maps: `questions`,
  `categories`, **`topics`**, and **`scope`**. `topics` localizes each collect-stage
  `topics_raised.pivot_en` concept while leaving that pivot as the stable count/key; it
  never substitutes a per-article `source_phrase` for a translation. Every manifest
  `include` / `exclude` bullet is keyed by its verbatim English original (the manifest's
  own hash is what `scope_approval` signed); `page-check` warns per bullet left in English
  and per localized bullet that drops a number the signed bullet states — a bullet is
  translated, never summarized (a measured zh panel lost the whole collection window).
- **Meaning, quantity and provenance never move.** Localized notation/units may change
  (`250 juta ton` → `2.5亿吨`), but preserve the quantity; `page-check` does not verify
  conversions.
- Anchors and `computed_from` stay untouched. Meaning changes go back to write.
- Quote translations sit beside the verbatim original, never replacing it. Every
  non-English quote's `translation.en` is write's to supply, not yours — English is the
  pivot master, so `page-check` refuses one missing here before you ever localize a line;
  a run that fails on it belongs back with write, not fixed in place.
- **Group names** come from the manifest's touchpoint-one `label` / `short_label` /
  `definition` when that language is one of the few the manifest carries (the manifest's
  own hash is what `scope_approval` signed, so a run cannot add a language there without
  invalidating that approval — same reason `scope` bullets live in the lexicon instead of
  the manifest, above). Every other language's side badge, tooltip label and definition
  goes in `page.lexicon.group_labels` / `group_short_labels` / `group_definitions`
  (`{group_id: {lang: text}}`, mirroring `categories`); the renderer prefers a lexicon
  entry over the manifest's own value when both exist for a language, and otherwise
  falls back to the manifest (English, if that is all the manifest has) — a missing
  lexicon entry here is why a reader could once meet an untranslated "Mongolian side"
  badge on a Mongolian-language page. `page-check` warns per group per `--langs` language
  with no wording anywhere (lexicon override or manifest field) — it used to only re-check
  entries a run had already started writing, so a run that never touched these three
  tables at all (the common case) was asked nothing; measured, a nine-locale run shipped a
  Russian page with the English short label "China side" on it, the same defect as the
  Mongolian one above. Answer every warning by adding the wording, not by leaving the
  manifest's fallback in place.
- A lexicon category left in English is a counting key shown to the reader.
- **Preserve Q–A–explain as reader logic, not English syntax.** Each angle must read as
  concise local-language news prose answering why that side arrived at the card's answer.
  Preserve evidence, causal chain and footnote position, but recast abstract scaffolding
  or spoken phrasing; a literal “from this position” / “the logic here” is unfinished.

Preserve evidence routes, avoid repeating cards/side tags, keep columns comparably dense,
and send master defects back to write; a joint paragraph stays joint.

## Extracting and merging: two commands, whole page

Do not hand-assemble the field list or hand-write a merge script. Both used to be
re-derived once per run and thrown away, and both are exactly the steps where a mistake is
silent: a field nobody enumerated ships untranslated, and a merge nobody constrained
rewrites approved bytes.

    python skills/render-localize/scripts/localization_units.py \
        --page <page.json> --lang <target> \
        --topics-root <topics_root> --topic-id <topic_id> --qa-run <qa-run-dir> \
        --reference-lang <reviewer_locale> -o <scratch>/units.<target>.json
    python skills/render-localize/scripts/apply_localization.py \
        --page <page.json> --translations <scratch>/<target>.json --lang <target> \
        --topics-root <topics_root> --topic-id <topic_id> \
        --run-id <this run_id> --model-id <localizer model> -o <out page.json>

The unit key is the page's own JSON path, and it is the same string
`localization_packet.py` prints as the judge's location label — so a defect the L2 judge
reports can be looked up in the packet the translator was given. What the two commands
give you that a hand-written pass does not:

- **Every** unit, checked against the page's structure rather than a remembered list: a
  language-carrying field the enumerator does not know about is a refusal, not a silent
  omission.
- **Quote units carry the verbatim source sentence**, resolved from the run's
  `data/sentence-index.*.json`, with its language and `source_id` in the note. The thing
  being translated is the source sentence, not the English gloss; a quote already written
  in the target language is marked not-applicable instead of inviting a paraphrase.
- **A merge cannot overwrite a language the page already carries** — those bytes may be
  what touchpoint two approved, and one own-language approval covers only *later*
  localizations of the *same* bytes. `--overwrite-lang <lang>` is the deliberate way past
  it and prints every replaced key with its old and new text.
- **The output states which run produced it** (`--run-id` / `--model-id`), so a localized
  page carrying the write run's stamp fails at the first `page-check` rather than at
  `review-preview`, after every panel and locale has been paid for.
- **The three group tables are seeded from the manifest** (`label` / `short_label` /
  `definition`, copied verbatim for the languages the lexicon lacks). The renderer already
  falls back to exactly those values, so no rendered byte moves; what changes is that the
  L2 judge has an English master for each side's badge instead of `(missing)`.
- **`--lang en` works too**: on an English master the gaps are the write stage's own
  missing reader wording — every answer category, question, scope bullet and topic concept
  the page displays, plus any non-English quote with no English translation.

The per-kind gap table it prints is the number to quote in the run report.

`scripts/prepare_localized_page.py` (topics lexicon only) and
`scripts/apply_angle_localizations.py` (angle prose only) are **superseded** by the pair
above and kept only because Phase 0 run records name them; a new run has no reason to
call either. Their input shapes are unchanged if you are reading an old run: bulk
`topics_raised` as `{topic_id: {pivot_en: reader_label}}`, angle rewrites keyed by rank.

## The localization judge (L2), per locale

The reviewer's own language is gated by their read at touchpoint two; every *other*
localized language ships without a human ever reading it (`skills/publish/references/
localization.md`), so its only meaning-level gate is this check — which is why its trigger
is a refusal rather than an escalation: there is no human fallback on that path.

Spawn it as its own agent whose **entire input** is `localization-judge.md` plus one
locale's packet — the same isolation contract as an L1 panel member, `standard`-class
recommended, both model ids recorded. It is **one judge per locale, not a panel**:
deliberately, for the reasons in that rubric. Save its JSON in the run directory as
`locjudge.<target>.json`.

`check_localization_judge.py` exit 1 blocks that locale: fix the localization, rebuild the
packet, run a **fresh** judge. Exit 2: the judge output is unusable — re-run the judge,
never hand-fix its JSON. The reviewer's locale may be judged this way as a courtesy, but
its gate remains the user's read.
