"""
Evaluation harness -- turning "trust us, it's AI" into measured numbers.

WHY THIS FILE IS THE CREDIBILITY UNLOCK
---------------------------------------
Any team can show a dashboard with red words on it. Almost none can answer
"how accurate is it?" with a number. Because we generated the data, we hold the
answer key -- so we can report real precision, recall, F1, AUC, ARI and
calibration.

FOUR DIFFERENT SCORES, MEASURING FOUR DIFFERENT THINGS
------------------------------------------------------
1. CLUSTERING  -> Adjusted Rand Index (ARI)
   Did our common-input clustering rediscover the true wallet groupings?
   ARI compares two partitions of the same addresses and corrects for the
   agreement you would get by chance:
        1.0 = perfect, 0.0 = random, <0 = worse than random.
   Chance-correction is why we use ARI and not plain accuracy: with 300+ small
   clusters, a naive accuracy score would look great while being meaningless.

2. ANOMALY     -> precision@k
   Of the k entities the unsupervised detector found most unusual, how many are
   truly illicit? There is no "recall" to report here, because the detector has
   no concept of a positive class -- it never saw a label. Precision@k is the
   honest metric for a ranking used as an investigative shortlist.

3. RISK        -> precision / recall / F1 / ROC-AUC / calibration
   A standard supervised evaluation, reported on entities the model did NOT
   train on, which is the only version of these numbers worth quoting.

4. THE RULE QUESTION -> three experiments
   "Is this just if-else rules?" is the first question a judge asks, and an
   argument is worth less than a number. So we measure it three ways:
     * RULES-ONLY BASELINE -- score using nothing but the hand-written detector
       thresholds, and report what they achieve on their own.
     * ABLATION -- retrain with every rule-derived feature REMOVED. If the
       performance holds, the signal came from the data, not from our rules.
     * DECOY TEST -- the dataset contains legitimate high-volume services
       deliberately built to look statistically suspicious. A rules engine
       collapses on them; a model that has learned to discriminate does not.

CROSS-VALIDATION, NOT A SINGLE SPLIT
------------------------------------
A single 75/25 split of 533 entities puts about eleven positives in the test
set. One unlucky split and every number moves several points. So the headline
metrics are 5-fold stratified cross-validation with a reported standard
deviation, and a single held-out split is kept only as a second view.

CALIBRATION, BECAUSE "RISK 92" SHOULD MEAN SOMETHING
----------------------------------------------------
A forest's probabilities are votes, not frequencies -- they cluster near 0 and 1
and are systematically overconfident. If the dashboard prints 92, an analyst
will read "92% likely illicit", so we measure whether that is true: the Brier
score and a reliability curve, plus isotonic calibration when it helps.
"""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    adjusted_rand_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import StratifiedKFold

# Hand-written detector thresholds, exactly as the pipeline uses them to label
# an entity's typology. The rules-only baseline must use the SAME thresholds, or
# it is not a fair test of the rules we actually shipped.
RULE_PEEL_THRESHOLD = 0.25
RULE_MIXER_THRESHOLD = 0.5
RULE_COLLECTOR_THRESHOLD = 0.3

# The features that are outputs of hand-written detectors rather than measured
# quantities. Removing these is what the ablation experiment measures.
RULE_DERIVED_FEATURES = [
    "change_ratio",
    "peel_score",
    "output_uniformity",
    "mixer_score",
    "mixer_interaction",
    "collector_score",
    "exchange_score",
    "round_amount_ratio",
    "mean_payment_btc",
]


# --------------------------------------------------------------------------
# Ground truth projection (unchanged: this join must never be by entity id)
# --------------------------------------------------------------------------
def load_ground_truth(data_dir: Path | str) -> tuple[dict[str, int], dict[str, str], dict[str, str]]:
    """Read the hidden answer key.

    Returns
    -------
    entity_label : dict entity_id -> 0/1
    address_owner : dict address -> true entity_id
    entity_typology : dict entity_id -> typology string
    """
    data_dir = Path(data_dir)
    entity_label: dict[str, int] = {}
    entity_typology: dict[str, str] = {}
    address_owner: dict[str, str] = {}

    entities_path = data_dir / "ground_truth_entities.csv"
    if entities_path.exists():
        with entities_path.open("r", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                entity_label[row["entity_id"]] = int(row["label"])
                entity_typology[row["entity_id"]] = row.get("typology", "")

    addresses_path = data_dir / "ground_truth_addresses.csv"
    if addresses_path.exists():
        with addresses_path.open("r", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                address_owner[row["address"]] = row["entity_id"]

    return entity_label, address_owner, entity_typology


def _project(address_to_entity: dict[str, str], address_owner: dict[str, str], lookup):
    """Majority-vote projection of a per-address ground-truth value onto our
    predicted entities.

    The join is ALWAYS through addresses. Correlation entity ids and generator
    entity ids are different namespaces that happen to share a format, and
    joining them produces confident nonsense.
    """
    votes: dict[str, list] = {}
    for address, predicted_entity in address_to_entity.items():
        true_entity = address_owner.get(address)
        if true_entity is None:
            continue
        value = lookup.get(true_entity)
        if value is None:
            continue
        votes.setdefault(predicted_entity, []).append(value)

    projected: dict[str, object] = {}
    for predicted_entity, values in votes.items():
        # For labels: >= 0.5 so a tie falls to "illicit" -- prefer the cautious
        # call. Majority rather than "any illicit" is the fairer rule: otherwise
        # one tainted address condemns a cluster of thousands.
        if isinstance(values[0], int):
            projected[predicted_entity] = int(np.mean(values) >= 0.5)
        else:
            # sorted() first so the tie-break is deterministic -- a set's
            # iteration order varies between runs, which would make the reported
            # typology differ run to run on the same data.
            projected[predicted_entity] = max(sorted(set(values)), key=values.count)
    return projected


def true_label_per_entity(address_to_entity, address_owner, entity_label) -> dict[str, int]:
    return _project(address_to_entity, address_owner, entity_label)  # type: ignore[return-value]


def typology_per_entity(address_to_entity, address_owner, entity_typology) -> dict[str, str]:
    return _project(address_to_entity, address_owner, entity_typology)  # type: ignore[return-value]


# --------------------------------------------------------------------------
# Point metrics
# --------------------------------------------------------------------------
def score_clustering(address_to_entity: dict[str, str], address_owner: dict[str, str]) -> float | None:
    """Adjusted Rand Index between our clusters and the true entity ids."""
    shared = [a for a in address_to_entity if a in address_owner]
    if len(shared) < 2:
        return None
    predicted = [address_to_entity[a] for a in shared]
    truth = [address_owner[a] for a in shared]
    if len(set(truth)) < 2 or len(set(predicted)) < 2:
        return None
    return float(adjusted_rand_score(truth, predicted))


def score_risk(y_true: np.ndarray, y_prob: np.ndarray, threshold: float = 0.5) -> dict:
    """Precision / recall / F1 / AUC for the supervised risk model."""
    if len(y_true) == 0 or len(np.unique(y_true)) < 2:
        return {
            "risk_precision": None, "risk_recall": None, "risk_f1": None,
            "risk_auc": None, "true_positives": None, "false_positives": None,
            "false_negatives": None, "true_negatives": None,
        }

    y_pred = (y_prob >= threshold).astype(int)
    tn, fp, fn, tp = confusion_matrix(y_true, y_pred, labels=[0, 1]).ravel()

    return {
        # zero_division=0 so a degenerate split reports 0.0 rather than raising
        # -- an evaluation harness must never crash the pipeline.
        "risk_precision": float(precision_score(y_true, y_pred, zero_division=0)),
        "risk_recall": float(recall_score(y_true, y_pred, zero_division=0)),
        "risk_f1": float(f1_score(y_true, y_pred, zero_division=0)),
        "risk_auc": float(roc_auc_score(y_true, y_prob)),
        "true_positives": int(tp),
        "false_positives": int(fp),
        "false_negatives": int(fn),
        "true_negatives": int(tn),
    }


def score_anomaly(anomaly_scores: np.ndarray, y_true: np.ndarray, k: int = 20) -> dict:
    """Precision@k for the unsupervised detector."""
    if len(anomaly_scores) == 0 or len(y_true) == 0:
        return {"anomaly_precision_at_k": None, "anomaly_k": k}

    k = min(k, len(anomaly_scores))
    top_k = np.argsort(-anomaly_scores)[:k]
    hits = int(np.sum(y_true[top_k] == 1))

    return {
        "anomaly_precision_at_k": float(hits / k),
        "anomaly_k": int(k),
        "anomaly_hits": hits,
        "anomaly_flagged": int(np.sum(y_true == 1)),
    }


def precision_at_k(y_prob: np.ndarray, y_true: np.ndarray, k: int) -> float | None:
    """Precision among the top k by score -- the right metric for a shortlist."""
    if len(y_prob) == 0 or k <= 0:
        return None
    k = min(k, len(y_prob))
    top_k = np.argsort(-y_prob)[:k]
    return float(np.sum(y_true[top_k] == 1) / k)


# --------------------------------------------------------------------------
# Calibration
# --------------------------------------------------------------------------
def calibration_report(y_true: np.ndarray, y_prob: np.ndarray, bins: int = 10) -> dict:
    """Does "risk 92" mean 92% likely illicit?

    Brier score is the mean squared error of the probability: 0 is perfect, 0.25
    is what you get by always predicting 0.5. Expected Calibration Error is the
    average gap between predicted probability and observed frequency across
    bins -- the number the reliability curve draws.
    """
    if len(y_true) == 0 or len(np.unique(y_true)) < 2:
        return {"brier": None, "expected_calibration_error": None, "reliability": []}

    y_true = np.asarray(y_true, dtype=float)
    y_prob = np.asarray(y_prob, dtype=float)

    edges = np.linspace(0.0, 1.0, bins + 1)
    reliability: list[dict] = []
    weighted_gap = 0.0

    for lower, upper in zip(edges[:-1], edges[1:]):
        # Last bin is inclusive at the top so probability 1.0 is counted.
        mask = (y_prob >= lower) & (y_prob < upper if upper < 1.0 else y_prob <= upper)
        count = int(mask.sum())
        if count == 0:
            continue
        predicted = float(y_prob[mask].mean())
        observed = float(y_true[mask].mean())
        reliability.append({
            "bin_lower": round(float(lower), 3),
            "bin_upper": round(float(upper), 3),
            "count": count,
            "predicted": round(predicted, 4),
            "observed": round(observed, 4),
            "gap": round(observed - predicted, 4),
        })
        weighted_gap += count * abs(observed - predicted)

    return {
        "brier": float(brier_score_loss(y_true, y_prob)),
        "expected_calibration_error": float(weighted_gap / len(y_true)),
        "reliability": reliability,
    }


def fit_calibrator(y_true: np.ndarray, y_prob: np.ndarray) -> IsotonicRegression | None:
    """Isotonic calibration, fitted on held-out predictions only.

    Fitting a calibrator on the same data the model trained on would make the
    calibration look better than it is -- the same leakage the model metrics are
    protected against.
    """
    if len(y_true) == 0 or len(np.unique(y_true)) < 2:
        return None
    calibrator = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
    calibrator.fit(np.asarray(y_prob, dtype=float), np.asarray(y_true, dtype=float))
    return calibrator


# --------------------------------------------------------------------------
# Cross-validation
# --------------------------------------------------------------------------
def cross_validate(
    X: np.ndarray,
    y: np.ndarray,
    feature_names: list[str],
    folds: int = 5,
    seed: int = 42,
) -> dict:
    """5-fold stratified CV for the risk model.

    Refits from scratch on every fold -- a fresh model per fold, not a
    warm-started one -- and reports mean and standard deviation. The standard
    deviation is the point: with eleven positives in a single test split, telling
    a judge "AUC 0.94" without saying how much it moves between splits is
    overclaiming.
    """
    from ml.risk import RiskModel

    y = np.asarray(y)
    counts = np.bincount(y) if len(y) else np.array([])
    usable_folds = int(min(folds, counts.min())) if len(counts) > 1 else 0
    if usable_folds < 2:
        return {"folds": 0, "note": "not enough of both classes to cross-validate"}

    splitter = StratifiedKFold(n_splits=usable_folds, shuffle=True, random_state=seed)
    per_fold: list[dict] = []

    for train_index, test_index in splitter.split(X, y):
        model = RiskModel(random_state=seed)
        model.fit(X[train_index], y[train_index], feature_names)
        probabilities = model.predict_proba(X[test_index])
        scores = score_risk(y[test_index], probabilities)
        scores["auc"] = scores.pop("risk_auc")
        scores["precision"] = scores.pop("risk_precision")
        scores["recall"] = scores.pop("risk_recall")
        scores["f1"] = scores.pop("risk_f1")
        scores["precision_at_k"] = precision_at_k(
            probabilities, y[test_index], k=min(10, len(test_index))
        )
        per_fold.append(scores)

    def aggregate(key: str) -> tuple[float | None, float | None]:
        values = [fold[key] for fold in per_fold if fold.get(key) is not None]
        if not values:
            return None, None
        return float(np.mean(values)), float(np.std(values))

    summary: dict = {"folds": usable_folds, "per_fold": per_fold}
    for key in ("auc", "precision", "recall", "f1", "precision_at_k"):
        mean, deviation = aggregate(key)
        summary[f"cv_{key}_mean"] = mean
        summary[f"cv_{key}_std"] = deviation
    return summary


# --------------------------------------------------------------------------
# The rule question, measured three ways
# --------------------------------------------------------------------------
def rules_only_baseline(table: pd.DataFrame, y_true: np.ndarray) -> dict:
    """What do the hand-written rules achieve with no model at all?

    Flags an entity if any detector crosses its shipping threshold. This is the
    system a rules-only team would have shipped, so it is the honest comparison.
    """
    if table.empty:
        return {"rules_precision": None, "rules_recall": None, "rules_f1": None}

    def column(name: str) -> np.ndarray:
        return (table[name].to_numpy(dtype=float)
                if name in table.columns else np.zeros(len(table)))

    flagged = (
        (column("peel_score") >= RULE_PEEL_THRESHOLD)
        | (column("mixer_score") >= RULE_MIXER_THRESHOLD)
        | (column("collector_score") >= RULE_COLLECTOR_THRESHOLD)
        | (column("mixer_interaction") >= 0.5)
    ).astype(int)

    return {
        "rules_flags": int(flagged.sum()),
        "rules_precision": float(precision_score(y_true, flagged, zero_division=0)),
        "rules_recall": float(recall_score(y_true, flagged, zero_division=0)),
        "rules_f1": float(f1_score(y_true, flagged, zero_division=0)),
    }


def ablation(
    X: np.ndarray,
    y: np.ndarray,
    feature_names: list[str],
    drop: list[str] | None = None,
    folds: int = 5,
    seed: int = 42,
) -> dict:
    """Cross-validate again with every rule-derived feature removed.

    If the model still separates the classes without them, the signal came from
    the measured traffic -- not from our own detectors echoed back at us. That is
    a measurement, not an argument.
    """
    drop = drop if drop is not None else RULE_DERIVED_FEATURES
    keep = [index for index, name in enumerate(feature_names) if name not in set(drop)]
    if not keep:
        return {"ablation_auc_mean": None, "note": "every feature was rule-derived"}

    reduced = X[:, keep]
    names = [feature_names[index] for index in keep]
    result = cross_validate(reduced, y, names, folds=folds, seed=seed)
    return {
        "ablation_dropped_features": sorted(set(feature_names) - set(names)),
        "ablation_features_remaining": len(names),
        "ablation_auc_mean": result.get("cv_auc_mean"),
        "ablation_auc_std": result.get("cv_auc_std"),
        "ablation_f1_mean": result.get("cv_f1_mean"),
    }


def decoy_test(
    entity_ids: list[str],
    y_prob: np.ndarray,
    y_true: np.ndarray,
    typology: dict[str, str],
    top_k: int = 25,
    prefix: str = "decoy_test",
) -> dict:
    """Do the legitimate decoys get flagged?

    The dataset contains high-volume payment processors with regional
    infrastructure -- they look statistically suspicious and are lawful. They are
    the falsification test for a rules engine: "flag high volume" and "flag
    multi-country" cannot avoid them, because those rules were written before the
    decoys existed.

    Call this TWICE with different prefixes and be explicit about which is which:
    once on HELD-OUT predictions (the honest evaluation) and once on the full
    ranking the tool actually ships. Reporting only the second would be
    in-sample, and would not survive the first question a judge asks about it.
    """
    if len(y_prob) == 0:
        return {f"{prefix}_k": 0, f"{prefix}_note": "no predictions"}

    k = min(top_k, len(y_prob))
    order = np.argsort(-y_prob)[:k]
    top_ids = [entity_ids[int(index)] for index in order]

    decoys = {name for name, kind in typology.items() if kind == "legitimate_service"}
    decoys_in_top = [entity for entity in top_ids if entity in decoys]

    return {
        f"{prefix}_k": k,
        f"{prefix}_precision": float(np.sum(y_true[order] == 1) / k),
        f"{prefix}_decoys_in_top_k": len(decoys_in_top),
        f"{prefix}_passed": len(decoys_in_top) == 0,
    }


def decoy_totals(typology: dict[str, str]) -> dict:
    """How many lawful decoys exist, for the report to compare against."""
    decoys = [name for name, kind in typology.items() if kind == "legitimate_service"]
    return {"decoy_total_in_dataset": len(decoys)}


def summary_table(metrics: dict) -> str:
    """A console-readable scorecard. This is what you put on the slide."""
    def fmt(value, digits: int = 3) -> str:
        if value is None:
            return "    n/a"
        if isinstance(value, float):
            return f"{value:.{digits}f}"
        return str(value)

    def cv(key: str) -> str:
        mean = metrics.get(f"cv_{key}_mean")
        deviation = metrics.get(f"cv_{key}_std")
        if mean is None:
            return "    n/a"
        return f"{mean:.3f} +/- {deviation:.3f}" if deviation is not None else f"{mean:.3f}"

    lines = [
        "",
        "  ==================== NETRA model scorecard ====================",
        f"  Evaluation     : {metrics.get('evaluated_on', 'unknown')}",
        f"  Entities       : {metrics.get('n_entities', '?')} "
        f"(illicit {metrics.get('n_illicit', '?')})",
        f"  Features       : {metrics.get('n_features', '?')}",
        "",
        f"  RISK MODEL  ({metrics.get('risk_model', 'RandomForest')}, supervised)",
        "    5-fold cross-validated (mean +/- std):",
        f"      ROC-AUC   : {cv('auc')}",
        f"      precision : {cv('precision')}",
        f"      recall    : {cv('recall')}",
        f"      F1        : {cv('f1')}",
        "",
        "    Single held-out split:",
        f"      precision : {fmt(metrics.get('risk_precision'))}",
        f"      recall    : {fmt(metrics.get('risk_recall'))}",
        f"      F1        : {fmt(metrics.get('risk_f1'))}",
        f"      ROC-AUC   : {fmt(metrics.get('risk_auc'))}",
        f"      confusion : TP={metrics.get('true_positives')} "
        f"FP={metrics.get('false_positives')} "
        f"FN={metrics.get('false_negatives')} "
        f"TN={metrics.get('true_negatives')}",
        f"    precision@{metrics.get('decoy_test_k', 25)} on the alert rail: "
        f"{fmt(metrics.get('decoy_test_precision'))}",
        "",
        "  CALIBRATION  (does 'risk 92' mean 92%?)",
        f"    Brier score            : {fmt(metrics.get('brier'))}",
        f"    expected calibration err: {fmt(metrics.get('expected_calibration_error'))}",
        "",
        "  ANOMALY MODEL  (IsolationForest, unsupervised -- never saw a label)",
        f"    precision@{metrics.get('anomaly_k', 20)} : "
        f"{fmt(metrics.get('anomaly_precision_at_k'))}",
        "",
        "  ENTITY CLUSTERING  (common-input heuristic)",
        f"    adjusted Rand index : {fmt(metrics.get('cluster_ari'))}",
        "",
        "  GRAPH  (communities on the material-flow backbone)",
        f"    modularity : {fmt(metrics.get('modularity'))} "
        f"(raw graph {fmt(metrics.get('modularity_raw'))})",
        "",
        "  IS IT JUST RULES?  -- three measurements",
        "    rules alone (thresholds as shipped):",
        f"      precision {fmt(metrics.get('rules_precision'))}  "
        f"recall {fmt(metrics.get('rules_recall'))}  "
        f"F1 {fmt(metrics.get('rules_f1'))}  "
        f"({metrics.get('rules_flags')} flagged)",
        f"    ablation (all {len(RULE_DERIVED_FEATURES)} rule features removed):",
        f"      ROC-AUC {fmt(metrics.get('ablation_auc_mean'))} "
        f"+/- {fmt(metrics.get('ablation_auc_std'))} "
        f"on {metrics.get('ablation_features_remaining')} features",
        f"    decoys (lawful high-volume services, {metrics.get('decoy_total_in_dataset', '?')} in the dataset):",
        f"      held-out    : {metrics.get('decoy_heldout_decoys_in_top_k')} flagged in the top "
        f"{metrics.get('decoy_heldout_k')} -> "
        f"{'PASSED' if metrics.get('decoy_heldout_passed') else 'FAILED'}",
        f"      full ranking: {metrics.get('decoy_insample_decoys_in_top_k')} flagged in the top "
        f"{metrics.get('decoy_insample_k')} -> "
        f"{'PASSED' if metrics.get('decoy_insample_passed') else 'FAILED'}",
        "",
        f"  Explanation method : {metrics.get('explanation_method', 'unknown')}",
        "  ==============================================================",
        "",
    ]
    return "\n".join(lines)


def logistic_baseline(X: np.ndarray, y: np.ndarray, folds: int = 5, seed: int = 42) -> dict:
    """A deliberately simple model, for the model-selection table.

    Included so the RandomForest is a CHOICE with evidence behind it rather than
    a default. If a linear model matched it, the honest thing would be to ship
    the linear model.
    """
    y = np.asarray(y)
    counts = np.bincount(y) if len(y) else np.array([])
    usable = int(min(folds, counts.min())) if len(counts) > 1 else 0
    if usable < 2:
        return {"logistic_auc_mean": None}

    splitter = StratifiedKFold(n_splits=usable, shuffle=True, random_state=seed)
    aucs: list[float] = []
    for train_index, test_index in splitter.split(X, y):
        model = LogisticRegression(max_iter=2000, class_weight="balanced", random_state=seed)
        model.fit(X[train_index], y[train_index])
        probabilities = model.predict_proba(X[test_index])[:, 1]
        if len(np.unique(y[test_index])) > 1:
            aucs.append(float(roc_auc_score(y[test_index], probabilities)))

    if not aucs:
        return {"logistic_auc_mean": None}
    return {"logistic_auc_mean": float(np.mean(aucs)), "logistic_auc_std": float(np.std(aucs))}
