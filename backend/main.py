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
    POST /upload                      ingest a file and report the data-quality gate
    POST /analyze                     start a windowed replay as a background job
    GET  /job/{id}                    progress and log for a running job
    GET  /metrics                     the measured scorecard
    GET  /report/{entity}             printable case dossier
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
OUT_DIR = ROOT / "out"
MODELS_DIR = ROOT / "models"
UPLOAD_DIR = ROOT / "uploads"
FRONTEND_DIR = ROOT / "frontend"
DATA_DIR = ROOT / "data"
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
        "frontend": (FRONTEND_DIR / "netra.html").exists(),
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
        records = store.windows()
        if not records:
            raise HTTPException(status_code=409, detail="no windows recorded")

        if window == "all":
            window_id: int | None = None
            cache = _payload_cache_path(0)
        else:
            try:
                window_id = int(window) if window else records[-1].window_id
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail="window must be a batch id or 'all'",
                ) from None
            if window_id not in {record.window_id for record in records}:
                raise HTTPException(status_code=404, detail=f"no such window: {window_id}")
            cache = _payload_cache_path(window_id)

        if cache.exists():
            return json.loads(cache.read_text(encoding="utf-8"))

        payload = build_window_payload(store, window_id, models_dir=MODELS_DIR)
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        return payload


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
        return {
            "alerts": json.loads(frame.to_json(orient="records")),
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
    dataset = Path(request.dataset) if request.dataset else DATA_DIR / "transactions.csv"
    if not dataset.exists():
        raise HTTPException(status_code=404, detail=f"no such dataset: {dataset}")

    def work(job_id: str) -> dict[str, Any]:
        from monitoring.pipeline import replay

        jobs.log(job_id, f"dataset: {dataset}")
        jobs.log(job_id, "splitting into windows")
        result = replay(
            store_path=STORE_PATH, dataset=dataset,
            data_dir=DATA_DIR, models_dir=MODELS_DIR,
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


@app.get("/metrics", summary="The measured scorecard")
def metrics() -> dict[str, Any]:
    path = MODELS_DIR / "metrics.json"
    if not path.exists():
        return {"evaluated_on": "model not trained"}
    return json.loads(path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# Case dossier
# --------------------------------------------------------------------------
@app.get("/report/{entity_key}", response_class=HTMLResponse,
         summary="Printable case dossier for one lead")
def report(entity_key: str, window: int | None = Query(default=None, ge=1)) -> HTMLResponse:
    with _open_store() as store:
        records = store.windows()
        if not records:
            raise HTTPException(status_code=409, detail="no windows recorded")
        # Default to the window where this lead was LAST scored, not simply the
        # newest window: a lead from earlier in the week would otherwise 404 at
        # the moment an analyst asks for its dossier.
        window_id = window or store.latest_window_for(entity_key) or records[-1].window_id
        payload = build_window_payload(store, window_id, models_dir=MODELS_DIR)

        entity = next(
            (item for item in payload["entities"] if item["id"] == entity_key), None
        )
        if entity is None:
            raise HTTPException(status_code=404, detail=f"no entity {entity_key} in window {window_id}")

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
if (FRONTEND_DIR / "index.html").exists():
    # One mount serves the whole site. `html=True` resolves a directory request to
    # `index.html`, which is why the entry point is now named index.html -- with
    # the old name the mount served every asset correctly while "/" itself 404'd.
    #
    # Static pages, not a single-page app: each page has its own URL, its own
    # question, and a browser that can revisit, bookmark and print it. No build
    # step, no framework, and nothing fetched at runtime.
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="site")
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
