"""
Structural pattern detectors -- peel chains, CoinJoins, collectors, exchanges.

WHY THESE ARE DETECTORS *AND* FEATURES
--------------------------------------
The problem statement lists "peeling-chain / mixing detection" as one of the
four AI/ML areas. We implement it as domain-informed structural detectors, and
then -- this is the important part -- **feed their outputs into the risk model
as features**.

That is a stronger design than a standalone rule, and it is easy to defend:

  * A pure rule says "this is a peel chain, ship it." Rigid, brittle, and it
    cannot be combined with other evidence.
  * A rule-as-feature says "this looks 0.84 like a peel chain." The trained
    model then weighs that alongside network-layer evidence and decides.

So the detectors encode domain knowledge; the model learns how much to trust
each signal. Both halves of the PS requirement are satisfied, and there is no
contradiction between "we use domain rules" and "we use real ML".

Every detector here is deliberately explainable -- an investigator must be able
to check the reasoning by hand.

PERFORMANCE
-----------
The previous version walked every transaction with `iterrows()` twice (once to
attribute output values to an owner, once to measure output uniformity), which
is the same Python-row-object cost that made the correlation layer quadratic.
Both passes are now a single explode + groupby. The per-entity assembly loops
that remain run once per ENTITY -- 533 times at demo scale, not 27,860.

One behaviour detail preserved deliberately: an owner is resolved as the FIRST
input address that maps to an entity, not the majority owner used by the
correlation layer. These differ only for coordinated multi-party transactions,
and matching the previous behaviour is what makes the rewrite provable.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from correlation.engine import CorrelationResult


def _clamp(values, low: float = 0.0, high: float = 1.0):
    """Clamp to a range, element-wise. Works for scalars and arrays."""
    return np.clip(values, low, high)


def _first_owner(
    addresses: pd.Series,
    address_to_entity: dict[str, str],
) -> pd.Series:
    """Per row, the FIRST input address that resolves to an entity.

    Vectorised: explode, keep the positions, and take the earliest resolving
    row. The previous implementation broke out of a per-row Python loop on the
    first hit, which is exactly what this reproduces -- without the loop.
    """
    frame = addresses.explode().rename("address").to_frame()
    if frame.empty:
        return pd.Series(dtype=object)

    frame["_pos"] = frame.groupby(level=0).cumcount()
    frame["_entity"] = frame["address"].map(address_to_entity)
    frame = frame.dropna(subset=["_entity"])
    if frame.empty:
        return pd.Series(dtype=object)

    frame = frame.rename_axis("_row").reset_index()
    earliest = frame.groupby("_row")["_pos"].idxmin()
    return frame.loc[earliest].set_index("_row")["_entity"]


def _output_stats(df: pd.DataFrame) -> pd.DataFrame:
    """Per-transaction count/min/max/mean and relative spread of output amounts."""
    exploded = df[["output_amounts"]].reset_index(drop=True).explode("output_amounts")
    values = pd.to_numeric(exploded["output_amounts"], errors="coerce").astype("float64")
    grouped = values.groupby(level=0)

    stats = pd.DataFrame({
        "count": grouped.count(),
        "min": grouped.min(),
        "max": grouped.max(),
        "mean": grouped.mean(),
    }).reindex(range(len(df)))

    # `max(amounts.max(), 1e-12)` in the original guards the division.
    denominator = np.maximum(stats["max"].to_numpy(dtype=float), 1e-12)
    stats["spread"] = (stats["max"].to_numpy(dtype=float) - stats["min"].to_numpy(dtype=float)) / denominator
    return stats


# --------------------------------------------------------------------------
# Peel chains
# --------------------------------------------------------------------------
def peel_scores(corr: CorrelationResult) -> pd.DataFrame:
    """Score each entity on how peel-chain-like its behaviour is.

    THE SIGNATURE
    -------------
    A peel chain moves a large balance through a series of wallets, shaving a
    small amount off at every hop:

        A --(62.0)--> B --(61.4)--> C --(58.1)--> mixer

    At each hop the sender keeps the *remainder* as change and sends only a
    small "peel" onward. So the measurable, chain-agnostic properties are:

      1. HIGH CHANGE RATIO -- most of the outgoing value comes straight back to
         the sender as change rather than being paid away.
      2. NARROW OUT-FOCUS -- the wallet forwards to very few counterparties. A
         peel chain is a pipeline, not a marketplace.

    Neither property alone is conclusive (a cautious user also keeps change), so
    we combine them multiplicatively: the score is high only when BOTH hold.
    """
    entities = corr.entities
    if entities.empty:
        return pd.DataFrame(columns=["entity_id", "change_ratio", "peel_score"])

    flows = corr.flows
    if flows.empty:
        external_sent = pd.Series(dtype=float)
        out_degree = pd.Series(dtype=int)
    else:
        grouped = flows.groupby("src")
        external_sent = grouped["value"].sum()
        out_degree = grouped["dst"].nunique()

    total_out = entities["value_sent"].astype(float).to_numpy()
    external = entities["entity_id"].map(external_sent).fillna(0.0).to_numpy(dtype=float)
    degree = entities["entity_id"].map(out_degree).fillna(0).to_numpy(dtype=int)

    with np.errstate(divide="ignore", invalid="ignore"):
        # Change = value that left the wallet in a transaction but came back to
        # addresses the same entity still controls.
        change_ratio = np.where(total_out > 0, (total_out - external) / total_out, 0.0)
    change_ratio = _clamp(change_ratio)

    # 1.0 for a single counterparty, decaying as the wallet fans out.
    out_focus = _clamp(1.0 / np.maximum(degree, 1) * 1.6)

    return pd.DataFrame({
        "entity_id": entities["entity_id"].to_numpy(),
        "change_ratio": change_ratio,
        "peel_score": _clamp(change_ratio * out_focus),
    })


# --------------------------------------------------------------------------
# Mixing (CoinJoin)
# --------------------------------------------------------------------------
def mixer_scores(
    corr: CorrelationResult,
    df: pd.DataFrame,
    coinjoin_mask: np.ndarray,
) -> pd.DataFrame:
    """Score entities on how mixer-like they are.

    Two distinct things get measured, and it is worth keeping them apart:

      * `mixer_score`    -- the entity IS a mixing service (it was the
                            counterparty of coordinated equal-value rounds)
      * `mixer_interaction` -- the entity USES a mixer. This is the laundering
                            signal: an ordinary user has no reason to be one
                            hop away from a CoinJoin.

    The second one is what actually flags the cash-out wallet at the end of the
    peel chain, and it is the feature the demo narrative leans on.
    """
    if corr.entities.empty:
        return pd.DataFrame(columns=["entity_id", "mixer_score", "mixer_interaction"])

    # A CoinJoin has a characteristic ASYMMETRY, and that asymmetry is what
    # identifies the service:
    #
    #   INPUT side  -- many addresses belonging to DIFFERENT owners. These are
    #                  the participants, and they would never normally co-spend.
    #   OUTPUT side -- the pooled, equal-value outputs land with ONE entity.
    #                  That entity is the mixing SERVICE.
    #
    # An earlier version of this code treated every owner on both sides as a
    # mixer, which flagged all nine participants as mixing services -- 8 "mixers"
    # in a dataset where only 3 were planted. That is a substantive error: telling
    # an investigator that a victim's wallet "is a mixer" is false evidence.
    if coinjoin_mask.any() and not df.empty:
        coordinated = df[coinjoin_mask]
        participants = set(
            coordinated["input_addresses"].explode().map(corr.address_to_entity).dropna()
        )
        mixer_services = set(
            coordinated["output_addresses"].explode().map(corr.address_to_entity).dropna()
        )
    else:
        participants: set[str] = set()
        mixer_services: set[str] = set()

    # Anyone who appears ONLY on the input side is a user of the mixer, not the
    # mixer itself. (If an entity is genuinely on both sides across rounds it is
    # the service, so we subtract only the exclusive participants.)
    mixer_services -= participants

    # Output uniformity: how equal are this entity's outputs? CoinJoin rounds
    # produce near-identical amounts; ordinary payments do not.
    uniformity_map: dict[str, float] = {}
    if not df.empty:
        owners = _first_owner(df["input_addresses"], corr.address_to_entity)
        stats = _output_stats(df)
        stats["_entity"] = owners.reindex(range(len(df))).to_numpy()

        # A transaction with one output, or with a non-positive mean, tells us
        # nothing about uniformity -- so it contributes no observation at all.
        usable = (stats["count"] >= 2) & (stats["mean"] > 0) & stats["_entity"].notna()
        if usable.any():
            observations = pd.DataFrame({
                "entity": stats.loc[usable, "_entity"].to_numpy(),
                "uniformity": (1.0 - stats.loc[usable, "spread"]).to_numpy(dtype=float),
            })
            uniformity_map = observations.groupby("entity")["uniformity"].mean().to_dict()

    # Who is adjacent to a mixer on-chain? This is a yes/no question per entity,
    # so it needs the SET of adjacent entities, not an adjacency map. The
    # previous version walked every flow in Python to build the map anyway.
    adjacent_to_mixer: set[str] = set()
    if not corr.flows.empty and mixer_services:
        pays_a_mixer = corr.flows[corr.flows["src"].isin(mixer_services)]["dst"]
        paid_by_mixer = corr.flows[corr.flows["dst"].isin(mixer_services)]["src"]
        adjacent_to_mixer = set(pays_a_mixer) | set(paid_by_mixer)

    rows: list[dict] = []
    for entity_id in corr.entities["entity_id"]:
        uniformity = float(uniformity_map.get(entity_id, 0.0))
        is_mixer = entity_id in mixer_services

        # Three distinct relationships, deliberately scored separately:
        #   mixer_score        -- this entity IS the mixing service
        #   mixer_interaction  -- this entity USES or is adjacent to one, or took
        #                         part in a coordinated round
        # Conflating them would put victims and launderers in the same bucket.
        if is_mixer:
            interaction = 0.0
        elif entity_id in participants or entity_id in adjacent_to_mixer:
            interaction = 1.0
        else:
            interaction = 0.0

        rows.append({
            "entity_id": entity_id,
            "output_uniformity": round(uniformity, 4),
            # The uniformity term is scaled BELOW 0.5 so that the 0.5 decision
            # threshold used downstream can only ever be crossed by an actual
            # identified service, never by a merely tidy wallet.
            "mixer_score": 1.0 if is_mixer else float(_clamp(uniformity * 0.35)),
            "mixer_interaction": interaction,
        })

    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# Collector (ransomware fan-in) and exchange-like services
# --------------------------------------------------------------------------
def flow_shape_scores(corr: CorrelationResult) -> pd.DataFrame:
    """Score the SHAPE of an entity's counterparty graph.

    Two shapes matter, and they are opposites:

      * COLLECTOR  -- very high fan-IN, low fan-out: hundreds of distinct
                      wallets paying one address. Classic ransomware.
      * EXCHANGE   -- high fan-in AND high fan-out with large volume: a
                      legitimate landmark, and the natural cash-out point.

    Distinguishing them matters: one is a target, the other is where you go to
    serve a warrant. A tool that conflates them produces nonsense leads.
    """
    entities = corr.entities
    if entities.empty:
        return pd.DataFrame(columns=["entity_id", "collector_score", "exchange_score"])

    fan_in = entities["fan_in"].astype(float).to_numpy()
    fan_out = entities["fan_out"].astype(float).to_numpy()
    max_fan_in = max(float(fan_in.max()), 1.0)
    max_fan_out = max(float(fan_out.max()), 1.0)

    fan_in_norm = fan_in / max_fan_in
    fan_out_norm = fan_out / max_fan_out

    # A collector is asymmetric: many pay in, few go out.
    asymmetry = _clamp((fan_in - fan_out) / np.maximum(fan_in, 1.0))
    collector = _clamp(fan_in_norm * asymmetry * 1.5)

    # An exchange is symmetric and busy in both directions.
    symmetry = 1.0 - np.abs(fan_in - fan_out) / np.maximum(fan_in + fan_out, 1.0)
    exchange = _clamp(np.minimum(fan_in_norm, fan_out_norm) * symmetry * 1.4)

    return pd.DataFrame({
        "entity_id": entities["entity_id"].to_numpy(),
        "collector_score": collector,
        "exchange_score": exchange,
    })


# --------------------------------------------------------------------------
# Payment hygiene (value shape)
# --------------------------------------------------------------------------
def value_shape_scores(df: pd.DataFrame, corr: CorrelationResult) -> pd.DataFrame:
    """How 'human' are this entity's payments?

    Automated laundering systems move precise, machine-computed amounts. People
    pay 0.05 or 0.1 or 1.0. So the fraction of round-number outputs is a weak
    but genuinely useful behavioural feature -- and it is the sort of thing an
    investigator recognises immediately.
    """
    if df.empty or corr.entities.empty:
        return pd.DataFrame(columns=["entity_id", "round_amount_ratio", "mean_payment_btc"])

    owners = _first_owner(df["input_addresses"], corr.address_to_entity)
    flat = df[["output_amounts"]].reset_index(drop=True).explode("output_amounts")
    values = pd.to_numeric(flat["output_amounts"], errors="coerce").astype("float64")

    observations = pd.DataFrame({
        "entity": owners.reindex(flat.index).to_numpy(),
        "value": values.to_numpy(),
    }).dropna(subset=["entity"])

    # "Round" = within 1% of a 0.1 BTC multiple.
    ratio = observations["value"].to_numpy(dtype=float) / 0.1
    observations["round"] = (
        (observations["value"].to_numpy(dtype=float) > 0)
        & (np.abs(ratio - np.round(ratio)) < 0.01)
    ).astype(float)

    grouped = observations.groupby("entity")
    round_ratio = grouped["round"].mean()
    mean_payment = grouped["value"].mean()

    return pd.DataFrame({
        "entity_id": corr.entities["entity_id"].to_numpy(),
        "round_amount_ratio": corr.entities["entity_id"].map(round_ratio).fillna(0.0).to_numpy(dtype=float),
        "mean_payment_btc": corr.entities["entity_id"].map(mean_payment).fillna(0.0).to_numpy(dtype=float),
    })


# --------------------------------------------------------------------------
# Convenience
# --------------------------------------------------------------------------
def all_structural_features(
    corr: CorrelationResult,
    df: pd.DataFrame,
    coinjoin_mask: np.ndarray,
) -> pd.DataFrame:
    """Run every detector and merge into one per-entity table."""
    frames = (
        peel_scores(corr),
        mixer_scores(corr, df, coinjoin_mask),
        flow_shape_scores(corr),
        value_shape_scores(df, corr),
    )

    merged: pd.DataFrame | None = None
    for frame in frames:
        if frame is None or frame.empty:
            continue
        merged = frame if merged is None else merged.merge(frame, on="entity_id", how="outer")

    if merged is None:
        return pd.DataFrame(columns=["entity_id"])
    return merged.fillna(0.0)
