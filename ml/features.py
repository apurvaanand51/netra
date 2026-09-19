"""
Feature engineering -- the highest-leverage step in the whole pipeline.

WHY THIS FILE MATTERS MORE THAN THE MODEL
-----------------------------------------
A model is only as good as what you feed it. Given the same RandomForest, an
analyst who expresses the right domain features will beat one who throws raw
columns at it every time. So this is where the domain knowledge (Bitcoin,
laundering, network telemetry) gets converted into numbers a model can use.

THE UNIT OF ANALYSIS IS THE ENTITY, NOT THE TRANSACTION
-------------------------------------------------------
This is the central design decision. An investigator does not care that
"transaction 8f3a... was odd". They care that "wallet cluster E-0007 looks like
a laundering pipeline". So we aggregate from transactions up to entities, and
everything downstream scores entities.

THE ONE RULE: NO LABEL LEAKAGE
------------------------------
Nothing in this file may read ground_truth_*.csv. Features are computed purely
from observable traffic. If a label leaks into a feature, the reported accuracy
becomes fiction -- the model would be reading the answer key. This is the single
most common way a hackathon ML demo becomes dishonest, usually by accident.

ROBUST STATISTICS, AND WHY THEY ARE HERE RATHER THAN IN THE FEATURES
--------------------------------------------------------------------
Two different problems get confused under the heading "outliers", and they need
opposite treatments:

  1. A CORRUPT extreme value (a bad SQL export, a sentinel like 999999, a unit
     error) must never be allowed to distort the model. That is a data-quality
     problem, and `FeatureBaseline.clamp` solves it by bounding every feature to
     the range observed in TRAINING.

  2. A GENUINE extreme value (a real whale) is not corrupt, and for a tree model
     it is harmless: trees split on order, so standardising or rescaling a
     feature changes nothing about the splits. So we deliberately do NOT
     standardise the model's inputs -- there is nothing to gain and a pipeline
     stage to get wrong.

But (2) bites hard in one place: EXPLAINABILITY. Our per-entity attributions are
`importance x how_unusual_is_this_value`, and "how unusual" computed with a
mean and standard deviation is destroyed by a single whale -- the standard
deviation inflates, and every other entity's attribution for that feature
collapses toward zero. So the robust z-score below is used for explanations,
where it fixes a real defect, and not for the model, where it would do nothing.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from correlation.engine import CorrelationResult
from ml.graph import GraphIntelligence, analyse_graph
from ml.patterns import all_structural_features

# The exact feature vector the models are trained on. Frozen alongside the
# contract: train and inference must agree, or the model silently mispredicts.
FEATURE_COLUMNS = [
    # --- scale: how big is this actor? ---
    "address_count",
    "tx_count",
    "tx_sent",
    "tx_received",
    "log_value_btc",
    "value_per_tx",
    # --- topology: what shape is its counterparty graph? ---
    "fan_in",
    "fan_out",
    "in_out_ratio",
    "distinct_counterparties",
    # --- network layer: WHERE was it controlled from? (the fusion signal) ---
    "ip_count",
    "country_count",
    "asn_count",
    "active_days",
    "burst_score",
    # --- structural detectors: WHAT does its behaviour look like? ---
    "change_ratio",
    "peel_score",
    "output_uniformity",
    "mixer_score",
    "mixer_interaction",
    "collector_score",
    "exchange_score",
    "round_amount_ratio",
    "mean_payment_btc",
    # --- graph position: WHERE does it sit in the operation? ---
    # These come from ml/graph.py. They are the only features that describe an
    # entity's role in the wider network rather than its own behaviour, and
    # betweenness in particular cannot be computed from any single entity.
    "pagerank",
    "betweenness",
    "community_size",
    "net_flow_ratio",
]

# Makes a MAD-based score directly comparable to a standard deviation under a
# normal distribution: for normal data, MAD ~= 0.6745 * sigma.
ROBUST_Z_CONSTANT = 0.6745


def _safe_divide(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    """Divide, returning 0 where the denominator is 0. Avoids inf, which would
    poison a tree model with nonsense splits."""
    result = numerator / denominator.replace(0, np.nan)
    return result.fillna(0.0).replace([np.inf, -np.inf], 0.0)


@dataclass
class FeatureBaseline:
    """Per-feature robust statistics, fitted on the TRAINING data only.

    Carries two things that must travel with a trained model, because both are
    only meaningful relative to the data the model was fitted on:

      * median and MAD  -- for robust z-scores used in explanations
      * percentile bounds -- for winsorisation, so a corrupt extreme value in a
        later batch cannot reach the model

    Fitting this at inference time instead would be a subtle form of leakage:
    the explanation would depend on which other entities happened to be in the
    same upload.
    """

    median: np.ndarray
    mad: np.ndarray
    lower: np.ndarray
    upper: np.ndarray

    @classmethod
    def fit(
        cls,
        matrix: np.ndarray,
        lower_percentile: float = 1.0,
        upper_percentile: float = 99.0,
    ) -> "FeatureBaseline":
        values = np.asarray(matrix, dtype=float)
        if values.size == 0:
            width = values.shape[1] if values.ndim == 2 else 0
            zeros = np.zeros(width)
            return cls(median=zeros, mad=np.ones(width), lower=zeros, upper=zeros)

        median = np.median(values, axis=0)
        mad = np.median(np.abs(values - median), axis=0)
        # A constant feature has MAD 0; dividing by it would give inf. Using 1.0
        # makes such a feature score a flat 0 -- "not unusual" -- which is the
        # truthful answer when nothing varies.
        mad = np.where(mad == 0, 1.0, mad)

        return cls(
            median=median,
            mad=mad,
            lower=np.percentile(values, lower_percentile, axis=0),
            upper=np.percentile(values, upper_percentile, axis=0),
        )

    def clamp(self, matrix: np.ndarray) -> np.ndarray:
        """Winsorise to the range seen in training.

        This is the guard against a corrupt value in a real feed: an amount of
        999999 or a sentinel of -1 cannot drag a prediction, because the model
        never saw anything outside these bounds and cannot act on the difference.
        """
        values = np.asarray(matrix, dtype=float)
        if values.size == 0:
            return values
        return np.clip(values, self.lower, self.upper)

    def robust_z(self, matrix: np.ndarray) -> np.ndarray:
        """Median/MAD z-score: how unusual is each value, robustly.

        Replaces `(x - mean) / std`, which a single extreme value destroys.
        """
        values = self.clamp(matrix)
        if values.size == 0:
            return values
        return ROBUST_Z_CONSTANT * (values - self.median) / self.mad

    def to_dict(self) -> dict[str, np.ndarray]:
        return {
            "median": self.median,
            "mad": self.mad,
            "lower": self.lower,
            "upper": self.upper,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, np.ndarray]) -> "FeatureBaseline":
        return cls(
            median=np.asarray(payload["median"], dtype=float),
            mad=np.asarray(payload["mad"], dtype=float),
            lower=np.asarray(payload["lower"], dtype=float),
            upper=np.asarray(payload["upper"], dtype=float),
        )


def build_feature_table(
    corr: CorrelationResult,
    df: pd.DataFrame,
    coinjoin_mask: np.ndarray,
    graph: "GraphIntelligence | None" = None,
) -> pd.DataFrame:
    """Build the per-entity feature matrix.

    Returns a DataFrame with `entity_id` plus every column in FEATURE_COLUMNS.

    `graph` may be passed in when the caller has already run the graph layer
    (for communities, roles or fund traces). Graph algorithms are the most
    expensive part of the pipeline, so paying for them twice would be wasteful --
    but leaving the parameter out entirely would mean every caller has to know
    the correct order to run things in.
    """
    entities = corr.entities
    if entities.empty:
        return pd.DataFrame(columns=["entity_id"] + FEATURE_COLUMNS)

    base = entities[[
        "entity_id", "address_count", "tx_count", "tx_sent", "tx_received",
        "value_btc", "value_sent", "value_received",
        "fan_in", "fan_out", "distinct_counterparties",
        "ip_count", "country_count", "asn_count", "active_days", "burst_score",
    ]].copy()

    # Log-transform the money columns. Bitcoin values span nine orders of
    # magnitude (0.0001 BTC to 10,000 BTC); on a raw scale a single whale would
    # dominate every split. log1p compresses that range while keeping zero at
    # zero, so the model sees relative size rather than absolute magnitude.
    base["log_value_btc"] = np.log1p(base["value_btc"].clip(lower=0))
    base["value_per_tx"] = _safe_divide(base["value_btc"], base["tx_count"])

    # Directionality: a wallet that receives from 200 sources and pays 3 is a
    # collector; the reverse is a distributor. This ratio encodes that shape.
    base["in_out_ratio"] = _safe_divide(base["fan_in"], base["fan_out"] + 1)

    # --- structural detector outputs, merged in ---
    structural = all_structural_features(corr, df, coinjoin_mask)
    table = base.merge(structural, on="entity_id", how="left")

    # --- graph position (PageRank, betweenness, community, value direction) ---
    if graph is None:
        graph = analyse_graph(corr, structural)
    table = table.merge(graph.metrics, on="entity_id", how="left")

    for column in FEATURE_COLUMNS:
        if column not in table.columns:
            table[column] = 0.0

    table[FEATURE_COLUMNS] = (
        table[FEATURE_COLUMNS]
        .apply(pd.to_numeric, errors="coerce")
        .fillna(0.0)
        .replace([np.inf, -np.inf], 0.0)
    )

    return table[["entity_id"] + FEATURE_COLUMNS]


def feature_matrix(table: pd.DataFrame) -> np.ndarray:
    """Just the numeric matrix, in the frozen column order."""
    return table[FEATURE_COLUMNS].to_numpy(dtype=float)
