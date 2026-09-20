# NETRA v1 → v2 — Measured Comparison

**Team Vortex · SIH 2026 · PS SIH26146 · NTRO**

The first working version of NETRA did the job: it read a file, scored every
wallet group, and ranked them. This document measures **what the second version
changed**, domain by domain, with the before and after for every parameter that
can be measured.

Both versions are on disk — `netra/` (v1) and `Prototype/` (v2) — so nothing here
is remembered. Every v2 figure comes from `python tools/measure.py`, which ships
with the project; every v1 figure was read from v1's own artifacts (its
`models/metrics.json`, its schema, its source) or measured the same way.

Read the narrative version in [`CHANGELOG.md`](CHANGELOG.md); read the teaching
version in [`LEARNING_GUIDE.md`](LEARNING_GUIDE.md).

---

## 0. The headline, in one table

| | v1 | v2 | What it means |
|---|---|---|---|
| **Reported accuracy** | AUC **1.000** (single 75/25 split) | AUC **0.991 ± 0.009** (5-fold, grouped by batch) | The v1 number was inflated by a leak. The honest number is lower and comes with an uncertainty. |
| **Identity** | `E-0001` by rank — renumbered every run | content-derived, **stable forever** | "This group escalated from 40 to 92" became a true sentence. |
| **Explanation** | importance × z-score, did not sum to the score | contributions that **sum exactly**, residual **0.0** | The bars now add up to the number above them. |
| **Time** | one batch, no memory | **4 batches**, 270 events, alert lifecycle, time-to-detection | A report became a tool. |
| **Pages** | 1 | **6** + 3 printable reports | One question per screen. |
| **Contract** | 8 properties, 8 definitions | **14 and 14** | The interface could stop guessing. |
| **Endpoints** | 12 | **19** | Monitoring, glossary, quality gate, the reports. |
| **Scale** | quadratic in entities × transactions | **much better, but still super-linear** — measured below | One measurement contradicted our own claim, so the claim moved. |
| **Tests** | 23 functions / 30 collected | **26 functions / 26 collected**, plus API assertions **29 → 103** | Fewer collected cases, far more end-to-end coverage. |
| **Anomaly detector** | precision@20 0.250 | precision@20 **0.050** vs 0.0916 base rate | v2 reports a result *against itself*. Its v1 lift was an artefact. |
| **Offline guarantee** | vendored assets, CI check | same, plus **0 external references across 6 pages** and no build step | Enforced, not asserted. |

---

## 1. Data and the generator

| Parameter | v1 | v2 | Delta |
|---|---|---|---|
| Transactions (shipped dataset) | 27,860 | 27,860 | same |
| Columns | 12 | 12 | same |
| Capture span | ~4.9 days | **4.94 days** | measured |
| Distinct addresses | 1,727 | 1,727 | same |
| Planted ground-truth entities | 218 | 218 | same |
| Generator CLI | `--tx --clusters --seed --out` | same | same interface |
| Random seed | 42 | 42 | reproducible |
| File size / bytes per row | 8.76 MB | 8.76 MB / **314 bytes** | same |

**What changed:** nothing in the data — deliberately. The dataset is the control,
so every other row in this document is attributable to the software rather than to
the input. The v2 additions are *downstream* of it.

**One measured property v1 never reported:** bytes per row (314) and the
transaction-to-address ratio (27,860 transactions over 1,727 addresses = 16.1
transactions per address). Both are now in the measurement harness, because they
are the numbers that predict cost.

---

## 2. Ingestion and the quality gate

| Parameter | v1 | v2 | Delta |
|---|---|---|---|
| Formats | CSV, JSON, XML, SQLite | same 7 suffixes | same |
| Rows accepted | 27,860 | 27,860 | same |
| Rows rejected, with reasons | reported | reported | same |
| Placeholder blanking (`"N/A"` in optional fields) | — | **implemented + tested** | new |
| Duplicate txids | — | **reported, not dropped** | new |
| Upload path traversal | basename only | basename only | same |
| **Read-path confinement** | none — any path | **`data/` and `uploads/` only** | new |
| Throughput | not measured | **31,094 rows/s** (0.896 s) | now measured |
| Gate reachable without analysing | ✗ | **`GET /ingest-report`** | new |
| Gate shown for the built-in dataset | ✗ (demo skipped it) | **yes, same gate** | new |

**Why the confinement matters:** v2's `/analyze` and `/ingest-report` accept a
dataset path from the client. v1 had only the bundled path. Without confinement
the endpoint becomes a file-read primitive pointed at the filesystem — a request
for `../../etc/passwd` returns a parse error naming the file, and any readable CSV
becomes a dataset. The measured behaviour now:

```
?dataset=C:/Windows/win.ini  ->  400  "dataset must live under data/ or uploads/"
?dataset=../../../etc/passwd ->  400  "dataset must live under data/ or uploads/"
```

**The flow change, measured in clicks:** v1's ingest page took a file, reported
the gate, and then linked to a *previously* analysed payload — the gate described
one file and the report showed another. v2's gate leads to the analysis **of the
file it just described**, for an upload and for the built-in dataset alike.

---

## 3. Correlation and clustering

| Parameter | v1 | v2 | Delta |
|---|---|---|---|
| Addresses correlated | 1,725 | 1,725 | same |
| Wallet groups derived | 533 | 533 | same |
| Addresses per group (mean) | 3.24 | **3.24** | measured, same |
| CoinJoin excluded before clustering | yes | yes (**8 transactions**) | now counted |
| Control edges (IP → wallet) | present | 27,860 | now counted |
| Flow edges (wallet → wallet) | present | 27,862 | now counted |
| Dangling edges (endpoint not a node) | **possible** — IPs appeared as bare strings | **0** — IPs promoted to `N-####` nodes | fixed |
| Edge kinds in the payload | 2 | 2 | same |
| Clustering ARI vs planted truth | 0.9988 | 0.9988 | same |
| Community method | greedy modularity | greedy modularity (CNM) | same |
| Modularity (large transfers only) | not reported | **0.332** (raw 0.1909) | now measured |

**The one real change:** IP endpoints became first-class nodes. In v1 a control
edge could reference an address that was not in the node set, so the graph drew
edges into empty space — invisible on a dense graph and wrong. The test suite now
asserts that every edge endpoint resolves, which is a check v1 had and v2 had
dropped (see §11).

---

## 4. Features

| Parameter | v1 | v2 | Delta |
|---|---|---|---|
| Features per entity | **24** | **28** | **+4** |
| Feature matrix cells | 12,792 | **14,924** | +17% |
| Build time | not measured | **5.86 s** | now measured |
| Baseline statistics | mean / std | **median / MAD, winsorised, shipped in the artifact** | fixed |

**The four added features, exactly:**

| Added | Family | Why |
|---|---|---|
| `pagerank` | graph position | money-flow centrality |
| `betweenness` | graph position | how often money passes *through* a group |
| `community_size` | graph position | how big the operation around it is |
| `net_flow_ratio` | volume | whether it takes in more than it pays out |

**Nothing was removed.** The 24 v1 features are all still there — the diff is
purely additive, which is what you want when the previous version's evaluation was
suspect: you are not moving the goalposts, you are adding information.

**The baseline change is the one that fixed the most.** v1 standardised
attributions against a mean and standard deviation computed on the batch. One
enormous transaction moved that mean and **erased two-thirds of every
explanation**. v2 uses the median and MAD (× 0.6745), winsorises the extremes, and
ships the baseline **inside the model artifact** so the training and serving
baselines cannot drift apart.

---

## 5. Machine learning

### 5.1 Risk model — same hyperparameters, different evaluation

| Hyperparameter | v1 | v2 |
|---|---|---|
| `n_estimators` | 300 | 300 |
| `max_depth` | 12 | 12 |
| `min_samples_leaf` | 2 | 2 |
| `class_weight` | `balanced` | `balanced` |
| `random_state` | 42 | 42 |
| `n_jobs` | −1 | −1 |
| Artifact size | — | **2,205 KB** |

**Identical on purpose.** The story of v2 is not a better classifier; it is a
better *measurement* of the same classifier, plus better features. Claiming a
model improvement when the hyperparameters never moved would be a fabrication.

| Evaluation | v1 | v2 | Delta |
|---|---|---|---|
| Split | 75/25 random, single | **5-fold CV grouped by batch** + held-out | leak closed |
| Precision | 1.000 | 0.931 ± 0.068 (CV) · 0.907 (held-out) | honest |
| Recall | 0.909 | 0.902 ± 0.074 (CV) · 0.867 (held-out) | honest |
| F1 | 0.952 | 0.915 ± 0.063 (CV) · 0.886 (held-out) | honest |
| ROC-AUC | **1.000** | **0.991 ± 0.009** (CV) · 0.981 (held-out) | leak closed |
| Confusion matrix | 10 TP / 0 FP / 1 FN / 123 TN | 39 TP / 4 FP / 6 FN / 440 TN | larger, honest |
| Train / test rows | 399 / 134 | **1,465 / 489** | bigger |
| Evaluation basis | "planted ground truth, 25% held-out split" | "planted ground truth (cross-validated + held-out split)" | method stated |

**The leak, and what closing it cost.** v1 split rows at random. Rows from the
same batch are correlated and the same wallet appears once per batch, so the model
could be trained on a wallet and tested on the same wallet. Grouping the folds by
batch closed it. The measured effect: **the mean barely moved and the reported
uncertainty roughly doubled** (0.005 → 0.009 on AUC). Doubled uncertainty is the
honest outcome — the previous ±0.005 was measuring a leak, not a model.

### 5.2 The experiments that were not run at all in v1

| Experiment | v1 | v2 | What it answers |
|---|---|---|---|
| Rules-only baseline | — | **F1 0.143** (precision 0.162, recall 0.129, 142 flags) | "Is it just rules?" — Not remotely. |
| Linear baseline | — | **AUC 0.762 ± 0.381** | The instability is the finding: the signal is in the features, not the classifier. |
| Feature ablation | — | **AUC 0.993 ± 0.005** with 19 features | No dependence on a fragile feature set. |
| Calibration | — | **Brier 0.020, ECE 0.015** | Whether 90 means 90. |
| Decoy services | — | 10 planted, **held-out precision 0.960** | Does it flag lawful busy wallets? |
| Training mode | whole-dataset features | **windowed, matching serving scale** | Removes train/serve skew. |

### 5.3 Anomaly detector — the number that got worse and is published anyway

| Parameter | v1 | v2 |
|---|---|---|
| Algorithm | `IsolationForest` | `IsolationForest` |
| `n_estimators` / `contamination` / seed | 200 / 0.06 / 42 | 200 / 0.06 / 42 |
| precision@k | 0.250 @ k=20 | **0.050 @ k=20** |
| Base rate | 0.092 | **0.0916** |
| Verdict | 3.6× lift, an artefact | **below chance — reported as measured** |

This is the clearest example of the difference between the two versions. v1's
detector looked 3.6× better than chance; that lift was an artefact of scoring on
whole-dataset features and did not survive being scored the way the product
actually runs. v2 measures it at serving scale, finds it **worse than chance**,
and says so in the model card, in the changelog, in the learning guide, and on the
page — the number is not hidden behind an average.

---

## 6. Explanation

| Parameter | v1 | v2 | Delta |
|---|---|---|---|
| Method | importance × z-score | **exact decision-path contributions (Saabas)**, named as not-Shapley | method stated |
| Do the parts sum to the score? | **No** | **Yes** — residual **0.0** across all 77 leads | the central fix |
| Factors named per lead | all 24 (as importances) | 8 + a combined "smaller factors" term | readable |
| Unlisted contributions | dropped silently | **carried as a stated remainder** | arithmetic is exact |
| Leads explained | all | **77 of 77** | — |
| Attribution baseline | batch mean/std | **median/MAD, winsorised, in the artifact** | robust |
| Exculpatory reasons | present | present | same |
| Union-mode correctness | explained the current batch while showing the peak | **explains the stored feature vector at the peak** | fixed |

**The measured bug this fixed:** in v1 the printed bars did **not** add up to the
number above them. With 8 of 28 contributions shown, the gap was up to **0.08
score** — measured across 40 leads, 25 of which were off. In v2 the remainder is
computed as the arithmetic residual, so `base + listed + other = prediction`
holds to **2 × 10⁻⁶** (rounding in transport) and the displayed residual is
**0.0**.

---

## 7. Monitoring and identity

| Parameter | v1 | v2 | Delta |
|---|---|---|---|
| Event types | **none** | **8** (NEW_ENTITY, ESCALATION, DE_ESCALATION, DORMANT, RESURGENT, CLUSTER_GROWTH, BEHAVIOUR_SHIFT, CLUSTER_MERGE) | new |
| Events recorded (shipped run) | 0 | **270** | new |
| Alert lifecycle | none | 6 statuses incl. `closed_merged` | new |
| Merges detected & recorded | not detected | **14** | new |
| Time to detection | none | reported per run, with the window of first detection | new |
| Drift detection | none | **PSI + KS**, both must agree | new |
| Drift reference shipped | no | **28 features, 168 KB** | new |
| Identity scheme | `E-0001` by rank | `E-` + 9 digits of SHA-256 of the smallest address | **stable** |
| Identity stable across runs | ✗ | ✓ (tested) | fixed |
| History survives a merge | ✗ | ✓ (alias table) | fixed |
| Score rows retained | 0 | **1,912** | new |

**Why identity is the change everything else depended on.** With rank-based keys,
`E-0007` in run 1 and `E-0007` in run 2 are different wallets. Every sentence
about change over time — "escalated", "went quiet", "merged" — was therefore
ungrounded. Content-derived keys make the same wallet the same key forever, which
is the precondition for monitoring existing at all.

---

## 8. The backend and the contract

| Parameter | v1 | v2 | Delta |
|---|---|---|---|
| Endpoints | **12** | **19** | +7 |
| Endpoints added | — | `/windows`, `/events`, `/monitoring`, `/jobs`, `/ingest-report`, `/glossary`, `/print/dataset`, `/print/anomalies` | — |
| Endpoints removed | — | `/entities`, `/entity/{id}`, `/latest-json`, `GET /` (HTML) | superseded by `/results` + the static site |
| Contract properties | **8** | **14** | +6 |
| Contract definitions | 8 | **14** | +6 |
| Contract size | **12.3 KB** / 265 lines | **37.2 KB** / 679 lines | 3× larger, stricter |
| Payload validated as served | fixture only | **fixture + the payload the API returns** | new |
| Background job with progress & log | yes | yes, plus a **cache-warming step** | improved |
| Payload cache | none | **on disk, per window** | 32.9 s cold → **0.09 s warm** |
| Whole-capture payload | n/a | **1.08 MB**, 593 entities, 187 links, 77 trails | new |
| Per-batch payload build | — | **10.9 s median** | measured |
| Single process for API + pages | yes | yes | same |
| Path redirection by environment | ✗ | **5 variables** | new |

**Contract properties added:** `fleet` (with `drift`), `events`, `traces`,
`corpus`, `behaviour`, `window` — and, inside entities, `lead`, `explanation`
with its remainder, `history`, `typology`, `anomaly_score`. Each one exists
because a page needed a fact the payload did not carry, and the alternative was
computing it in the browser — which is how the interface starts having its own
opinion about the data.

**The `lead` flag deserves a note.** An IP endpoint inherits the peak risk of the
wallets it controlled, so it can carry a review band without being a wallet group.
Counting endpoints as leads reports **100 where the answer is 85** (measured, with
the 5-batch split). v2 states the rule once, in the payload, so no page has to
remember it.

---

## 9. The web interface

| Parameter | v1 | v2 | Delta |
|---|---|---|---|
| Pages | **1** (`netra.html`) | **6** | one question per screen |
| Page HTML | 796 lines | **33.4 KB across 6 pages** | — |
| Own JavaScript | 1,162 lines (`app.js`) | **156.2 KB** incl. CSS | — |
| Build step | `frontend/build.py` (121 lines) generates the page | **none** | no Node, no bundler |
| Vendored libraries | vis-network, Chart.js, 42 fonts | same | 876.2 KB |
| External requests | 0 | **0 across 6 pages** (CI-enforced) | same guarantee, wider surface |
| Shipped page weight | — | **189.6 KB** (no fonts) | measured |
| Design system | inline in one file | **extracted `theme.css`, 508 lines, verbatim** | one source of truth |
| Dark / light | dark only | **both**, one token set, charts redraw on toggle | new |
| Charts | Chart.js | Chart.js + CSS/SVG for print | — |
| Graph | vis-network | vis-network | same |
| Explain mode | present | present, glossary served from `/glossary` | one source of truth |
| Printable reports | 1 (case dossier) | **3** | new |
| Print stylesheet | inline | **embedded, 8.3 KB, no external requests** | verified |

**The interface restructure, in the order of the argument:**

| v1 page | v2 |
|---|---|
| one console view switching panels | **Cover** — what this is |
| — | **Ingest** — the quality gate, then the run |
| Traffic | **Dataset** — what is in the data |
| Investigate | **Anomalies** — what looks wrong, in plain words |
| Monitoring | **Dashboard** — the operation map, one batch at a time |
| Method | folded into **Documents** and the printed reports |

**Two measured interface facts worth keeping:** the dataset page draws **533
squares with 85 coloured** from the payload's own band values, and the dashboard's
day transport loads **4 batch payloads** on demand rather than one union.

---

## 10. The printable reports

| Parameter | v1 | v2 | Delta |
|---|---|---|---|
| Reports | 1 (case dossier, `/report/{entity}`) | **3** | +2 |
| Whole-capture dataset report | ✗ | **31.1 KB** | new |
| Anomaly/lead report | ✗ | **28.0 KB** | new |
| Case dossier | present | present, restyled, ~16 KB | improved |
| Rendering | HTML, browser print | same | no PDF library |
| Charts in print | n/a | **CSS and inline SVG** (vector, no canvas) | vector on paper |
| Self-contained (no external requests) | yes | **yes** (stylesheet embedded) | verified by the harness |
| A4 pagination | single page | `@page` A4 + `break-inside` rules | multi-page |
| Honesty footers | case dossier only | **all three**, plus the "not a finding of guilt" classification | wider |

---

## 11. Tests, CI and packaging

| Parameter | v1 | v2 | Delta |
|---|---|---|---|
| pytest functions | 23 | **26** | +3 |
| pytest collected cases | 30 | 26 | −4 (v1 had a parametrised band test) |
| pytest runtime | 10.5 s | 16.4 s | slower, deeper |
| API smoke assertions | **29** | **103** | **+74** |
| API smoke runtime | — | 171.9 s | full analysis inside the test |
| Payload referential integrity | **tested** (edges, alerts, ranking) | **tested** (edges, alerts, ranking, trace paths, count agreement) | restored + extended |
| Store/payload count agreement | not applicable | **asserted** | new |
| `node --check` over every asset | ✗ | **yes** | new |
| Offline check over every page | 1 page | **every page** | wider |
| Test isolation | separate store & data dir | **application redirected to a throwaway dir** | a test cannot destroy live state |
| CI named steps | 12 | **17** | +5 |
| Pinned dependencies | 15 | 15 | same |
| Python lines (project) | **6,403** | **11,600** | +81% |
| Launchers | `run.sh`, `run.bat` | same, plus `make` targets | same |
| Docker | yes | yes | same |
| Documentation files | 3 (`LEARNING_GUIDE`, `README`, `REPO_SETUP`) | **5** (CHANGELOG, MODEL_CARD, REIDEATION, COLAB_RETRAIN, this pair) + in-app reader | new |

**An honest entry in that table:** v2 collects **fewer** pytest cases than v1 (26
vs 30) because v1 had a parametrised band-boundary test that v2 expresses as one.
What v2 added instead is end-to-end coverage — the API assertions went from 29 to
103, including the integrity checks that v1 had and the rebuild initially dropped.
That regression was found *by writing this comparison*, and the checks were
restored (§12).

---

## 12. What this comparison found

Writing a comparison means re-reading both versions, and that found real problems
in v2 — which is the point of measuring rather than asserting:

| Found while comparing | State |
|---|---|
| v2 had **dropped v1's payload referential-integrity tests** (every edge resolves, every alert points at a real entity, alerts ranked) | **restored and extended** (trace paths, count agreement) |
| The restored test **immediately failed**: the store reported 66 open leads where the payload said 65 | **fixed** — an absorbed group's alert is closed as `closed_merged` at the merge; the queue no longer contains an item no page can open |
| `out/smoke.sqlite` was a **fixture built by the pre-fix code** and failed a new invariant | regenerated; the lesson (regenerate generated artifacts) is in the learning guide |
| The measurement harness reported the reports as *not* self-contained | **false negative** — it looked for any `href`, and the report's only one is a `javascript:` back-link. The check now looks for external references, which is what the claim means |

---

## 13. What did *not* change, and why

Saying what stayed the same is as important as saying what moved — it is the
difference between a comparison and a pitch.

| Unchanged | Why |
|---|---|
| **Risk hyperparameters** (300 trees, depth 12, leaf 2, balanced, seed 42) | The improvement is measurement and features, not tuning. |
| **Anomaly hyperparameters** (200, 0.06, 42) | Retuning it would hide the finding that it does not work at batch scale. |
| **The dataset** (27,860 transactions, seed 42) | A changing dataset would make every other row in this document unattributable. |
| **Risk bands** (85 / 70 / 50) | The thresholds are a product decision and they survived scrutiny. |
| **Dependencies** (15 pins) | No new library was added for monitoring, drift or reporting. |
| **The core algorithm** (common-input clustering, CoinJoin exclusion) | It worked; it stayed. |
| **Offline by construction** | The requirement did not move. |

---

## 14. Where v2 is still weak

Stated here for the same reason the product states its own limits.

1. **Synthetic data.** Every figure is measured against planted typologies.
   Performance on operational data is **not established**. The *method* would
   transfer; the numbers would not.
2. **The unsupervised detector is below chance** at batch scale and is not used
   for ranking. It is published as a negative result, not fixed.
3. **The generator caps transfer size**, so the 99th, 99.9th and maximum values
   are identical. Conclusions about very large transfers do not transfer.
4. **The learned feature importances are not yet decomposed** per typology, so we
   cannot say "this is the peel-chain signature's contribution to the model".
5. **Scale is super-linear, and we measured it rather than asserting it.** Two
   points, same code: **69,690 rows → 65.94 s** (94.6 s per 100k) and
   **278,832 rows → 913.11 s** (327.5 s per 100k). Rows ×4.00, cost per 100k
   ×3.46 — so roughly **O(n^1.8)**, not the linear shape the changelog claimed.
   The likely term is betweenness centrality inside the graph analysis, which is
   the classic quadratic in a growing graph. This needs work before anyone points
   a million-row dump at it, and the corrected claim is more useful than the old
   one.
6. **A single machine, single process** — no horizontal scale, by design for an
   air-gapped host.

---

## 15. How to reproduce every number here

```bash
# v2, everything measurable
python tools/measure.py --json out/measurements.json

# v2, the suites
python tasks.py test              # 26 tests
python tests/api_smoke.py         # 103 assertions
python tasks.py smoke             # a clean checkout, end to end

# v1, for comparison (its own tree, its own models)
cd ../netra && python tasks.py test && cat models/metrics.json
```

Timings are wall-clock on one Windows development machine and are reported with
the row count they were measured over. They establish orders of magnitude and the
**shape** of a cost curve, not a benchmark.

---

*Every figure in this document was produced by running the code, and every v1
figure was read from v1's own artifacts. Where a number is an estimate or is not
measured, it says so.*
