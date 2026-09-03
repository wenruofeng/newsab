# What the renderer builds itself — never hand-written

Read this only when debugging the renderer or deciding whether a field is the writer's
or the renderer's. A normal run never needs it: everything below is deterministic, from
the pinned artifacts, and a writer who hand-writes any of it is writing a second,
drifting copy.

- **The page furniture**: the floating circular light/dark control and the footer's two
  panel links. There is no top bar, reading-position rail or 01 / 02 / 03 section pointer.
  Quote translation controls stay beside translated quotes.
- **The evidence list**: one original sentence address per reporting cluster the badge
  counts (badge says `9/12` → nine rows). The compact count badge only explains its
  fraction; the evidence control in the card's upper-right opens one shared two-side modal
  on the clicked side; its columns are report (outlet +
  date), quoted text and original (Pxx:Sxx), with no cluster id in the reader table.
  Every route that would expose sentence text—including a storyline writer pick—shares
  the per-article half-text budget. Past it the renderer emits only the sentence address;
  the publisher page remains the place to read the article.
- **The three record levels and the links between them**: the sentence card behind every
  quote (outlet, date, cluster, position, collection date and only then the outbound link),
  the article card a timeline dot opens (including that article's topic phrases), and the
  **reporting-cluster panel** every cluster id on the page opens — a cluster of one goes
  straight to that article; a cluster of several lists outlet / date / headline with the
  original reporting first.
- **The annotation appendix**: every question in the set as a collapsed `Q:` question row
  (one overlapping-cards `+` / `−` control above them toggles all), each opening the same data card the storyline
  folds — the collapsed row owns the rank, kind and evidence badges; the expanded card
  does not repeat them. The card carries both sides' rates, the butterfly of answer shares,
  and the annotation-table and statistics controls. It is the annotation record, not
  writing — if it reads wrong, the defect is in annotate or analyze.
- **Every statistical label and its explanation**: the angle kind (agreement / divergence /
  silence — which is the storyline's three tabs, with their counts), the strength (the
  solid green or subdued dotted amber ring around the storyline's relation symbol, and a chip in
  the data card), the tied lead, the `#n`
  candidate rank — each carrying the rule and the thresholds of the *pinned* analyze run.
  The **statistics panel**, titled “Statistics” in English, is generated from the finding by
  one template per kind. It presents three short claims in reading order: the top-answer
  phenomenon and its reproducibility over 1,000 resamples; the two sides' answer-rate
  difference and its 90% interval; and the agreement/divergence effect estimate and its
  90% interval. Threshold version names stay out of this reader panel. A question whose
  kind asserts nothing (`no_significant_relation`, `too_thin`) gets no strength chip, no
  panel and no interval — there is no hypothesis to explain.
- **The side tags**: a side is named by the manifest's `short_label`, with `label` +
  `definition` in the tooltip. The renderer never invents a name for a side and the
  writer never types one.
- **The relation between the two answer cards**: the project's meet / part / fade symbols
  for agreement / divergence / silence. The same symbols lead the three storyline tabs;
  in an angle, a generated strength ring surrounds the symbol and carries a threshold
  tooltip that names both the strength and the relation kind. The compact count and
  evidence control remain neutral rather than inheriting the side colour. The quiet side's card is greyed and its near-silence is worded by the renderer
  (with the mention count when non-zero).
- **The concept cloud**: two columns, each ranked by its own share, sized proportionally on
  one shared map (with only a 10px readability floor) so heights compare across the
  midline. The section title is renderer-owned as “Concept cloud”; its calculation note
  sits behind the same circular `?` control the timeline uses for scope. The source is a render-time switch
  (`--concept-cloud`): `categories` sums the annotated answers from `question_stats`
  (`unclear` / `none_reported` leave numerator and denominator); `topics_raised` counts
  the collect stage's per-article phrases once per independent report, over that side's
  whole set of reports. The writer declares the visual and its caption; the mechanism
  sentence, percentages, ranking and the footnote naming what the floors hid are the
  renderer's. `page-render` recomputes the whole section from the pinned run and refuses a
  mismatch; the floors, cap and font range are module constants, never per-page settings.
- **The report search**: a compact per-article index built only from the article record
  fields, collection-stage phrases and annotation rows already exposed on the reader page.
  It covers headline, outlet, dates, side and origin metadata, reporting cluster, source
  and localized concept phrases, reader question, answer label, annotation summary and
  annotation note. The browser applies an adaptive short debounce, AND-matches every query
  term, ranks title and phrase matches first, and opens the existing article record modal.
  It never reads or serializes `Article.structured_text`; adding a new search field requires
  naming the reader-visible place where that same field already appears.
- **The reporting timeline**: one point per independent report, represented by its
  original article or earliest captured version, drawn in the browser from the dates the
  renderer ships, so
  bucket width, tick density, dot size and lane height follow the reader's window. Both
  lanes are always the same height, visible dots have desktop-sized hit targets, and a
  busy bucket uses at most two columns. The browser chooses an odd-numbered bucket width
  (1 / 3 / 5 / 7 / 9 / … days); hover always shades that whole bucket and places its date
  label above the shade (a one-day bucket names one date). Plus each side's cluster count
  and the scope panel.
- **The media cards**: every outlet named anywhere on the page, from
  `sources/registry.yaml` — country, language, `category`, `beat_scope` and the
  registry's one-sentence reader description. If a card reads badly, fix that outlet's
  `notes` in the registry and re-render — it is the same sentence for every topic.
- **The scope panel**: period, per-side targets and the `include` / `exclude` bullets from
  the topic manifest. An open-ended window is shown as the day collection actually
  finished. The bullets are shown in the reader's language from `page.lexicon.scope` —
  that map is localize's to fill; the manifest itself is never translated.
- **The methodology panel** ("Method" in English): template text owned by this renderer,
  identical on every page there will ever be — counting unit, the Q×A model, what
  "supported" means, silence-in-the-data-is-not-silence-in-the-world, what a reader can
  check. No writer contributes to it.
- **The page record panel**: generated from the topic manifest, the page's four
  compatibility run pointers and the append-only manifest ledger. It opens with the
  topic's **contributors** — the humans answerable for it, "anonymous" when the manifest
  names none — then lists scope, corpus, questions, annotations, category map, analysis,
  the run that **wrote** the sentences (one ledger hop back from the render, and named
  because a reader asking "who wrote this" deserves an answer) and this page snapshot.
  Each carries its run id, timestamp, producer version, the **model that did the judging**
  and the run's own output counters. A deterministic step records no model and the panel
  says nothing rather than announcing an absence. Two steps also name a person: the scope
  signer, and who takes touchpoint two — a contributor, or the model declared in
  `review_stand_in_model_id`, which is then marked as standing in (AGENTS.md §8).
  **Content hashes are not shown** (product decision): a run id already identifies a
  step, and a fingerprint only earns its row once a reader can re-verify what it names.
  It never reads `how_we_counted.notes`; no writer or localizer contributes prose to it.
- **The quote controls**: a text control opening the original sentence record and, where
  `Quote.translation` exists, an inline control that changes the page-wide quote state.
  There is no original/translation control in a top bar.
- **The article concept control**: article records may show the collect-stage concepts and
  switch between the article's original wording and the localized concept. This is a
  conceptualization switch, not a translation icon. Sentence/original records omit the
  concept list so the quoted text remains the focus.
