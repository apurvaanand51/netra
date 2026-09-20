# NETRA

**Network-Enhanced Transaction Risk Analysis**

Team Vortex · SIH 2026 · PS ID **SIH26146** · Org **NTRO** · Theme: Cryptocurrency

> **An offline, air-gapped tool that analyses bulk Bitcoin transaction traffic and
> produces ranked, explainable investigative leads — with a monitoring history.**

The problem statement asks for a Linux solution that runs with **no network
access**. That is not a deployment option here; it is the requirement the whole
build is arranged around. This document is therefore written backwards from
that: what to install, how to get it onto a machine that has never seen the
internet, and how to prove it still works with the cable pulled out.

---

## Find what you need

| If you want to… | Go to |
|---|---|
| **Install it on a Linux machine and run it offline** | [Install & run](#install--run-on-linux) |
| **Run it on this machine right now** | [Running it on Windows](#running-it-on-this-windows-machine-development) |
| **Present it / see the pages and the reports** | [The six pages](#the-six-pages) |
| Prove the offline claim to someone | [Proof it is actually offline](#proof-it-is-actually-offline) |
| Know the commands | [Command reference](#command-reference) |
| Fix something that broke | [Troubleshooting](#troubleshooting) |
| Understand what it does and how well | [The project](#the-project) |

---

# Install & run on Linux

## 1. What you need

| | Requirement | Why |
|---|---|---|
| **OS** | **Ubuntu 22.04 LTS** (or any Linux x86_64 with Python 3.10) | 22.04 is the recommended target because it **ships Python 3.10 in its base repositories** — so a machine with no network already has the interpreter. Debian 12 (3.11), Ubuntu 24.04 (3.12) and RHEL 9 (3.9) do *not*. |
| **Python** | **3.10.x — exactly** | Not 3.11, not 3.12. The pins in `requirements.txt` (`numpy==1.23.5`) have no wheels for newer interpreters, and the trained `.joblib` artifacts were pickled by Python 3.10 + numpy 1.23.5 + scikit-learn 1.6.1. A newer Python either refuses to install the pins or loads the models and dies with `ModuleNotFoundError: No module named 'numpy._core'`. See [Troubleshooting](#troubleshooting). |
| **`python3.10-venv`** | `sudo apt install python3.10-venv` | Without it, `python3.10 -m venv` fails with *"ensurepip is not available"*. On a truly air-gapped box, install it from your OS image or carry the `.deb`. |
| **Disk** | ~2 GB free | virtualenv ≈ 500 MB, wheel cache ≈ 300 MB, dataset 40 MB, models 4 MB. The Docker image is ≈ 1.2 GB. |
| **RAM** | 4 GB minimum, 8 GB comfortable | Training is the peak (scikit-learn fits in ~20 s on the shipped 27,860-transaction dataset). Serving is light. |
| **Docker** | *Optional* — only for [Path B](#path-b--docker-one-command) | Docker 20.10+ and Compose v2. Not needed for a native install. |
| **Network** | **None at run time.** Needed once, on a *different* machine, to build the wheel cache. | That machine must be the same OS family and CPU architecture as the target. |

**No GeoIP database is required.** This trips people up, so it is worth stating:
many designs call a GeoIP service or ship a MaxMind file. NETRA does not. The
`geo_country` and `asn` columns arrive **inside the transaction dump** (the
capture that produced it resolved the GeoIP offline). There is no second data
source to fetch, and no library in `requirements.txt` for it.

`python3.10-venv` is the only OS-level prerequisite beyond the interpreter. No
compiler and no build tools are needed, because every dependency is installed
from a pre-built wheel — which is exactly why the wheel cache below matters.

---

## 2. The whole thing, if you already have a bundle

```bash
tar -xzf netra-v1.0.0.tar.gz
cd netra-v1.0.0
./run.sh
```

Then open **http://localhost:8000**. That is the intended experience: one
command, nothing to configure, no registry to reach.

`run.sh` is safe to run twice — it prepares only what is **missing**, which is
what makes a second run need no network at all.

If you do not have a bundle yet, build one:

| You have | Use |
|---|---|
| A connected Linux machine, and a target that is air-gapped | **[Path A — native](#path-a--native-install-recommended)** |
| Docker on both ends, or you want the laziest possible target | **[Path B — Docker](#path-b--docker-one-command)** |
| The repository in GitHub, and you want the release artifact | **[Path C — the release bundle](#path-c--the-ci-release-bundle)** |

---

## Path A — native install (recommended)

### A1. On the connected machine: build and train

Use a machine with the **same OS family and architecture as the target** (Linux
x86_64). If your only connected machine is Windows or macOS, you can still
prepare this — see [A2](#a2-preparing-on-windowsmacos-for-a-linux-target).

```bash
git clone https://github.com/apurvaanand51/netra.git netra
cd netra

python3.10 -m venv .venv
source .venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt

# Produce the dataset, the models and the monitoring history.
python tasks.py gen
python tasks.py train
python tasks.py replay

# THE OFFLINE INSTALL CACHE — this is what the target machine installs from.
pip download -r requirements.txt -d wheels/
```

`pip download` writes every wheel, **including transitive dependencies**, into
`wheels/`. The verbatim file list is not pinned here on purpose — it follows
from `requirements.txt`, and the workaround is always the same: re-run
`pip download` and ship whatever it produces.

Optional, and worth the 30 seconds — prove the prepared tree works before you
carry it anywhere:

```bash
python tasks.py smoke
```

Expected last line: `SMOKE PASSED -- a clean checkout runs end to end and honours the contract.`

### A2. Preparing on Windows/macOS for a Linux target

`pip download` fetches wheels for **the machine it runs on** by default. A
wheelhouse built on Windows installs perfectly on Windows and fails on your
Linux target with *"no matching distribution found"* — a confusing error, since
the folder is obviously full of wheels.

Cross-download for the target instead:

```bash
pip download -r requirements.txt -d wheels/ \
  --only-binary=:all: \
  --platform manylinux2014_x86_64 \
  --python-version 3.10 \
  --implementation cp \
  --abi cp310
```

Two things about those flags:

- pip requires `--only-binary=:all:` (or `--no-deps`) alongside `--platform`, and
  the combination has a second benefit: it guarantees you never silently pull a
  *source* tarball. A source tarball would try to compile on the air-gapped host,
  where it cannot download a build backend — a failure that only shows up at the
  worst moment.
- If a package has no `manylinux2014` wheel, add
  `--platform manylinux_2_17_x86_64` (the modern spelling of the same tag) and
  re-run. `manylinux2014_x86_64` is an alias, so most projects need only one.

### A3. Carry it in, and first boot

```bash
# on the connected machine
tar -czf netra-offline.tar.gz netra/          # or use the release bundle
```

Transfer on whatever physical media your process allows, then:

```bash
tar -xzf netra-offline.tar.gz
cd netra
./run.sh
```

**What `run.sh` does, in order** — it is short and readable, but here is the
contract:

1. Picks `python3.10` if present, otherwise `python3` (`--version` is printed).
2. Creates `.venv/` if it is missing.
3. Installs dependencies **only if** `fastapi, sklearn, pandas, networkx,
   jsonschema` are not already importable. When it does install, it uses
   `pip install --no-index --find-links=wheels/` if `wheels/` has content —
   **`--no-index` is what makes the install offline**, not the folder alone.
4. Runs `gen` + `train` if `models/risk.joblib` or `data/transactions.csv` is
   missing, and `replay` if `out/monitoring.sqlite` is missing.
5. Prints the page map and starts uvicorn on port 8000.

Options:

```bash
./run.sh                 # prepare what is missing, then serve
./run.sh --fresh         # regenerate the dataset and retrain first
./run.sh --port 9000     # serve elsewhere (when 8000 is taken)
```

`run.bat` is the Windows equivalent, for development only. The target is Linux.

Both launchers print the six page URLs and the reports when they start, so the
list below and the running system cannot drift apart.

### Running it on this Windows machine (development)

The same one command, from the repository root, in a plain `cmd` or PowerShell
window:

```bat
run.bat                  :: prepare what is missing, then serve
run.bat --fresh          :: regenerate the dataset and retrain first
run.bat --port 9000      :: serve elsewhere
```

`run.bat` builds `.venv` with **Python 3.10** specifically (`py -3.10 -m venv
.venv`), checks that the pinned stack imports, and — if it does not — installs
from `wheels/` with `--no-index` when that folder is populated, falling back to
the online index only when it is empty. If a `venv/` folder (no dot) exists, it is
left alone: `run.bat` uses `.venv`, so an old `venv/` from an earlier attempt can
be deleted.

Nothing else is needed: no Node, no build step, no framework to install. The
browser loads the files that are on disk, and every vendored library is already
in `frontend/vendor/`.

### Manual equivalent

If you would rather not run a shell script — or you need to script it — this is
the same thing spelled out:

```bash
python3.10 -m venv .venv
source .venv/bin/activate

# offline install, by construction:
pip install --no-index --find-links=wheels/ -r requirements.txt

python tasks.py gen       # synthetic dataset + hidden ground truth
python tasks.py train     # train and measure both models
python tasks.py replay    # windowed pipeline -> out/monitoring.sqlite
python tasks.py serve 8000
```

Run those from the repository root. `PYTHONPATH` is set by `tasks.py`, so the
modules resolve without installing the project as a package.

---

## Path B — Docker (one command)

The image **bakes in the dataset, the trained models and the recorded history**,
so a container that starts on an isolated host comes up fully populated with no
setup step.

### B1. On a connected machine: build and save

```bash
docker build -t netra:monitoring-2 .
docker save netra:monitoring-2 | gzip > netra-image.tar.gz
```

`docker save` matters because `docker pull` is exactly the thing your target
cannot do. A registry is a network dependency; a `.tar.gz` on a USB stick is not.

### B2. On the air-gapped machine: load and run

```bash
docker load < netra-image.tar.gz
docker compose up --no-build -d
```

**`--no-build` is not optional here.** `docker-compose.yml` contains a `build:`
section, so a plain `docker compose up` on an isolated host tries to *rebuild*
the image, reaches the pip step, finds no index, and fails. `--no-build` pins it
to the image you just loaded.

No Compose available? The image is self-contained:

```bash
docker run -d -p 8000:8000 --name netra netra:monitoring-2
```

Useful checks:

```bash
docker compose ps                     # is it up?
curl http://localhost:8000/health     # is it WORKING, not merely up?
docker compose logs -f netra
docker compose down
```

The image runs as a **non-root user** (`uid 10001`) and carries a `HEALTHCHECK`
against `/health`, so *"the container is running"* and *"the tool works"* are
distinguishable — a process can be alive and serving 500s.

Building from source on a host with no internet also works, provided `wheels/`
was populated: the Dockerfile detects a non-empty `wheels/` and switches to
`pip install --no-index --find-links=wheels/` automatically.

---

## Path C — the CI release bundle

`.github/workflows/release.yml` runs on a version tag (`v*`) and produces two
artifacts for a machine that cannot pull anything:

| Artifact | What it is |
|---|---|
| `netra-<version>.tar.gz` | code, schemas, tests, `wheels/`, `data/`, `models/`, `out/`, vendored frontend, `run.sh`, `COMMIT` |
| `netra-<version>-image.tar.gz` | the Docker image, ready for `docker load` |
| `RELEASE_NOTES.txt` | the commit SHA and the full scorecard from `models/metrics.json` |

Release the tag, download the artifacts on a connected machine, carry them
across, and follow [Path A](#path-a--native-install-recommended) or
[Path B](#path-b--docker-one-command).

The release job **regenerates the dataset and retrains from the seed** before
packaging, so the numbers in the bundle come from that commit rather than from
artifacts committed earlier — and `COMMIT` is written into the bundle so the
shipped tool and the reported metrics are provably from the same source.

> There is no server to deploy to. For an air-gapped tool, "continuous delivery"
> means *a self-contained artifact you can carry in*, which is what this
> produces. The honest version of that constraint is more useful than pretending
> to deploy to a cluster.

---

## What travels in the bundle

| Path | In git? | Why |
|---|---|---|
| `generator/`, `ingestion/`, `correlation/`, `ml/`, `monitoring/`, `backend/` | ✅ | the pipeline |
| `frontend/` incl. `frontend/vendor/` | ✅ | six pages + the offline JavaScript and fonts |
| `schemas/results.schema.json` | ✅ | the frozen contract |
| `tests/` | ✅ | the suite, incl. the contract validator and API smoke test |
| `models/*.joblib`, `metrics.json`, `reference_distribution.json`, `ENVIRONMENT.txt` | ✅ | **committed on purpose** — a model is only reproducible if you ship the exact bytes you measured, and drift detection cannot run without the training distribution |
| `data/transactions.csv`, `ground_truth_*.csv` | ❌ gitignored | **regenerated offline from a fixed seed** by `tasks.py gen` — shipping it would ship an output, not a source |
| `out/` (SQLite history) | ❌ gitignored | produced by `tasks.py replay` |
| `wheels/*` | ❌ gitignored (the folder is tracked via `.gitkeep`) | large and rebuildable; **you populate it** with `pip download`, per [A1](#a1-on-the-connected-machine-build-and-train) |

That last row is the one to internalise: **a fresh `git clone` has an empty
`wheels/`.** The folder exists so the Dockerfile's `COPY wheels/` never fails —
but the offline install only works once you have run `pip download`.

`models/` is the exception to "generated things stay out of git", and
deliberately so: if the artifacts stayed out, this README would quote numbers
that the shipped `.joblib` no longer produces. For an investigative tool, *a
number is evidence*, so the artifact and the claim travel together.

---

# Proof it is actually offline

A paragraph in a README does not make a tool offline. These do — and every one
of them is checked in CI on every push, because a claim that is not enforced is
a claim that quietly stops being true.

### Run these eight checks

```bash
# 1. No page or stylesheet references an external resource.
grep -rn "https\?://" frontend/*.html frontend/assets/*.css
#    -> no output. An air-gapped browser fails a CDN load SILENTLY and renders a
#       blank dashboard, which is why this is a failing build in CI, not advice.

# 2. The offline libraries and fonts are actually present.
ls frontend/vendor
#    -> vis-network.min.js  chart.umd.min.js  fonts.css  fonts/
ls frontend/vendor/fonts | wc -l
#    -> 42

# 3. The install needs no index.
pip install --no-index --find-links=wheels/ -r requirements.txt
#    -> succeeds. --no-index means pip is forbidden from reaching the network.

# 4. The whole pipeline runs with no network.
python tasks.py smoke
#    -> SMOKE PASSED

# 5. The service answers.
curl -fsS http://localhost:8000/health
#    -> {"status":"ok","engine_version":"netra-monitoring-2","models":{...true...}, ...}
#    model flags false or a missing store mean the /health body will tell you,
#    rather than a blank page telling you nothing.

# 6. Nothing is listening for outbound connections.
ss -tupn | grep -i python
#    -> only the LISTEN socket on :8000

# 7. The printable reports render, which is what the Download buttons open.
for report in /print/dataset /print/anomalies; do
  curl -fsS -o /dev/null "http://localhost:8000$report" && echo "ok $report"
done
#    -> ok both. They are HTML, printed by the browser: no PDF library, nothing
#       to install on a host with no package registry.

# 8. The demonstration itself: UNPLUG THE NETWORK, reload the browser.
#    -> every page keeps working, including the graph and the charts.
```

Docker path instead of steps 3–4 — but note it **builds from scratch**, so
`wheels/` must already be populated (or the build host must have an index): the
`--no-cache` flag guarantees no cached layer is hiding a download, which is the
whole point of the check.

```bash
make offline-check      # docker compose build --no-cache, up, curl /health, down
```

### Why it holds

| Dependency a naive build would have | How it is removed here |
|---|---|
| CDN for the graph and chart libraries | `vis-network` and `Chart.js` are **vendored** into `frontend/vendor/`; CI fails the build if an `http://` appears in any page or stylesheet |
| Web font from Google Fonts | **42 font files** vendored locally, with `fonts.css` rewritten to point at them |
| A GeoIP service or MaxMind database | `geo_country` / `asn` arrive **as columns in the dump**; no library, no download |
| A second process for the UI (and CORS) | the API and the six pages are served by **one process**, same origin — one fewer moving part, and nothing to misconfigure |
| A package registry at install time | `--no-index --find-links=wheels/`; the Dockerfile bakes in the dataset, the models and the history so the image needs no setup step |
| A telemetry or update call | none exists; the tool makes no outbound requests |

---

# Command reference

One vocabulary on every platform — `python tasks.py <command>`. It is
stdlib-only, so it works before any dependency is installed. The `Makefile` is a
thin wrapper over the same commands for Linux, Docker and CI; there is no second
implementation.

| Command | What it does |
|---|---|
| `python tasks.py gen` | Generate the synthetic dataset with hidden ground truth |
| `python tasks.py train` | Train both models, measure them, write `models/` |
| `python tasks.py replay` | Run the windowed pipeline, record history into `out/monitoring.sqlite`. **Replaces** the previous history |
| `python tasks.py payload` | Build a contract payload for one window (or all) |
| `python tasks.py drift` | Compare each batch against the training distribution (PSI + KS) |
| `python tasks.py serve [port]` | Start the API and the dashboard |
| `python tasks.py smoke` | End-to-end check: generate → replay → contract → every HTTP endpoint |
| `python tasks.py test` | Run the pytest suite |
| `python tasks.py clean` | Delete generated data, models, output and history |

`make gen | train | replay | payload | drift | serve | smoke | test | clean`
does the same, plus `make docker` and `make offline-check`.

Useful flags:

```bash
python tasks.py gen --tx 4000 --clusters 200 --out data   # smaller dataset
python tasks.py payload --window 2 --out out/payload.json # one window
./run.sh --fresh                                          # regenerate everything
python -m monitoring.pipeline --keep-history              # append instead of replace
```

**A replay replaces the history; it does not add to it.** Analysing a second
dataset that way is deliberate — appending two captures would make the
whole-capture view the sum of two unrelated dumps, with numbers that still look
plausible. The genuinely incremental case (a new batch arriving for a capture
already loaded) is `--keep-history`.

**Where the paths live.** Every directory the server uses can be redirected by
environment variable, which is what makes the bundled demo, the tests and a
packaged deployment able to run from one codebase:

| Variable | Default | What it moves |
|---|---|---|
| `NETRA_OUT_DIR` | `out/` | the state store, the payload cache |
| `NETRA_DATA_DIR` | `data/` | the dataset and the per-batch files |
| `NETRA_MODELS_DIR` | `models/` | the trained artifacts and the scorecard |
| `NETRA_UPLOAD_DIR` | `uploads/` | files dropped in on the ingest page |
| `NETRA_FRONTEND_DIR` | `frontend/` | the pages and the vendored libraries |

**Reset to a clean state:** `python tasks.py clean` deletes `data/`, `models/`,
`out/` and `uploads/` contents (keeping the `.gitkeep` sentinels). Everything is
regenerated offline by `gen` + `train` + `replay`. Nothing it deletes is source
code.

---

# Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `bash: ./run.sh: /usr/bin/env: bad interpreter: No such file or directory` | `run.sh` has CRLF line endings (it was edited on Windows). The kernel reads the interpreter as `/usr/bin/env\r`. | `.gitattributes` already pins `*.sh text eol=lf`, so a clone is safe. If you copied the file by hand: `dos2unix run.sh` or `sed -i 's/\r$//' run.sh`. |
| `ModuleNotFoundError: No module named 'numpy._core'` | The model was pickled under numpy **2.x** and is being loaded by numpy **1.x** (or vice versa). | **Do not debug the pickle.** Reinstall the pinned stack on Python 3.10 and retrain: `python tasks.py train`. See `docs/COLAB_RETRAIN.md` for the full explanation. |
| `ERROR: Could not find a version that satisfies the requirement numpy==1.23.5` | You are on Python 3.11+ — the pins have no wheels for it. | Use Python 3.10. On Ubuntu 22.04 it is the default `python3`. Otherwise the Docker path pins it for you. |
| `ensurepip is not available` / `venv` creation fails | `python3.10-venv` is not installed. | `sudo apt install python3.10-venv` (on the connected machine, or from your OS image/`.deb`). |
| Python is 3.12+/3.14 and you cannot install the stack | Wrong interpreter, as above. | `python3.10 -m venv .venv` explicitly, or use Docker. |
| `pip` hangs, or fails with a DNS/timeout error during `./run.sh` | `wheels/` is empty, so the script fell through to the online branch. | Populate it per [A1](#a1-on-the-connected-machine-build-and-train), or use the Docker image. Confirm with `ls -A wheels`. |
| `ERROR: No matching distribution found` while installing from `wheels/` | The wheelhouse was built for a different platform or Python version. | Rebuild it with the cross-platform flags in [A2](#a2-preparing-on-windowsmacos-for-a-linux-target). |
| `docker compose up` tries to build and fails at pip | Compose saw the `build:` section and rebuilt instead of using the loaded image. | `docker compose up --no-build -d`. |
| `Error response from daemon: … pull access denied` / manifest unknown | The host tried to pull from a registry. | `docker load < netra-image.tar.gz` first — the loaded image needs no registry. |
| Dashboard loads but graphs and charts are blank | A vendored asset is missing (a CDN load would fail the same silent way). | `ls frontend/vendor` — expect `vis-network.min.js`, `chart.umd.min.js`, `fonts.css`, `fonts/`. Re-extract the bundle; do not "fix" it by adding a CDN link, which CI rejects anyway. |
| `Address already in use` / port 8000 taken | Another process holds 8000. | `./run.sh --port 9000`. |
| The numbers on screen look old / the server "did nothing" | A stale process is serving cached per-window payloads. This has happened: a failed restart left an old process serving sixteen-minute-old analytics. | `curl -X POST http://localhost:8000/reload` — it re-reads state and reports how old the data is. Every payload also prints its own timestamp. |
| `SMOKE FAILED` | Something is genuinely broken. | Stop and fix it before anything else. The test runs the whole application against a **throwaway directory** (`NETRA_OUT_DIR` is redirected to a temp dir before the app is imported), so it cannot touch the store the demonstration is using. It used to: the test posts to `/analyze`, and a full analysis replaces the history — one run mid-session left the pages reporting different lead counts depending on when they were loaded. |
| Two pages quote different lead counts | One of them is reading a payload built before the last analysis. | `curl -X POST http://localhost:8000/reload` drops the cached payloads; the next request rebuilds them from the current store. The strip at the bottom of every page prints the batch it is showing and when the payload was generated. |
| You edited a stylesheet or a script and the page did not change | The browser had the old file cached. | Static files are served `Cache-Control: no-cache`, so a normal reload is enough — the browser revalidates and gets a 304 with no body. If you were serving the files with something else, hard-refresh (`Ctrl+F5`). This cost us an hour: a correct fix on disk, still-cached in the browser, and the page still showing 533 grey squares. |
| You edited a **`.py`** file and the running server behaves as before | uvicorn is not started with `--reload`, so the already-imported module is still in memory. Saving a file does not change a running process. | Stop it and restart (`Ctrl+C`, then `run.bat`). This caught us twice in one session: a fix to the batch splitter was on disk, tested with pytest, and had no effect on the server until it was restarted — so the pages kept showing a "day" that held 19 transactions. |

---

# The project

## The idea in one paragraph

The problem statement does not ask for a fraud detector. It asks to **analyse
Bitcoin transaction traffic** — and that distinction shaped the whole build. So
NETRA reads a bulk dump (`CSV / JSON / XML / SQLite` from a network capture and a
chain extract), **correlates the network layer with the blockchain layer** so a
wallet has a country as well as a balance, describes the *whole* capture, and then
ranks the small share of it that behaves like money laundering — every lead
carrying the factors that produced its score and the trail it follows. It runs on
one machine with no network, because that is what the problem statement demands.

## What makes it different

| Most approaches | NETRA |
|---|---|
| Analyse the chain alone, bolt a map on the side | **Fuses** the two layers — *"this cluster of 6 wallets was controlled from IPs in RU and NL between 02:11–02:40"* |
| Report only what they flagged | **Analyses everything read**, and reports the flagged subset as a share of it |
| "Trust us, it's AI" | A **trained, measured** model — precision, recall, F1, AUC and calibration against **planted ground truth** |
| A black-box risk score | Every lead carries contributions that **sum exactly to the score**, and plain-English reasons |
| A batch report | **Monitoring**: 8 event types across time, an alert lifecycle, and measured time-to-detection |
| Cloud, subscription, foreign-hosted | **Offline, sovereign, auditable** — no data leaves the agency |

## Two things it does that are easy to miss

**1. It reports what it examined, not only what it found.** The Dataset page
partitions **every** wallet group, not just the suspects: on the shipped run
roughly seven in eight groups are ordinary activity that fired no structural
detector, the largest actors by value are lawful services, and the groups raised
for review account for a minority of the value moved. A lead list alone would
imply the money sits with the suspects. It does not, and the page says so. The
exact figures for the run in front of you are printed on that page.

**2. Some of its findings are against itself.** A scorecard that only reports
successes is advocacy:

- The **unsupervised detector performs worse than chance** at batch scale
  (precision@20 = 0.050 against a 0.092 base rate). Its earlier 3.6× lift was an
  artifact of whole-dataset features, and the collapse is published rather than
  dropped.
- A **logistic-regression baseline** on the same grouped folds reaches
  **AUC 0.762 ± 0.381** against the forest's **0.991 ± 0.009** — and that
  standard deviation is itself the finding: the linear model is unstable across
  batches, scoring near-chance on some and well on others. What the ablation
  below shows is that the *feature engineering*, not the choice of classifier,
  is where the signal is.
- Cross-validation was **leaking** — folds split rows from the same batch, and the
  same wallet appears once per batch. Grouping the folds did not move the mean and
  **doubled the reported uncertainty**, which is now what we quote.

## Architecture

```
┌──────────────┐   ┌──────────────┐   ┌───────────────┐   ┌──────────────┐
│  SYNTHETIC   │   │  INGESTION   │   │  CORRELATION  │   │   FEATURES   │
│  GENERATOR   │──▶│ CSV/JSON/XML │──▶│ network ⇄     │──▶│ per-entity   │
│ + hidden     │   │ SQLite       │   │ blockchain    │   │ 28 features  │
│ ground truth │   │ + quality    │   │ fusion        │   │              │
│              │   │   gate       │   │               │   │              │
└──────────────┘   └──────────────┘   └───────────────┘   └──────┬───────┘
                                                                  │
                                                                  ▼
┌──────────────┐   ┌──────────────┐   ┌───────────────┐   ┌──────────────┐
│  SIX PAGES   │   │   FastAPI    │   │  THE FROZEN   │   │   ML CORE    │
│  + case      │◀──│  one process │◀──│  CONTRACT     │◀──│ 2 trained    │
│  dossier     │   │  API + UI    │   │ results.json  │   │ models +     │
│              │   │              │   │               │   │ metrics      │
└──────────────┘   └──────────────┘   └───────────────┘   └──────┬───────┘
                                                                  │
                          ┌──────────────┐   ┌───────────────┐     │
                          │  MONITORING  │◀──│    SQLITE     │◀────┘
                          │ 8 events ·   │   │  state store  │
                          │ lifecycle    │   │ + identity    │
                          └──────────────┘   └───────────────┘
```

## The six pages

Open **http://localhost:8000**.

The order is the order of the argument. Each page answers one question and links to
the next, each is its own URL so a presenter can jump straight to it, and each leans
on charts rather than prose — a caption line under each visual, not a paragraph.

| Page | The question it answers |
|---|---|
| **Cover** `/` | What is this, whose is it, and what does it claim? |
| **Ingest** `/ingest.html` | What did we make of the file you gave us? |
| **Dataset** `/dataset.html` | What is in this data? — the whole capture |
| **Anomalies** `/anomalies.html` | What looks wrong, in plain words, and why? |
| **Dashboard** `/dashboard.html` | Where is it, one batch at a time? |
| **Documents** `/documents.html` | How it was built, including the mistakes |

Every page that shows a body of evidence also offers it as a **PDF**, rendered for
A4 by the server and saved with the browser's own print-to-PDF — vector text and
vector charts, no PDF library, and nothing to install on a host with no package
registry.

| Report | What it contains |
|---|---|
| `/print/dataset` | The whole capture: the summary sentence, every chart, the examined-vs-flagged grid, the method |
| `/print/anomalies` | Every lead with its priority, the top lead decomposed in full, the plain-language glossary, the limits |
| `/report/{entity}` | A one-page case dossier: the lead, its evidence, its money trail, and what the model is *not* |

### The flow, as a demo runs it

1. **Ingest** — drop a file, or press *Run the built-in dataset*.
2. **The gate** — rows read, usable, rejected, and the reason for each. Nothing
   expensive has happened yet. The button under it says *Analyse this file*, and
   it analyses the file the gate just described — including an uploaded one.
3. **The run** — four named stages and the pipeline's own log, then the page
   moves on by itself.
4. **Dataset** — the whole capture in charts: 27,860 transactions, 533 wallet
   groups, one square per group, and the flagged minority standing out from the
   grey mass (77 on the shipped dataset). The page prints the count it found, and
   the count is a function of how the batches were split — fold the last partial
   day differently and it moves by a few, which is why every page names the batch
   it is showing rather than assuming.
5. **Anomalies** — pick a lead; the page explains the pattern in plain words,
   shows the factors that produced the score and makes them add up, then follows
   the money.
6. **Dashboard** — the operation map, with the batches on a transport you can
   play through in order.
7. **PDF** — the *Download* button on any of those pages opens an A4 report;
   the browser's print-to-PDF produces the file.

A replay of a **different** dataset starts from an empty history, so two captures
cannot end up in one analysis. Re-running the built-in dataset keeps its history.


`/docs` is the generated API console.

The API surface, for anyone wiring this into something larger:
`/health` · `/windows` · `/results?window=n` · `/events?window=n` ·
`/alerts?status=…` · `POST /alerts/{entity}/status` · `/glossary` ·
`/ingest-report` · `POST /upload` ·
`POST /analyze` · `/job/{id}` · `/metrics` · `/print/dataset` · `/print/anomalies` ·
`/report/{entity}` · `POST /reload`.

## What the models achieve

Measured against **planted ground truth**, with cross-validation folds grouped by
batch so the same wallet cannot appear on both sides of a split.

| Model | Metric | Value |
|---|---|---|
| Risk (`RandomForest`, supervised) | ROC-AUC · precision · recall · F1 | **0.991 ± 0.009 · 0.931 ± 0.068 · 0.902 ± 0.074 · 0.915 ± 0.063** |
| Risk, held-out split | precision · recall · F1 · ROC-AUC | 0.907 · 0.867 · 0.886 · 0.981 |
| Calibration | Brier · expected calibration error | **0.020 · 0.015** |
| Anomaly (`IsolationForest`, unsupervised) | precision@20 | 0.050 (base rate 0.092 — **below chance**, see below) |
| Entity grouping | Adjusted Rand Index | **0.999** |
| Graph structure | community modularity | 0.332 (0.191 on the unfiltered graph) |

**Is it just rules?** Measured three ways, because an argument is worth less than
a number:

```
rules alone, thresholds exactly as shipped   precision 0.162  recall 0.128  F1 0.143
ablation, all 9 rule features REMOVED        ROC-AUC 0.993 ± 0.005 on 19 features
decoys, 10 lawful high-volume services       0 flagged in the top 25
```

Deleting every hand-written detector does not move AUC. The signal is in the
measured traffic, not in our own rules echoed back.

Training and measurement take about 22 seconds on the shipped dataset. Every
number above is in `models/metrics.json` — the printable reports print that file, so
the scorecard and the artifacts cannot drift apart.

## The four required AI/ML areas

All four are implemented, and each is labelled honestly:

| Area | Implementation | Kind |
|---|---|---|
| **Entity clustering** | common-input ownership → connected components | graph algorithm (ARI 0.999) |
| **Anomaly detection** | `IsolationForest` over per-entity features | trained model — **and it does not work well here** |
| **Peel-chain / mixing detection** | structural detectors whose outputs become model *features* | domain detectors feeding ML |
| **Risk scoring** | `RandomForestClassifier` → 0–100 + precision/recall/F1/AUC + per-lead contributions | trained model |

Two of the four are genuinely trained models. The detectors encode domain
knowledge; the model learns how much to trust each signal — and the ablation shows
it does not need them.

## Monitoring, which is the half that is easy to skip

Every batch is compared against the previous one, and the deltas become typed
events with attribution — *"risk 14 → 55 because burst concentration 0.2 → 0.5"*:

`NEW_ENTITY` · `ESCALATION` · `DE_ESCALATION` · `DORMANT` · `RESURGENT` ·
`CLUSTER_GROWTH` · `BEHAVIOUR_SHIFT` · `CLUSTER_MERGE`

Some of those can only exist across time: **"went quiet" is not visible in a single
batch**. Identity is *pinned* across batches, because a wallet that gains an
address must not silently become a different entity — and when a co-spend proves
two clusters are one, that is a **finding**, emitted as an event rather than
papered over.

**Drift detection** compares each batch against the training distribution (PSI and
KS, agreeing before a feature is called drifted). It immediately flagged the
degenerate 19-transaction tail batch — *"standard confidence in these scores is
not warranted"* — and independently rediscovered the train/serve skew that had
been a bug an hour earlier.

## Data

**Synthetic, and deliberately so.** Generated from a fixed seed, schema-identical
to fused Bitcoin and network telemetry, carrying **planted illicit typologies**
(peel chains, CoinJoin mixing, ransomware fan-in, cross-border control) with
**hidden labels**.

That is what makes the reported accuracy meaningful: **we know the answer, so we
can measure whether the models found it.** No privacy exposure, no legal risk,
reproducible from a seed.

The shipped dataset: **27,860 transactions, 532 wallet entities (43 carrying a
planted illicit label), 12 countries, 12 ASNs**, across five batches — four full
windows of ~7,000 transactions and a deliberately degenerate 19-transaction tail
that the drift check catches. It is produced offline by
`python tasks.py gen`; nothing is downloaded.

Two things exist purely to keep the evaluation honest:

- **Decoy legitimate services** — high-volume payment processors with regional
  infrastructure that look statistically suspicious and are lawful (10 planted).
  Without them, "busy" and "criminal" would coincide and precision would mean
  nothing.
- **Diluted signatures** — real launderers also buy coffee, so planted wallets
  also make ordinary payments. Without this the models would score perfectly on a
  technicality.

Required ingest fields: `timestamp, src_ip, dst_ip, src_port, dst_port, txid,
input_addresses[], output_addresses[], input_amounts[], output_amounts[],
geo_country, asn`.

## Repository layout

```
netra/
├─ schemas/results.schema.json   ⭐ THE FROZEN CONTRACT — start here
├─ generator/                    synthetic data + planted ground truth
├─ ingestion/                    CSV/JSON/XML/SQLite + the data-quality gate
├─ correlation/                  network ⇄ blockchain fusion
├─ ml/                           clustering, anomaly, patterns, risk, drift, evaluation
├─ monitoring/                   state store, identity pinning, events, corpus analysis
├─ backend/                      FastAPI app, job queue, the three A4 reports
├─ frontend/                     six pages + vendored offline libraries
│  └─ assets/theme.css           the design system, extracted whole
├─ models/                       trained artifacts + the measured scorecard
├─ tests/                        pytest suite, contract validator, API smoke test
├─ docs/                         the review, the model card, the changelog, the retrain guide
├─ wheels/                       the offline install cache (populate with pip download)
├─ tasks.py                      cross-platform task runner
└─ Dockerfile / docker-compose.yml / run.sh / run.bat / Makefile
```

New to the codebase? Read `docs/REIDEATION.md` first — it records the review that
reshaped the project, including a false alarm we raised and retracted.

Anything about the **models** specifically — including the numpy trap that would
have shipped a `.joblib` that refuses to load on the demo machine — is in
`docs/COLAB_RETRAIN.md`.

## Known limitations

Stated here because a judge will find them anyway, and a project that hides them
is worth less than one that does not:

- **Not evidence of guilt.** A high score means *look here first*.
- **Not validated on operational data.** Every figure comes from synthetic traffic.
- **The anomaly detector does not work at batch scale** — below the base rate, and
  reported as measured.
- **The generator caps transfer size**, so the 99th, 99.9th and maximum values are
  identical. Conclusions about very large transfers do not transfer to reality.
- **Fund trails are estimates.** Bitcoin is fungible, so a multi-hop trail is a
  proportional allocation, labelled as one everywhere it appears.
- **Clustering assumes common-input ownership**, which CoinJoin deliberately
  breaks. That is why CoinJoin is detected and excluded first.
- **Bitcoin only.** Privacy coins are out of scope.

## Cited technologies

Python 3.10 · pandas · numpy · scikit-learn (`RandomForest`, `IsolationForest`,
metrics) · scipy (KS test) · networkx · FastAPI · uvicorn · SQLite · jsonschema ·
pytest · Docker · GitHub Actions · vis-network · Chart.js

## Licence

MIT — see `LICENSE`. The dataset is synthetic and contains no real addresses,
IPs, or personal data.
