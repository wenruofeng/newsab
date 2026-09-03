# News A/B comparison report generator

English | [中文](README.zh-CN.md)

![](title.png)

Clone this repository, open your AI agent (Codex / Claude Code), and tell it the news topic
you are interested in and the two media groups you want to compare. Your agent can then use
the included skills and Python scripts to generate, locally, a news-comparison report
webpage in which every conclusion is auditable down to the source sentence and
statistically checked. The finished product looks like this:

[news-ab.com](https://news-ab.com/)

What this repository shares is the reusable AI workflow behind news-ab.com. The Python
packages and scripts still carry News A/B or `newsab` in their names, but this repository
has no operational relationship with the website and contains none of its data.

## How a report is made

The workflow arranges the sampled reporting into a shared question × answer model: it
first clusters duplicate reporting (reprints) into independent reporting groups, then asks
both media groups the same set of questions, compares answer rates and answers, and in the
end reports only findings that trace back to verbatim source sentences and carry a measure
of statistical support.

Deterministic work (such as checks and statistics) is done by code. The semantic parts of
collection, questioning, annotation, writing, and self-review are done by AI. The initial
collection-scope confirmation and the final page each get one human review.

The process is not linear: the main agent decides for itself, from stage artifacts and
code feedback, whether to advance, rework, delegate to subagents, or request additional
human review.

| Step | Actor | Output or decision |
|---|---|---|
| 0. input | user | rough scope: topic + A/B media grouping |
| 1. scope | AI | collection plan and reference questions |
| 1.5 human touchpoint 1 | user | confirm the collection scope; review the reference questions |
| 2. collect | AI/code | balanced per-side collection, sentence corpus, independent reporting groups |
| 3. annotate | AI | pose the questions; subagents annotate answers with sentence-level evidence |
| 3.5 normalize | AI/code | answer categories unified across sides and batches |
| 4. analyze | code | answer-rate and answer comparisons, statistical tests and confidence intervals |
| 5. write | AI | English master page copy, constrained by the statistical results |
| 6. render + localize | AI/code | page checks, subagent self-review, translation into the review language |
| 7. human touchpoint 2 | user | review the candidate page; comments route back to the responsible step |
| 8. publish | code | frozen static report (optional multi-language release) |

### Cost per run

Current rough average cost of one full topic report:

| Active agent time | Model requests | Total tokens | At API list prices |
|---|---|---|---|
| ~3–4 hours | ~500–1300 | ~160M | ~$100–150 |

"Active time" excludes waiting for human review. The vast majority of the tokens are
input. **We recommend running on a subscription plan rather than an API key.** On the
most basic subscription plans, waiting out rate limits along the way can stretch the
elapsed time to 2–3 five-hour quota windows.

## Getting started

Open the clone with an agent that reads `AGENTS.md` or `CLAUDE.md`, then ask it to
configure the workspace and generate a report. For example:

> Configure this News A/B workspace for me, then create a comparison report about
> `<topic>`, comparing coverage from `<group A>` and `<group B>`.

On first run, the agent asks for your public website and contact email and writes them to
your own local file `.newsab/operator_identity.json` (gitignored). This information is used
only while your agent collects news with the programmatic web-browsing tools: the code
presents the visitor's identity to news sites as required (that visitor should be you, not
some company's agent). Until the identity is configured, the collection tools refuse
network access. On first run, the agent also installs the required environment (Python
3.10+) and runs the offline acceptance gate:

```sh
uv sync
uv run python tools/public_release_gate.py
```

## Package a finished report

If you would like the News A/B website to consider publishing a complete report you
generated locally, ask the agent to package it, then submit it on news-ab.com. An uploaded
submission is published once it passes human review.

The submission package is verified locally first:

```sh
uv run python -m newsab_submission pack topics <topic_id> --out submission.tgz --json
uv run python -m newsab_submission inspect submission.tgz --json
uv run python -m newsab_submission verify submission.tgz --json
```

The package contains verbatim snapshots of the news sources and must stay private. Do not
put it in a GitHub issue, pull request, release, or email.

## Data and contribution boundary

Do not put article archives, credentials, personal data, or submissions in GitHub issues,
pull requests, or releases.

What each report run produces is committed to your own local clone by the AI — that
history is the key to agents working together across sessions. The article text itself
stays out of Git, but the small run records quote source sentences verbatim. So either
keep the clone on your own machine, or push it to a private repository you created and
control. When you want to contribute code, fork a clean copy from this repository then.

Code and documentation contribution rules are in [`CONTRIBUTING.md`](CONTRIBUTING.md); the
licensing boundary is in [`LICENSE_SCOPE.md`](LICENSE_SCOPE.md).
