# What changed, v1 → v2

**Team Vortex · SIH 2026 · PS SIH26146**

The first working version of NETRA did the job: it read a file, scored every
wallet group, and ranked them on a dashboard. This document records what changed
in the second version and, wherever possible, **the number that changed**.

Where a figure appears, it was measured on the same 27,860-transaction dataset
unless stated otherwise.

---

## 1. The short version

| | v1 | v2 |
|---|---|---|
| Outputs | one ranked table | ranked leads · operation map · fund trails · monitoring feed · case dossier |
| Time | a single batch, no memory | windowed, with history and deltas |
| Identity | `E-0001` re-assigned every run | derived from the wallet's own addresses, stable forever |
| Scale | quadratic in entities × transactions | super-linear (≈O(n^1.8)), measured at two points |
| Explaining | importance × z-score | contributions that **sum exactly to the score** |
| Evaluation | one 75/25 split | 5-fold CV, calibration, and three experiments answering "is it just rules?" |
| Robustness | clean input only | SQLite source, validation gate, outlier protection |
| Monitoring | none | events, alert lifecycle, time-to-detection |

---

## 2. Identity: the change everything else depended on

**v1** numbered wallet groups `E-0001, E-0002, …` sorted by size within each run.
Deterministic for one dataset — and wrong the moment there is more than one:

```
run 1:  E-0007 = wallet group A
run 2:  E-0007 = a completely different group, because the ranking shifted
```

So "entity E-0007 escalated from 40 to 92" could describe two unrelated wallets.
**Confident, false intelligence is the worst failure mode an investigative tool
has**, and it made monitoring impossible: you cannot track a trend for a wallet
whose name changes every run.

**v2** derives the key from the group's content — the lexicographically smallest
address it contains — and then **pins** it: the first time an address is seen it
is bound to a key for good, and later groups inherit that key.

| Check | Result |
|---|---|
| Same grouping as before | identical partition, ARI 0.9988 unchanged |
| Keys stable across runs | yes |
| Contract-compatible | yes — numeric, matching `^[EN]-[0-9]{4,}$` |

The ordering assumption was also a subtle trap: correlation entity ids and
generator entity ids are **different namespaces that share a format**. Joining
them compares two unrelated numberings and produces nonsense with total
confidence. Every join in v2 is through **addresses**.

---

## 3. Scale: 630 seconds to 8.9

**v1** scanned the whole frame three times *per entity*:

```python
sent     = work[work["_in_owner"] == entity_id]      # full scan
received = work[work["_out_owner"] == entity_id]     # full scan
network  = controls[controls["entity"] == entity_id] # full scan
```

Cost scaled as `entities × transactions`. Not a slow path — a **latent failure**:
a ten-times-larger evaluation set would have made the pipeline appear to hang.

| Rows | Correlate, v1 | Correlate, v2 | Speedup |
|---|---|---|---|
| 27,860 | 11.06 s | 0.83 s | 14.9× |
| 100,000 | **630.0 s** | 8.88 s | **70.9×** |
| 301,178 | — | 8.93 s | — |
| 1,003,816 | ~17 h (projected) | **33.34 s** | — |

**CORRECTION (measured again later):** the claim above says "linear". Re-measured
with `python tools/measure.py`, the full pipeline is **super-linear**: 69,690 rows
→ 65.94 s, and 278,832 rows → 913.11 s. Rows ×4.00, cost per 100k rows ×3.46,
which is roughly O(n^1.8). The correlate step may well be flat as measured here;
the pipeline as a whole is not, and the likely term is betweenness centrality in
the graph analysis. The earlier throughput figures stand as measured for the step
they measured — the generalisation from them did not. Clustering went 1.02 s → 0.07 s; the structural detectors
3.60 s → 1.55 s.

**Ingestion** also changed shape: readers now return DataFrames rather than a
list of dicts, which at 1M rows was roughly a gigabyte of Python object overhead
before validation began.

---

## 4. Robustness: one bad row was erasing two-thirds of every explanation

**v1** computed feature attributions as `importance × z-score`, with the z-score
from the training **mean and standard deviation**. Contaminating a single row of
the 533×24 feature matrix and re-measuring mean |z| across all entities:

| | Attribution magnitude retained |
|---|---|
| v1: mean / standard deviation | **−62.0%** (worst feature −68.8%) |
| v2: median / MAD | **+0.4%** |

So a single corrupt value was destroying about two-thirds of every explanation in
the system — a defect in what we shipped, not a hypothetical about future data.

Two further changes:

- **Winsorisation.** Every feature is bounded to the range seen in training, and
  those bounds travel **inside the model artifact**, so inference cannot silently
  skip them. A sentinel `999999` arrives as 13.82 and is clamped to 7.57.
- **A data-quality gate.** Placeholders (`N/A`, `NULL`, `-`), sentinel ports
  (`-1`, `999999`), non-finite amounts (`inf`), and malformed IPs such as
  `40.52.114` are now **rejected with a reason code** rather than flowing
  through. On 14 deliberately hostile rows: 4 accepted, 10 rejected, 10 distinct
  reasons.

Deliberately **not** standardised: the model's inputs. Trees split on order, so
rescaling changes nothing about the splits. The robust z-score is used only where
it fixes something — the explanations.

---

## 5. New: graph intelligence

v1 used the flow graph for exactly two numbers per entity (`fan_in`, `fan_out`),
which treats the graph as a bag of local degrees. v2 asks what **shape** the
operation has:

- **Communities** — which wallets belong to the same operation.
- **Roles** — collector / distributor / relay / cash-out / mixing service.
- **Centrality** — PageRank and betweenness as model features.
- **Fund trails** — *"of the 62 BTC entering this collector, 41 reached an
  exchange within three hops."*

A finding worth recording: community detection on the **raw** graph gives a
modularity of **0.19**, barely better than chance, because 24,000 edges of small
transfers connect unrelated entities almost randomly. Filtering to the top 10% of
edges by value gives **0.33**, and the top 1% gives **0.88**. The laundering
structure is genuinely and highly modular — it was hidden underneath the small
payments.

Features went from **24 to 28**.

Roles are deliberately **not** model features: a rule-derived label handed to the
model as a feature is how a rule quietly becomes the answer while still looking
like machine learning.

---

## 6. Explaining: numbers that now add up

**v1** shipped `importance × z-score`. It was readable, but it had a property
nobody had checked: **it does not sum to the prediction.** Nothing tied the
explanation to the score the analyst was looking at.

**v2** computes contributions along each entity's actual decision path through
all 300 trees. They reconcile exactly:

```
base 0.5010 + contributions 0.4195 = prediction 0.9961   residual 0.00e+00
```

The residual is printed in the payload so it can be **checked** rather than
trusted. The method is named precisely — *exact decision-path contributions,
not Shapley* — because it is exact along the path but can under-credit
interaction effects, and we do not call two different methods "SHAP".

Explanations are computed only for the ranked leads that reach the screen:
300 trees × depth 12 per entity is not free at 19,000 entities.

---

## 7. Evaluation: from one split to a measurement programme

| | v1 | v2 |
|---|---|---|
| Split | single 75/25, ~11 positives | 5-fold stratified CV, mean ± std |
| Calibration | none | Brier score + expected calibration error |
| Model selection | RandomForest, assumed | logistic baseline vs forest, compared |
| "Is it just rules?" | an argument | **three measurements** |

The three experiments, on the windowed dataset:

```
rules alone, thresholds exactly as shipped   precision 0.162  recall 0.128  F1 0.143
ablation, all 9 rule features REMOVED        ROC-AUC 0.993 ± 0.005 on 19 features
decoys, 10 lawful high-volume services       0 flagged in the top 25   PASSED
```

Deleting every hand-written detector does not move AUC. **The signal is in the
measured traffic, not in our rules echoed back.**

An honest note also recorded: a logistic regression reaches AUC 0.995 against the
forest's 1.000. The margin over a linear model is small — **the feature
engineering is doing more work than the model choice.**

---

## 8. New: monitoring

This is the half of the problem statement v1 did not implement at all. The
statement says *"AI-Powered **Monitoring** & Analysis of Bitcoin Transaction
Traffic"*; v1 was a batch scorer with no memory.

v2 keeps state in SQLite and, each batch, emits **typed events with attribution**:

| Event | Meaning |
|---|---|
| `NEW_ENTITY` | never seen before |
| `ESCALATION` / `DE_ESCALATION` | priority band moved |
| `DORMANT` / `RESURGENT` | went quiet, then came back — invisible without history |
| `CLUSTER_GROWTH` | gained addresses or a new country |
| `BEHAVIOUR_SHIFT` | the inputs moved before the score did |
| `CLUSTER_MERGE` | two groups proved to be one — a finding, not bookkeeping |

Each carries the reason: *"risk 14 → 55 because burst concentration 0.2 → 0.5 and
peel-chain signature…"*. Alerts have a **lifecycle** and are one row per entity,
so a wallet critical for four batches is one alert whose history grows, not four
nobody can triage.

### The bug this step exposed

Time-to-detection first came back **5 of 46** planted cases. The cause was a
**train/serve skew**: the model was trained on four-day feature totals and served
one-day totals.

| Feature | Window | Training | Ratio |
|---|---|---|---|
| `tx_count` | 26 | 101 | 3.9× |
| `fan_in` | 12 | 45 | 3.8× |
| `fan_out` | 13 | 45 | 3.5× |

Those three are its dominant features, so it had never seen numbers that small
and scored everything ~10 — while the offline scorecard looked perfect. Fixed by
training at the served scale. Held-out, leave-one-window-out:

**detection 158/179 = 88.3%, alert precision 91.3%** (from 5/46; median
time-to-detection 3 batches → 1).

---

## 9. Findings reported against ourselves

Four results came out of this work that make us look worse, and all four are in
the product and the documents rather than in a drawer.

1. **The decoy test failed held-out** — 2 of 10 lawful high-volume services
   flagged, while the in-sample version passed. Only visible because the test was
   moved onto held-out predictions. The windowed retrain later fixed it.
2. **The anomaly detector collapsed at window scale** — precision@20 fell from
   0.300 (a 3.6× lift) to **0.050 against a 0.092 base rate**, i.e. worse than
   chance. Its lift was a batch-scale artifact and did not survive the way the
   product actually runs.
3. **A false alarm we retracted** — an "87% country mismatch" that turned out to
   be our own test joining two unrelated id namespaces.
4. **The cross-validation leaks.** Folds are random and stratified, but rows from
   the same batch — and the same wallet across batches — are correlated.
   Grouped-by-window CV is the correct method and is outstanding; reassuringly
   the pooled recall (0.899) is close to the grouped figure (0.883), so the leak
   is not inflating the headline.

---

## 10. Interface

The interface is six pages, in the order of the argument: what this is, what we
made of your file, what is in it, what looks wrong, where it is, and how it was
built. Each answers one question and links to the next.

- a **data-quality gate** before anything expensive happens: rows read, rows
  usable, rows rejected and the reason for each, then "analyse this file". The
  button after the gate runs the analysis **of the file the gate just described**
- a **replay transport** so the batches can be walked through in order, live
- a **plain-language layer**: every technical term either replaced with a plain
  phrase or carrying an explanation, surfaced by Explain mode
- **charts before prose** — the dot grid, the paired size-class bars and the
  geography bars each make their point without a sentence being read
- **PDF reports from the same payload the pages render**: a whole-capture report,
  a lead report, and a one-page case dossier, all A4 and print-safe
- a **documents page** — this file among them

### The defects this pass found in the product

Every one of these was caught by looking at the rendered page rather than at the
code, and every one is now fixed with a test or a stated rule:

| What it looked like | What it was |
|---|---|
| 60 of 85 leads had no explanation | attributions were computed for the top 25 only; the caps are gone |
| the waterfall bars did not add up to the score above them | the payload kept the 8 largest contributions and dropped the rest silently; the remainder is now a stated term and the sum is exact |
| "88 open leads" beside "85 flagged groups" | merged entities leave an alert row under a key that no longer exists; `open_alerts` now resolves aliases |
| a fifth day on the chart with an invisible bar | the capture ends mid-day, so a 19-transaction tail was being presented as a day; a trailing fragment is now folded into the day before it |
| "peaking at 22:00" on a flat profile | the busiest of 24 near-equal hours is not a peak; the share is now stated and the flatness named |
| 533 grey squares | the payload says `critical`/`medium` and the stylesheet said `crit`/`med`; a rule matched nothing and nothing complained |
| country bars rendered as slivers | the bar fill was an inline element with a percentage width; it laid out at zero |
| a fix on disk that did not appear | the browser had cached the stylesheet; static files are now served `no-cache` |

---

*Every figure in this document was produced by running the code. Where a number
is a projection or an estimate, it says so.*
