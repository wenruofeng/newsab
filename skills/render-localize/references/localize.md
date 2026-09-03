# Localization invariants (segment 3)

**Read this if you are running the stage**, before translating anything. `page-check
--langs en,<reviewer_locale>` names each missing field precisely, so work to the checker
rather than to a memorized field list; these are the rules the checker cannot state for
you.

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
- Quote translations sit beside the verbatim original, never replacing it.
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
  badge on a Mongolian-language page.
- A lexicon category left in English is a counting key shown to the reader.
- **Preserve Q–A–explain as reader logic, not English syntax.** Each angle must read as
  concise local-language news prose answering why that side arrived at the card's answer.
  Preserve evidence, causal chain and footnote position, but recast abstract scaffolding
  or spoken phrasing; a literal “from this position” / “the logic here” is unfinished.

Preserve evidence routes, avoid repeating cards/side tags, keep columns comparably dense,
and send master defects back to write; a joint paragraph stays joint.

For bulk `topics_raised`, keep `{topic_id: {pivot_en: reader_label}}`; mint the page copy
with `scripts/prepare_localized_page.py --help`. Angle-by-angle rewrites go in through
`scripts/apply_angle_localizations.py`.

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
