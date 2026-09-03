"""Persisting the feature matrix, and reconstructing it for recomputation.

§3.3 A1 says the matrix is stored as parquet.  It is, when ``pyarrow`` is importable;
otherwise the same rows are written as CSV and the run record says which happened.  The
important property is not the container: it is that ``a1_run_id`` is derived from a
**canonical JSON serialisation of the rows**, so the hash — and therefore every audit
claim built on it — is identical whichever format was written.
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Optional

from newsab_schema.models.analysis import Feature

from .features import ClusterMeta, FeatureMatrix, sort_key

COLUMNS = [
    "group_id",
    "cluster_id",
    "category",
    "category_mixed",
    "dimension",
    "concept_id",
    "attr_key",
    "attr_value",
    "observations",
    "articles",
]


def _pyarrow():
    """Import pyarrow, or return ``None``.

    The probe is silenced because a *broken* pyarrow (built against a different NumPy, say)
    prints a C-level warning block to stderr before raising, which would look like a
    pipeline failure in the middle of a successful run. The fallback is recorded in the run
    record instead, where it belongs.
    """
    import contextlib
    import io

    try:  # pragma: no cover - environment dependent
        with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            import pyarrow  # noqa: F401
            import pyarrow.parquet  # noqa: F401

        return pyarrow
    except Exception:
        return None


def rows_digest(rows: list[dict]) -> str:
    """``sha256:<hex>`` over canonical JSON — format-independent by construction."""
    payload = json.dumps(rows, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"


def write_matrix(matrix: FeatureMatrix, run_dir: Path) -> dict:
    """Write the matrix and everything needed to rebuild it.  Returns a storage record."""
    run_dir.mkdir(parents=True, exist_ok=True)
    rows = matrix.rows()

    pa = _pyarrow()
    if pa is not None:  # pragma: no cover - environment dependent
        import pyarrow.parquet as pq

        table = pa.table({column: [row[column] for row in rows] for column in COLUMNS})
        pq.write_table(table, run_dir / "feature_matrix.parquet")
        written = "feature_matrix.parquet"
        fmt = "parquet"
    else:
        with open(run_dir / "feature_matrix.csv", "w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
        written = "feature_matrix.csv"
        fmt = "csv"

    (run_dir / "clusters.json").write_text(
        json.dumps(
            {cid: meta.to_dict() for cid, meta in sorted(matrix.clusters.items())},
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (run_dir / "support_observations.json").write_text(
        json.dumps(
            {
                "|".join(str(part) for part in key) + "||" + cluster_id: sorted(obs)
                for (key, cluster_id), obs in sorted(
                    matrix.support_observations.items(),
                    key=lambda item: (sort_key(item[0][0]), item[0][1]),
                )
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    return {
        "format": fmt,
        "file": written,
        "rows": len(rows),
        "rows_digest": rows_digest(rows),
        "parquet_available": pa is not None,
    }


def read_matrix(run_dir: Path) -> FeatureMatrix:
    """Rebuild the matrix from a stored run — the basis of §4.4.1 invariant 1."""
    run_dir = Path(run_dir)
    parquet = run_dir / "feature_matrix.parquet"
    csv_path = run_dir / "feature_matrix.csv"

    if parquet.exists():  # pragma: no cover - environment dependent
        import pyarrow.parquet as pq

        rows = pq.read_table(parquet).to_pylist()
    elif csv_path.exists():
        with open(csv_path, encoding="utf-8", newline="") as fh:
            rows = list(csv.DictReader(fh))
        for row in rows:
            row["observations"] = int(row["observations"])
            row["articles"] = int(row["articles"])
            row["category_mixed"] = row["category_mixed"] in ("True", "true", "1")
            for optional in ("concept_id", "attr_key", "attr_value"):
                row[optional] = row[optional] or None
    else:
        raise FileNotFoundError(f"no feature matrix in {run_dir}")

    clusters_raw = json.loads((run_dir / "clusters.json").read_text(encoding="utf-8"))
    run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))

    matrix = FeatureMatrix(
        topic_id=run["topic_id"],
        ontology_version=run.get("ontology_version"),
        clusters={cid: ClusterMeta(**_tuplify(meta)) for cid, meta in clusters_raw.items()},
    )
    for row in rows:
        feature = Feature(
            dimension=row["dimension"],
            concept_id=row["concept_id"] or None,
            attr_key=row["attr_key"] or None,
            attr_value=row["attr_value"] or None,
        )
        matrix.features.setdefault(feature.key, feature)
        matrix.cells[(feature.key, row["cluster_id"])] = int(row["observations"])

    support_path = run_dir / "support_observations.json"
    if support_path.exists():
        for packed, obs in json.loads(support_path.read_text(encoding="utf-8")).items():
            key_part, cluster_id = packed.split("||")
            parts = key_part.split("|")
            key = (parts[0],) + tuple(p if p != "None" else None for p in parts[1:])
            matrix.support_observations[(key, cluster_id)] = obs

    return matrix


def _tuplify(meta: dict) -> dict:
    out = dict(meta)
    out["source_ids"] = tuple(out["source_ids"])
    out["article_ids"] = tuple(out["article_ids"])
    return out
