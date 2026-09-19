#!/usr/bin/env python
"""
NETRA task runner -- cross-platform, standard library only.

WHY THIS FILE EXISTS INSTEAD OF A MAKEFILE
------------------------------------------
`make` is not installed on Windows by default. The team practises on Windows and
ships on Linux, so a Makefile would mean one command vocabulary on the developer's
machine and a different one in the container -- and "it worked on my laptop" is
exactly the class of failure this project keeps trying to remove.

This gives ONE vocabulary that behaves identically on both, with nothing to
install. The `Makefile` is kept as a thin wrapper over these same commands for
Linux, Docker and CI, so there is still a single implementation.

Usage:
    python tasks.py <command>

Commands:
    gen        Generate the synthetic dataset (with hidden ground truth)
    train      Train the models, measure them, and write artifacts to models/
    replay     Run the windowed pipeline over the dataset and record history
    payload    Build a contract payload for one batch (or all of them)
    drift      Compare each batch against the training distribution
    serve      Start the API and the dashboard
    smoke      Fast end-to-end check: generate -> replay -> contract -> API
    test       Run the pytest suite
    clean      Delete generated data, models, output and history
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.resolve()
PY = sys.executable

# A small dataset for the smoke test: big enough to exercise every stage,
# small enough that the whole check finishes while you are still looking at it.
# A smoke test you avoid running because it is slow is not a smoke test.
SMOKE_TX = "3000"
SMOKE_CLUSTERS = "120"
SMOKE_STORE = "out/smoke.sqlite"
SMOKE_DATA = "data/smoke"


def _run(title: str, args: list, env: dict | None = None, quiet: bool = False) -> int:
    """Run a subprocess from the repo root, echoing what we are doing."""
    if not quiet:
        print(f"\n=== {title} ===")
        print(f"$ {' '.join(str(a) for a in args)}\n")
    # PYTHONPATH is set so every module can do `from ml.features import ...`
    # without the project needing to be installed as a package.
    full_env = {**os.environ, "PYTHONPATH": str(ROOT), **(env or {})}
    result = subprocess.run([str(a) for a in args], cwd=ROOT, env=full_env)
    return result.returncode


def cmd_gen(args: list) -> int:
    return _run("Generating the synthetic dataset",
                [PY, "-m", "generator.generate", *args])


def cmd_train(args: list) -> int:
    return _run("Training and measuring the models",
                [PY, "-m", "ml.train", *args])


def cmd_replay(args: list) -> int:
    """The windowed pipeline: split the dataset into batches and record history."""
    return _run("Running the windowed pipeline",
                [PY, "-m", "monitoring.pipeline", *args])


def cmd_payload(args: list) -> int:
    return _run("Building a contract payload",
                [PY, "-m", "monitoring.payload", *args])


def cmd_drift(args: list) -> int:
    return _run("Checking each batch against the training distribution",
                [PY, "-m", "ml.drift", *args])


def cmd_serve(args: list) -> int:
    """Start the API and the dashboard. Blocks until interrupted."""
    port = args[0] if args and args[0].isdigit() else "8000"
    extra = [a for a in args if a != port]
    print(f"\n=== NETRA -- open http://localhost:{port} ===\n")
    return _run("Starting the API and the dashboard",
                [PY, "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0",
                 "--port", port, *extra])


def cmd_test(args: list) -> int:
    return _run("Running the test suite", [PY, "-m", "pytest", "-q", *args])


def cmd_smoke(args: list) -> int:
    """The check that must always pass. If this is red, the project is broken.

    Runs the same sequence a clean checkout would: generate a small dataset, push
    it through the whole windowed pipeline into a throwaway store, build and
    contract-validate a payload, then exercise every HTTP endpoint. It uses a
    separate store and data directory so it can never damage real history.
    """
    steps = [
        ("Smoke 1/4: generate a small dataset",
         [PY, "-m", "generator.generate", "--tx", SMOKE_TX,
          "--clusters", SMOKE_CLUSTERS, "--out", SMOKE_DATA]),
        ("Smoke 2/4: run the windowed pipeline",
         [PY, "-m", "monitoring.pipeline", "--dataset", f"{SMOKE_DATA}/transactions.csv",
          "--data", SMOKE_DATA, "--store", SMOKE_STORE]),
        ("Smoke 3/4: build and validate a payload",
         [PY, "-m", "monitoring.payload", "--store", SMOKE_STORE,
          "--window", "2", "--out", "out/smoke_payload.json"]),
        ("Smoke 4/4: exercise every HTTP endpoint",
         [PY, "tests/api_smoke.py"]),
    ]
    for title, args in steps:
        if _run(title, args) != 0:
            print("\nSMOKE FAILED -- stop and fix this before anything else.\n")
            return 1

    print("\nSMOKE PASSED -- a clean checkout runs end to end and honours the contract.\n")
    return 0


def cmd_clean(args: list) -> int:
    """Delete everything generated. The generator and the code are the source."""
    print("\n=== Cleaning generated artifacts ===")
    keep = {".gitkeep", "spec.md"}
    for target in ("data", "models", "out", "uploads"):
        path = ROOT / target
        if not path.exists():
            continue
        for child in path.iterdir():
            if child.name in keep:
                continue  # never delete the sentinels that keep the folder in git
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink(missing_ok=True)
        print(f"  cleaned {target}/")
    print("\n  The dataset and the models are regenerated by 'python tasks.py gen'"
          "\n  and 'python tasks.py train'. Nothing here was source code.\n")
    return 0


COMMANDS = {
    "gen": cmd_gen,
    "train": cmd_train,
    "replay": cmd_replay,
    "payload": cmd_payload,
    "drift": cmd_drift,
    "serve": cmd_serve,
    "run": cmd_serve,          # alias: people reach for "run" first
    "smoke": cmd_smoke,
    "test": cmd_test,
    "clean": cmd_clean,
}


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        print(__doc__)
        print("Available commands:", ", ".join(sorted(set(COMMANDS) - {"run"})))
        return 0
    name = sys.argv[1]
    handler = COMMANDS.get(name)
    if handler is None:
        print(f"Unknown command: {name}\n")
        print(__doc__)
        return 2
    return handler(sys.argv[2:])


if __name__ == "__main__":
    raise SystemExit(main())
