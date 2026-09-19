"""
Network <-> blockchain correlation.

THIS IS THE DIFFERENTIATOR.
===========================
Most tools analyse the chain alone and bolt a map on the side. The problem
statement explicitly asks to FUSE the two layers, because each one alone leaves
the investigator guessing:

    blockchain layer alone  ->  "this wallet sent 41 BTC to a mixer"
                                ... but WHO controlled that wallet?

    network layer alone     ->  "this IP broadcast transactions at 02:11"
                                ... but to WHICH wallet, and how much?

    CORRELATED              ->  "the cluster of 6 wallets was controlled from
                                 IPs in RU and NL between 02:11-02:40, and moved
                                 12.4 BTC through a peel chain into a mixer,
                                 then out to a KYC exchange."

That last sentence is the product. It is what an investigator can act on, and
it is only reachable by joining the two layers on time.

WHAT THIS MODULE PRODUCES
-------------------------
  entities : one row per controlling actor, enriched with
             * blockchain facts  -- addresses, tx count, value in/out
             * network facts     -- IPs, countries, ASNs, bursts
             * the FUSION signal -- multi-country control, IP reuse across hops
  flows    : entity -> entity value transfers (the graph's solid edges)
  controls : IP -> entity observations (the graph's dashed edges)

Note the two different edge kinds. On-chain money movement and network-plane
control are NOT the same relationship, and conflating them would misrepresent
the evidence. Keeping them separate is what lets the dashboard show
"controlled from" differently from "paid".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

import numpy as np
import pandas as pd

from ml.cluster import common_input_clusters, detect_coinjoin_like


@dataclass
class CorrelationResult:
    """Everything the correlation layer learned, ready for feature engineering."""

    entities: pd.DataFrame
    flows: pd.DataFrame
    controls: pd.DataFrame
    address_to_entity: dict[str, str] = field(default_factory=dict)
    stats: dict[str, Any] = field(default_factory=dict)


def _dominant_entity(
    addresses: list[str],
    address_to_entity: dict[str, str],
) -> tuple[str | None, int]:
    """Which entity owns most of these addresses?

    For an ordinary transaction every input belongs to one entity, so the answer
    is unambiguous. For a CoinJoin it is not -- which is precisely the signal
    that the transaction is multi-party. We return the dominant owner AND how
    many distinct entities participated, so callers can treat ambiguous
    transactions carefully instead of pretending the ambiguity isn't there.
    """
    owners: dict[str, int] = {}
    for address in addresses:
        owner = address_to_entity.get(address)
        if owner:
            owners[owner] = owners.get(owner, 0) + 1
    if not owners:
        return None, 0
    dominant = max(owners, key=lambda k: owners[k])
    return dominant, len(owners)


def _burst_score(timestamps: pd.Series, window_minutes: int = 60) -> float:
    """How concentrated in time is this entity's activity?

    Automated laundering sweeps a wallet in minutes; a human pays bills over
    days. So "most transactions inside any single hour, as a fraction of all
    their transactions" cleanly separates machine behaviour from human.

    Returns 0..1, where 1 means everything happened inside one window.
    """
    if len(timestamps) < 2:
        return 1.0
    ordered = timestamps.sort_values().reset_index(drop=True)
    window = timedelta(minutes=window_minutes)
    best = 1
    start = 0
    for end in range(len(ordered)):
        while ordered[end] - ordered[start] > window:
            start += 1
        best = max(best, end - start + 1)
    return best / len(ordered)


def correlate(df: pd.DataFrame, coinjoin_mask: np.ndarray | None = None) -> CorrelationResult:
    """Fuse the network and blockchain layers into per-entity intelligence."""
    if df.empty:
        empty = pd.DataFrame()
        return CorrelationResult(empty, empty, empty, {}, {"entities": 0, "addresses": 0})

    # ---- Step 1: resolve addresses into entities (common-input heuristic) ----
    # CoinJoin-like transactions are excluded because their inputs come from
    # many unrelated owners -- including them would merge innocent users.
    if coinjoin_mask is None:
        coinjoin_mask = detect_coinjoin_like(df)
    address_to_entity, entity_members = common_input_clusters(df, exclude=coinjoin_mask)

    # ---- Step 2: attach entity identity to both layers of every transaction ----
    work = df.copy()
    in_pairs = work["input_addresses"].map(lambda a: _dominant_entity(a, address_to_entity))
    out_pairs = work["output_addresses"].map(lambda a: _dominant_entity(a, address_to_entity))
    work["_in_owner"] = [pair[0] for pair in in_pairs]
    work["_in_owners"] = [pair[1] for pair in in_pairs]
    work["_out_owner"] = [pair[0] for pair in out_pairs]
    work["_out_owners"] = [pair[1] for pair in out_pairs]

    work["_value_in"] = work["input_amounts"].map(lambda a: float(np.sum(a)))
    work["_value_out"] = work["output_amounts"].map(lambda a: float(np.sum(a)))

    # Entities that touched a coordinated multi-party transaction. We compute
    # this once rather than scanning per entity -- otherwise this is
    # O(entities x coinjoin_rows) and it shows up at 20k+ transactions.
    if coinjoin_mask.any():
        coordinated = work[coinjoin_mask]
        coinjoin_entities = set(coordinated["_in_owner"].dropna()) | set(
            coordinated["_out_owner"].dropna()
        )
    else:
        coinjoin_entities: set[str] = set()

    # ---- Step 3: on-chain flows (entity -> entity) ----
    # Outputs that stay with the sender are CHANGE, not a transfer. Counting
    # change as a payment would inflate every wallet's apparent activity and
    # make peel chains invisible -- so we separate them explicitly.
    flow_rows: list[dict[str, Any]] = []
    for _, row in work.iterrows():
        sender = row["_in_owner"]
        if sender is None:
            continue
        receiver = row["_out_owner"]
        amounts = np.asarray(row["output_amounts"], dtype=float)
        addrs = list(row["output_addresses"])
        owners = [
            (address_to_entity.get(a), float(v))
            for a, v in zip(addrs, amounts)
        ]
        external = [(o, v) for o, v in owners if o and o != sender]
        if not external:
            continue  # pure self-transfer: no payment left the entity
        by_receiver: dict[str, float] = {}
        for owner, value in external:
            by_receiver[owner] = by_receiver.get(owner, 0.0) + value
        for owner, value in by_receiver.items():
            flow_rows.append({
                "src": sender,
                "dst": owner,
                "value": round(value, 8),
                "txid": row["txid"],
                "timestamp": row["timestamp"],
            })

    flows = pd.DataFrame(flow_rows) if flow_rows else pd.DataFrame(
        columns=["src", "dst", "value", "txid", "timestamp"]
    )

    # ---- Step 4: network control observations (IP -> entity) ----
    # An IP that broadcast a wallet's transactions was, at that moment, under
    # the operator's control. That is the bridge between the two layers.
    control_rows: list[dict[str, Any]] = []
    for _, row in work.iterrows():
        owner = row["_in_owner"]
        if owner is None:
            continue
        control_rows.append({
            "ip": row["src_ip"],
            "entity": owner,
            "country": row["geo_country"] or "",
            "asn": row["asn"] or "",
            "timestamp": row["timestamp"],
            "txid": row["txid"],
        })
    controls = pd.DataFrame(control_rows) if control_rows else pd.DataFrame(
        columns=["ip", "entity", "country", "asn", "timestamp", "txid"]
    )

    # ---- Step 5: per-entity fusion ----
    rows: list[dict[str, Any]] = []
    for entity_id, members in entity_members.items():
        sent = work[work["_in_owner"] == entity_id]
        received = work[work["_out_owner"] == entity_id]
        network = controls[controls["entity"] == entity_id]

        timestamps = pd.concat([sent["timestamp"], received["timestamp"]]) if len(sent) or len(received) else pd.Series(dtype="datetime64[ns, UTC]")

        # Country / ASN footprint -- the cross-border signal.
        countries = sorted({c for c in network["country"].tolist() if c})
        asns = sorted({a for a in network["asn"].tolist() if a})
        ips = sorted(set(network["ip"].tolist()))

        # Counterparties, counted in each direction. High fan-in is a collector
        # (ransomware); high fan-out is a distributor (exchange, payout).
        fan_out = int(flows[flows["src"] == entity_id]["dst"].nunique()) if len(flows) else 0
        fan_in = int(flows[flows["dst"] == entity_id]["src"].nunique()) if len(flows) else 0

        total_sent = float(sent["_value_out"].sum()) if len(sent) else 0.0
        total_received = float(received["_value_in"].sum()) if len(received) else 0.0

        # IP reuse across different days is a strong same-operator signal: an
        # innocent one-off share and a recurring controller look very different.
        n_days = int(network["timestamp"].dt.date.nunique()) if len(network) else 0

        rows.append({
            "entity_id": entity_id,
            "address_count": len(members),
            "addresses": members,
            "tx_count": int(len(sent) + len(received)),
            "tx_sent": int(len(sent)),
            "tx_received": int(len(received)),
            "value_sent": round(total_sent, 8),
            "value_received": round(total_received, 8),
            "value_btc": round(total_sent + total_received, 8),
            "fan_in": fan_in,
            "fan_out": fan_out,
            "distinct_counterparties": len(
                set(flows[flows["src"] == entity_id]["dst"]) | set(flows[flows["dst"] == entity_id]["src"])
            ) if len(flows) else 0,
            "ip_count": len(ips),
            "ips": ips,
            "countries": countries,
            "country_count": len(countries),
            "asns": asns,
            "asn_count": len(asns),
            "active_days": n_days,
            "first_seen": timestamps.min() if len(timestamps) else pd.NaT,
            "last_seen": timestamps.max() if len(timestamps) else pd.NaT,
            "burst_score": _burst_score(timestamps) if len(timestamps) else 0.0,
            "in_coinjoin": entity_id in coinjoin_entities,
        })

    entities = pd.DataFrame(rows)

    stats = {
        "addresses": len(address_to_entity),
        "entities": len(entity_members),
        "flows": len(flows),
        "control_observations": len(controls),
        "distinct_ips": int(controls["ip"].nunique()) if len(controls) else 0,
        "coinjoin_like_transactions": int(coinjoin_mask.sum()),
        "cross_border_entities": int((entities["country_count"] >= 2).sum()) if len(entities) else 0,
    }

    return CorrelationResult(
        entities=entities,
        flows=flows,
        controls=controls,
        address_to_entity=address_to_entity,
        stats=stats,
    )
