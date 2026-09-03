# Drafting the collection plan — targets, outlet mix, window rationale

Read this only when drafting the collection plan (core loop step 4): the plan is the half
of the sitting the user is really ruling on.

## Per side, in that side's own language

- **Search terms** — the namings that side's media actually use: policy name, that side's
  framings, affected parties, official responses. These seed the collect stage's
  `term_variant × group` matrix, so missing a naming here becomes systematic
  under-sampling there.
- **Candidate outlets**, each with `category` (`serious` / `other`) and `beat_scope`
  (`general` / `vertical`). Mark which ones
  `python -m newsab_corpus registry find --country <CC> --lang <lang>` already returns —
  and whether they carry a `channel` — versus which collect will have to register from
  scratch (the registry-gaps list).
- **Channels shown to work for that language**, or the plain statement that the channel
  is unproven. A plan whose thin side has no proven channel is predicting its own
  collection failure.

## Access policy — one row, ruled on here, applied to both sides

The collect stage fetches under a fixed identity and a fixed reading of what a host has
published about machines. That decision **belongs in this sitting**, because taken later
it is taken by whichever agent happens to be fetching, per outlet, invisibly — and it
moves which media end up in the sample. Write these three lines into the plan:

- **Identity** — the named research fetcher, in both the HTTP and browser layers. Not a
  vendor crawler token, not a disguised browser UA. Copy the exact string from the code
  that sends it (`python -m newsab_corpus fetch --show-identity`) rather than retyping it.
  Under it, the robots group that applies is `*` (RFC 9309), and **no rule addressed to
  `GPTBot` / `ClaudeBot` / `CCBot` is adopted** — see
  `skills/collect/references/fetch-extract.md` §1.
- **Retry rule** — every host that refuses the HTTP fetcher is retried in the Playwright
  browser; only a failure surviving both layers is recorded as one.
- **Retention row** — which of `fetch-extract.md` §1.5's rows this topic uses. The default
  is that table as written: full body everywhere except behind a purpose-addressed TDM
  reservation (`tdmrep` / `ai.txt` / `noai`), which is title + lead only.

Why it is a scope decision and not an etiquette detail: robots policy toward AI agents is
a **national publishing convention**, and it is not symmetric. In `aabb-market-meal-2024` the
German press had opted out collectively and the Turkish press had not, so a collector that
read those rules as addressed to itself deleted every German national daily and public
broadcaster from the sample — which a reader meets as "the German press covered this
less". The same policy on both sides, fixed here, is what keeps that from being a finding.

Anything with genuine legal weight — a topic where sources sit behind TDM reservations, or
where the retention row would move — is a user call in the sitting, not an agent's.

## The window rationale

Say *why* `period.start` sits where it does — normally the event that makes the topic a
topic — and check the window is answerable on **both** sides: a window in which one side
had not yet begun reporting produces a collection artefact that reads as an attention
gap. `period.end` stays null while the topic is live.

## Targets — adaptive, denominated in clusters

Every prevalence statement divides by **independent reporting clusters**, and instance
counts sit far from cluster counts (40 articles that are 34 copies of one wire story are
7 clusters). Provisional defaults, pending calibration:

| tier | target |
|---|---|
| independent clusters per group (`target_clusters_per_group`) | ≥ 20 |
| `serious`-category independent clusters per group | ≥ 6 |
| `other`-category independent clusters, where the category occurs | ≥ 4 |
| publication instances per group | 25–40 — over-collect the side you expect to be wire-homogeneous |

These are targets collect aims at and may miss **with a reason**: a shortfall is a
conclusion, not a failure — the page marks a thin category "sample too small to compare",
and a whole silent group is a silence statement. A side expected to produce near-zero
independent coverage goes in `expected_silence` up front, making silence the finding
rather than a sampling failure. `newsab_corpus build` prints the `thin:` / `silence:`
lines that say which is which.
