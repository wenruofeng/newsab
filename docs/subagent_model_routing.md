# Sub-agent model routing

This is the repository-wide, vendor-neutral recommendation for deciding whether to
delegate work to a language-model sub-agent and, if so, what capability class to use.
It applies to Claude Code, Codex and contributor harnesses alike.

This document is a **routing recommendation, not a gate**. The delegating agent owns the
decision. A pipeline stage is an artifact boundary, not a mandatory model invocation;
the agent may run a stage itself, split it into bounded workers, or use no LLM at all.
Skills define the work and its artifact contract. They deliberately do not select models.

## Capability classes

| Class | Meaning | Selection rule |
|---|---|---|
| `deterministic` | No LLM. Plain code or a tool performs the work. | Use whenever the result is fully computable or mechanically checkable without semantic judgement. |
| `economy` | Small/cheap model for narrow, repetitive, structured work. | Use only when inputs and output schema are bounded and a script or focused review catches common failures. |
| `standard` | Default model for semantic, multilingual, tool-using and ordinary implementation work. | Use for any LLM task not clearly covered by `economy` or the two default-`advanced` tasks below. |
| `advanced` | Highest-capability model for editorial synthesis or a demonstrated hard failure. | Use by default for `write` and for `annotate` question-set design (responsibilities 5 and 10 — both are one-shot, high-leverage framing work); otherwise only after a `standard` attempt exposes an escalation trigger. |

The classes describe capability, not a vendor or product name. Use your best judgement to 
choose the least expensive available model that credibly meets the class. Record the actual 
model ID in provenance and reports; do not commit a vendor-specific mapping as policy.

## The 14 recurring responsibility classes

| # | Responsibility | Recommendation | Boundary |
|---|---|---|---|
| 1 | Orchestration and delegation planning | `standard` | Coordinate artifacts and bounded workers. Escalate only for a cross-stage design conflict or repeated hard failure. |
| 2 | `scope` enrichment | `standard` | One topic's comparison, window, collection plan and seed questions. The user remains in the sitting; a background sub-agent is optional. |
| 3 | `collect` discovery | `standard` | One side's query matrix, source discovery, inclusion decisions and failure log. Split by side when useful. |
| 4 | `collect` extraction and staging | `economy` when URLs and extraction boundaries are fixed; otherwise `standard` | Preserve publisher text verbatim and stage records; deterministic build follows. |
| 5 | `annotate` question-set design | `advanced` | One topic's template and reader-tier questions plus category guidance. |
| 6 | `annotate` cluster answers | `economy` | A bounded cluster list; read every member article, answer every active question, emit one checked batch. |
| 7 | Cross-batch category normalization | `standard` | Compare all batch tallies for one topic, merge only semantic duplicates, then assemble. |
| 8 | `analyze` computation | `deterministic` | Run `newsab_a1 qa`; no LLM computes or changes the result. |
| 9 | `analyze` semantic sanity read | `standard` | Inspect the top findings against a small anchor sample and route defects upstream; do not re-judge arithmetic. |
| 10 | `write` | `advanced` | One topic's English master: hook, storyline, claims, quotes and reader-facing framing. |
| 11 | Mechanical page checking and rendering | `deterministic` | Run the checkers and renderer; an LLM does not substitute for an exit code. |
| 12 | Localization | `standard` | Localize the complete page and preserve quantity, meaning and provenance. |
| 13 | Independent spot-check judge | `standard` | Read only the judge packet and emit the rubric JSON. Independence comes from that bounded input, not from the vendor — the writer's own model is allowed, and the model that ran is recorded. |
| 14 | Publish/package | `deterministic` | Pin runs and build the public bundle. Use an LLM only if a separate implementation defect must be diagnosed. |

**Incremental answer passes (responsibility 6) that extend an existing answers run must
keep that run's judgement conventions, and model class is a proxy for those.** Default to
the class the inherited answers were written at. Switching class is allowed, but only
after proving parity: re-answer a small overlap of already-answered clusters at the new
class and compare addressed rates and category choices (the per-shard table in
`qa_batch.py check` is the instrument) before mixing the two in one run. An unproven
switch shows up downstream as an addressed-rate shift that analyze cannot tell from an
attention gap.

For repository work outside these fourteen recurring pipeline responsibilities, start at
`standard`. Use `economy` only for a narrowly specified, reversible change with strong
tests. Use `advanced` only after the escalation rules below are met.

## When to delegate

Delegation is useful when it buys at least one of: independent context, parallel work on
disjoint artifacts, a bounded repetitive shard, or a genuinely independent review. It is
usually unnecessary for a short deterministic command, a tightly coupled local edit, or
work whose context-transfer cost is larger than the task.

There is no required number of sub-agents per stage. If work is sharded, every worker gets
an explicit input set, output path, self-check and stop condition. A designated integrating
agent owns cross-shard consistency; parallel workers do not silently normalize one
another's output.

## Escalation to `advanced`

Try `standard` first. Escalate only the unresolved task or shard when
one of these is observed:

- the standard attempt exposes a real conflict across schemas, stages or standing decisions;
- repeated validator-clean outputs remain semantically wrong against their anchors;
- a multilingual ambiguity changes the claim, category or denominator and cannot be
  resolved from the source-local rubric;
- a debugging task remains unresolved after the standard agent has isolated the failure
  and recorded the evidence;
- the change has broad architectural blast radius and competing valid designs must be
  reconciled.

Do not escalate merely because a task is long, important, or has many files. Split bounded
work first. Do not rerun a clean batch with a stronger model just for reassurance.

If different models contribute semantic judgements to one assembled run, provenance must
describe that truthfully. Until the relevant artifact supports per-batch or per-record
model provenance, prefer one actual model for all semantic shards in that run rather than
recording a misleading single `model_id`.
