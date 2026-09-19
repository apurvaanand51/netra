"""
Graph intelligence -- communities, roles, centrality, and fund tracing.

WHY THIS MODULE EXISTS
----------------------
Until now the flow graph was used for exactly two numbers per entity: `fan_in`
and `fan_out`. That treats the graph as a bag of local degrees and throws away
the thing an investigator actually wants, which is its SHAPE:

    "this is not forty separate wallets. It is four laundering communities, and
     inside each one there is a collector, a set of relays, and a cash-out."

Three distinct products come out of the same edges:

  1. COMMUNITIES      -- which wallets belong to the same operation
  2. ROLES            -- what each wallet does within that operation
  3. FUND PATHS       -- where the money actually went, and how much arrived

(3) is the one that matters most, because it is a different KIND of output from
everything else in the system. Every other number we produce scores an entity.
A fund trace answers the question an investigator asks second: *"and then what
happened to it?"*

ON LOUVAIN, AND AN HONEST SUBSTITUTION
--------------------------------------
We wanted Louvain. Our pinned networkx is 2.6.3, and `louvain_communities` did
not arrive until 3.0 -- `hasattr` says False, so the choice was to upgrade a
verified dependency days before a demo, or to use what is actually present.

We use `greedy_modularity_communities` (Clauset-Newman-Moore): also a modularity-
optimising algorithm, deterministic, and available in the pinned version. For
graphs too large for it we fall back to `asyn_lpa_communities`, which is near-
linear and takes a seed so it stays reproducible.

We report WHICH method ran and the resulting MODULARITY, so the quality of the
partition is a number the reader can judge rather than a claim we make.

On upgrading: bumping networkx would invalidate the environment we verified, the
Docker image, and the offline wheel cache, to change one function call. That
trade is not worth making before a demo -- and saying so out loud is better than
quietly running a different algorithm than we advertised.

THE DUST PROBLEM, AND WHY THE BACKBONE EXISTS
---------------------------------------------
Detecting communities on the raw flow graph gives a modularity of about 0.19 --
barely better than chance. That is not a bug in the algorithm: background traffic
is a near-random graph, and 24,000 edges of small transfers drown the structure
that the investigation actually cares about.

Filtering by VALUE fixes it, and the effect is measurable:

    edge threshold    nodes   edges   communities   modularity
    all edges           533   24001            11       0.1909
    >= 75th pct         455    6001            13       0.2357
    >= 90th pct         454    2401            12       0.3317
    >= 99th pct         275     241            51       0.8809

So the laundering structure is real and highly modular (0.88 at the top 1% of
edges) -- it is simply hidden underneath the small payments. This is the same
lesson as the rest of the project: the money trail is in the large transfers, and
a graph you have not filtered is a graph you cannot read.

We therefore partition the MATERIAL-FLOW BACKBONE (value threshold, default the
90th percentile) and report BOTH modularities, so the improvement is a visible
number rather than a claim. The threshold is a parameter, not a hidden constant.

The fund-trace assumption below is unchanged and must be read before quoting any
traced amount.
-----------------------------------------------
Bitcoin is fungible: once coins are mixed into a wallet, no observer can say
which output corresponds to which input. So *any* fund trace across hops is an
ALLOCATION MODEL, not a fact. We use the industry-standard one:

    proportional allocation -- a downstream wallet receives a share of the
    tainted amount equal to its share of the sender's outgoing value

Three deliberate consequences, each in the conservative direction:

  * Change already excluded from `flows` means taint shrinks at every hop. We
    under-report reach rather than overstate it.
  * Each entity is expanded ONCE, at the first hop it is reached. Later arrivals
    do not expand again, so a long winding path cannot inflate the total.
  * Branches below `min_amount` are dropped.

The output carries `method` and `assumption` fields so a report can never quote a
traced figure without the model that produced it. Overstating a fund trace is how
an investigative tool puts an innocent wallet in a warrant application.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

import networkx as nx
import numpy as np
import pandas as pd

# Above this node count, greedy modularity becomes too slow to run inside a
# pipeline, so we switch to label propagation. Both are deterministic.
_GREEDY_NODE_LIMIT = 20_000

# Sampling budget for betweenness. Exact betweenness is O(V*E); sampling k
# sources approximates it in O(k*E) and is what makes it usable here at all.
_BETWEENNESS_SAMPLES = 500

# Edges below this value percentile are dropped before community detection, so
# the partition reflects the material money trail rather than background chatter.
# Measured effect on the demo dataset: modularity 0.19 -> 0.33, and 0.88 at the
# 99th percentile. See the docstring table.
DEFAULT_BACKBONE_PERCENTILE = 0.90

# Role assignment thresholds. These are HEURISTICS for the analyst's narrative --
# they are deliberately not model inputs, because a rule-derived label fed to the
# model as a feature is how a rule quietly becomes the answer.
_ROLE_ASYMMETRY = 3.0            # fan_in vs fan_out ratio that implies a shape
_ROLE_BETWEENNESS_PERCENTILE = 0.80   # "well connected" within the graph

# Which structural thresholds make an entity a TERMINUS for a fund trace.
_SINK_EXCHANGE_SCORE = 0.5
_SINK_MIXER_SCORE = 0.5


@dataclass
class GraphIntelligence:
    """Per-entity graph position, plus the partition and its quality."""

    metrics: pd.DataFrame          # entity_id, pagerank, betweenness, community_id, ...
    communities: pd.DataFrame      # community_id, size, members, total_value
    roles: pd.DataFrame            # entity_id, role, role_reason
    summary: dict[str, Any] = field(default_factory=dict)


@dataclass
class FundTrace:
    """Where a seed's outgoing value ended up. An ESTIMATE, not a fact."""

    seed: str
    tainted: float                 # value sent by the seed
    hops_reached: int
    sinks: list[dict[str, Any]]    # one entry per sink reached
    method: str = "proportional allocation along value-weighted flows"
    assumption: str = (
        "Bitcoin is fungible, so per-hop allocation is an estimate. Change "
        "excluded from flows means reach is under-reported, not overstated."
    )

    def as_dict(self) -> dict[str, Any]:
        return {
            "seed": self.seed,
            "tainted": round(self.tainted, 8),
            "hops_reached": self.hops_reached,
            "sinks": self.sinks,
            "method": self.method,
            "assumption": self.assumption,
        }


# --------------------------------------------------------------------------
# Graph construction
# --------------------------------------------------------------------------
def build_flow_graph(flows: pd.DataFrame) -> nx.DiGraph:
    """Aggregate per-transaction flows into one weighted edge per pair.

    Aggregation is not just cosmetic: the contract's `count` field exists because
    a pair that transacts 400 times is one relationship, not 400 edges, and a
    graph that cannot be read is not a visualisation.
    """
    graph = nx.DiGraph()
    if flows.empty:
        return graph

    grouped = (
        flows.groupby(["src", "dst"], sort=False)["value"]
        .agg(value="sum", count="size")
        .reset_index()
    )
    graph.add_weighted_edges_from(
        zip(grouped["src"], grouped["dst"], grouped["value"]),
        weight="value",
    )
    for row in grouped.itertuples(index=False):
        graph[row.src][row.dst]["count"] = int(row.count)
    return graph


def _undirected(graph: nx.DiGraph) -> nx.Graph:
    """Undirected view for community detection.

    Communities are about cohesion, not direction: two wallets that trade with
    each other belong to the same operation regardless of who paid whom. Using
    the directed graph here would split a community along the direction of money
    flow, which is precisely the structure we are trying to find.
    """
    return graph.to_undirected()


def community_backbone(
    graph: nx.DiGraph,
    percentile: float = DEFAULT_BACKBONE_PERCENTILE,
) -> tuple[nx.DiGraph, float]:
    """Keep only the edges that carry material value.

    Small transfers are close to random noise connecting unrelated entities; the
    investigative signal is in the large ones. Returns (backbone, cutoff_value)
    so the threshold applied is a reported number, not a hidden constant.

    Isolated nodes are dropped: an entity with no material flow belongs to no
    community, and leaving it in would inflate the community count with
    singletons created by our own filtering.
    """
    if graph.number_of_edges() == 0:
        return graph.copy(), 0.0

    values = np.array([float(data.get("value", 0.0)) for _, _, data in graph.edges(data=True)])
    cutoff = float(np.quantile(values, percentile))

    backbone = nx.DiGraph()
    backbone.add_edges_from(
        (source, target, data)
        for source, target, data in graph.edges(data=True)
        if float(data.get("value", 0.0)) >= cutoff
    )
    backbone.remove_nodes_from(
        [node for node in list(backbone.nodes()) if backbone.degree(node) == 0]
    )
    return backbone, cutoff


def detect_communities(graph: nx.DiGraph) -> tuple[dict[str, int], str, float]:
    """Partition entities into communities.

    Returns (entity -> community index, method name, modularity). Modularity is
    reported so the quality of the partition is a number rather than a claim.
    """
    if graph.number_of_nodes() == 0:
        return {}, "none (empty graph)", 0.0

    view = _undirected(graph)
    try:
        if view.number_of_nodes() <= _GREEDY_NODE_LIMIT:
            from networkx.algorithms.community import greedy_modularity_communities
            groups = greedy_modularity_communities(view, weight="value")
            method = "greedy modularity (Clauset-Newman-Moore)"
        else:
            from networkx.algorithms.community import asyn_lpa_communities
            groups = asyn_lpa_communities(view, weight="value", seed=42)
            method = "label propagation (graph too large for greedy modularity)"
        groups = [set(group) for group in groups]
    except Exception:
        # A partition is a nice-to-have; crashing the pipeline is not. Every
        # entity simply becomes its own community, and the method says so.
        groups = [{node} for node in view.nodes()]
        method = "none (community detection unavailable)"

    labels: dict[str, int] = {}
    for index, group in enumerate(sorted(groups, key=lambda g: (-len(g), min(g)))):
        for node in group:
            labels[node] = index

    try:
        from networkx.algorithms.community import modularity
        quality = float(modularity(view, groups, weight="value"))
    except Exception:
        quality = 0.0

    return labels, method, quality


# --------------------------------------------------------------------------
# Centrality and metrics
# --------------------------------------------------------------------------
def graph_metrics(
    graph: nx.DiGraph,
    labels: dict[str, int],
) -> pd.DataFrame:
    """Per-entity centrality and community position, as model features.

    Betweenness is SAMPLED (k sources) rather than exact. Exact betweenness is
    O(V*E) and would dominate the pipeline; sampling approximates it in
    O(k*E). We pass a fixed seed so the approximation is at least reproducible.
    """
    if graph.number_of_nodes() == 0:
        return pd.DataFrame(columns=[
            "entity_id", "pagerank", "betweenness", "community_id",
            "community_size", "net_flow_ratio",
        ])

    view = _undirected(graph)

    try:
        pagerank = nx.pagerank(graph, weight="value")
    except Exception:
        pagerank = {}

    samples = min(_BETWEENNESS_SAMPLES, view.number_of_nodes())
    try:
        betweenness = nx.betweenness_centrality(view, k=samples, seed=42, weight=None)
    except Exception:
        betweenness = {}

    community_sizes: dict[int, int] = {}
    for label in labels.values():
        community_sizes[label] = community_sizes.get(label, 0) + 1

    # Value direction: is this entity a net sink (receiving) or source (paying)?
    # Computed from the directed graph, independent of the undirected partition.
    value_out: dict[str, float] = {}
    value_in: dict[str, float] = {}
    for source, target, data in graph.edges(data=True):
        weight = float(data.get("value", 0.0))
        value_out[source] = value_out.get(source, 0.0) + weight
        value_in[target] = value_in.get(target, 0.0) + weight

    rows: list[dict[str, Any]] = []
    for node in graph.nodes():
        received = value_in.get(node, 0.0)
        sent = value_out.get(node, 0.0)
        total = received + sent
        label = int(labels.get(node, -1))
        rows.append({
            "entity_id": node,
            "pagerank": float(pagerank.get(node, 0.0)),
            "betweenness": float(betweenness.get(node, 0.0)),
            "community_id": label,
            # Label -1 means "no material flow, so no community". Reporting the
            # unassigned bucket's size here would give a wallet that is in no
            # community the same `community_size` as one in a 79-member
            # operation -- and that bucket is not an operation.
            "community_size": int(community_sizes.get(label, 0)) if label >= 0 else 0,
            "net_flow_ratio": float((received - sent) / total) if total > 0 else 0.0,
        })

    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------
def assign_roles(
    metrics: pd.DataFrame,
    corr: Any,
    sinks: dict[str, str] | None = None,
) -> pd.DataFrame:
    """Label each entity's function inside its community.

    These labels are for the analyst's narrative and the UI. They are NOT model
    features, deliberately: a rule-derived label handed to the model as a feature
    is how a rule quietly becomes the answer while still looking like ML.

    Precedence matters and is fixed: a service is a service even if it is also
    busy in one direction.
    """
    sinks = sinks or {}
    if metrics.empty:
        return pd.DataFrame(columns=["entity_id", "role", "role_reason"])

    lookup = corr.entities.set_index("entity_id")
    betweenness = metrics.set_index("entity_id")["betweenness"]
    threshold = (
        float(betweenness.quantile(_ROLE_BETWEENNESS_PERCENTILE))
        if len(betweenness) else 0.0
    )

    rows: list[dict[str, Any]] = []
    for entity_id in metrics["entity_id"]:
        if entity_id in sinks:
            kind = sinks[entity_id]
            role, reason = ("cash-out/exchange" if kind == "exchange" else "mixing service"), \
                           f"identified as a {kind}"
        elif entity_id not in lookup.index:
            role, reason = "wallet", "no flow activity observed"
        else:
            entity = lookup.loc[entity_id]
            fan_in = float(entity["fan_in"])
            fan_out = float(entity["fan_out"])
            received = float(entity["value_received"])
            sent = float(entity["value_sent"])

            if fan_in >= _ROLE_ASYMMETRY * max(fan_out, 1) and received >= sent:
                role = "collector"
                reason = f"{int(fan_in)} senders vs {int(fan_out)} recipients, net receiver"
            elif fan_out >= _ROLE_ASYMMETRY * max(fan_in, 1) and sent > received:
                role = "distributor"
                reason = f"{int(fan_out)} recipients vs {int(fan_in)} senders, net payer"
            elif betweenness.get(entity_id, 0.0) >= threshold and threshold > 0:
                role = "relay"
                reason = "high betweenness: funds pass through this wallet"
            else:
                role = "wallet"
                reason = "ordinary flow shape"

        rows.append({"entity_id": entity_id, "role": role, "role_reason": reason})

    return pd.DataFrame(rows)


def sink_entities(structural: pd.DataFrame) -> dict[str, str]:
    """Classify entities that should TERMINATE a fund trace.

    An exchange is where an investigation goes next (a warrant); a mixer is where
    the trail is deliberately broken. Both are endpoints of a trace, for
    different reasons.
    """
    if structural.empty:
        return {}
    sinks: dict[str, str] = {}
    for row in structural.itertuples(index=False):
        entity_id = getattr(row, "entity_id")
        if getattr(row, "mixer_score", 0.0) >= _SINK_MIXER_SCORE:
            sinks[entity_id] = "mixer"
        elif getattr(row, "exchange_score", 0.0) >= _SINK_EXCHANGE_SCORE:
            sinks[entity_id] = "exchange"
    return sinks


# --------------------------------------------------------------------------
# Fund tracing -- the new output type
# --------------------------------------------------------------------------
def trace_funds(
    flows: pd.DataFrame,
    seeds: Iterable[str],
    sinks: dict[str, str],
    *,
    max_hops: int = 4,
    min_amount: float = 0.0,
) -> list[FundTrace]:
    """Follow a seed's outgoing value to the sinks it reaches.

    Read the module docstring's ASSUMPTION section before quoting any number this
    returns. Short version: Bitcoin is fungible, so this is an allocation model.
    We allocate proportionally, shrink taint at every hop because change is
    excluded from `flows`, and expand each entity only once -- every choice in
    the conservative direction.
    """
    if flows.empty:
        return []

    # ---- adjacency and per-entity outflow totals ----
    grouped = (
        flows.groupby(["src", "dst"], sort=False)["value"].sum().reset_index()
    )
    adjacency: dict[str, list[tuple[str, float]]] = {}
    total_out: dict[str, float] = {}
    for source, target, value in grouped.itertuples(index=False):
        amount = float(value)
        adjacency.setdefault(source, []).append((target, amount))
        total_out[source] = total_out.get(source, 0.0) + amount

    results: list[FundTrace] = []
    for seed in seeds:
        tainted = total_out.get(seed, 0.0)
        if tainted <= 0:
            results.append(FundTrace(seed=seed, tainted=0.0, hops_reached=0, sinks=[]))
            continue

        parent: dict[str, str] = {}
        reached: set[str] = {seed}
        frontier = {seed: tainted}
        sink_hits: dict[str, dict[str, Any]] = {}
        hops_used = 0

        for hop in range(1, max_hops + 1):
            next_frontier: dict[str, float] = {}
            for node, amount in frontier.items():
                outflow = total_out.get(node, 0.0)
                if outflow <= 0:
                    continue
                for target, value in adjacency.get(node, ()):
                    share = amount * (value / outflow)
                    if share <= 0 or share < min_amount:
                        continue
                    next_frontier[target] = next_frontier.get(target, 0.0) + share
                    parent.setdefault(target, node)

            if not next_frontier:
                break
            hops_used = hop

            # A sink is recorded on arrival and never expanded through: an
            # exchange is where we stop, not a waypoint.
            #
            # `target != seed` matters. Taint can cycle back to where it started,
            # and recording that as "reached an exchange" would report the seed
            # as its own destination -- a one-element path labelled as two hops,
            # which is exactly the kind of line that reads as evidence.
            for target, amount in next_frontier.items():
                if target in sinks and target != seed and target not in sink_hits:
                    sink_hits[target] = {
                        "entity": target,
                        "kind": sinks[target],
                        "amount": round(amount, 8),
                        "hops": hop,
                        "path": _path_to(seed, target, parent),
                    }

            # Each entity expands ONCE, at the first hop it is reached.
            frontier = {node: amount for node, amount in next_frontier.items()
                        if node not in reached}
            reached.update(frontier)
            if not frontier:
                break

        results.append(FundTrace(
            seed=seed,
            tainted=tainted,
            hops_reached=hops_used,
            sinks=sorted(sink_hits.values(), key=lambda hit: -hit["amount"]),
        ))

    return results


def _path_to(seed: str, target: str, parent: dict[str, str]) -> list[str]:
    """Reconstruct the shortest arrival path, seed first."""
    path = [target]
    node = target
    while node != seed and node in parent:
        node = parent[node]
        path.append(node)
    path.reverse()
    return path


# --------------------------------------------------------------------------
# Convenience
# --------------------------------------------------------------------------
def analyse_graph(
    corr: Any,
    structural: pd.DataFrame,
    backbone_percentile: float = DEFAULT_BACKBONE_PERCENTILE,
) -> GraphIntelligence:
    """Run the whole graph layer: partition, metrics, roles, and a summary."""
    graph = build_flow_graph(corr.flows)

    # Modularity on the UNFILTERED graph as well, so the effect of the backbone
    # is a before/after number rather than an assertion that filtering helps.
    _, _, raw_quality = detect_communities(graph)

    backbone, cutoff = community_backbone(graph, backbone_percentile)
    labels, method, quality = detect_communities(backbone)

    # Centrality comes from the FULL graph, deliberately: every entity must get a
    # value, because a missing feature silently reads as zero and would look like
    # "no influence" rather than "not in the filtered backbone".
    metrics = graph_metrics(graph, labels)
    sinks = sink_entities(structural)
    roles = assign_roles(metrics, corr, sinks)

    if metrics.empty:
        communities = pd.DataFrame(columns=["community_id", "size", "members"])
    else:
        # Exclude the unassigned bucket (label -1). It is not a community, and
        # listing it would put "community -1, 79 members" at the top of the UI as
        # though 79 unrelated wallets were one operation.
        assigned = metrics[metrics["community_id"] >= 0]
        communities = (
            assigned.groupby("community_id", sort=True)["entity_id"]
            .agg(size="size", members=lambda values: sorted(values))
            .reset_index()
        )

    summary = {
        "nodes": int(graph.number_of_nodes()),
        "edges": int(graph.number_of_edges()),
        "communities": int(metrics["community_id"].nunique()) if not metrics.empty else 0,
        "modularity": round(quality, 4),
        "modularity_raw": round(raw_quality, 4),
        "backbone_percentile": backbone_percentile,
        "backbone_value_cutoff": round(cutoff, 8),
        "backbone_nodes": int(backbone.number_of_nodes()),
        "backbone_edges": int(backbone.number_of_edges()),
        "unassigned_entities": int((metrics["community_id"] < 0).sum()) if not metrics.empty else 0,
        "method": method,
        "sink_entities": len(sinks),
        "roles": roles["role"].value_counts().to_dict() if not roles.empty else {},
    }

    return GraphIntelligence(metrics=metrics, communities=communities, roles=roles, summary=summary)
