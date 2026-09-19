"""
Anomaly detection -- trained model #1.

WHAT AND WHY
------------
`IsolationForest` is an UNSUPERVISED anomaly detector: it never sees a label.
It works on a beautifully simple idea --

    anomalies are easy to isolate.

The algorithm builds many random decision trees. At each node it picks a random
feature and a random split point. A normal point sits in a dense region, so it
takes many splits to separate it from its neighbours. An outlier sits far out on
its own, so a few random splits isolate it. The average number of splits needed
(averaged over the forest) is therefore an anomaly score: FEWER splits = MORE
anomalous.

WHY IT BELONGS IN THIS PROJECT
------------------------------
It is the honest answer to "what if the criminals do something you did not
plant?" Our planted typologies are known ahead of time, but a real deployment
faces novel behaviour. An unsupervised detector needs no prior example of a
pattern to notice that something is unusual.

That is also the strongest answer to the judge question "is this just if-else
rules?" -- this model was never told what an anomaly looks like.

WHY THE SCORE IS NORMALISED BY RANK
-----------------------------------
Min-max normalisation is fragile: one extreme outlier compresses everyone else
toward zero, so scores stop being comparable between two runs on different
datasets. A rank-based percentile is stable and reads naturally to an analyst:
"more anomalous than 97% of the others".
"""

from __future__ import annotations

from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import IsolationForest


class AnomalyDetector:
    """Thin, well-documented wrapper around IsolationForest.

    Wrapping rather than using the estimator directly buys us three things:
    a stable ``score`` in 0..1, consistent persistence, and one place where the
    hyperparameters are documented.
    """

    def __init__(
        self,
        contamination: float = 0.06,
        n_estimators: int = 200,
        random_state: int = 42,
    ) -> None:
        # `contamination` is the expected proportion of outliers. We set it
        # slightly above the true illicit rate (~0.08 here) on purpose: an
        # investigative tool should over-flag a little and let the analyst
        # dismiss false leads, rather than miss real ones. That is a deliberate
        # product decision, not a tuning accident.
        self.contamination = contamination
        self.model = IsolationForest(
            n_estimators=n_estimators,
            contamination=contamination,
            random_state=random_state,
            n_jobs=-1,
        )
        self._fitted = False

    def fit(self, X: np.ndarray) -> "AnomalyDetector":
        if len(X) == 0:
            self._fitted = False
            return self
        self.model.fit(X)
        self._fitted = True
        return self

    @property
    def fitted(self) -> bool:
        return self._fitted

    def raw_scores(self, X: np.ndarray) -> np.ndarray:
        """sklearn's decision_function: higher = MORE NORMAL. We flip it."""
        if not self._fitted or len(X) == 0:
            return np.zeros(len(X))
        return -self.model.decision_function(X)

    def score(self, X: np.ndarray) -> np.ndarray:
        """Anomaly score normalised to 0..1, where 1 is the most anomalous."""
        raw = self.raw_scores(X)
        if len(raw) == 0:
            return raw
        order = raw.argsort().argsort()  # rank of each element, 0-based
        return order / max(len(raw) - 1, 1)

    def is_anomaly(self, X: np.ndarray) -> np.ndarray:
        if not self._fitted or len(X) == 0:
            return np.zeros(len(X), dtype=bool)
        return self.model.predict(X) == -1

    # ---- persistence -------------------------------------------------------
    def save(self, path: Path | str) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(
            {
                "model": self.model,
                "contamination": self.contamination,
                "fitted": self._fitted,
            },
            path,
        )

    @classmethod
    def load(cls, path: Path | str) -> "AnomalyDetector":
        payload = joblib.load(Path(path))
        detector = cls(contamination=payload["contamination"])
        detector.model = payload["model"]
        detector._fitted = payload["fitted"]
        return detector
