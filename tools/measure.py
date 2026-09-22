"""
Measure the system, on every parameter that can be measured from inside it.

WHY THIS FILE EXISTS
--------------------
A report that quotes numbers nobody can reproduce is a marketing document. Every
figure in `docs/LEARNING_GUIDE.md` and `docs/V1_V2_REPORT.md` comes from running
this, so the two cannot drift: re-run it and either the numbers match or the
document is wrong and you have just found out which.

    python tools/measure.py                 # measure and print a report
    python tools/measure.py --json out/measurements.json

WHAT IT MEASURES, AND WHAT IT REFUSES TO
----------------------------------------
It measures only things that can be MEASURED here: row counts, byte sizes,
seconds, and the values the trained artifacts already recorded. It does not
estimate, extrapolate, or fill in a cell it could not compute -- a missing
measurement prints as `not measured` with the reason, because a plausible-looking
number that nobody computed is worse than a blank.

Timings are wall-clock on whatever machine runs it, so they are reported with the
row count they were measured over. They are evidence of an order of magnitude and
of the SHAPE of the cost (linear vs quadratic), not a benchmark.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

RESULTS: dict[str, Any] = {}
NOTES: dict[str, str] = {}


def section(name: str) -> None:
    print(f"\n{'=' * 72}\n{name}\n{'=' * 72}")


def timed(label: str, work: Callable[[], Any], note: str = "") -> tuple[Any, float]:
    """Run something and record how long it took, to one decimal place."""
    started = time.perf_counter()
    value = work()
    seconds = time.perf_counter() - started
    print(f"  {label:<44} {seconds:>8.3f} s   {note}")
    return value, seconds


def record(key: str, value: Any) -> Any:
    RESULTS[key] = value
    return value


# --------------------------------------------------------------------------
# 1 · Data and the generator
# --------------------------------------------------------------------------
def measure_data() -> None:
    section("1 · DATA AND THE GENERATOR")
    import pandas as pd

    dataset = ROOT / "data" / "transactions.csv"
    if not dataset.exists():
        NOTES["data"] = "data/transactions.csv missing -- run `python tasks.py gen`"
        print("  not measured: no dataset")
        return

    frame = pd.read_csv(dataset, low_memory=False)
    size_mb = dataset.stat().st_size / 1e6
    rows = len(frame)
    print(f"  {'rows':<44} {rows:>8,}")
    print(f"  {'columns':<44} {len(frame.columns):>8}")
    print(f"  {'distinct transactions':<44} {frame['txid'].nunique():>8,}")
    print(f"  {'file size':<44} {size_mb:>8.2f} MB")
    print(f"  {'bytes per row':<44} {dataset.stat().st_size / max(rows, 1):>8.1f}")
    record("data", {
        "rows": rows,
        "columns": len(frame.columns),
        "column_names": list(frame.columns),
        "distinct_txids": int(frame["txid"].nunique()),
        "file_bytes": dataset.stat().st_size,
        "bytes_per_row": round(dataset.stat().st_size / max(rows, 1), 1),
    })

    # Timestamps: the span decides how many batches the replay produces.
    stamps = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    if stamps.notna().any():
        span_days = (stamps.max() - stamps.min()).total_seconds() / 86400
        print(f"  {'capture span':<44} {span_days:>8.2f} days")
        record("data", {**RESULTS["data"], "span_days": round(span_days, 2)})

    # Ground truth: what was planted, so precision and recall mean something.
    truth = ROOT / "data" / "ground_truth_entities.csv"
    if truth.exists():
        frame_truth = pd.read_csv(truth)
        illicit = frame_truth[frame_truth.iloc[:, -1].astype(str)
                              .str.lower().isin(("1", "true", "illicit"))]
        print(f"  {'planted entities (ground truth)':<44} {len(illicit):>8,}")
        record("ground_truth", {
            "entities": int(len(frame_truth)),
            "planted_illicit": int(len(illicit)),
            "columns": list(frame_truth.columns),
        })
    else:
        NOTES["ground_truth"] = "data/ground_truth_entities.csv missing"

    # Address → entity reduction is a property of the data, not of the model.
    # Addresses arrive as list-valued columns; the separator is normalised at
    # ingest, so counting here means splitting on whichever one survived.
    addresses: set[str] = set()
    for column in ("input_addresses", "output_addresses"):
        if column not in frame.columns:
            continue
        for value in frame[column].dropna().astype(str):
            addresses.update(part for part in value.replace(",", "|").split("|") if part)
    print(f"  {'distinct addresses seen':<44} {len(addresses):>8,}")
    record("data", {**RESULTS["data"], "distinct_addresses": len(addresses)})


# --------------------------------------------------------------------------
# 2 · Ingestion
# --------------------------------------------------------------------------
def measure_ingestion() -> None:
    section("2 · INGESTION AND THE QUALITY GATE")
    from ingestion.load import load_any

    dataset = ROOT / "data" / "transactions.csv"
    if not dataset.exists():
        print("  not measured: no dataset")
        return

    from ingestion.load import SQLITE_SUFFIXES, SUPPORTED_SUFFIXES
    print(f"  {'formats accepted':<44} "
          f"{', '.join(sorted(SUPPORTED_SUFFIXES))}")
    print(f"  {'  of which a database':<44} {', '.join(sorted(SQLITE_SUFFIXES))}")

    # One load, timed, then read the report off the same call: running it twice
    # would have measured a warm cache and reported it as throughput.
    started = time.perf_counter()
    frame, report = load_any(dataset)
    elapsed = time.perf_counter() - started
    rows_per_second = len(frame) / max(elapsed, 1e-9)
    print(f"  {'rows accepted':<44} {report.accepted:>8,}")
    print(f"  {'rows rejected':<44} {report.rejected:>8,}")
    print(f"  {'rejections by reason':<44} {report.rejections or 'none':>8}")
    print(f"  {'blanked placeholders':<44} {report.notes or 'none':>8}")
    print(f"  {'detected format':<44} {report.format:>8}")
    print(f"  {'throughput':<44} {rows_per_second:>8,.0f} rows/s")
    print(f"  {'seconds':<44} {elapsed:>8.3f}")
    record("ingestion", {
        "formats": sorted(SUPPORTED_SUFFIXES),
        "rows_accepted": int(report.accepted),
        "rows_rejected": int(report.rejected),
        "rejections": dict(report.rejections or {}),
        "notes": dict(report.notes or {}),
        "format": report.format,
        "seconds": round(elapsed, 3),
        "rows_per_second": round(rows_per_second),
    })


# --------------------------------------------------------------------------
# 3 · Correlation and features
# --------------------------------------------------------------------------
def measure_correlation() -> None:
    section("3 · CORRELATION AND FEATURES")
    import pandas as pd
    from correlation.engine import correlate
    from ingestion.load import load_any
    from ml.cluster import detect_coinjoin_like
    from ml.features import FEATURE_COLUMNS, build_feature_table

    dataset = ROOT / "data" / "transactions.csv"
    if not dataset.exists():
        print("  not measured: no dataset")
        return

    frame, _ = load_any(dataset)
    # The coinjoin mask has to exist BEFORE correlation: equal-value multi-party
    # rounds are excluded from clustering, because a mixing round deliberately
    # spends unrelated people's coins together and would otherwise fuse them into
    # one "owner".
    coinjoin_mask = detect_coinjoin_like(frame)
    print(f"  {'coinjoin transactions excluded':<44} {int(coinjoin_mask.sum()):>8,}")
    record("correlation", {"coinjoin_transactions": int(coinjoin_mask.sum())})
    corr = correlate(frame, coinjoin_mask=coinjoin_mask)
    addresses = len(corr.address_to_entity)
    entities = corr.entities["entity_id"].nunique() if "entity_id" in corr.entities else 0
    print(f"  {'addresses correlated':<44} {addresses:>8,}")
    print(f"  {'wallet groups derived':<44} {entities:>8,}")
    print(f"  {'addresses per group (mean)':<44} {addresses / max(entities, 1):>8.2f}")
    kinds = corr.controls["kind"].value_counts().to_dict() if "kind" in corr.controls else {}
    print(f"  {'control (network) edges':<44} {len(corr.controls):>8,}")
    print(f"  {'flow (money) edges':<44} {len(corr.flows):>8,}")
    record("correlation", {
        **RESULTS.get("correlation", {}),
        "addresses": addresses,
        "wallet_groups": int(entities),
        "addresses_per_group": round(addresses / max(entities, 1), 2),
        "control_edges": int(len(corr.controls)),
        "flow_edges": int(len(corr.flows)),
        "edge_kinds": {str(k): int(v) for k, v in kinds.items()},
    })

    table, _ = timed("build the feature table",
                     lambda: build_feature_table(corr, frame, coinjoin_mask))
    print(f"  {'features per entity':<44} {len(FEATURE_COLUMNS):>8}")
    print(f"  {'feature matrix cells':<44} {len(table) * len(FEATURE_COLUMNS):>8,}")
    record("features", {
        "count": len(FEATURE_COLUMNS),
        "names": list(FEATURE_COLUMNS),
        "rows": int(len(table)),
        "cells": int(len(table) * len(FEATURE_COLUMNS)),
    })


# --------------------------------------------------------------------------
# 4 · The models
# --------------------------------------------------------------------------
def measure_models() -> None:
    section("4 · THE MODELS")
    metrics_path = ROOT / "models" / "metrics.json"
    if not metrics_path.exists():
        NOTES["models"] = "models/metrics.json missing -- run `python tasks.py train`"
        print("  not measured: no scorecard")
        return

    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    record("metrics", metrics)

    print("  -- what was measured, quoted straight from models/metrics.json")
    for key in sorted(metrics):
        value = metrics[key]
        if isinstance(value, float):
            print(f"  {key:<44} {value:>8.4f}")
        elif isinstance(value, (int, str, bool)) or value is None:
            print(f"  {key:<44} {str(value):>8}")

    print("\n  -- hyperparameters, read from the fitted artifact")
    model_path = ROOT / "models" / "risk.joblib"
    if model_path.exists():
        from ml.risk import RiskModel
        model = RiskModel.load(model_path)
        forest = getattr(model, "model", None)
        params = dict(forest.get_params()) if forest is not None else {}
        for key in ("n_estimators", "max_depth", "min_samples_leaf", "class_weight",
                    "random_state", "n_jobs"):
            if key in params:
                print(f"  {key:<44} {str(params[key]):>8}")
        record("risk_hyperparameters", {
            k: params.get(k) for k in
            ("n_estimators", "max_depth", "min_samples_leaf", "class_weight", "random_state")
            if k in params
        })
        print(f"  {'artifact size':<44} {model_path.stat().st_size / 1024:>8.1f} KB")
        record("risk_artifact_kb", round(model_path.stat().st_size / 1024, 1))
    else:
        NOTES["risk_artifact"] = "models/risk.joblib missing"

    anomaly_path = ROOT / "models" / "anomaly.joblib"
    if anomaly_path.exists():
        from ml.anomaly import AnomalyDetector
        detector = AnomalyDetector.load(anomaly_path)
        inner = getattr(detector, "model", None)
        params = dict(inner.get_params()) if inner is not None else {}
        for key in ("n_estimators", "contamination", "random_state", "max_samples"):
            if key in params:
                print(f"  {key:<44} {str(params[key]):>8}")
        record("anomaly_hyperparameters", {k: params.get(k) for k in
                                           ("n_estimators", "contamination", "random_state")
                                           if k in params})
    else:
        NOTES["anomaly_artifact"] = "models/anomaly.joblib missing"

    # The reference distribution is what makes drift detectable at serve time.
    reference = ROOT / "models" / "reference_distribution.json"
    if reference.exists():
        blob = json.loads(reference.read_text(encoding="utf-8"))
        features = blob.get("features", blob)
        print(f"  {'drift reference features':<44} {len(features):>8}")
        print(f"  {'drift reference size':<44} {reference.stat().st_size / 1024:>8.1f} KB")
        record("drift_reference", {
            "features": len(features),
            "bytes": reference.stat().st_size,
        })


# --------------------------------------------------------------------------
# 5 · The served payload and the reports
# --------------------------------------------------------------------------
def measure_serving() -> None:
    section("5 · PAYLOAD, ENDPOINTS AND REPORTS")
    store_path = ROOT / "out" / "monitoring.sqlite"
    if not store_path.exists():
        NOTES["serving"] = "out/monitoring.sqlite missing -- run `python tasks.py replay`"
        print("  not measured: no state store")
        return

    from monitoring.payload import build_window_payload
    from monitoring.store import MonitoringStore

    with MonitoringStore(store_path) as store:
        windows = store.windows()
        summary = store.summary()
        print(f"  {'batches recorded':<44} {len(windows):>8}")
        print(f"  {'batches in store summary':<44} {summary['windows']:>8}")
        print(f"  {'addresses tracked':<44} {summary['addresses']:>8,}")
        print(f"  {'wallet groups':<44} {summary['entities']:>8,}")
        print(f"  {'merges recorded':<44} {summary['merged_entities']:>8}")
        print(f"  {'events recorded':<44} {summary['events']:>8,}")
        print(f"  {'score rows':<44} {summary['score_rows']:>8,}")
        print(f"  {'alerts (rows)':<44} {summary['alerts']:>8}")
        print(f"  {'open leads (resolved)':<44} {summary['open_alerts']:>8}")
        record("store", dict(summary))

        payload, seconds = timed("build the whole-capture payload",
                                 lambda: build_window_payload(store, None))
        size = len(json.dumps(payload, default=str))
        leads = [entity for entity in payload["entities"] if entity.get("lead")]
        print(f"  {'  payload size':<44} {size / 1e6:>8.2f} MB")
        print(f"  {'  entities in payload':<44} {len(payload['entities']):>8,}")
        print(f"  {'  leads in payload':<44} {len(leads):>8,}")
        print(f"  {'  links drawn':<44} {len(payload['edges']):>8,}")
        print(f"  {'  fund trails':<44} {len(payload['traces']):>8,}")
        print(f"  {'  explanations produced':<44} "
              f"{sum(1 for e in payload['entities'] if e.get('explanation')):>8,}")
        record("payload", {
            "bytes": size,
            "entities": len(payload["entities"]),
            "leads": len(leads),
            "edges": len(payload["edges"]),
            "traces": len(payload["traces"]),
            "explained": sum(1 for e in payload["entities"] if e.get("explanation")),
            "seconds": round(seconds, 2),
            "seconds_per_window": round(seconds / max(len(windows), 1), 2),
        })

        # Every lead must reconcile: this is the product's central claim.
        residuals = [abs(float(e["explanation"]["residual"]))
                     for e in leads if e.get("explanation")]
        worst = max(residuals) if residuals else None
        print(f"  {'  worst explanation residual':<44} {worst if worst is not None else 'n/a':>8}")
        record("payload_reconciliation", {"worst_residual": worst, "leads": len(leads)})

        # Per-window payloads: the dashboard loads these on demand.
        per_window: list[float] = []
        for record_window in windows:
            _, seconds = timed(f"build payload for {record_window.label}",
                               lambda w=record_window.window_id:
                               build_window_payload(store, w))
            per_window.append(seconds)
        if per_window:
            print(f"  {'  median per-window build':<44} "
                  f"{statistics.median(per_window):>8.2f} s")
            record("payload_per_window_seconds", {
                "median": round(statistics.median(per_window), 2),
                "max": round(max(per_window), 2),
                "min": round(min(per_window), 2),
            })

        # Time to detection: the scorecard that monitoring exists to produce.
        planted = 0
        detected = 0
        for entity in payload["entities"]:
            history = entity.get("history") or []
            if not any(row.get("risk", 0) >= 50 for row in history):
                continue
            planted += 1
            if len(history) >= 2:
                detected += 1
        print(f"  {'  leads with a multi-batch history':<44} {detected:>8,} of {planted:,}")
        record("history_coverage", {"leads_with_history": detected, "leads": planted})


def measure_reports() -> None:
    section("6 · THE REPORTS AND THE FRONTEND")
    from backend.report import PRINT_STYLE, anomalies_report_html, dataset_report_html
    from ml.explainers import ANOMALY_EXPLAINERS
    from monitoring.payload import build_window_payload
    from monitoring.store import MonitoringStore

    store_path = ROOT / "out" / "monitoring.sqlite"
    if store_path.exists():
        with MonitoringStore(store_path) as store:
            payload = build_window_payload(store, None)
        dataset_html = dataset_report_html(payload)
        anomalies_html = anomalies_report_html(payload, ANOMALY_EXPLAINERS)
        print(f"  {'dataset report (bytes)':<44} {len(dataset_html):>8,}")
        print(f"  {'anomaly report (bytes)':<44} {len(anomalies_html):>8,}")
        print(f"  {'print stylesheet (bytes)':<44} {len(PRINT_STYLE):>8,}")
        external = [marker for marker in ("http://", "https://", "src=", "//cdn")
                    if marker in dataset_html or marker in anomalies_html]
        print(f"  {'self-contained (no external requests)':<44} "
              f"{'yes' if not external else 'NO: ' + ', '.join(external)}")
        embedded = "<style>" in dataset_html
        print(f"  {'stylesheet embedded, not linked':<44} "
              f"{'yes' if embedded else 'no'}")
        record("reports", {
            "dataset_bytes": len(dataset_html),
            "anomalies_bytes": len(anomalies_html),
            "stylesheet_bytes": len(PRINT_STYLE),
            "external_references": external,
        })
    else:
        print("  not measured: no state store")

    frontend = ROOT / "frontend"
    pages = sorted(frontend.glob("*.html"))
    assets = sorted((frontend / "assets").glob("*.js")) + sorted((frontend / "assets").glob("*.css"))
    vendor = sorted((frontend / "vendor").glob("*.js"))
    print(f"  {'pages':<44} {len(pages):>8}")
    for page in pages:
        print(f"    {page.name:<42} {page.stat().st_size / 1024:>8.1f} KB")
    print(f"  {'page HTML total':<44} "
          f"{sum(p.stat().st_size for p in pages) / 1024:>8.1f} KB")
    print(f"  {'own JS + CSS':<44} "
          f"{sum(a.stat().st_size for a in assets) / 1024:>8.1f} KB")
    print(f"  {'vendored libraries':<44} "
          f"{sum(v.stat().st_size for v in vendor) / 1024:>8.1f} KB")
    fonts = list((frontend / "vendor" / "fonts").glob("*"))
    print(f"  {'vendored font files':<44} {len(fonts):>8}")
    total = sum(p.stat().st_size for p in pages) + sum(a.stat().st_size for a in assets)
    print(f"  {'--- shipped page weight (no fonts)':<44} {total / 1024:>8.1f} KB")
    record("frontend", {
        "pages": [p.name for p in pages],
        "page_count": len(pages),
        "page_bytes": sum(p.stat().st_size for p in pages),
        "own_asset_bytes": sum(a.stat().st_size for a in assets),
        "vendored_bytes": sum(v.stat().st_size for v in vendor),
        "font_files": len(fonts),
        "shipped_bytes": total,
    })


# --------------------------------------------------------------------------
# 7 · Scale, which is the claim most worth checking
# --------------------------------------------------------------------------
def measure_scale(sizes: tuple[int, ...] = (50_000, 200_000)) -> None:
    """Two sizes, because one cannot tell linear from quadratic.

    The claim under test is that the pipeline is linear in rows. A single point
    fits any curve, so this measures the cost per 100,000 rows at two sizes and
    reports both: if the per-row cost is flat, the shape is linear.
    """
    section(f"7 · SCALE (generated {', '.join(f'{s:,}' for s in sizes)} rows)")
    results: dict[str, Any] = {}
    for rows in sizes:
        measured = _measure_scale_once(rows)
        if measured:
            results[f"{rows}"] = measured
    if len(results) >= 2:
        keys = sorted(results, key=lambda k: int(k))
        first, last = results[keys[0]], results[keys[-1]]
        ratio = last["rows"] / first["rows"]
        cost_ratio = last["seconds_per_100k_rows"] / max(first["seconds_per_100k_rows"], 1e-9)
        print(f"  {'rows multiplier':<44} {ratio:>8.2f}x")
        print(f"  {'per-100k cost multiplier':<44} {cost_ratio:>8.2f}x")
        print(f"  {'verdict':<44} "
              f"{'linear' if cost_ratio < ratio ** 0.5 else 'super-linear'}")
        record("scale_verdict", {"rows_multiplier": round(ratio, 2),
                                 "cost_multiplier": round(cost_ratio, 2)})
    record("scale", results)


def _measure_scale_once(rows: int) -> dict[str, Any]:
    from correlation.engine import correlate
    from generator.generate import Generator, write_ground_truth, write_transactions
    from ingestion.load import load_any
    from ml.cluster import detect_coinjoin_like
    from ml.features import build_feature_table
    import tempfile

    with tempfile.TemporaryDirectory() as scratch:
        out = Path(scratch)
        # The generator is used through its own class rather than a convenience
        # wrapper, so this measures the same code path `tasks.py gen` runs.
        generator = Generator(seed=7, n_clusters=max(50, rows // 20), n_background=rows)
        generator.build()
        write_transactions(generator, out / "transactions.csv")
        write_ground_truth(generator, out)
        dataset = out / "transactions.csv"
        if not dataset.exists():
            NOTES["scale"] = "the generator did not write transactions.csv"
            print("  not measured: generator output differs")
            return
        actual = sum(1 for _ in dataset.open(encoding="utf-8")) - 1

        started = time.perf_counter()
        frame, _ = load_any(dataset)
        mask = detect_coinjoin_like(frame)
        corr = correlate(frame, coinjoin_mask=mask)
        table = build_feature_table(corr, frame, mask)
        seconds = time.perf_counter() - started
        print(f"  {'load+correlate+features':<44} {seconds:>8.2f} s   "
              f"{actual:,} rows -> {len(corr.entities):,} groups")
        return {
            "rows": int(actual),
            "wallet_groups": int(len(corr.entities)),
            "feature_rows": int(len(table)),
            "seconds": round(seconds, 2),
            "seconds_per_100k_rows": round(seconds / max(actual, 1) * 100_000, 2),
        }


# --------------------------------------------------------------------------
# 8 · Tests and packaging
# --------------------------------------------------------------------------
def measure_quality() -> None:
    section("8 · TESTS, CONTRACT AND PACKAGING")
    import subprocess

    def count_files(pattern: str, root: Path) -> int:
        return len(list(root.rglob(pattern)))

    python_lines = sum(
        len(path.read_text(encoding="utf-8", errors="ignore").splitlines())
        for path in ROOT.rglob("*.py")
        if ".venv" not in str(path) and "node_modules" not in str(path)
        and "wheels" not in str(path)
    )
    print(f"  {'Python lines (whole project)':<44} {python_lines:>8,}")
    record("size", {"python_lines": python_lines})

    schema_path = ROOT / "schemas" / "results.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    defs = schema.get("$defs", {})
    print(f"  {'contract properties':<44} {len(schema.get('properties', {})):>8}")
    print(f"  {'contract definitions':<44} {len(defs):>8}")
    print(f"  {'contract required at root':<44} {len(schema.get('required', [])):>8}")
    print(f"  {'contract size':<44} {schema_path.stat().st_size / 1024:>8.1f} KB")
    record("contract", {
        "properties": len(schema.get("properties", {})),
        "defs": len(defs),
        "property_names": sorted(schema.get("properties", {}).keys()),
        "required": list(schema.get("required", [])),
        "bytes": schema_path.stat().st_size,
    })

    pytest_tests = sum(
        len([line for line in path.read_text(encoding="utf-8").splitlines()
             if line.strip().startswith("def test_")])
        for path in (ROOT / "tests").glob("test_*.py")
    )
    api_checks = len([line for line in
                      (ROOT / "tests" / "api_smoke.py").read_text(encoding="utf-8").splitlines()
                      if "check(" in line and "def check" not in line])
    print(f"  {'pytest test functions':<44} {pytest_tests:>8}")
    print(f"  {'API smoke assertions (static count)':<44} {api_checks:>8}")
    record("tests", {"pytest_functions": pytest_tests,
                     "api_check_call_sites": api_checks})
    print("    (the call-site count is static; the run below reports how many "
          "executed)")

    requirements = ROOT / "requirements.txt"
    if requirements.exists():
        pins = [line.strip() for line in requirements.read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.startswith("#")]
        print(f"  {'pinned dependencies':<44} {len(pins):>8}")
        record("dependencies", pins)

    print("\n  -- measured by running the suites (this takes a minute)")
    for label, command in (
        ("pytest suite", [sys.executable, "-m", "pytest", "-q", "tests/test_smoke.py"]),
        ("API smoke test", [sys.executable, "tests/api_smoke.py"]),
    ):
        started = time.perf_counter()
        proc = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
        seconds = time.perf_counter() - started
        tail = [line for line in proc.stdout.splitlines() if line.strip()][-1:] or [""]
        print(f"  {label:<44} {seconds:>8.1f} s   {tail[0][:40]}")
        record("suite_runs", {**RESULTS.get("suite_runs", {}),
                              label: {"seconds": round(seconds, 1),
                                      "ok": proc.returncode == 0,
                                      "last_line": tail[0]}})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path, default=None,
                        help="also write the measurements here")
    parser.add_argument("--skip-scale", action="store_true",
                        help="skip section 7 (generates a 200k-row dataset)")
    args = parser.parse_args()

    started = time.perf_counter()
    measure_data()
    measure_ingestion()
    measure_correlation()
    measure_models()
    measure_serving()
    measure_reports()
    if not args.skip_scale:
        measure_scale()
    measure_quality()

    elapsed = time.perf_counter() - started
    section("SUMMARY")
    print(f"  measurements taken in {elapsed:.1f} s")
    if NOTES:
        print("  NOT MEASURED, and why:")
        for key, reason in NOTES.items():
            print(f"    - {key}: {reason}")
    RESULTS["_notes"] = NOTES
    RESULTS["_seconds"] = round(elapsed, 1)

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(RESULTS, indent=2, default=str), encoding="utf-8")
        print(f"  written to {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
