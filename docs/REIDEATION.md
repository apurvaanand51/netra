# Re-ideation — what we found, what we changed, and why

**Team Vortex · SIH 2026 · PS ID SIH26146**

This document records the review that reshaped the project. It exists because the
most valuable thing we produced during it was not code — it was **four findings
that changed the design**, three of which came from testing our own assumptions
and one of which was a mistake we made and corrected.

Read §1 if you want the honest story. Read §2 if you want the decisions. Read §3
if you want to know what we are building now.

---

## 1. What we found when we interrogated our own pipeline

### 1.1 We raised a false alarm, and retracting it mattered more than the alarm

Testing the correlation layer, we noticed entity `E-0416` reporting country `GB`
where ground truth said `HK`, and measured an **87% mismatch** across all 533
entities. That looked like a serious defect in the differentiator — the tool
would be attributing the wrong country of control to a wallet.

**It was our test that was wrong.** `common_input_clusters` assigns entity ids
`E-0001, E-0002, …` sorted *by size, biggest first* — a numbering completely
independent of the generator's ids, which merely looks identical. Joining
`correlation.entity_id` to `ground_truth.entity_id` compares two unrelated
numbering schemes.

Re-run correctly — projecting entities through their **addresses**, which is what
`ml/evaluate.py` does — the picture inverted:

| Check | Result |
|---|---|
| Address purity | **1.0000** — all 533 entities map to exactly one ground-truth entity |
| Country attribution | **91.6% exact**; the 45 that differ are precisely the 45 planted multi-country entities |

**The lesson we are carrying forward:** two ID namespaces that share a format are
a trap. `E-0416` in the correlation output and `E-0416` in the ground truth are
different wallets. We are now making this structural: entity keys become
**content-derived and self-verifying** (§2.2), so the join can never silently be
wrong again.

*And a second lesson about process: we published the alarm before verifying the
test. The cost was zero this time. At 3am it would not have been.*

### 1.2 Our own rules carry almost none of the model's decision

We read the trained importances rather than assuming them:

| Hand-written detector | Importance in the trained model |
|---|---|
| `peel_score` | 0.012 |
| `mixer_score` | 0.023 |
| `collector_score` | 0.0003 |
| `mixer_interaction` | 0.0000027 |

Meanwhile `tx_count` (0.134), `exchange_score` (0.131), `distinct_counterparties`
(0.117) and `fan_in`/`fan_out` (0.109) dominate. **The model is driven ~80% by
volume and topology**, while the detectors our demo narrative leans on contribute
almost nothing — one code comment even calls `mixer_interaction` "the feature the
demo narrative leans on."

Two things follow. First, this is *evidence the model is reasoning rather than
echoing our rules* — a rules engine reproduces its rules, ours re-ranks them. We
should lead with that when defending "this is not rule-based." Second, our
narrative and our model disagree, and a judge will find that. So we are
measuring it properly rather than hoping (§2.4).

### 1.3 The outlier problem was already inside our explainability

Our per-entity attributions are `global_importance × z_score`, where the z-score
uses the training set's **mean and standard deviation**. One corrupt value
inflates that standard deviation, and **every other entity's attribution for that
feature collapses toward zero.**

Measured, by contaminating a single row of the feature matrix and re-measuring
the mean `|z|` across all 533 entities: the mean/std attributions lose **62% of
their magnitude** (median across the 24 features, worst features −69%). The same
test against a **median/MAD** z-score moves by **+0.4%**.

This is not a hypothetical about future SQL data — it is a live defect in the
explanations we shipped, and it was found by testing rather than by reading. It
also pointed at the wider problem: our ingestion rejects malformed *rows* but
does nothing about statistically hostile *values*.

Related, and found the same way — by feeding the ingestion layer deliberately
broken input: a 3-octet IP address (`40.52.114`) was **silently accepted**.
`src_ip`/`dst_ip` sit in `STR_FIELDS`, so they are whitespace-stripped and never
validated for shape. The learning guide already lists "IPs had three octets" as
bug #2 — the fix went into the *generator*, so synthetic data is clean, but never
into the *validator*, so a real feed would not be. In an investigative tool, that
is false evidence entering the pipeline.

### 1.4 Our reproducibility instruction did not reproduce anything

The generated `data/README.md` says:

> Regenerate with: `python -m generator.generate`

The defaults produce **25,065 transactions / 353 entities**. The dataset every
metric in our README was measured on is **27,860 / 532 / 43 illicit**, which
requires `--tx 20000 --clusters 400`. The headline credibility claim is "measured
against planted ground truth, reproducible from a seed" — and the instruction for
reproducing it was wrong.

### 1.5 We could not answer "how does it scale?", and the answer was bad

`correlation/engine.py` iterates `for _, row in work.iterrows()` over every
transaction, and so do `detect_coinjoin_like` and two detectors in `patterns.py`.
That is why 27,860 transactions take ~40 seconds. Extrapolating linearly:

| Volume | Projected runtime |
|---|---|
| 28k (demo) | ~40 s |
| 1M | **~25 minutes** |
| 10M | **~4 hours** |

For a tool whose problem statement says "bulk" and "monitoring", that is the
single most damaging question we could not answer.

### 1.6 The perception problem, which is the real reason for this document

None of the above is what makes the project read as simple. What makes it read as
simple is that **the demo is a straight line**: file in → score → table on screen.
A mentor watching that sees something they could build in a weekend — and
effectively, we did.

The problem statement says *"AI-Powered **Monitoring** & Analysis of Bitcoin
Transaction Traffic."* We built the **Analysis** half. There is no Monitoring
half: we run once, on a batch, and print a ranking. Nothing is watching. Nothing
changes over time. Nothing tells an analyst what to *do* next.

---

## 2. The decisions

### 2.1 Reframe: the models are components, not the product

| Before | Now |
|---|---|
| "We train two models and show a risk table." | "We turn a dirty bulk traffic dump into **four investigative products**: ranked leads, network-level operation mapping, traced fund paths to cash-out, and a monitoring feed of what changed." |

Same code, different surface. Two models is not the weakness; two models and one
output was.

### 2.2 Entity identity becomes content-derived and stable

Required, because monitoring is impossible without it: ids are assigned by size
ranking per run, so "entity `E-0007` escalated from 40 to 92" could refer to two
unrelated wallets.

```
anchor      = lexicographically smallest address ever observed in the cluster
entity_key  = "E-" + 9 decimal digits of SHA-256(anchor)
```

Constraints and consequences:
- The frozen contract requires `^[EN]-[0-9]{4,}$`, so the key must stay numeric.
  It does — **no contract change needed**.
- Same cluster across runs → same key, so history attaches correctly.
- A cluster *growing* does not re-key, so growth becomes a **detectable event**
  instead of a new entity. (In stateful mode the anchor is pinned on first
  observation, so absorbing a smaller address cannot re-key either.)
- Collisions are handled deterministically by escalating digits.

### 2.3 Two new architectural pillars

**Scale.** Vectorise the pipeline. The insight that makes this cheap: the
*co-spend edges* are few (bounded by the address count), while the expensive part
was iterating 27,860 rows in Python. Explode-based edge extraction plus a
union-find structure gives connected components in near-linear time; `networkx`
stays for the graph-intelligence features where it earns its place.

**State.** Monitoring needs memory across runs. SQLite via the stdlib `sqlite3`
module — no new dependency, single file, offline-friendly. This is what turns a
batch scorer into a monitoring system.

### 2.4 Model rigour, with XGBoost for the right reasons

Held-out ROC-AUC is already **1.000** — there is no accuracy headroom, and adding
XGBoost to chase a higher number would be an admission we do not understand our
own result. We add it for three defensible reasons:

1. **Exact TreeSHAP** (`pred_contribs`) — replaces our weakest caveat. Today our
   explainability says *"this is not SHAP, it is a first-order approximation."*
   With XGBoost we claim exact Shapley values with no extra dependency.
2. **Calibration** — "risk 92" should mean ~92% likely illicit. RandomForest
   probabilities from 300 trees are badly calibrated. We add a reliability curve,
   Brier score, and isotonic/Platt calibration.
3. **Model selection as documented engineering** — logistic baseline vs
   RandomForest vs XGBoost, compared on held-out AUC *and* explainability cost,
   with the selection justified.

Plus: **5-fold stratified cross-validation** replaces a single 134-entity split
that contains only **11 positive cases**. "How do you know that wasn't a lucky
split?" currently has no good answer.

### 2.5 We will settle the rules question with a measurement

Three experiments, because an argument is worth less than a number:

| Experiment | What it proves |
|---|---|
| **Ablation** — retrain with all 9 rule-based features removed | if AUC holds, the signal is learned from raw structure |
| **Rules-only baseline** — threshold on `peel_score`/`mixer_score` alone | the rules' standalone precision/recall, next to the model's |
| **Decoy test** | the decoy legitimate services are designed to break rules; a rules engine collapses on them, precision 1.000 does not |

### 2.6 Robust statistics replace fragile scaling

Median/MAD robust z-scores and percentile winsorisation replace mean/std
throughout features and attributions. This fixes §1.3 rather than working around
it, and it is the honest answer to "what happens when a real SQL dump contains
values your generator never produced?"

### 2.7 A data-quality gate, made visible

Real SQL exports are hostile in ways synthetic data is not: NULLs and sentinels
(`-1`, `999999`, `'N/A'`), duplicate txids, timezone-less timestamps, numeric
strings, extreme values, distribution shift. Each gets an explicit handling path
and a reason code — and the *gate itself becomes a deliverable*, shown in the UI.
Plus **PSI/KS drift checks per feature**, so the system can say *"this batch does
not look like what I was trained on — trust me less."*

### 2.8 Graph intelligence and taint tracing

We already build `corr.flows` and were using it only for `fan_in`/`fan_out`. From
the same data: Louvain communities ("this is not 40 wallets, it is 4 laundering
communities"), role assignment within each community (collector / layering /
cash-out), PageRank and betweenness as features, and **taint propagation** —
*"of the 62 BTC entering this collector, 41 BTC reached a KYC exchange via 3
hops."* That last one gives an output *type* we did not have: fund paths, not just
scores.

### 2.9 Monitoring, which is the missing half of the problem statement

The full design is in `MONITORING_DESIGN.md`. In one paragraph: stable keys plus a
SQLite state store, windowed inference over trailing windows, and **deltas against
the previous window** turned into events — `NEW_ENTITY`, `ESCALATION`,
`RESURGENT`, `CLUSTER_GROWTH`, `CLUSTER_MERGE`, `BEHAVIOUR_SHIFT` — each carrying
**delta attribution** ("risk 71 → 92 because `country_count` 1 → 3 and a mixer
interaction appeared"). An alert lifecycle the analyst works. And because the
ground truth is planted, the monitoring itself is **measurable**: *time-to-
detection, alert precision per window*. A replay mode makes all of it
demonstrable in 60 seconds.

---

## 3. What this reshaped

| | Before | After |
|---|---|---|
| Outputs | a risk table | leads · operation mapping · fund paths · monitoring feed · daily brief |
| Time | one batch | windowed, with history and deltas |
| Scale | ~40 s at 28k, projected hours at 1M | vectorised, benchmarked across volumes |
| Identity | per-run size ranking | content-derived, stable, contract-compliant |
| Explaining | importance × z-score, self-declared not SHAP | exact TreeSHAP, calibrated, with counterfactuals |
| Evaluation | one 75/25 split, 11 positives | 5-fold CV ± std, ablations, rules-only baseline, decoy test |
| Robustness | clean synthetic input only | quality gate + drift detection + robust statistics |
| Honesty | caveats in a doc | caveats as measured numbers |

### The step plan

Development restarts here, in this order, each ending at a push checkpoint:

1. **Stable entity identity + vectorised clustering** — the prerequisite
2. **Vectorised correlation engine** + scaling benchmark
3. **Vectorised detectors + robust statistics**
4. **Ingestion hardening**: SQL source, quality gate, drift checks
5. **Graph intelligence**: communities, roles, centrality, taint tracing
6. **ML core**: XGBoost + TreeSHAP + calibration + CV + baselines
7. **Monitoring**: state store, windows, events, replay, time-to-detection
8. **Contract extension + backend** (contract change = Captain announcement)
9. **UI** — *paused pending a Manus design pass*
10. **Colab retrain, docs, CI, packaging, release**

Steps 1–3 change features, so the retrain happens **once**, after them. Steps 4–8
follow the same rule. No retraining in the middle.

---

## 4. What we are deliberately not doing

- **Not chasing accuracy.** There is no headroom, and pretending otherwise would
  be the least credible thing we could do.
- **Not adding complexity we cannot defend in one sentence.** Every addition above
  has a stated reason; anything that only looks impressive is a liability in a
  Q&A.
- **Not deleting the honest caveats.** The planted-ground-truth design *is* our
  credibility. "AUC 1.000 because the planted patterns are genuinely learnable,
  measured on held-out data, and here is the harder unsupervised number" is
  stronger than pretending 1.000 is heroic.
- **Not adding a frontend library.** CI asserts zero CDN references; an air-gapped
  browser fails a CDN load silently and renders a blank dashboard.

---

*Found by running the code and disbelieving the output — including our own.*
