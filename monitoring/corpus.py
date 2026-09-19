"""
Analysis of the WHOLE ingested traffic -- not only the part that got flagged.

WHY THIS MODULE EXISTS
----------------------
The problem statement asks to analyse Bitcoin transaction traffic. It does not
ask to detect fraud; it asks to analyse traffic, with anomaly detection,
clustering and risk scoring as techniques applied to it. Our first dashboard
inverted that: every panel was framed around leads, the geography panel showed
"countries the FLAGGED groups were controlled from", and roughly nine tenths of
what we had just read was invisible on screen.

That is not a presentation problem, it is a scope error. An analyst who cannot
see the corpus cannot judge whether a lead is remarkable. "This group moved 62
BTC" means nothing until you know the median transaction in the same capture
moved 1.35 BTC and the capture moved 26,000 BTC in total.

So this module computes the descriptive statistics of everything ingested, and
the flagged subset is reported as a share OF that whole.

WHAT IT REPORTS, AND WHY EACH PART EARNS ITS PLACE
--------------------------------------------------
    volume and span    how much traffic, over how long -- the denominator for
                       everything else
    value distribution Bitcoin values span nine orders of magnitude, so a mean
                       is meaningless. Percentiles and size classes show the
                       actual shape.
    top actors         the largest participants in the whole capture. Most are
                       lawful exchanges, and that is the point: the analysis
                       covers everyone, not a curated list of suspects.
    geography          countries across ALL traffic, with the flagged count
                       shown as a highlight within each
    composition        a PARTITION of every wallet group by observed behaviour
    score coverage     every entity by priority band, including the cleared ones
                       -- the statement that the corpus was examined, not just
                       the suspects

ONE MODELLING NOTE WORTH DEFENDING
----------------------------------
The behaviour composition is a PARTITION: every group is counted exactly once,
under the first class whose test it meets. The detectors overlap heavily (a
mixer is usually also multi-country), so reporting them as independent flags
would make the shares sum to well over 100% and the chart would be unreadable
and misleading. Precedence is fixed and written into each class's explanation so
the assignment is auditable rather than implied.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

# Transaction size buckets, by total output value. Chosen on Bitcoin's own
# conventions: sub-0.01 BTC is dust and rarely economical to spend, 1-10 BTC is a
# substantial retail payment, and above 100 BTC is institutional or movement of
# a treasury.
SIZE_CLASSES: list[tuple[str, float, float]] = [
    ("dust (< 0.01 BTC)", 0.0, 0.01),
    ("small (0.01 - 1 BTC)", 0.01, 1.0),
    ("medium (1 - 10 BTC)", 1.0, 10.0),
    ("large (10 - 100 BTC)", 10.0, 100.0),
    ("very large (>= 100 BTC)", 100.0, float("inf")),
]

# Behaviour classes, in PRECEDENCE ORDER. The first test a group meets is the
# class it is counted under, so the composition sums to exactly 1.
BEHAVIOUR_CLASSES: list[tuple[str, str, str, Any]] = [
    ("mixing_service", "Mixing services",
     "Identified as a mixing service: it received the pooled equal-value outputs "
     "of a coordinated multi-party round.",
     lambda row: row.get("mixer_score", 0.0) >= 0.5),
    ("exchange_like", "Exchanges and payment processors",
     "High volume in BOTH directions with a balanced counterparty graph -- the "
     "shape of a legitimate service, not a launderer.",
     lambda row: row.get("exchange_score", 0.0) >= 0.5),
    ("fan_in_collector", "Fan-in collectors",
     "Many distinct wallets paying in and very few paying out -- the classic "
     "ransomware collection shape.",
     lambda row: row.get("collector_score", 0.0) >= 0.3),
    ("peel_chain", "Peel chains",
     "Forwards most of its value onward while keeping change back, across a very "
     "narrow set of recipients -- a layering pipeline.",
     lambda row: row.get("peel_score", 0.0) >= 0.25),
    ("multi_country", "Multi-country controllers",
     "Operated from more than one country. NOT suspicious on its own: legitimate "
     "services have regional infrastructure too.",
     lambda row: row.get("country_count", 0.0) >= 2),
    ("ordinary", "Ordinary activity",
     "No structural detector fired. Most of any real capture looks like this.",
     lambda row: True),
]


def _transaction_values(frame: pd.DataFrame) -> np.ndarray:
    """Total output value per transaction -- the amount that actually moved."""
    if frame.empty:
        return np.zeros(0)
    return np.array([
        float(np.sum(amounts)) for amounts in frame["output_amounts"]
    ], dtype=float)


def corpus_statistics(
    frame: pd.DataFrame,
    corr: Any,
    scored: pd.DataFrame,
    load_report: Any | None = None,
    *,
    flagged_floor: int = 50,
    top_n: int = 8,
    country_limit: int = 10,
) -> dict[str, Any]:
    """Descriptive statistics of everything ingested, plus coverage of the scoring."""
    values = _transaction_values(frame)
    total_value = float(values.sum()) if len(values) else 0.0

    # ---- value distribution ----
    percentiles = [
        {"percentile": point, "value_btc": round(float(np.percentile(values, point)), 8)}
        for point in (50, 90, 95, 99, 99.9, 100)
    ] if len(values) else []

    size_rows: list[dict[str, Any]] = []
    for label, low, high in SIZE_CLASSES:
        in_class = (values >= low) & (values < high)
        count = int(in_class.sum())
        moved = float(values[in_class].sum())
        size_rows.append({
            "label": label,
            "transactions": count,
            "value_btc": round(moved, 8),
            "share_of_transactions": round(count / len(values), 6) if len(values) else 0.0,
            "share_of_value": round(moved / total_value, 6) if total_value > 0 else 0.0,
        })

    # ---- the largest actors in the WHOLE capture ----
    risk_by_entity = dict(zip(scored["entity_id"], scored["risk"])) if "risk" in scored else {}
    kind_by_entity = dict(zip(scored["entity_id"], scored.get("role", [])))
    entities = corr.entities
    top_entities: list[dict[str, Any]] = []

    # The denominator for an actor's share has to measure the same thing the
    # actor's own figure measures. `total_value` above is the sum of transaction
    # OUTPUTS -- the true value moved. An entity's `value_btc` is its sent outputs
    # PLUS its received inputs, so every transaction contributes to it twice and
    # dividing by the output total can produce a share above 100%. Using the sum
    # of the entities' own figures keeps numerator and denominator consistent.
    attributed_value = float(entities["value_btc"].sum()) if not entities.empty else 0.0

    if not entities.empty:
        ranked = entities.sort_values("value_btc", ascending=False).head(top_n)
        for row in ranked.itertuples(index=False):
            top_entities.append({
                "entity": row.entity_id,
                "label": (list(row.addresses)[0] if row.addresses else row.entity_id),
                "kind": str(kind_by_entity.get(row.entity_id, "wallet")),
                "value_btc": round(float(row.value_btc), 8),
                "tx_count": int(row.tx_count),
                "flagged": bool(risk_by_entity.get(row.entity_id, 0) >= flagged_floor),
                "share_of_value": round(float(row.value_btc) / attributed_value, 6)
                                   if attributed_value > 0 else 0.0,
            })

    # ---- geography across ALL traffic, with the flagged count inside each ----
    country_entities: dict[str, int] = {}
    country_flagged: dict[str, int] = {}
    for row in entities.itertuples(index=False):
        flagged = bool(risk_by_entity.get(row.entity_id, 0) >= flagged_floor)
        for code in (row.countries or []):
            if not code:
                continue
            country_entities[code] = country_entities.get(code, 0) + 1
            if flagged:
                country_flagged[code] = country_flagged.get(code, 0) + 1
    total_seen = sum(country_entities.values()) or 1
    countries = [
        {
            "country": code,
            "code": code,
            "entities": count,
            "share": round(count / total_seen, 6),
            "flagged": country_flagged.get(code, 0),
        }
        for code, count in sorted(country_entities.items(), key=lambda kv: (-kv[1], kv[0]))[:country_limit]
    ]

    spans = frame["timestamp"] if len(frame) else pd.Series(dtype="datetime64[ns, UTC]")
    span_hours = (
        float((spans.max() - spans.min()).total_seconds() / 3600) if len(spans) > 1 else 0.0
    )

    accepted = int(load_report.accepted) if load_report is not None else int(len(frame))
    rejected = int(load_report.rejected) if load_report is not None else 0

    return {
        "records": int(len(frame)),
        "transactions": int(frame["txid"].nunique()) if len(frame) else 0,
        "entities": int(len(entities)),
        "addresses": int(len(corr.address_to_entity)),
        "distinct_ips": int(sum(len(ips) for ips in entities["ips"])) if not entities.empty else 0,
        "distinct_countries": len(country_entities),
        "distinct_asns": int(len({asn for asns in entities["asns"] for asn in asns}))
                          if not entities.empty else 0,
        "total_value_btc": round(total_value, 8),
        "mean_value_btc": round(float(values.mean()), 8) if len(values) else 0.0,
        "median_value_btc": round(float(np.median(values)), 8) if len(values) else 0.0,
        "span_hours": round(span_hours, 3),
        "span_start": str(spans.min()) if len(spans) else None,
        "span_end": str(spans.max()) if len(spans) else None,
        "value_percentiles": percentiles,
        "size_classes": size_rows,
        "top_entities": top_entities,
        "countries": countries,
        "coverage": {
            "entities_scored": int(len(scored)),
            "entities_flagged": int(len(risk_by_entity) and sum(
                1 for risk in risk_by_entity.values() if risk >= flagged_floor
            )),
            "flagged_share": round(
                sum(1 for risk in risk_by_entity.values() if risk >= flagged_floor)
                / max(len(risk_by_entity), 1), 6
            ),
            "records_accepted": accepted,
            "records_rejected": rejected,
        },
    }


def behaviour_composition(
    corr: Any,
    structural: pd.DataFrame,
    scored: pd.DataFrame,
    *,
    flagged_floor: int = 50,
) -> dict[str, Any]:
    """A partition of every wallet group by behaviour, and the score spread.

    See the module docstring: this is a partition with fixed precedence, not a
    set of overlapping flags, because overlapping shares that sum past 100% is a
    chart that misleads while looking fine.
    """
    component = structural.set_index("entity_id") if not structural.empty else pd.DataFrame()
    value_by_entity = (
        dict(zip(corr.entities["entity_id"], corr.entities["value_btc"]))
        if not corr.entities.empty else {}
    )
    risk_by_entity = dict(zip(scored["entity_id"], scored["risk"])) if "risk" in scored else {}

    counts = {name: 0 for name, _label, _why, _test in BEHAVIOUR_CLASSES}
    values = {name: 0.0 for name, _label, _why, _test in BEHAVIOUR_CLASSES}

    for entity_id in (component.index if not component.empty else []):
        row = component.loc[entity_id].to_dict()
        for name, _label, _why, test in BEHAVIOUR_CLASSES:
            if test(row):
                counts[name] += 1
                values[name] += float(value_by_entity.get(entity_id, 0.0))
                break

    total_entities = sum(counts.values()) or 1
    classes = [
        {
            "class": name,
            "label": label,
            "entities": counts[name],
            "share": round(counts[name] / total_entities, 6),
            "value_btc": round(values[name], 8),
            "explanation": why,
        }
        for name, label, why, _test in BEHAVIOUR_CLASSES
    ]

    # Every entity by band, including the cleared ones. This is the statement
    # that the entire corpus was scored, rather than only the suspects.
    bands = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    from ml.risk import band_for
    for risk in risk_by_entity.values():
        bands[band_for(int(risk))] += 1
    total_scored = sum(bands.values()) or 1
    distribution = [
        {"band": band, "entities": count, "share": round(count / total_scored, 6)}
        for band, count in bands.items()
    ]

    total_value = sum(values.values()) or 0.0
    flagged_value = sum(
        float(value_by_entity.get(entity_id, 0.0))
        for entity_id, risk in risk_by_entity.items()
        if int(risk) >= flagged_floor
    )

    return {
        "classes": classes,
        "score_distribution": distribution,
        "value_share_of_flagged": round(flagged_value / total_value, 6) if total_value > 0 else 0.0,
    }
