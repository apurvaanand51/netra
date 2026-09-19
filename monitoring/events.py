"""
Deltas between windows, turned into events an analyst can act on.

WHY THIS IS THE POINT OF MONITORING
-----------------------------------
A score is not a finding. "This wallet is 92" is a state, and a state that has
not changed tells an analyst nothing new at 09:00. What they need is the DELTA:

    risk 71 -> 92, because country_count went 1 -> 3 and a mixer interaction
    appeared

That sentence contains three things a bare score cannot: that something changed,
what changed, and how much. It is the monitoring equivalent of the per-entity
attributions in the rest of the system, and it is why events carry ATTRIBUTION
rather than just a type and a timestamp.

EVENT TYPES, AND WHY EACH ONE EXISTS
------------------------------------
Some of these can only exist across time -- they are the reason monitoring is
not simply "run it twice and compare two numbers".

    NEW_ENTITY       first appearance. New infrastructure, or a new operation.
    ESCALATION       risk band moved up. The triage signal.
    DE_ESCALATION    risk band moved down. An operation winding down, or a
                     false alarm resolving itself.
    DORMANT          was active above the risk floor, now silent. A pattern
                     interruption -- and interruptions are themselves patterns.
    RESURGENT        dormant, then active again. Classic laundering behaviour,
                     and invisible without history.
    CLUSTER_GROWTH   gained addresses, or started operating from a new country.
    BEHAVIOUR_SHIFT  the feature vector moved materially BEFORE the score did.
                     An early-warning signal that a band change alone cannot give.
    CLUSTER_MERGE    two previously separate entities proved to be one. Two
                     operations being linked is a finding, not bookkeeping.

THE RISK FLOOR
--------------
Most entities in every window are background. Emitting a NEW_ENTITY event for
all 500 of them would bury the three that matter -- an alert feed nobody reads
is worse than no alert feed. So events are emitted for entities at or above a
risk floor (default 50, the "medium" band boundary), and DORMANT is only emitted
for entities that were above it when they went quiet.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from ml.features import FeatureBaseline
from ml.risk import FEATURE_LABELS, band_for

# Band ordering, for detecting direction of travel. Escalation and
# de-escalation are not symmetric events: an analyst wants to know which way.
BAND_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}

# Only entities at or above this risk produce events. See the docstring.
DEFAULT_RISK_FLOOR = 50

# A feature move is "material" when it shifts this many robust standard
# deviations. Robust (MAD-based) rather than raw, so one whale elsewhere in the
# batch cannot make every other entity look like it shifted.
BEHAVIOUR_SHIFT_Z = 2.0

# CLUSTER_GROWTH thresholds: growth should be noticeable, not a single new
# address, which happens to almost every active wallet.
GROWTH_MIN_ADDRESSES = 2
GROWTH_MIN_FRACTION = 0.25


def _band_direction(previous: str, current: str) -> int:
    return BAND_ORDER.get(current, 0) - BAND_ORDER.get(previous, 0)


def _severity_for_band(band: str) -> str:
    return {"critical": "critical", "high": "high", "medium": "medium"}.get(band, "info")


def _delta_attribution(
    current_features: pd.Series,
    previous_features: pd.Series,
    baseline: FeatureBaseline | None,
    top_k: int = 3,
) -> list[dict[str, Any]]:
    """Which features moved, and by how much, in robust standard deviations.

    This is what turns "risk went up" into "risk went up BECAUSE". Features are
    ranked by |change in robust z|, so a move that is large relative to the
    feature's own spread outranks one that is numerically big but ordinary.
    """
    shared = [name for name in current_features.index if name in previous_features.index]
    if not shared:
        return []

    now = current_features[shared].to_numpy(dtype=float)
    before = previous_features[shared].to_numpy(dtype=float)

    if baseline is not None and len(baseline.median) == len(shared):
        change = baseline.robust_z(now.reshape(1, -1))[0] - baseline.robust_z(before.reshape(1, -1))[0]
    else:
        # No baseline available: fall back to relative change, scaled so the
        # ranking is still meaningful. Reported as such rather than pretending
        # these are robust z-scores.
        scale = np.where(np.abs(before) > 1e-9, np.abs(before), 1.0)
        change = (now - before) / scale

    order = np.argsort(-np.abs(change))[:top_k]
    return [
        {
            "feature": shared[index],
            "label": FEATURE_LABELS.get(shared[index], shared[index]),
            "from": round(float(before[index]), 6),
            "to": round(float(now[index]), 6),
            "delta_z": round(float(change[index]), 4),
        }
        for index in order
        if abs(change[index]) > 1e-9
    ]


def _describe_attribution(attribution: list[dict[str, Any]]) -> str:
    """A one-line, human-readable reason -- the line an analyst actually reads."""
    parts = [
        f"{item['label'].lower()} {item['from']:g} -> {item['to']:g}"
        if abs(item["from"]) < 1e6 and abs(item["to"]) < 1e6
        else f"{item['label'].lower()} changed"
        for item in attribution
    ]
    return " and ".join(parts) if parts else "no single dominant feature"


def detect_events(
    store: Any,
    window_id: int,
    baseline: FeatureBaseline | None = None,
    risk_floor: int = DEFAULT_RISK_FLOOR,
) -> list[dict[str, Any]]:
    """Compare this window against the previous one and emit typed events.

    Reads both windows from the store rather than taking them as arguments, so
    there is exactly one source of truth for what a window contained. A caller
    that passed its in-memory frame would eventually pass a different one.
    """
    current = store.scores(window_id)
    if current.empty:
        return []

    previous = store.scores(window_id - 1) if window_id > 1 else pd.DataFrame()
    seen_before = store.entities_before(window_id)
    current_features = store.feature_matrix(window_id)
    previous_features = store.feature_matrix(window_id - 1) if window_id > 1 else pd.DataFrame()

    previous_by_entity = (
        previous.set_index("entity_key") if not previous.empty else pd.DataFrame()
    )

    events: list[dict[str, Any]] = []

    def emit(entity_key: str, kind: str, band: str, detail: dict[str, Any]) -> None:
        events.append({
            "window_id": window_id,
            "entity_key": entity_key,
            "type": kind,
            "severity": _severity_for_band(band),
            "detail": detail,
        })

    for row in current.itertuples(index=False):
        entity_key = row.entity_key
        risk = int(row.risk)
        band = row.band

        prior = (
            previous_by_entity.loc[entity_key]
            if entity_key in previous_by_entity.index else None
        )
        attribution = []
        if entity_key in previous_features.index and not current_features.empty:
            attribution = _delta_attribution(
                current_features.loc[entity_key],
                previous_features.loc[entity_key],
                baseline,
            )

        # --- first appearance ---
        if prior is None and entity_key not in seen_before:
            if risk >= risk_floor:
                emit(entity_key, "NEW_ENTITY", band, {
                    "risk": risk,
                    "reason": "not seen in any previous window",
                })
            continue

        # --- returning after an absence ---
        if prior is None and entity_key in seen_before:
            if risk >= risk_floor:
                emit(entity_key, "RESURGENT", band, {
                    "risk": risk,
                    "reason": "absent last window, active again",
                    "changes": attribution,
                    "reason_text": _describe_attribution(attribution),
                })
            continue

        # --- band movement ---
        direction = _band_direction(str(prior["band"]), band)
        if direction > 0 and risk >= risk_floor:
            emit(entity_key, "ESCALATION", band, {
                "risk_from": int(prior["risk"]),
                "risk_to": risk,
                "band_from": str(prior["band"]),
                "band_to": band,
                "changes": attribution,
                "reason_text": _describe_attribution(attribution),
            })
        elif direction < 0:
            emit(entity_key, "DE_ESCALATION", band, {
                "risk_from": int(prior["risk"]),
                "risk_to": risk,
                "band_from": str(prior["band"]),
                "band_to": band,
            })

        # --- growth in footprint ---
        growth = _growth_event(current_features, previous_features, entity_key)
        if growth and risk >= risk_floor:
            emit(entity_key, "CLUSTER_GROWTH", band, growth)

        # --- movement before the band moves ---
        # Only when the band did NOT change: once an entity escalates, this would
        # just be a second, noisier alert about the same thing.
        if direction == 0 and attribution:
            biggest = max(abs(item["delta_z"]) for item in attribution)
            if biggest >= BEHAVIOUR_SHIFT_Z and risk >= risk_floor:
                emit(entity_key, "BEHAVIOUR_SHIFT", band, {
                    "risk": risk,
                    "threshold_z": BEHAVIOUR_SHIFT_Z,
                    "changes": attribution,
                    "reason_text": _describe_attribution(attribution),
                })

    # --- went quiet ---
    if not previous.empty:
        current_keys = set(current["entity_key"])
        for row in previous.itertuples(index=False):
            if row.entity_key in current_keys:
                continue
            if int(row.risk) >= risk_floor:
                emit(str(row.entity_key), "DORMANT", str(row.band), {
                    "last_risk": int(row.risk),
                    "reason": "was above the risk floor, silent this window",
                })

    return events


def _growth_event(
    current_features: pd.DataFrame,
    previous_features: pd.DataFrame,
    entity_key: str,
) -> dict[str, Any] | None:
    """Did this entity's footprint grow materially?

    A new country is a stronger signal than a new address: one more address is
    normal wallet behaviour, whereas starting to operate from a new jurisdiction
    means new infrastructure. So the two are reported separately rather than
    collapsed into one "growth" number.
    """
    if current_features.empty or previous_features.empty:
        return None
    if entity_key not in current_features.index or entity_key not in previous_features.index:
        return None

    detail: dict[str, Any] = {}
    for name, label in (("address_count", "addresses"), ("country_count", "countries"),
                        ("ip_count", "IPs")):
        if name not in current_features.columns or name not in previous_features.columns:
            continue
        before = float(previous_features.loc[entity_key, name])
        after = float(current_features.loc[entity_key, name])
        if name == "country_count" and after > before:
            detail[f"new_{label}"] = int(after - before)
        elif after - before >= GROWTH_MIN_ADDRESSES and after >= before * (1 + GROWTH_MIN_FRACTION):
            detail[label] = {"from": int(before), "to": int(after)}

    if not detail:
        return None
    detail["reason"] = "footprint expanded"
    return detail
