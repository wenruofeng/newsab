# Third-party notices

Intended readers: public release operators and developers reusing the toolkit.

The News A/B toolkit's Python package metadata declares the following direct dependencies.
They are not relicensed as project-authored code under the repository's MIT `LICENSE`; each
remains subject to its upstream license.

| Project | Use | Upstream license |
|---|---|---|
| Pydantic | Schema validation | MIT |
| PyYAML | YAML parsing and writing | MIT |
| Apache Arrow / PyArrow (optional) | Optional Parquet output | Apache-2.0 |
| setuptools (build dependency) | Python package build backend | MIT |

The exporter does not vendor these dependencies into the public repository. The exact
versions installed by a package tool and the notices shipped with those distributions
remain authoritative. Before a public release adds a direct dependency, vendored code,
font, image, or demo dataset, this table must be updated and all upstream-required notices
must be retained.

`sources/registry.yaml` contains project-compiled factual outlet metadata, public URLs, and
collection notes. Outlet names and marks remain the property of their respective owners;
the registry contains and licenses no article body text. Every person, institution, URL,
reporting sentence, and run record in the synthetic demo is newly fictional and is not
adapted from a real news-ab.com topic or third-party report.

The neutral favicon and logo SVGs are original project-authored geometric placeholders.
The neutral social card is original project-authored output reproduced by
`tools/generate_neutral_assets.py` using only Python's standard library; it contains no
third-party font, photograph, icon, or production brand asset.
