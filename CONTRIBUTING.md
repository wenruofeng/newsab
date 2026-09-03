# Contributing

English | [Chinese](CONTRIBUTING.zh-CN.md)

Thank you for improving the News A/B toolkit.

The public repository accepts bug and feature issues as well as small pull requests. It does
not accept any news-topic data, including suggestions and submissions (those go through the
web forms on news-ab.com).

Fork a clean copy from this repository before sending a pull request. Generating your own
reports is the other path: clone the repository directly, and that Git history should stay
only with you (see the README).

## Before submitting a pull request

1. New tests must use entirely synthetic outlets, URLs, sentences, and topic, publication,
   and run IDs. Do not turn a published topic into a fixture by deleting some fields.
2. Update the relevant package or skill documentation when behavior changes. Do not turn a
   one-off run record into a permanent method contract.
3. From the repository root, run:

   ```sh
   uv sync          # once per checkout; builds ./.venv from the root pyproject.toml
   uv run pytest    # the whole suite (packages + tests)
   ```

## DCO and licensing

This project uses an inbound-equals-outbound policy: your original contribution is provided
under the repository's MIT terms. Every commit must carry a Developer Certificate of Origin
1.1 sign-off:

```text
Signed-off-by: Your Name <your.email@example.com>
```

Use `git commit -s` to add it. The sign-off states that you have the right to submit the
change under this license. Do not present third-party code, images, fonts, data, or text as
your original work. If third-party material is necessary, the pull request must identify its
source and license, explain the required notices, and update `THIRD_PARTY_NOTICES.md`.

## One-way contribution bridge

At first, `public_export.yaml` deterministically generates the public repository from a
private operations repository. After approving a public pull request, a maintainer applies
the patch to the same paths in the private repository, preserves the author and public PR
URL, runs the full suite, and exports again. The PR is merged only when the exported tree
matches the proposed public tree. Do not rely on manual changes that exist only in generated
output and cannot return to their definition source.

Report security issues through the repository's private security-reporting channel. Never
paste secrets or exploitable private data into a public issue.
