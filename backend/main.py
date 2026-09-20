"""
FastAPI backend -- the API and the dashboard in one process.

WHY ONE PROCESS
---------------
The problem statement demands offline deployment on a Linux host. Serving the
JSON API and the dashboard's static files from the same process means:
deployment is one command, there is NO CORS to configure (same origin), and
there is no reverse proxy to misconfigure. For an air-gapped target every moving
part you remove is a failure mode you cannot have.

ENDPOINT MAP
------------
    GET  /health                      liveness + what state exists
    GET  /windows                     the window sequence and store totals
    GET  /results?window=n            the frozen contract payload for a window
    GET  /events?window=n             the monitoring event feed
    GET  /alerts?status=...           ranked leads with lifecycle state
    POST /alerts/{entity}/status      record the analyst's decision
    GET  /ingest-report               the data-quality gate for a dataset, without analysing it
    POST /upload                      ingest a file and report the data-quality gate
    POST /analyze                     start a windowed replay as a background job
    GET  /job/{id}                    progress and log for a running job
    GET  /metrics                     the measured scorecard
    GET  /glossary                    plain-language explanations of the vocabulary
    GET  /print/dataset               printable whole-capture report (A4)
    GET  /print/anomalies             printable lead report (A4)
    GET  /report/{entity}             printable case dossier for one lead (A4)
    POST /reload                      re-read state and report how old it is
    /docs                             FastAPI's generated API console

THE STALE-DATA GUARD, AND WHY IT EXISTS
---------------------------------------
The server holds a SQLite handle and caches per-window payloads. Both can go
stale silently: the data is valid, just old, so nothing LOOKS wrong. That already
cost us once, when a failed restart left an old process serving sixteen-minute-old
analytics. So `POST /reload` exists, and every payload reports the timestamp it
was generated at -- you can always tell exactly how old what you are looking at
is, rather than assuming.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend.jobs import JobStore
from backend.report import case_report_html
from monitoring.payload import build_window_payload
from monitoring.store import ALERT_STATUSES, MonitoringStore

ROOT = Path(__file__).resolve().parent.parent

# Every path is overridable by environment variable so a TEST can point the whole
# application at a scratch directory.
#
# This is not configuration for its own sake. The smoke test exercises every
# endpoint, and one of them is "run a full analysis" -- which, because a full
# analysis REPLACES the previous one, meant that running the test deleted the
# state the demonstration was using. It caught us: a test run mid-session left the
# pages reporting 70 leads where the cover said 77, and one page rendered empty
# because it loaded while the store was being rebuilt. A test that can destroy the
# thing it is testing is not a test.
def _path(variable: str, default: Path) -> Path:
    return Path(os.environ.get(variable, default))


OUT_DIR = _path("NETRA_OUT_DIR", ROOT / "out")
MODELS_DIR = _path("NETRA_MODELS_DIR", ROOT / "models")
UPLOAD_DIR = _path("NETRA_UPLOAD_DIR", ROOT / "uploads")
FRONTEND_DIR = _path("NETRA_FRONTEND_DIR", ROOT / "frontend")
DATA_DIR = _path("NETRA_DATA_DIR", ROOT / "data")
STORE_PATH = OUT_DIR / "monitoring.sqlite"

# One place, so the version the API reports and the version the dossier prints
# cannot drift apart.
ENGINE_VERSION = "netra-monitoring-2"

app = FastAPI(
    title="NETRA",
    version="2.0",
    description=(
        "Network-Enhanced Transaction Risk Analysis. Ingests bulk Bitcoin and "
        "network metadata, fuses the two layers, and produces ranked, explainable "
        "investigative leads with a monitoring history. Offline by design."
    ),
)

jobs = JobStore()


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def _open_store() -> MonitoringStore:
    """A connection per request.

    sqlite3 connections are NOT safe to share across threads, and FastAPI runs
    sync endpoints in a threadpool -- so a module-level connection would be a
    latent corruption bug that surfaces only under concurrent requests. Opening
    one is cheap, and the alternative is a bug that appears once under load.
    """
    if not STORE_PATH.exists():
        raise HTTPException(
            status_code=409,
            detail="no monitoring state yet -- POST /analyze first (or run "
                   "'python -m monitoring.pipeline')",
        )
    return MonitoringStore(STORE_PATH)


def _safe_filename(name: str) -> str:
    """Strip any path components from an uploaded filename.

    Uploaded filenames are attacker-controlled. Without this, a file named
    '../../etc/cron.d/x' escapes the upload directory. Path traversal is a real
    vulnerability class and this is a two-second fix.
    """
    cleaned = Path(name or "upload.csv").name.strip() or "upload.csv"
    return "".join(character for character in cleaned if character.isalnum() or character in "._-")


def _clear_payload_cache() -> int:
    """Drop cached per-window payloads. They are derived, so stale ones are worse
    than absent ones -- an absent cache is rebuilt, a stale one is served."""
    removed = 0
    for path in OUT_DIR.glob("window-*.json"):
        path.unlink(missing_ok=True)
        removed += 1
    return removed


def _payload_cache_path(window_id: int) -> Path:
    return OUT_DIR / f"window-{window_id}.json"


def _select_window(store: MonitoringStore, window: str | None, *,
                   default: str = "latest") -> tuple[int | None, Path]:
    """Parse a window selector into `(window_id, cache path)`.

    ONE PARSE RULE, because there are now three callers -- the payload endpoint
    and both printable reports -- and they disagreeing is how you get a report
    about a different batch than the screen was showing.

    `None` means the UNION of every batch, and it is a real distinction: the
    union is what the dataset report is about, and it is cached under id 0, which
    is a CACHE KEY rather than a window id (no batch is numbered 0). Passing 0 as
    `window_id` to the payload builder raises, so the two must not be confused --
    that confusion is exactly what made both print routes fail before they were
    ever opened.

    `default` decides what an absent selector means: the newest batch for the
    payload endpoint (an analyst opening a page wants the current picture), and
    the whole capture for a report (a report is about the data, not about today).
    """
    records = store.windows()
    if not records:
        raise HTTPException(status_code=409, detail="no windows recorded")

    if window in (None, ""):
        if default == "all":
            return None, _payload_cache_path(0)
        return records[-1].window_id, _payload_cache_path(records[-1].window_id)
    if window == "all":
        return None, _payload_cache_path(0)

    try:
        window_id = int(window)
    except ValueError:
        raise HTTPException(
            status_code=400, detail="window must be a batch id or 'all'"
        ) from None
    if window_id not in {record.window_id for record in records}:
        raise HTTPException(status_code=404, detail=f"no such window: {window_id}")
    return window_id, _payload_cache_path(window_id)


def _resolve_dataset(requested: str | None) -> Path:
    """Resolve a dataset path, confined to the two directories that may hold one.

    `/analyze` and the gate both take a path from the client. Without this, the
    API is a file-read primitive pointed at the whole filesystem: a request for
    `../../etc/passwd` would not return a secret, but it WOULD return a parse
    error naming the file, and a request for any readable CSV would become a
    dataset. Offline or not, that is an unnecessary capability to hand out.

    The default is the bundled dataset, which is what the demo button asks for.
    """
    if not requested:
        return DATA_DIR / "transactions.csv"
    candidate = Path(requested)
    if not candidate.is_absolute():
        candidate = (ROOT / candidate).resolve()
    else:
        candidate = candidate.resolve()

    allowed = [DATA_DIR.resolve(), UPLOAD_DIR.resolve()]
    if not any(candidate == root or root in candidate.parents for root in allowed):
        raise HTTPException(
            status_code=400,
            detail="dataset must live under data/ or uploads/ -- refusing to read "
                   f"{candidate}",
        )
    return candidate


# --------------------------------------------------------------------------
# Health and state
# --------------------------------------------------------------------------
@app.get("/health", summary="Liveness and what state exists")
def health() -> dict[str, Any]:
    state: dict[str, Any] = {
        "status": "ok",
        "engine_version": ENGINE_VERSION,
        "models": {
            "risk": (MODELS_DIR / "risk.joblib").exists(),
            "anomaly": (MODELS_DIR / "anomaly.joblib").exists(),
            "metrics": (MODELS_DIR / "metrics.json").exists(),
        },
        "store": {"path": str(STORE_PATH), "exists": STORE_PATH.exists()},
        "frontend": (FRONTEND_DIR / "index.html").exists(),
    }
    if STORE_PATH.exists():
        with _open_store() as store:
            state["store"].update(store.summary())
            latest = store.last_window()
            if latest is not None:
                state["latest_window"] = {
                    "id": latest.window_id, "label": latest.label,
                    "end": latest.end_ts, "transactions": latest.n_tx,
                }
    return state


@app.get("/windows", summary="The window sequence and store totals")
def windows() -> dict[str, Any]:
    with _open_store() as store:
        records = store.windows()
        return {
            "windows": [
                {
                    "id": record.window_id, "label": record.label,
                    "start": record.start_ts, "end": record.end_ts,
                    "transactions": record.n_tx, "entities": record.n_entities,
                    "index": position + 1, "total": len(records),
                }
                for position, record in enumerate(records)
            ],
            "store": store.summary(),
        }


@app.get("/results", summary="The contract payload for a window, or for every batch")
def results(window: str | None = Query(default=None)) -> dict[str, Any]:
    """`window=<id>` for one batch; `window=all` for the complete dataset.

    The traffic analysis page uses `all`, because the problem statement asks to
    analyse the ingested traffic and one slice of it is not that. Union mode
    correlates every batch together and reports per-entity risk as the PEAK the
    group reached -- the question there is "what is in this data", and a group
    that was critical in any batch belongs in the answer.
    """
    with _open_store() as store:
        return _payload_for(store, window)


@app.get("/events", summary="The monitoring event feed")
def events(window: int | None = Query(default=None, ge=1)) -> dict[str, Any]:
    with _open_store() as store:
        frame = store.events(window)
        if frame.empty:
            return {"events": [], "counts": {}}
        return {
            "events": json.loads(frame.to_json(orient="records", date_format="iso")),
            "counts": {str(k): int(v) for k, v in frame["type"].value_counts().items()},
        }


@app.get("/alerts", summary="Ranked leads with their lifecycle state")
def alerts(status: str | None = None) -> dict[str, Any]:
    if status and status not in ALERT_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"unknown status '{status}' -- expected one of {list(ALERT_STATUSES)}",
        )
    with _open_store() as store:
        frame = store.alerts(status)
        if frame.empty:
            return {"alerts": [], "open": 0}
        records = json.loads(frame.to_json(orient="records"))
        # Every key leaving this endpoint is a CURRENT identity.
        #
        # A group that was merged into another during the replay keeps its alert
        # row as a historical record, but its key no longer names a group -- so a
        # client that followed one would ask for a case dossier that 404s, or
        # highlight a node that is not in the graph. Resolution belongs here, once,
        # rather than in every consumer.
        for record in records:
            record["entity_key"] = store.canonical(str(record["entity_key"]))
        return {
            "alerts": records,
            "open": int((~frame["status"].str.startswith("closed")).sum()),
        }


class AlertStatusUpdate(BaseModel):
    status: str = Field(description=f"One of {list(ALERT_STATUSES)}")
    assignee: str | None = None
    note: str | None = None


@app.post("/alerts/{entity_key}/status", summary="Record the analyst's decision")
def set_alert_status(entity_key: str, update: AlertStatusUpdate) -> dict[str, Any]:
    """The decision persists between runs. That is what makes this a tool rather
    than a report: the system remembers what you already looked at."""
    if update.status not in ALERT_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"unknown status '{update.status}' -- expected one of {list(ALERT_STATUSES)}",
        )
    with _open_store() as store:
        if entity_key not in set(store.alerts()["entity_key"]):
            raise HTTPException(status_code=404, detail=f"no alert for {entity_key}")
        store.set_alert_status(entity_key, update.status, update.assignee, update.note)
        row = store.alerts()
        row = row[row["entity_key"] == entity_key]
    return {"entity": entity_key, "alert": json.loads(row.to_json(orient="records"))[0]}


# --------------------------------------------------------------------------
# Ingestion and analysis
# --------------------------------------------------------------------------
@app.post("/upload", summary="Ingest a file and report the data-quality gate")
async def upload(file: UploadFile = File(...)) -> dict[str, Any]:
    """Store the file and run the gate -- no analysis.

    Deliberately fast: an operator needs to know IMMEDIATELY that 412 of 50,000
    rows were unparseable and why, before spending a minute on a full run.
    """
    from ingestion.load import load_any

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    target = UPLOAD_DIR / _safe_filename(file.filename or "upload.csv")
    with target.open("wb") as handle:
        shutil.copyfileobj(file.file, handle)

    try:
        frame, report = load_any(target)
    except ValueError as exc:                # unsupported suffix, unreadable table
        raise HTTPException(status_code=415, detail=str(exc)) from exc

    return {
        "stored_as": str(target),
        "bytes": target.stat().st_size,
        "report": report.as_dict(),
        "columns": list(frame.columns),
        "sample_rows": int(min(len(frame), 3)),
    }


@app.get("/ingest-report", summary="The quality gate for a dataset, without analysing it")
def ingest_report(dataset: str | None = Query(default=None)) -> dict[str, Any]:
    """Read a dataset and report what would be accepted, in seconds.

    The upload path gets this for free. The built-in dataset did not -- so the
    demo skipped the one screen that answers "did you actually use my data?",
    which is the screen that makes the rest of the tool credible. Same gate, same
    code, before anything expensive happens.
    """
    from ingestion.load import load_any

    target = _resolve_dataset(dataset)
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"no such dataset: {target}")
    started = time.time()
    try:
        frame, report = load_any(target)
    except ValueError as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc

    return {
        "dataset": str(target),
        "report": report.as_dict(),
        "columns": list(frame.columns),
        "read_ms": int((time.time() - started) * 1000),
    }


class AnalyzeRequest(BaseModel):
    mode: str = Field(default="replay", description="'replay' processes every window in order")
    dataset: str | None = Field(default=None, description="path to the traffic file")


@app.post("/analyze", status_code=202, summary="Start a windowed replay in the background")
def analyze(request: AnalyzeRequest | None = None) -> dict[str, Any]:
    """Return immediately with a job id; poll `GET /job/{id}`.

    A full replay takes tens of seconds. Holding the request open that long means
    the browser times out and the analyst watches a spinner with no explanation.
    """
    request = request or AnalyzeRequest()
    dataset = _resolve_dataset(request.dataset)
    if not dataset.exists():
        raise HTTPException(status_code=404, detail=f"no such dataset: {dataset}")

    def work(job_id: str) -> dict[str, Any]:
        from monitoring.pipeline import replay

        jobs.log(job_id, f"dataset: {dataset}")

        # ALWAYS a fresh history.
        #
        # Both entry points on the ingest page -- an uploaded file and the built-in
        # dataset -- are complete analyses of a whole file, so both REPLACE the
        # previous run rather than adding to it. An earlier version exempted the
        # built-in dataset "because it is the same data", which was wrong in a way
        # that only showed up on the second click: the alert table kept both runs,
        # and the cover reported 85 opens where the payload reported 77 flagged
        # groups. Appending is never what a full analysis of a file means.
        #
        # The genuine incremental case -- a new batch arriving for a capture that is
        # already loaded -- is `--keep-history` on the CLI, where it is stated.
        jobs.log(job_id, "clearing the previous analysis (this replaces it)")
        for stale in (STORE_PATH, OUT_DIR / "monitoring.sqlite-wal",
                      OUT_DIR / "monitoring.sqlite-shm"):
            stale.unlink(missing_ok=True)

        jobs.log(job_id, "splitting into windows")
        result = replay(
            store_path=STORE_PATH, dataset=dataset,
            data_dir=DATA_DIR, models_dir=MODELS_DIR,
            reset=True,
        )
        windows = result["windows"]
        for position, window in enumerate(windows, start=1):
            jobs.log(
                job_id,
                f"[{position}/{len(windows)}] {window['label']}: "
                f"{window['transactions']} tx -> {window['entities']} entities, "
                f"{window['new_entities']} new, {window['merged_entities']} merged, "
                f"{window['events']} events",
            )
            jobs.progress(job_id, position / max(len(windows), 1))

        cleared = _clear_payload_cache()
        jobs.log(job_id, f"cleared {cleared} cached payload(s)")

        # Warm the view the browser is about to open, while the progress bar is
        # still on screen.
        #
        # This job just DELETED the cache, and the ingest page redirects straight
        # to the dataset page, which needs exactly this payload. Building it here
        # moves ten seconds of work from a blank page a judge is staring at to the
        # progress bar they are already watching. It is the same build either way;
        # the only question is who is looking at it.
        jobs.log(job_id, "preparing the whole-capture view")
        with _open_store() as store:
            _payload_for(store, "all")
        jobs.log(job_id, "whole-capture view ready")

        return {"store": result["store"], "time_to_detection": result["time_to_detection"]}

    job = jobs.submit("replay", work)
    return {"job_id": job.id, "status": job.status,
            "poll": f"/job/{job.id}", "dataset": str(dataset)}


@app.get("/job/{job_id}", summary="Progress and log for a running job")
def job_status(job_id: str) -> dict[str, Any]:
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"no such job: {job_id}")
    return job.as_dict()


@app.get("/jobs", summary="Recent jobs, newest first")
def job_list() -> dict[str, Any]:
    return {"jobs": [job.as_dict() for job in jobs.list()]}


@app.post("/reload", summary="Re-read state and report how old it is")
def reload_state() -> dict[str, Any]:
    """Clear derived caches and report the data's own timestamp.

    Serving stale analytics is invisible -- the numbers are valid, just old. So
    this endpoint exists and every payload carries `generated_at`, making the age
    of what is on screen a fact rather than an assumption.
    """
    cleared = _clear_payload_cache()
    with _open_store() as store:
        summary = store.summary()
        latest = store.last_window()
    return {
        "cleared_caches": cleared,
        "store": summary,
        "latest_window": (
            {"id": latest.window_id, "label": latest.label, "end": latest.end_ts}
            if latest else None
        ),
        "reloaded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


@app.get("/monitoring", summary="Batches, events, alert lifecycle, and detection speed")
def monitoring() -> dict[str, Any]:
    """Everything the Monitoring page needs, in one call.

    Assembled server-side rather than by the page making four requests, because
    the pieces have to agree: the per-batch event counts, the lifecycle totals and
    the time-to-detection figure all describe the same history, and computing
    them in separate round trips is how they drift.
    """
    from monitoring.pipeline import time_to_detection

    with _open_store() as store:
        records = store.windows()
        events = store.events()
        alerts = store.alerts()

        per_batch = []
        for position, record in enumerate(records, start=1):
            batch_events = events[events["window_id"] == record.window_id] if not events.empty else events
            per_batch.append({
                "id": record.window_id,
                "label": record.label,
                "start": record.start_ts,
                "end": record.end_ts,
                "transactions": record.n_tx,
                "entities": record.n_entities,
                "events": int(len(batch_events)),
                "index": position,
                "total": len(records),
            })

        type_counts = (
            {str(k): int(v) for k, v in events["type"].value_counts().items()}
            if not events.empty else {}
        )
        status_counts = (
            {str(k): int(v) for k, v in alerts["status"].value_counts().items()}
            if not alerts.empty else {}
        )
        severity_counts = (
            {str(k): int(v) for k, v in events["severity"].value_counts().items()}
            if not events.empty else {}
        )

        return {
            "batches": per_batch,
            "event_types": type_counts,
            "alert_status": status_counts,
            "event_severity": severity_counts,
            "open_alerts": int((~alerts["status"].str.startswith("closed")).sum()) if not alerts.empty else 0,
            "time_to_detection": time_to_detection(store, DATA_DIR),
            "store": store.summary(),
        }


@app.get("/glossary", summary="Plain-language explanations of the vocabulary")
def glossary_endpoint() -> dict[str, Any]:
    """What each anomaly type means, in words a non-specialist can act on.

    Served from the backend rather than written into the interface, because the
    same explanation appears on the anomalies page, in the printed report and in
    the case dossier. Three hand-written copies is three chances to drift, and
    the copy that drifts is the one quoted back at you.
    """
    from ml.explainers import glossary

    return glossary()


@app.get("/metrics", summary="The measured scorecard")
def metrics() -> dict[str, Any]:
    path = MODELS_DIR / "metrics.json"
    if not path.exists():
        return {"evaluated_on": "model not trained"}
    return json.loads(path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# The printable reports
# --------------------------------------------------------------------------
# Three documents, one code path. They are served as HTML and saved with the
# browser's own print-to-PDF, which means vector text and vector charts, no PDF
# library, and nothing to install on a host that cannot reach a package registry.
def _report_payload(store: MonitoringStore, window: str | None) -> dict[str, Any]:
    """The payload a report is rendered from, through the same window rule and the
    same on-disk cache as the screen. A report that reads a different payload from
    the page it summarises is a report that will one day contradict it."""
    return _payload_for(store, window, default="all")


def _payload_for(store: MonitoringStore, window: str | None, *,
                 default: str = "latest") -> dict[str, Any]:
    """Build-or-read through one rule, so `/results`, the reports and the cache
    warmer cannot disagree about what a window selector means or where the result
    is stored."""
    window_id, cache = _select_window(store, window, default=default)
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    payload = build_window_payload(store, window_id, models_dir=MODELS_DIR)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return payload


@app.get("/print/dataset", response_class=HTMLResponse,
         summary="Printable whole-capture dataset report (A4)")
def print_dataset(window: str | None = Query(default=None)) -> HTMLResponse:
    """Open in a browser, then print to PDF. `?window=all` (the default) is the
    whole capture; a batch id gives the report for that batch alone."""
    from backend.report import dataset_report_html

    with _open_store() as store:
        payload = _report_payload(store, window)
    return HTMLResponse(content=dataset_report_html(payload))


@app.get("/print/anomalies", response_class=HTMLResponse,
         summary="Printable lead and anomaly report (A4)")
def print_anomalies(window: str | None = Query(default=None)) -> HTMLResponse:
    from backend.report import anomalies_report_html
    from ml.explainers import ANOMALY_EXPLAINERS

    with _open_store() as store:
        payload = _report_payload(store, window)
    return HTMLResponse(content=anomalies_report_html(payload, ANOMALY_EXPLAINERS))


@app.get("/report/{entity_key}", response_class=HTMLResponse,
         summary="Printable case dossier for one lead")
def report(entity_key: str, window: int | None = Query(default=None, ge=1)) -> HTMLResponse:
    with _open_store() as store:
        records = store.windows()
        if not records:
            raise HTTPException(status_code=409, detail="no windows recorded")

        # An analyst may be holding a link to a group that a later batch merged
        # into another. The dossier they want is the surviving group's, and 404ing
        # on a key WE printed -- in an alert, in a report -- is our bug, not a
        # missing record.
        entity_key = store.canonical(entity_key)

        # Default to the window where this lead was LAST SCORED, not simply the
        # newest one -- a lead from earlier in the week would otherwise 404 at the
        # moment an analyst asks for it. Then VERIFY it is actually in that
        # window's payload, and walk back if it is not: the scores table records
        # that an entity was scored, while the payload only carries entities with
        # material flow, so "scored in window 4" does not imply "present in window
        # 4's payload". Trusting the first without checking the second produced a
        # 404 on a lead the tool had just printed.
        candidates: list[int] = []
        if window:
            candidates = [window]
        else:
            latest = store.latest_window_for(entity_key)
            if latest is not None:
                candidates.append(latest)
            candidates += [record.window_id for record in reversed(records)
                           if record.window_id not in candidates]

        entity = None
        payload: dict[str, Any] = {}
        for candidate in candidates:
            payload = build_window_payload(store, candidate, models_dir=MODELS_DIR)
            entity = next(
                (item for item in payload["entities"] if item["id"] == entity_key), None
            )
            if entity is not None:
                break
        if entity is None:
            raise HTTPException(
                status_code=404,
                detail=f"no entity {entity_key} carries material flow in any of the "
                       f"{len(records)} recorded batches",
            )

        related = [
            event for event in payload["events"]
            if event.get("entity") == entity_key or entity_key in (event.get("absorbed") or [])
        ]
        traces = [trace for trace in payload["traces"] if trace.get("seed") == entity_key]
        html = case_report_html(entity, payload.get("window"), related, traces, payload["metrics"])
    return HTMLResponse(content=html)


# --------------------------------------------------------------------------
# The written record
# --------------------------------------------------------------------------
# Mounted BEFORE "/" on purpose. Route matching is in order, so a "/" mount
# registered first swallows every other path -- the documents page would 404
# with no obvious cause.
DOCS_DIR = ROOT / "docs"
if DOCS_DIR.exists():
    app.mount("/documents", StaticFiles(directory=str(DOCS_DIR)), name="documents")


# --------------------------------------------------------------------------
# The dashboard itself
# --------------------------------------------------------------------------
class _NoCacheStatic(StaticFiles):
    """Static files served with `Cache-Control: no-cache`.

    WHY THIS IS NOT A MICRO-OPTIMISATION
    ------------------------------------
    There is no build step here: the browser loads the files that are on disk. That
    means the browser's heuristic cache is the only thing between an edited
    stylesheet and the person looking at the result -- and during a hackathon that
    gap is a trap. It caught us: a fix to the dot grid's colour classes was on disk
    and served correctly by the API, while the browser had quietly kept the old
    copy, so the page still rendered 533 grey squares and the fix looked wrong.

    `no-cache` does NOT mean "do not cache". It means "revalidate before using it":
    the browser asks, the server answers 304 with no body, and the cost on
    localhost is nil. Correctness over bandwidth, on a host where bandwidth is
    free and being wrong is expensive.
    """

    def file_response(self, *args, **kwargs):  # type: ignore[override]
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


if (FRONTEND_DIR / "index.html").exists():
    # One mount serves the whole site. `html=True` resolves a directory request to
    # `index.html`, which is why the entry point is named index.html -- with
    # another name the mount served every asset correctly while "/" itself 404'd.
    #
    # Static pages, not a single-page app: each page has its own URL, its own
    # question, and a browser that can revisit, bookmark and print it. No build
    # step, no framework, and nothing fetched at runtime.
    app.mount("/", _NoCacheStatic(directory=str(FRONTEND_DIR), html=True), name="site")
else:  # pragma: no cover - only until the frontend lands
    @app.get("/", include_in_schema=False)
    def dashboard_placeholder() -> JSONResponse:
        return JSONResponse({
            "message": "NETRA API is running. The dashboard is not installed yet.",
            "api_docs": "/docs",
            "hint": "build the frontend into frontend/netra.html, or open /docs to explore the API",
        })


def main() -> int:  # pragma: no cover - convenience entry point
    import uvicorn

    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=False)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
