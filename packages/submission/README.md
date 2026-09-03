# newsab-submission — pack, inspect and locally verify a topic submission

**Specified reader:** anyone building a submission archive from their own workspace, and
any agent changing the submission protocol, the pack closure, or the G0/G1/G2 gates.
Protocol version: `0.1.0`.

One topic's reviewed candidate run closure travels as a single `tar.gz` archive.  This
package is the contributor-facing half: everything here runs on your machine, needs no
site credential and calls no model. The site's invitation-only
upload, private operator pull, independent semantic audit and final human review remain
separate trust boundaries.

```bash
export PYTHONPATH=packages/schema:packages/corpus:packages/a1:packages/editorial:packages/publish:packages/submission

# Build the archive for a topic's active editorial (page) run:
python -m newsab_submission pack topics <topic_id> --out submission.tgz --json

# What the site's intake would do, in order, locally:
python -m newsab_submission inspect submission.tgz        # G0 only, streaming, no writes
python -m newsab_submission verify  submission.tgz --json # G0 + G1 + G2
```

Exit codes: `0` pass, `2` structured refusal (JSON `issues` with stable `code`s on
stdout), `1` unexpected error.  Run `verify` before uploading: the same deterministic
rules run on both sides, so a package that fails here would be refused there without a
human ever looking at it (plan §7.1).

## What `pack` puts in the archive — and what it refuses to

The closed file list is *computed* from the page run's manifest pins, never copied from
the topic directory:

- `submission.json` — the envelope, always the first member: protocol/toolkit versions,
  random `submission_id`, operation (`create` / `withdraw` — there is no revise; a
  corrected report is a withdraw plus a new create), sponsor display
  choice, terms version, source-responsibility statement, the seven pinned closure
  stages (scope → corpus → questions → answers → normalization → analysis → page), and
  the closed member table with per-file SHA-256.
- `topic/…` — the pinned run directories, the scope manifest, the manifest subset
  (the page run's ancestor entries, original lines verbatim), and exactly the articles
  the pinned corpus run references (its source snapshots, at their pinned content).
  `topic/corpus/topics_by_article.json` carries the derived public-safe keyword map;
  its private staging inputs stay home.
- `sources/registry.yaml` — the exact registry bytes the resolution used.

Refused by construction: executables, scripts, symlinks, HTML/CSS/JS, contributor-chosen
paths, staging files, the gold worksheet.  The page run's rendered `preview.*.html` are
recorded as `hash_only` members — hash on the record, bytes never in the archive; the
site rebuilds every displayable surface with its own renderer.

Everything in an archive is data.  No gate ever imports, installs, sources or executes
archive content, so a malicious member has nothing to hook (plan §6.2).

## The gates

| Gate | Question it answers | Failure |
|---|---|---|
| **G0** (`g0.py`) | Is the archive structurally safe to even extract?  Streaming caps on bytes, members, compression ratio; path normalization; regular files only; closed extension list; envelope first. | `G0_*`, before any write outside the work dir |
| **G1** (`verify.py`) | Is it exactly the closure it declares?  Envelope schema + protocol compatibility; member table ↔ bytes ↔ hashes; hash-only rules; import into a throwaway namespace; stage-8-equivalent resolution (`resolver.py`) recomputes every pin fingerprint; recomputed closure must equal the envelope's claim. | `G1_*`, structured |
| **G2** (`verify.py`) | Do the deterministic layers reproduce?  The trusted analyzer re-derives the findings and question stats from the archived inputs; the trusted renderer builds the candidate bundle twice and both fingerprints must agree. | `G2_*`, structured |

G2 recomputes with the thresholds recorded in the archived analysis run and refuses
(`G2_ANALYZER_UNSUPPORTED`) any analyzer version the current toolkit does not reproduce —
re-run the analyze stage and repack rather than guessing.

The prototype caps in `g0.ArchiveLimits` are deliberately generous and deliberately not
frozen (plan §10): production quotas are set in P4 from measured archive sizes.

## Layout

```
newsab_submission/
  envelope.py   protocol models: SubmissionEnvelope, member table, version compat
  closure.py    the closed file list, shared by pack and G1
  pack.py       deterministic tar.gz writer (fixed metadata; same inputs ⇒ same bytes)
  g0.py         streaming inspect / safe extract
  resolver.py   stage-8-mirror resolution with the hash-only overlay (parity-tested)
  verify.py     G1 + G2 + the verify report
  errors.py     SubmissionRefused with stable issue codes
tests/          public synthetic-topic fixture, round-trip/determinism, adversarial archives
```

`tests/test_bad_archives.py` is the adversarial suite — traversal, symlinks, zip-bomb
metadata, hash mismatches, missing runs, self-consistent tampered findings — and doubles
as the reference for what each error code means in practice.
