"""
API smoke test -- exercise every endpoint over HTTP and check the responses.

WHY THIS EXISTS RATHER THAN pytest ONLY
---------------------------------------
The pytest suite tests the library functions directly. This hits the actual
application: routing, status codes, request parsing, response shapes and the
contract payload as SERVED. A function can be perfect while the route that
exposes it returns 500, and only this test would notice.

It also validates the served payload against the frozen contract, so a schema
drift that only appears through the API is caught here.

Run:
    python tests/api_smoke.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from backend.main import app, jobs  # noqa: E402
from tests.validate_contract import validate_document  # noqa: E402

PASSED: list[str] = []
FAILED: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    (PASSED if condition else FAILED).append(label)
    mark = "ok  " if condition else "FAIL"
    print(f"  {mark} {label}" + (f"  -- {detail}" if detail and not condition else ""))


def main() -> int:
    # A context manager is not optional here. `TestClient(app)` WITHOUT `with`
    # does not run the app's lifespan, so startup hooks never fire -- a mistake
    # that once produced a smoke test which passed while testing nothing.
    with TestClient(app) as client:
        print("\n=== health and state ===")
        response = client.get("/health")
        check("GET /health -> 200", response.status_code == 200, response.text[:200])
        health = response.json()
        check("health reports the engine version", health.get("engine_version") is not None)
        check("health reports the store", "store" in health)

        if not health.get("store", {}).get("exists"):
            print("\n  No monitoring state present. Run:")
            print("      python -m monitoring.pipeline")
            print("  then re-run this smoke test.\n")
            return 1

        response = client.get("/windows")
        check("GET /windows -> 200", response.status_code == 200, response.text[:200])
        windows = response.json()["windows"]
        check("windows listed", len(windows) > 0)
        check("windows carry index and total",
              all("index" in w and "total" in w for w in windows))
        # Test the most substantial window. The last one is often a partial day
        # (the capture ends mid-window), and asserting "alerts present" against a
        # 19-transaction tail would test the edge case instead of the product.
        substantive = max(windows, key=lambda w: w["transactions"])
        window_id = substantive["id"]
        print(f"  .. using window {window_id} ({substantive['transactions']} tx) "
              f"of {len(windows)}")
        # And confirm the degenerate window still serves rather than crashing.
        edge = min(windows, key=lambda w: w["transactions"])
        edge_response = client.get("/results", params={"window": edge["id"]})
        check("a small/partial window still serves a payload",
              edge_response.status_code == 200, edge_response.text[:200])

        print("\n=== the contract payload, as SERVED ===")
        response = client.get("/results", params={"window": window_id})
        check("GET /results -> 200", response.status_code == 200, response.text[:300])
        payload = response.json()
        problems = validate_document(payload)
        check("served payload satisfies the frozen contract", not problems,
              "; ".join(problems[:3]))
        check("payload carries a window block", "window" in payload)
        check("payload carries the fleet block", "fleet" in payload)
        check("entities present", len(payload["entities"]) > 0)
        check("alerts present", len(payload["alerts"]) > 0)
        check("events present", len(payload["events"]) > 0)

        explained = [e for e in payload["entities"] if e.get("explanation")]
        check("at least one entity carries a reconciling explanation", len(explained) > 0)
        if explained:
            residual = max(abs(e["explanation"]["residual"]) for e in explained)
            check("explanations reconcile to the prediction", residual < 1e-6,
                  f"max |residual| = {residual}")

        check("no look-ahead in entity history",
              all(
                  all(h["window"] <= payload["window"]["label"] for h in e.get("history", []))
                  for e in payload["entities"]
              ))

        print("\n=== monitoring feed and alerts ===")
        response = client.get("/events", params={"window": window_id})
        check("GET /events -> 200", response.status_code == 200, response.text[:200])
        check("event counts reported", "counts" in response.json())

        response = client.get("/alerts")
        check("GET /alerts -> 200", response.status_code == 200, response.text[:200])
        alerts = response.json()["alerts"]
        check("alerts listed with lifecycle", all("status" in a for a in alerts))
        check("alerts carry peak_risk and first_window",
              all(a.get("peak_risk") is not None and a.get("first_window") for a in alerts))

        response = client.get("/alerts", params={"status": "not-a-status"})
        check("unknown alert status -> 400", response.status_code == 400)

        print("\n=== analyst decision persists ===")
        target = alerts[0]["entity_key"]
        response = client.post(f"/alerts/{target}/status",
                               json={"status": "acknowledged", "assignee": "apurv"})
        check("POST /alerts/{entity}/status -> 200", response.status_code == 200, response.text[:200])
        response = client.get("/alerts", params={"status": "acknowledged"})
        check("acknowledged alert is retrievable by status",
              any(a["entity_key"] == target for a in response.json()["alerts"]))
        # put it back so repeated runs start clean
        client.post(f"/alerts/{target}/status", json={"status": "new", "assignee": "apurv"})

        print("\n=== upload and the data-quality gate ===")
        sample = ROOT / "data" / "windows" / f"{windows[-1]['label']}.csv"
        if not sample.exists():
            sample = ROOT / "data" / "transactions.csv"
        with sample.open("rb") as handle:
            response = client.post("/upload", files={"file": ("probe.csv", handle, "text/csv")})
        check("POST /upload -> 200", response.status_code == 200, response.text[:200])
        report = response.json()["report"]
        check("upload reports accepted/rejected counts",
              "accepted" in report and "rejected" in report)
        check("upload reports the source format", report.get("format") in ("csv", "sqlite"))

        # A path-traversal filename must be neutralised, not honoured.
        response = client.post("/upload", files={"file": ("../../evil.csv", b"x,y\n1,2\n", "text/csv")})
        check("path traversal in filename is neutralised",
              response.status_code in (200, 415) and "evil.csv" in response.text
              and ".." not in response.json().get("stored_as", ""))

        print("\n=== background job ===")
        response = client.post("/analyze", json={"mode": "replay"})
        check("POST /analyze -> 202", response.status_code == 202, response.text[:200])
        job_id = response.json()["job_id"]
        time.sleep(3)
        response = client.get(f"/job/{job_id}")
        check("GET /job/{id} -> 200", response.status_code == 200)
        job = response.json()
        check("job is running or already done", job["status"] in ("running", "done", "error"),
              job.get("error") or "")
        check("job produces log lines", len(job["log"]) > 0)
        response = client.get("/job/does-not-exist")
        check("unknown job -> 404", response.status_code == 404)

        print("\n=== metrics, dossier, reload ===")
        response = client.get("/metrics")
        check("GET /metrics -> 200", response.status_code == 200)
        check("metrics report a training mode",
              response.json().get("training_mode") is not None)

        lead = payload["alerts"][0]["entity"]
        response = client.get(f"/report/{lead}")
        check("GET /report/{entity} -> 200", response.status_code == 200, response.text[:200])
        body = response.text
        check("dossier states the fund-trace caveat", "Estimate, not a fact" in body
              or "not a fact" in body.lower())
        check("dossier states what the model is not", "not a verdict" in body)
        check("dossier includes the explanation method",
              "decision-path" in body or "TreeSHAP" in body)
        response = client.get("/report/NOPE-1234")
        check("unknown entity report -> 404", response.status_code == 404)

        response = client.post("/reload")
        check("POST /reload -> 200", response.status_code == 200, response.text[:200])
        check("reload reports cleared caches", "cleared_caches" in response.json())

        print("\n=== dashboard placeholder ===")
        response = client.get("/")
        check("GET / -> served (placeholder until the UI lands)",
              response.status_code == 200)

    print(f"\n  {len(PASSED)} passed, {len(FAILED)} failed")
    if FAILED:
        print("\n  FAILURES:")
        for label in FAILED:
            print(f"    - {label}")
        return 1
    print("  API SMOKE PASSED\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
