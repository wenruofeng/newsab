# AGENTS.md — Repo Contract for AI Agents

Shared operating contract for every AI agent in this repo (Claude Code, Codex, any
contributor's agent). When `CLAUDE.md` is present, it mirrors this file for harness
discovery.

## 1. What this repo is

A free, AI-produced + human-audited website generator showing how two groups of media (usually two
countries, in their own languages) tell the same story differently — consensus,
divergence, blindspots — with every statement clickable down to verbatim source sentences.

**Canonical spec: [`docs/value_chain.md`](docs/value_chain.md).** Read it before building
anything; it defines the product, the Q×A comparison model, the 8-stage chain, the two
human touchpoints, and the non-negotiables. It wins over everything else, this file
included. `docs/archive/` is history — do not read it without a specific reason.

## 2. Session protocol

The repo is the only memory shared between agent sessions.

- **Start**: read `TODO.md`; `git status` / `git log --oneline -10`.
- **Work**: take the highest-priority unblocked task; mark it `[~]` with your agent name.
  New discoveries become TODO items, not silent scope expansion.
  If a doc conflicts with reality, fix the doc in the same change. Every doc needs a named reader ("which stage's
  agent must read this?"): one with no reader is not written, a stale one is archived
  immediately, and a lesson goes into the relevant skill, not into a new doc.

- **End**: write `docs/reports/task_<YYYYMMDDHHMM PT>_<name>.md` (template:
  `docs/reports/README.md`); update `TODO.md` (finished → `[x]` + report link, stale
  items deleted, new follow-ups added); summarize in chat.
- **Git**: work on `main` unless asked otherwise; commit in meaningful units; never
  amend/rebase another agent's commits; never edit another agent's report — write a new
  one that links back.
- Reports are append-only history. Read the newest one or two only when you need to know
  what just happened; never read the backlog wholesale.

## 3. Language policy

| Artifact | Language |
|---|---|
| Code, comments, identifiers, schema fields/enums | English (free text carries `lang`) |
| Agent-facing docs (this file, `docs/value_chain.md`, `skills/**`, schemas) | English |
| User-facing docs (`TODO.md`, `docs/decisions.md`, `docs/reports/**`, chat) | User's language of choice |
| Collection and verbatim evidence | the source's own language |
| Q×A summaries, normalized categories, comparison writing | English pivot |
| Reader/reviewer-facing output (render + localize) | per-reader/reviewer language |

## 4. Repo layout

```
AGENTS.md            this contract        CLAUDE.md mirrors it for Claude discovery
TODO.md              work queue (User's lang) — only "what's next"
sources/registry.yaml  cross-topic outlet registry (append-only, never a gate)
docs/
  value_chain.md     CANONICAL SPEC — product, Q×A model, stages, non-negotiables
  decisions.md       still-binding conclusions that have no other home yet (User's lang)
  artifact_versioning.md  write protocol: article store / run records / active pointers
  archive/           superseded history — do not read by default
  reports/           task_<ts>_<name>.md, append-only
packages/            plain Python, no model calls (schema / corpus / a1 / editorial / publish / submission)
skills/              pipeline skills, one dir per stage — registry in skills/README.md
topics/              per-topic artifacts; corpus stores and stage-6 previews are
                     gitignored — on disk, never in git, never deleted (see below)
tests/               cross-package integration
```

### Python environment: one per checkout, never shared

This checkout owns its interpreter: the root `pyproject.toml` is a
[uv](https://docs.astral.sh/uv/) workspace whose members are every `packages/*`, and
`uv sync` creates or refreshes `.venv/` (gitignored) beside it. **Prefix every command
with `uv run`** — `uv run pytest`, `uv run python -m newsab_publish …` — and it runs in
this checkout's environment with all packages importable; skill scripts bootstrap
`sys.path` themselves and work either way.

- **Never install into a shared interpreter** (a system or base conda Python, another
  checkout's venv): `pip install -e` writes a global import finder into whichever
  interpreter runs pip, so one install from a throwaway worktree silently re-points *every*
  session on the machine at that worktree — this has happened here and cost hours. No
  shared interpreter should hold a `newsab_*` install, so a bare `python -m newsab_*`
  outside `uv run` fails loudly instead of running foreign code.
- A worktree or clone gets its own environment by running `uv sync` inside it (seconds;
  uv hard-links a shared cache). Working there, `uv run` from that directory is enough.
- If a module's behaviour ever disagrees with the source in front of you, check where it
  resolves before suspecting the code:
  `uv run python -c "import newsab_publish as m; print(m.__file__)"`.

Tests: `uv run pytest` — the full suite (`packages tests`, per `pytest.ini`) is the commit
gate; for a fast feedback loop use `uv run pytest -m "not repo_artifact and not cli_e2e"`
(lanes: `pytest.ini`).

### Local website preview and human review

One command, from the repo root, is the user/reviewer's entry point for both touchpoints:

    uv run python -m newsab_publish dev-serve

It prints a map of loopback ports (dashboard at `http://127.0.0.1:8787/`) and holds until
`Ctrl+C`. Add `--preview <dir>` to index a `review-preview` output. Details:
[`packages/publish/README.md`](packages/publish/README.md).

- **Never wrap `dev-serve` (or any process whose job is to stay alive) in a `timeout`.**
  Measured: one run wrapped it in `timeout 900`, and the review server was killed before
  the reviewer ever opened the link — the process's whole purpose was to outlive that turn.

- **Never hand a human a file path.** Production pages use root-relative URLs
  (`/zh-CN/topics/...`) and link the site chrome at `/assets/…`, so `file://` breaks them
  and a candidate bundle has no chrome beside it at all. Any step that ends in human
  review ends with a server running and a clickable `http://127.0.0.1:…` link.
- Never edit the derived `site/public/` tree to make file URLs work. If it is missing or
  stale, rebuild and verify it per `packages/publish/README.md`.
- **Large bytes live on disk, not in git, and are never deleted.** `site/public/**`,
  `site/publications/*/bundle/**`, the stage-6 `preview.*.html` files and the corpus
  stores are gitignored; git keeps the small records that carry their hashes, and every
  verifier hashes the disk. Paths never move — read them where they always were.
  Protocol and the full rule: [`docs/artifact_versioning.md`](docs/artifact_versioning.md) §7.
- Stage-6 previews are **intermediate artifacts, not a review surface.** Touchpoint two
  happens on the publish stage's candidate (`review-preview`), which is the only thing a
  human ever approves; the dashboard neither lists nor serves the stage-6 files. They stay
  on disk under §7's never-delete rule. To put a stage-6 page in front of a human, render
  a candidate from its page run and serve that.

## 5. Skills and delegation

One pipeline stage = one skill dir = one artifact boundary. You are authorized by the user 
to make a subagent call to delegate any pipeline stage where you find reasonable: you decides 
whether/when/where to run it directly, delegate it to a subagent, split bounded shards, 
or use no LLM. Whenever delegating to a language-model subagent, consult the vendor-neutral 
routing recommendation in [`docs/subagent_model_routing.md`](docs/subagent_model_routing.md) 
and put the recommended capability class in the task. Skills stay decoupled from model selection.

Stages communicate only through on-disk artifacts. Skills are harness-neutral (plain
Markdown + scripts); anything checkable is a script, not prose. Packaging contract and
registry: [`skills/README.md`](skills/README.md). One directory per value-chain stage:
`scope` / `collect` / `annotate` / `normalize` / `analyze` / `write` / `render-localize` / `publish`
(stage 7 is the human review). Retired skills sit in
`skills/archive/`, kept only because Phase 0 runs name them in `skill_id`.

## 6. You are in a public clone

This repository is a standalone copy of the toolkit, assembled from one exact commit of a
private operating repository.  Nobody upstream can see this clone, and nothing in the
toolkit writes outside it.  Sections 1-5 apply here unchanged; this section is the part
that is true only here, and it is where the user's own boundary lives.

### First run: the collector identity

Before any network collection, inspect
`packages/corpus/newsab_corpus/data/operator_identity.v1.json`. A public starter copy has
`configured: false`; it deliberately contains neither the website owner's identity nor a
fake contact. Ask the user for both of these public, collector-facing values:

- a website URL that explains who operates this collector;
- an email address where publishers can reach that operator.

Write them to `.newsab/operator_identity.json` using the same schema and set
`configured: true`. This local file is gitignored and is the only supported identity
override. Never infer these values and never use `news-ab.com` or its operator's contact
details unless that operator is actually the user running this clone. Collection refuses
to make network requests until the identity is configured. The Python package and command
names remain News A/B / `newsab`; that name does not imply an operational relationship
with news-ab.com.

### The user's work stays where the user put it

§2's Git protocol applies in full — commit in meaningful units, because those commits are
how the next session knows what this one did. It stops at this machine. Do not add a Git
remote, do not `git push`, and never put topic artifacts in a pull request: run records
quote publisher sentences verbatim, and where those bytes go is a decision the user makes
explicitly, not a step in your workflow. If the user asks you to publish their work, say
what the history contains before you help them do it.

Improving the toolkit itself is the one thing that travels upstream, as public code paths
only and never as topic artifacts: [`CONTRIBUTING.md`](CONTRIBUTING.md).
