# NETRA

**Network-Enhanced Transaction Risk Analysis**

Team Vortex · SIH 2026 · PS ID **SIH26146** · Org **NTRO** · Theme: Cryptocurrency

> **An offline, air-gapped tool that analyses bulk Bitcoin transaction traffic and
> produces ranked, explainable investigative leads — with a monitoring history.**

---

## The idea in one paragraph

The problem statement does not ask for a fraud detector. It asks to **analyse
Bitcoin transaction traffic** — and that distinction shaped the whole build. So
NETRA reads a bulk dump (`CSV / JSON / XML / SQLite` from a network capture and a
chain extract), **correlates the network layer with the blockchain layer** so a
wallet has a country as well as a balance, describes the *whole* capture, and then
ranks the small share of it that behaves like money laundering — every lead
carrying the factors that produced its score and the trail it follows. It runs on
one machine with no network, because that is what the problem statement demands.

---

## What makes it different

| Most approaches | NETRA |
|---|---|
| Analyse the chain alone, bolt a map on the side | **Fuses** the two layers — *"this cluster of 6 wallets was controlled from IPs in RU and NL between 02:11–02:40"* |
| Report only what they flagged | **Analyses everything read**, and reports the flagged subset as a share of it |
| "Trust us, it's AI" | A **trained, measured** model — precision, recall, F1, AUC and calibration against **planted ground truth** |
| A black-box risk score | Every lead carries contributions that **sum exactly to the score**, and plain-English reasons |
| A batch report | **Monitoring**: 8 event types across time, an alert lifecycle, and measured time-to-detection |
| Cloud, subscription, foreign-hosted | **Offline, sovereign, auditable** — no data leaves the agency |

---

## Two things it does that are easy to miss

**1. It reports what it examined, not only what it found.** On the shipped dataset,
**84.1% of wallet groups are ordinary**, the largest actors by value are all
lawful services, and the flagged groups account for **20.3% of the value moved**.
A lead list alone would imply the money sits with the suspects. It does not, and
the Traffic page says so.

**2. Some of its findings are against itself.** A scorecard that only reports
successes is advocacy:

- The **unsupervised detector performs worse than chance** at batch scale
  (precision@20 = 0.050 against a 0.092 base rate). Its earlier 3.6× lift was an
  artifact of whole-dataset features, and the collapse is published rather than
  dropped.
- A **logistic regression reaches AUC 0.995** against the forest's 0.991. The
  margin over a linear model is small: **the feature engineering is doing more
  work than the model choice.**
- Cross-validation was **leaking** — folds split rows from the same batch, and the
  same wallet appears once per batch. Grouping the folds did not move the mean and
  **doubled the reported uncertainty**, which is now what we quote.

---

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

---

## Run it

```bash
./run.sh          # Linux / macOS      — prepares what is missing, then serves
run.bat           # Windows

docker compose up # or: one command, image bakes in the dataset and the models
```

Then open **http://localhost:8000**.

| Page | The question it answers |
|---|---|
| **Ingest** | What did we make of the file you gave us? |
| **Traffic** | What is in this data? — the whole capture |
| **Investigate** | Which groups need attention, and why? |
| **Monitoring** | What changed since the last batch? |
| **Method** | How well does it work, and what is it *not*? |
| **Documents** | How it was built, including the mistakes |

`/docs` is the generated API console. `/report/{entity}` is a printable case dossier.

---

## What the models achieve

Measured against **planted ground truth**, with cross-validation folds grouped by
batch so the same wallet cannot appear on both sides of a split.

| Model | Metric | Value |
|---|---|---|
| Risk (`RandomForest`, supervised) | ROC-AUC · precision · recall · F1 | **0.991 ± 0.009 · 0.931 ± 0.068 · 0.902 ± 0.074 · 0.915 ± 0.063** |
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

---

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

---

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

---

## Data

**Synthetic, and deliberately so.** Generated from a fixed seed, schema-identical
to fused Bitcoin and network telemetry, carrying **planted illicit typologies**
(peel chains, CoinJoin mixing, ransomware fan-in, cross-border control) with
**hidden labels**.

That is what makes the reported accuracy meaningful: **we know the answer, so we
can measure whether the models found it.** No privacy exposure, no legal risk,
reproducible from a seed.

Two things exist purely to keep the evaluation honest:

- **Decoy legitimate services** — high-volume payment processors with regional
  infrastructure that look statistically suspicious and are lawful. Without them,
  "busy" and "criminal" would coincide and precision would mean nothing.
- **Diluted signatures** — real launderers also buy coffee, so planted wallets
  also make ordinary payments. Without this the models would score perfectly on a
  technicality.

Required ingest fields: `timestamp, src_ip, dst_ip, src_port, dst_port, txid,
input_addresses[], output_addresses[], input_amounts[], output_amounts[],
geo_country, asn`.

---

## Offline by construction

- Every frontend library (**vis-network**, **Chart.js**, and **42 font files**) is
  **vendored locally**. There are **zero CDN references**, and CI fails the build
  if one appears — because an air-gapped browser fails a CDN load *silently* and
  renders a blank dashboard.
- The API and the dashboard ship in **one process**: nothing else to deploy, no
  CORS to configure.
- `wheels/` carries a pre-downloaded wheel cache, so the install needs no registry.
- **CI asserts all of the above**, rather than a paragraph asking you to believe it.

To prove it live: **disconnect the network, reload, everything keeps working.**

---

## Repository layout

```
netra/
├─ schemas/results.schema.json   ⭐ THE FROZEN CONTRACT — start here
├─ generator/                    synthetic data + planted ground truth
├─ ingestion/                    CSV/JSON/XML/SQLite + the data-quality gate
├─ correlation/                  network ⇄ blockchain fusion
├─ ml/                           clustering, anomaly, patterns, risk, drift, evaluation
├─ monitoring/                   state store, identity pinning, events, corpus analysis
├─ backend/                      FastAPI app, job queue, case dossier
├─ frontend/                     six pages + vendored offline libraries
├─ models/                       trained artifacts + the measured scorecard
├─ tests/                        pytest suite, contract validator, API smoke test
├─ docs/                         the review, the model card, the changelog
├─ tasks.py                      cross-platform task runner
└─ Dockerfile / docker-compose.yml / run.sh / run.bat
```

New to the codebase? Read `docs/REIDEATION.md` first — it records the review that
reshaped the project, including a false alarm we raised and retracted.

---

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

---

## Cited technologies

Python 3.10 · pandas · numpy · scikit-learn (`RandomForest`, `IsolationForest`,
metrics) · scipy (KS test) · networkx · FastAPI · uvicorn · SQLite · jsonschema ·
pytest · Docker · GitHub Actions · vis-network · Chart.js

---

## Licence

MIT — see `LICENSE`. The dataset is synthetic and contains no real addresses,
IPs, or personal data.
