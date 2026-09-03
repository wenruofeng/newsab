---
name: publish
description: Prepare or change a production publication from exact human-approved page bytes; run after review, never before it or in place of it.
metadata:
  newsab-stage: "publish"
  newsab-version: "0.8.0"
  newsab-inputs: "publication_review,page,qa_analysis,corpus,topic_manifest,site_metadata,theme_registry,source_registry"
  newsab-outputs: "publication,event,catalog,public_bundle"
  newsab-language: "reader-local"
---

# publish

Turn one exact, human-approved localized page into an immutable public-safe publication,
then append the authorized lifecycle event and rebuild the production selector and
per-locale catalog. This stage packages and selects; it never edits content, chooses an
angle, approves its own output or follows a topic's mutable active pointer. If
`python -m newsab_publish --help` fails, stop — the storage contract exists apart from
the builder, and no generic archive command, file copy or preview deploy substitutes.

## Start here

Working directory: repo root. Inputs: an explicit final `page_run_id`, its complete topic
manifest/run closure, the private corpus for quote verification, a `PublicationReview`
approving the exact locale page hash, and versioned site metadata. Never accept "the
active page" or an approval that names only a topic.

Before any mode, read [references/threat-model.md](references/threat-model.md) — refusal
conditions for bytes crossing from topic/audit storage into the site root or public
bundle. Shipped languages come from `site_metadata.v1.json` → `locales`, never the
command line; reviews carry across locale sets: [references/localization.md](references/localization.md).

    export PYTHONPATH=packages/schema:packages/corpus:packages/a1:packages/editorial:packages/publish
    python -m newsab_schema validate-topic <topics_root> <topic_id>
    python -m newsab_publish --help

## Choose a mode

- **prepare** — build and verify a reviewed `PublicationRecord`, public bundle and catalog
  candidates; append no event. This represents "approved, not published."
- **activate** — publish a prepared candidate, or atomically supersede the topic's one
  live publication. Requires a human approval for the lifecycle operation.
- **lifecycle** — withdraw, restore or record audit deletion. Changes no publication
  bytes; requires an explicit human approval and reason.

## Core loop

1. *(command)* Resolve and verify the explicit dependency closure — scope, corpus,
   questions, answers, normalization, analysis and final page pins, each qualified by
   topic and output fingerprint. Recompute every restorable set; ignore active pointers.
2. *(command)* Re-render every requested locale from the pinned artifacts into a fresh
   scratch directory. Run the page, quote-verbatim, finding/count recomputation,
   sentence-budget and locale-completeness checks before comparing the reviewer locale's
   final hash with `PublicationReview.page_hash`.
3. *(command)* Assemble from a closed output list: final pages, one deterministic share
   card per published angle/locale, methodology and typed public records only. Reject
   links, symlinks, unlisted files, executable input, private paths, full article text,
   control credentials and non-deterministic bytes. Resolve the theme through the
   checked-in token registry; never accept colours, CSS, scripts or component parameters
   from a topic. A candidate bundle holds **content documents only** — page markup,
   per-language inline overlay, and the data islands pinned as `data_assets`; site chrome
   ships once per release at stable URLs, never inside a publication, and a chrome
   release may never change the islands (`docs/value_chain.md`, "Content document and
   site chrome").

       python -m newsab_publish prepare <topics_root> <site_root> <topic_id> \
         --page-run <run_id> --review <review.json> --site-metadata <metadata.json> \
         [--submission SUB-<id>]

   `--submission` is required whenever the topic came from an external submission, and
   its `<topics_root>` is then that import's namespace. The record pins the archive hash,
   the passing independent-audit run id (there is no publishing an external report
   without one) and the contributor's sponsor choice — and every later rebuild finds
   the topic tree from the record instead of a flag, because one `--topics-root` cannot
   hold both the site's own topics and every imported namespace.

4. *(command)* Rebuild the same candidate in a separate empty directory and require the
   same public-bundle fingerprint. Validate `PublicationRecord` and every locale's
   `CatalogRecord`; catalog questions, answers, group definitions and page fragments must
   derive from the pinned page, never parallel copy. Replacing approved bytes always
   means a new review plus `supersede`; which records re-render and which verify against
   stored bytes: `packages/publish/README.md`, "Producer versions and verification tiers".

       python -m newsab_publish verify-candidate <topics_root> <site_root> <publication_id>

   Before touchpoint-two approval of an M2 candidate, run the browser gate against the
   private review directory (it names each check it runs: DOM semantics against the data
   islands and shipped locales, geometry, keyboard/touch, modal focus, angle fragments,
   reduced motion, share assets, chrome split; `--full` so no review inherits a sample):

       python -m newsab_publish web-gate <private_review_dir> --full --screenshots <audit_dir>

   **Never end a human-review handoff with a file path.** Production pages use
   root-relative URLs and link the site chrome, so a candidate is only readable when
   served as a root. Finish by starting the review shell and handing over the link:

       python -m newsab_publish dev-serve --preview <private_review_dir>

   The user reads the page there and takes touchpoint two beside it: one confirmation
   writes every record a release needs — a `PublicationReview` per locale bound to the
   exact served bytes, the `HumanApproval` (mandatory reason) for the `publish`/`supersede`
   move, a `TopicCategoryApproval` for the proposed categories, and a `LocalePlan`
   naming which of the halo's nine locales beyond this candidate's own — English
   pivot plus **whichever language the reviewer reads**, never assumed to be `zh-CN` —
   the user authorizes reaching after the fact, without a second review
   ([references/localization.md](references/localization.md), "Expanding one topic ahead
   of the site"). Approving bytes a human read *is* the authorization to ship them;
   `verify-candidate` refuses bad bytes either way. A pre-`prepare` approval is a
   **single-use** `activate-intent-<topic>-<hash8>.json` (promotion rules:
   `packages/publish/README.md`, "Touchpoint two and the replacement authorization are
   one decision"). The shell never injects anything into a page under review and never
   runs `activate`/`supersede`/`lifecycle`.

5. *(command, activate only)* Append exactly one hash-bound event under the site-store
   lock — `publish` for a first version, one `supersede` naming both old and replacement
   records for a revision. Only after the event fsyncs, atomically replace selector,
   catalog and deployed bundle as one release unit.

       python -m newsab_publish activate <topics_root> <site_root> <publication_id> \
         --approval <approval.json> --site-metadata <metadata.json> \
         --production <public_dir> --base-url <https://origin.example>

6. *(command, lifecycle only)* Apply the named transition; never simulate withdrawal by
   deleting a page or editing the selector. Audit deletion removes legally required
   private bytes only via its separate authorized procedure; its content-free event
   survives.

       python -m newsab_publish lifecycle <topics_root> <site_root> <publication_id> \
         --operation <withdraw|restore|audit_delete> --approval <approval.json> \
         --reason <approved-reason> --site-metadata <metadata.json> \
         --production <public_dir> --base-url <https://origin.example>

No model call belongs in this loop. Upstream model ids appear only as worker attribution
backed by their pinned run ids; publish provenance records `model_id: null`.

## Done

    python -m newsab_publish verify-site <topics_root> <site_root> \
      --site-metadata <metadata.json> --production <public_dir>
    python -m newsab_publish cost-report <site_root> <publication_id>

Exit 0 means every publication hash and topic run restores, the event chain derives the
stored selector, catalogs reproduce from source records, the final bundle matches its
fingerprint, and a public/private scan is clean. Prepare mode ends with
`site/publications/<publication_id>/publication.json` and no new event; activate and
lifecycle also end with the fsynced event and matching atomic derived caches.
`cost-report` auto-discovers Claude Code/Codex and writes `site/audit/cost/`; dry-run
before backfill. Coverage qualifies totals; null-USD usage is telemetry no verifier reads.

## Stop and return upstream when

- Final bytes do not match the human-reviewed locale hash: back to render-localize, and
  any change means a new review.
- A run is missing, unrestorable or failing its deterministic check: back to the stage
  that owns that artifact; never repin or recompute around it here.
- The requested transition is illegal, its approval is absent, or another writer moved
  the event head: reload and require a fresh authorized operation; never force the cache.
- Any private/full-text byte appears in the closed bundle, or deterministic rebuilds
  differ: leave production untouched and report the exact path/hash.
