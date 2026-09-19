# Retraining on Colab

**Team Vortex · SIH 2026 · PS SIH26146**

The notebook is [`notebooks/NETRA_Colab_Retrain.ipynb`](../notebooks/NETRA_Colab_Retrain.ipynb).
This document explains why it exists, what it changes, and how to get the
artifacts back.

---

## Why retrain in the cloud at all

Not for speed. The dataset is 27,860 transactions and training takes about
twenty seconds — a GPU buys nothing here, and both models are tree ensembles that
do not use one.

**The reason is `xgboost`, which Colab ships preinstalled.** NETRA's explainability
layer checks for it, and when it is present the per-lead contributions switch
method:

| | Library present | What the bars are |
|---|---|---|
| Local / demo machine | neither `xgboost` nor `shap` | **decision-path (Saabas) contributions** — exact along the path, summing exactly to the prediction, but **not** Shapley values and able to under-credit interactions |
| Colab | `xgboost` preinstalled | **exact TreeSHAP** — game-theoretically justified, correct under interactions, summing exactly to the prediction |

So the retrain is not just moving the work. It **upgrades what the explanations
are**, and the model card records which method produced the artifacts.

We tried to install `xgboost` locally and **the wheel download was still zero
bytes after ten minutes** — consistent with the ~25 KB/s this machine measured
during the build. Rather than fight it, the notebook does it where the library
already exists, and the code names the method honestly either way.

---

## The one trap, and it is the reason this document exists

**A `.joblib` pickled under numpy 2.x cannot be loaded by numpy 1.x.** It fails
with:

```
ModuleNotFoundError: No module named 'numpy._core'
```

Colab's runtime ships **numpy 2.x**. The demo target is numpy 1.x. So the default
Colab environment would produce a model that trains perfectly and **refuses to
load on the machine the judges are watching**.

Two rules, both enforced by an assertion in the notebook:

1. **`scikit-learn` must match exactly (1.6.1).** That is the version whose pickle
   format the demo machine reads.
2. **`numpy` must stay on the 1.x line.** `requirements.txt` pins 1.23.5, which has
   no wheels for Colab's Python, so the notebook takes the newest 1.x line
   (`1.26.4`) instead. Pickles written under any numpy 1.x are readable by every
   other numpy 1.x.

> The general principle, and worth saying to a judge: **a model is not portable
> just because the file copies. The library versions that wrote it are part of the
> artifact.** That is why `models/ENVIRONMENT.txt` is written next to the weights,
> and why the drift reference travels with them too.

---

## The procedure

1. Open the notebook in Colab and run the cells in order.
   - **Runtime → Change runtime type → CPU** is fine. No GPU is used.
2. Edit `REPO_URL` in the clone cell. For a private repository, supply a
   fine-grained token with `Contents: Read and write` — the prompt is hidden.
3. The install cell pins the stack; the next cell **asserts** it. If it reports a
   problem, restart the runtime and run the install cell again before continuing.
4. `python tasks.py train` writes everything to `models/`, including
   `reference_distribution.json` (the training distribution the drift check
   compares batches against) and `ENVIRONMENT.txt`.
5. `python tasks.py smoke` runs the whole verification — generate, pipeline,
   contract-validated payload, and every HTTP endpoint. **If this fails, do not
   ship the artifacts.**
6. Download the zip, or push straight back to the repository from the last cell.

---

## Getting the artifacts back

### Copy them in (recommended)

Unzip and copy `models/*` over the local `models/`, then confirm the demo machine
agrees with Colab before committing anything:

```bash
python tasks.py smoke        # the same verification the notebook ran
python tests/api_smoke.py    # the API serves the new analysis
```

If `smoke` passes locally, the artifacts are portable. If it fails with
`numpy._core`, the pins drifted — retrain, do not debug the pickle.

Then:

```bash
git add models/
git status --short     # the .joblib files SHOULD appear; see .gitignore
git commit -m "Retrain on Colab: refresh model artifacts and metrics"
git push
```

### Or push from the notebook

The final cell commits `models/` back with no download. Set `PUSH = True` and
supply a token with write access.

---

## Why the artifacts are committed

`.gitignore` ignores `models/*` but explicitly lets through:

```
!models/risk.joblib
!models/anomaly.joblib
!models/feature_columns.json
!models/metrics.json
!models/ENVIRONMENT.txt
!models/reference_distribution.json
```

That is deliberate. **A model is only reproducible if you ship the exact bytes you
measured.** If the artifacts stayed out of the repository, the README would quote
numbers that the shipped `.joblib` no longer produces — and for an investigative
tool, *a number is evidence*, so the artifact and the claim have to travel
together.

`reference_distribution.json` earns its exception for a different reason: without
it the drift check cannot run at all, and the console can only say "not measured".

The dataset stays ignored. It is regenerated from a seed by the committed
generator, so shipping it would be shipping an output, not a source.

---

## What to check afterwards

- [ ] `models/ENVIRONMENT.txt` records the numpy and scikit-learn versions.
- [ ] `metrics.json` reports `explanation_method` as **exact TreeSHAP** if xgboost
      was available.
- [ ] `metrics.json` reports `cv_method` as **StratifiedGroupKFold** — grouped by
      batch, so a wallet cannot appear on both sides of a split.
- [ ] The Method page renders the new scorecard and the reliability curve.
- [ ] The README's numbers still match `metrics.json`. **If they disagree, update
      the README — never leave the two describing different runs.**
