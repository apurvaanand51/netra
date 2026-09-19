"""
Distribution drift -- does this batch look like the data the model was trained on?

WHY THIS EXISTS
---------------
A model is a statement about the data it was trained on. Feed it a batch from a
different world -- a new exchange, a shift in traffic mix, a feed that started
reporting a new field -- and it will still return confident scores. Nothing in
the pipeline would notice, and the scores would be quietly meaningless.

So we compare each batch's feature distribution against the training
distribution, and report when they have diverged. The point is not to block the
analysis; it is to let the tool say **"this looks unlike what I was trained on,
so trust these scores less"** -- which is a sentence the console otherwise could
not produce at all.

TWO MEASURES, BECAUSE THEY FAIL DIFFERENTLY
-------------------------------------------
**Population Stability Index** answers "how much has the shape moved?" It bins
both distributions on the TRAINING deciles and sums the symmetric difference in
proportions. It is the standard in credit risk for exactly this job, it is
interpretable, and it is bounded by the bins we chose.

    PSI < 0.10   no meaningful shift
    0.10 - 0.25  moderate shift; worth knowing
    > 0.25       significant shift; the model is being asked about a different world

**Kolmogorov-Smirnov** answers "could these two samples plausibly be the same?"
It is a hypothesis test on the continuous values, so it catches a shift that
lands inside one bin and that PSI's binning would smooth away.

Neither alone is enough. PSI can miss a shift confined to one bin; KS can flag a
trivial difference as significant on a large sample. So a feature is reported as
drifted only when the two AGREE, and both numbers are printed so a reader can
overrule the combination.

WHAT IS DELIBERATELY NOT DONE
-----------------------------
We do not auto-retrain, and we do not adjust the scores. A drift warning is
information for an operator; wiring it to an automatic action would let a
distribution shift silently change what the tool means.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

# Interpretation bands, stated here rather than in the reporting code so the
# thresholds cannot drift away from the module that defines what they mean.
PSI_MODERATE = 0.10
PSI_SIGNIFICANT = 0.25

# A KS p-value below this means the two samples almost certainly differ. Set low
# on purpose: with thousands of rows, even a trivial difference is statistically
# significant, and we do not want to cry drift over it.
KS_ALPHA = 0.01

# How many reference values to keep so KS can run later. Bounded because the
# reference ships inside the model artifact, and an artifact that grows with the
# training set is an artifact nobody wants to move between machines.
REFERENCE_SAMPLE = 500

# Bins are deciles of the training distribution.
_BINS = 10


def fit_reference(matrix: np.ndarray, feature_names: list[str]) -> dict[str, Any]:
    """Describe each feature's training distribution.

    Stores the decile edges (for PSI), the counts per bin, and a bounded sample
    (so KS can be run later without keeping the training set). Small enough to
    travel inside the model artifact, which is what makes the comparison possible
    on a machine that never saw the training data.
    """
    values = np.asarray(matrix, dtype=float)
    features: dict[str, Any] = {}

    for index, name in enumerate(feature_names):
        column = values[:, index]
        column = column[np.isfinite(column)]
        if column.size == 0:
            features[name] = {"edges": [], "counts": [], "sample": []}
            continue

        edges = np.quantile(column, np.linspace(0, 1, _BINS + 1))
        # Duplicate edges (a constant or near-constant feature) would make a
        # zero-width bin, and PSI divides by bin proportions.
        edges = np.unique(edges)
        counts = np.histogram(column, bins=_edges_for(edges))[0]

        sample = column if column.size <= REFERENCE_SAMPLE else np.random.default_rng(42).choice(
            column, REFERENCE_SAMPLE, replace=False,
        )
        features[name] = {
            "edges": [float(edge) for edge in edges],
            "counts": [int(count) for count in counts],
            "median": float(np.median(column)),
            "sample": [float(value) for value in np.sort(sample)],
        }

    return {"features": features, "n_rows": int(values.shape[0]), "bins": _BINS}


def _edges_for(edges: np.ndarray) -> np.ndarray:
    """Make the first and last bin open-ended, so values outside the training
    range are counted rather than dropped -- an out-of-range value is precisely
    the signal we are looking for."""
    if edges.size < 2:
        return np.array([-np.inf, np.inf])
    return np.concatenate([[-np.inf], edges[1:-1], [np.inf]])


def compare(reference: dict[str, Any], matrix: np.ndarray, feature_names: list[str]) -> dict[str, Any]:
    """Compare a batch against the training distribution, feature by feature."""
    values = np.asarray(matrix, dtype=float)
    rows: list[dict[str, Any]] = []

    for index, name in enumerate(feature_names):
        entry = reference.get("features", {}).get(name)
        if not entry or len(entry.get("edges", [])) < 2:
            continue

        column = values[:, index]
        column = column[np.isfinite(column)]
        if column.size == 0:
            continue

        edges = np.array(entry["edges"], dtype=float)
        expected = np.array(entry["counts"], dtype=float)
        actual = np.histogram(column, bins=_edges_for(edges))[0].astype(float)

        # Proportions, floored so a bin with no members cannot divide by zero.
        # The floor is small enough not to mask a real appearance, and the
        # alternative (dropping empty bins) would hide the most interesting case:
        # a bin the training data had and this batch does not.
        expected_pct = np.maximum(expected / max(expected.sum(), 1), 1e-6)
        actual_pct = np.maximum(actual / max(actual.sum(), 1), 1e-6)
        psi = float(np.sum((actual_pct - expected_pct) * np.log(actual_pct / expected_pct)))

        ks_statistic, ks_pvalue = _ks(entry.get("sample", []), column)
        drifted = bool(
            psi > PSI_MODERATE and (ks_pvalue is None or ks_pvalue < KS_ALPHA)
        )

        rows.append({
            "feature": name,
            "psi": round(psi, 5),
            "ks_statistic": None if ks_statistic is None else round(ks_statistic, 5),
            "ks_pvalue": None if ks_pvalue is None else round(ks_pvalue, 6),
            "drifted": drifted,
            "reference_median": entry.get("median"),
            "current_median": float(np.median(column)),
        })

    drifted = [row["feature"] for row in rows if row["drifted"]]
    by_psi = sorted(rows, key=lambda row: -row["psi"])
    return {
        "features": rows,
        "drifted_features": drifted,
        "drifted_count": len(drifted),
        "worst_feature": by_psi[0]["feature"] if by_psi else None,
        "max_psi": by_psi[0]["psi"] if by_psi else None,
        "verdict": _verdict(rows),
        "psi_thresholds": {"moderate": PSI_MODERATE, "significant": PSI_SIGNIFICANT},
        "ks_alpha": KS_ALPHA,
    }


def _ks(sample: list[float], column: np.ndarray) -> tuple[float | None, float | None]:
    """Two-sample Kolmogorov-Smirnov, if scipy is available.

    Optional on purpose: the drift check must not become a hard dependency of the
    pipeline, because a missing statistics library should degrade the report, not
    stop the analysis.
    """
    if not sample:
        return None, None
    try:
        from scipy.stats import ks_2samp
    except ImportError:  # pragma: no cover - scipy ships as a sklearn dependency
        return None, None
    result = ks_2samp(np.asarray(sample, dtype=float), column)
    return float(result.statistic), float(result.pvalue)


def _verdict(rows: list[dict[str, Any]]) -> str:
    """One sentence an operator can act on, not a code."""
    if not rows:
        return "not measured"
    drifted = [row for row in rows if row["drifted"]]
    worst = max(rows, key=lambda row: row["psi"])
    if drifted:
        return (
            f"{len(drifted)} feature(s) shifted beyond the training range "
            f"(worst: {worst['feature']}, PSI {worst['psi']:.3f}). Standard "
            "confidence in these scores is not warranted."
        )
    if worst["psi"] > PSI_MODERATE:
        return (
            f"Moderate shift in {worst['feature']} (PSI {worst['psi']:.3f}), which "
            "is worth knowing but does not invalidate the batch."
        )
    return "This batch resembles the training distribution."


def save_reference(reference: dict[str, Any], path: Path | str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(reference), encoding="utf-8")


def load_reference(path: Path | str) -> dict[str, Any] | None:
    path = Path(path)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def format_report(report: dict[str, Any], limit: int = 6) -> str:
    """A console-readable summary. The worst features first, because that is the
    order someone would act on them."""
    lines = [
        "",
        "  ==================== distribution drift ====================",
        f"  {report['verdict']}",
        "",
        f"  {'feature':<26} {'PSI':>8} {'KS p':>10}  verdict",
        "  " + "-" * 56,
    ]
    for row in sorted(report["features"], key=lambda item: -item["psi"])[:limit]:
        pvalue = "—" if row["ks_pvalue"] is None else f"{row['ks_pvalue']:.4f}"
        mark = "DRIFTED" if row["drifted"] else ("shift" if row["psi"] > PSI_MODERATE else "stable")
        lines.append(f"  {row['feature']:<26} {row['psi']:>8.4f} {pvalue:>10}  {mark}")
    lines += [
        "",
        "  A feature is called drifted only when PSI and KS AGREE: PSI alone can",
        "  miss a shift inside one bin, and KS alone flags trivial differences as",
        "  significant on large samples.",
        "  ============================================================",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":  # pragma: no cover - convenience entry point
    import sys

    from ingestion.load import load_any
    from ml.cluster import detect_coinjoin_like
    from ml.features import FEATURE_COLUMNS, build_feature_table, feature_matrix
    from ml.graph import analyse_graph
    from ml.patterns import all_structural_features
    from monitoring.pipeline import split_into_windows

    root = Path(__file__).resolve().parent.parent
    reference = load_reference(root / "models" / "reference_distribution.json")
    if reference is None:
        print("no reference distribution found; run 'python -m ml.train' first")
        raise SystemExit(1)

    frame, _ = load_any(root / "data" / "transactions.csv")
    windows = split_into_windows(frame, root / "data" / "windows", prefix="drift-probe")
    for label, path, _start, _end in windows:
        batch, _ = load_any(path)
        mask = detect_coinjoin_like(batch)
        from correlation.engine import correlate
        corr = correlate(batch, coinjoin_mask=mask)
        structural = all_structural_features(corr, batch, mask)
        table = build_feature_table(corr, batch, mask, graph=analyse_graph(corr, structural))
        report = compare(reference, feature_matrix(table), FEATURE_COLUMNS)
        print(f"\n{label}: max PSI {report['max_psi']}, drifted {report['drifted_count']}")
        print(format_report(report, limit=4))
