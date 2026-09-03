# Synthetic demo and test-rewrite inventory

> Designated reader: the P1 public exporter/demo implementation agent. This document is
> the closed input inventory for that task; it is not permission to copy any real topic.

## Demo identity and provenance

- Topic id: `aabb-river-light-2026`; groups `aa` / `bb`, article prefixes `AA` / `BB`.
- Subject: a fictional municipal river-lighting pilot in fictional places. No real person,
  outlet, institution, event, quote, domain, publication id, run id, or source URL may be
  adapted from `topics/`, `site/`, reports, or news-ab.com.
- Source URLs use only RFC 2606 reserved names below `https://example.com/` and
  `https://example.org/`; every article sentence is newly written for the fixture.
- The fixture is generated from checked-in small text/data inputs. It contains no model
  output, credential, network fetch, timestamp from a private run, or production hash.
- Sponsor and worker labels are neutral (`Synthetic toolkit demo`, `fixture-model`).

## Closed artifact inventory

P1 creates `examples/synthetic-topic/` with exactly the minimum schema-valid closure below.
Every run record uses fixed fixture timestamps and valid synthetic run ids; a deterministic
builder derives hashes rather than copying them from production.

| Stage | Required synthetic content | Acceptance proof |
|---|---|---|
| scope | signed stand-in scope, two fictional groups, fixed window, approved reference seeds | scope preflight passes; no human-only `required` seed |
| collect | 3 independent clusters per side, 1 deliberately syndicated pair, article store and pinned corpus run | IDs derive from reserved URLs; cluster denominator is 3/side |
| annotate | template + reader questions, every cluster answer, source-language anchors | every addressed answer binds to a fixture sentence |
| normalize | one merge-only category map with a no-op question and one genuine synonym merge | normalize checker passes |
| analyze | deterministic findings containing one consensus, one divergence, and one attention gap | `newsab_a1 qa` reproduces checked-in output |
| write | English master with claim objects and only short fixture quotes | page checker resolves every claim and quote |
| render-localize | English and Chinese fixture pages plus content-addressed data islands | deterministic render reproduces fingerprints |
| publish | reviewed-fixture record, candidate bundle, event, selector, and catalog in a temporary tree | lifecycle test runs without repository `site/` state |

The example must expose one command that rebuilds the closure into a caller-supplied
temporary directory. It must never write into the checked-in fixture in place, call a
model, fetch a URL, or require a news-ab.com credential.

## Test rewrites required by the P1 release gate

### A. Replace production-looking identifiers in synthetic fixtures

The following synthetic-only test families use `aabb-river-light-2026` (or a second
clearly synthetic `aabb-*` id when a test needs isolation). Expected IDs are derived from
those fixtures and the test semantics stay unchanged:

- `tests/pipeline_fixture.py` and all repo integration tests importing it;
- `packages/a1/tests/conftest.py`, `packages/a1/tests/test_qa_analyze.py`;
- `packages/editorial/tests/test_previews.py`, `packages/editorial/tests/test_reader_page.py`;
- `packages/publish/tests/conftest.py`, `examples/synthetic-topic/demo_fixture.py`, and
  publish tests that consume those fixtures;
- schema unit tests containing `QST/ANS/OBS/ANG/PUB-aabb-*` fixture literals.

Comments may name a historical regression only when needed to explain a general rule; no
test may read production artifacts to obtain its fixture values.

### B. Remove direct real-topic/site dependencies from the public suite

These exact tests or sections must be split into private repo-artifact coverage or replaced
with the synthetic closure. Merely skipping them on a clean clone does not make them a
public test:

- `tests/test_phase0_pipeline.py::test_s4_finalize_commands_validate_manifest_and_activate_both_phases`;
- `tests/test_annotate_preflight_debt_gate.py::test_every_real_topic_gate_matches_its_active_record`;
- `tests/test_collect_log_reconciliation.py::test_every_topic_in_the_repo_still_passes`;
- `tests/test_scope_question_review.py::test_the_cluster_threshold_is_outside_the_signed_surface`;
- `packages/schema/tests/test_category_map_and_refactor_compat.py::test_every_committed_run_still_deserializes`;
- `packages/publish/tests/test_page_semantics.py::test_every_live_publication_passes`.

P1 also replaces `packages/publish/newsab_publish/data/site_metadata.v1.json` with synthetic
site metadata in public test fixtures. Production taxonomy approvals and topic mappings are
not demo inputs.

### C. Neutral site identity required by generic collection and publish code

The public export intentionally omits `favicon.svg`, both transparent logo SVGs,
`share-card.png`, and production `site_metadata.v1.json`. P1 must add newly authored neutral
placeholder assets/metadata under a public definition-source directory, map them to the
same package-data targets during export, and update `THIRD_PARTY_NOTICES.md`. Placeholders
must not trace or modify the News A/B marks.

P1 must also parameterize or replace production identity defaults in these selected source
surfaces: `packages/corpus/newsab_corpus/fetch.py` and
`skills/collect/references/fetch-extract.md` (operator URL/email);
`packages/editorial/newsab_editorial/render/strings.py` (footer domain); and the publish
package's `about.py`, `builder.py`, `crawler_meta.py`, `dev_shell.py`, `fallback.py`,
`share_cards.py`, `site_strings.py`, and `themes.py` (site name, contact, titles, and card
copy). A public clone may use a clearly neutral local default and let its operator configure
an identity; it must not impersonate news-ab.com or tell downstream users to contact its
operator. The seven halo locales' translation files (`*_i18n.v1.json` under the editorial
renderer and the publisher) are exported unchanged, so they carry identity *slots* only —
`{site_name}`, the about paragraph, the contact line and the footer domain are filled from
the overlaid identity files at import — and the exporter refuses a production token in
them. The neutral `site_metadata.v1.json` must list every locale in `SITE_LOCALES` with a
label per locale, because the exported test suite asserts nine-locale coverage. Package/module names such as `newsab_schema` are API identifiers, not brand
artwork, and do not require renaming.

## P1 exit checks

The `synthetic-demo`, `synthetic-test-rewrites`, and `neutral-site-identity` gates in
`public_export.yaml` become `ready` only when all of the following pass in a fresh exported
tree: full pytest; eight active skill preflights; schema regeneration diff; demo closure
rebuild; candidate render/verify; forbidden-id/path scan; license/notices scan. No check may
read the private checkout, its Git history, `topics/<real-topic>`, or `site/` state.
