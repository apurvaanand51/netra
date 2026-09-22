# Where we stand

**Team Vortex · SIH 2026 · PS SIH26146 · NTRO**

Written after the first round. What is finished and verified, what is not, and
what to do next — in the order the risk sits, not the order that flatters us.

---

## 1. What is done, and how we know

Every claim below was measured, not asserted. The harness ships with the project:
`python tools/measure.py`.

| Area | State | Evidence |
|---|---|---|
| Pipeline | working | 27,860 transactions → 533 wallet groups, 4 batches, 77 leads |
| Models | trained and measured | CV AUC **0.991 ± 0.009**, precision 0.931, recall 0.902, calibration Brier 0.020 |
| Contract | frozen and enforced | 14 properties, 14 definitions, validated on the payload **as served** |
| Interface | six pages + three A4 reports | verified in a browser, 0 external requests |
| Tests | green | **26** pytest, **103** API assertions, `SMOKE PASSED` |
| Offline guarantee | enforced by CI | no page or stylesheet references an external resource |
| Docs | complete | learning guide, v1→v2 comparison, changelog, model card, review, retrain guide |

**Known defects we found and fixed are listed in two places:** `docs/CHANGELOG.md`
§"The defects this pass found" and `docs/LEARNING_GUIDE.md` §16. That list is
deliberately in the product — a project that only reports successes is not
evidence.

---

## 2. Open items, in order of risk

### 2.1 The pipeline is super-linear in dataset size — **the biggest technical risk**

Measured at two points, same code:

| Rows | Time | Cost per 100k rows |
|---|---|---|
| 69,690 | 65.9 s | 94.6 s |
| 278,832 | 913.1 s | 327.5 s |

Rows ×4.00, cost per 100k ×3.46 → roughly **O(n^1.8)**. The stage is not yet
isolated (betweenness/page-rank in the graph analysis is the prime suspect, since
`ml/graph.py` already samples betweenness and falls back at 20k nodes to protect
against exactly this).

**Why it matters:** a real dump is millions of rows, not 27,860.
**Next step:** per-stage timings in `tools/measure.py` (an hour), then fix the
stage that dominates.

### 2.2 Three features are not scale-invariant — **the model-behaviour risk**

Measured, two graphs (431 groups vs 3,307 groups):

| Feature | 431 groups | 3,307 groups | Shift |
|---|---|---|---|
| `pagerank` (median) | 0.002319 | 0.000257 | **9.0× smaller** |
| `betweenness` (median) | 0.001173 | 0.000095 | **12.3× smaller** |
| `community_size` (median) | 38 | 115 | **3.0× larger** |

PageRank sums to 1 across the graph, so a bigger graph means smaller per-node
values. The model learned its thresholds on a 533-entity graph; at a larger scale
those three features slide into the same branch and quietly stop discriminating.
The score distribution shifts with them, so a fixed alert floor of 50 yields a
different number of leads at a different scale.

**What the system does today:** detects it. The drift check compares every feature
against the reference shipped inside the artifact (PSI **and** KS must agree) and
the interface states plainly when the scores are outside what the model was
trained on. That is disclosure, not correction.
**Next step:** normalise the three (pagerank × N, betweenness as a percentile,
community_size as a share), then refit the reference at the target scale.

### 2.3 Small, concrete, before the next demo

| Item | Why | Effort |
|---|---|---|
| **Team names on the cover** — five `[ name ]` placeholders | it is the first thing on screen | five minutes |
| **Commit and push** | this session's work is uncommitted | `git add -A && git commit` |
| Set the real GitHub URL in `README.md` if it changed | the clone line is a placeholder | one line |
| Decide the fate of the `netra/` folder (the v1 build) | it is a separate git repo sitting inside the workspace, and `docs/V1_V2_REPORT.md` reads its artifacts | your call |

---

## 3. Next round: what to build

Ordered by how much a judge learns per hour spent.

1. **Isolate and fix the scale cost** (§2.1). "Linear to a million rows" is
   currently false, and the honest version — with the measurement and the fix — is
   a stronger story than the claim ever was.
2. **Scale-free the relational features** (§2.2), then retrain and refit the
   reference. `docs/COLAB_RETRAIN.md` has the procedure; the notebook is in
   `notebooks/`.
3. **Real-data dry run.** The model is trained on planted typologies. Feeding it
   one public dataset (or a realistic synthetic capture with a different shape)
   and reporting what breaks is the single most credible thing we could add.
4. **Analyst workflow depth** — case notes, an export of the acknowledged set,
   and a diff between two batches for one lead. The monitoring store already
   holds everything this needs.
5. **Performance of the first paint.** The whole-capture payload takes 33 s cold
   (0.09 s warm). It is warmed by the analysis job, so the demo never sees it, but
   a cold start on a big dump is still 33 s.

---

## 4. Repo hygiene — the state we leave it in

Cleaned after the first round: `__pycache__`, `.pytest_cache`, `*.pyc`, test junk
in `uploads/`, the payload cache, the state store, the per-batch CSVs and the
smoke dataset. **62 MB → 38 MB.**

Nothing regenerable is tracked, and nothing needed is missing:

| Kept (tracked) | Regenerated (ignored) |
|---|---|
| all source, docs, frontend, vendored libraries | `out/` — state store, payload cache |
| `data/transactions.csv` + ground truth | `data/windows/`, `data/smoke/` |
| `models/*.joblib`, `metrics.json`, `reference_distribution.json` | `uploads/` |
| `schemas/`, `tests/`, `tools/`, `wheels/` placeholder | `__pycache__/`, `.pytest_cache/` |

A fresh clone reaches a running system with three commands:

```bash
python tasks.py replay     # rebuild the history in out/monitoring.sqlite
python tasks.py serve 8000 # or ./run.sh, or run.bat on Windows
python tools/measure.py    # re-measure every number in the docs
```

`tasks.py gen` and `tasks.py train` are only needed if you want new data or new
models. Both work offline.

---

*Everything in this document was produced by running the code; `tools/measure.py`
reproduces it.*
