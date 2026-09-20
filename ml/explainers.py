"""
Plain-language explanations of what each anomaly type MEANS.

WHY THIS IS IN THE BACKEND AND NOT IN THE INTERFACE
---------------------------------------------------
When the tool reports "peel chain", the person reading it may never have seen a
Bitcoin transaction. The explanation that follows has to be the same sentence
everywhere it appears -- on the anomalies page, in the printable report, and in
the case dossier. Three hand-written copies of one explanation is three chances
to drift, and the one that drifts is the one quoted back at you.

So the wording lives here, once, and the interface and the report renderer both
read it from `/glossary`.

WHAT MAKES A GOOD EXPLANATION HERE
----------------------------------
Two constraints, and they pull against each other:

  * it must be readable by someone who does not know what a UTXO is, and
  * it must not be so vague that it stops being useful to an analyst.

The resolution is two lines: `plain` says what it IS, `why` says why it MATTERS.
The first is for the room; the second is for the file. Neither is allowed to be
a paragraph -- if it needs three sentences, the concept has not been understood
well enough to explain.

Each entry also names a `schematic`, so the same small diagram is drawn wherever
the explanation appears rather than being redrawn from memory each time.
"""

from __future__ import annotations

from typing import Any

# Order matters: it is the order they appear in the interface.
ANOMALY_EXPLAINERS: list[dict[str, Any]] = [
    {
        "type": "peel_chain",
        "label": "Peel chain",
        "plain": "Value moved through a series of wallets, each forwarding most of it onward "
                 "and keeping a little behind.",
        "why": "Splitting a large balance into small hops makes the original source hard to "
               "follow. It is layering, in plain sight.",
        "schematic": "chain",
    },
    {
        "type": "mixer",
        "label": "Mixing service",
        "plain": "Many people's coins pooled together so nobody can tell whose is whose.",
        "why": "It deliberately breaks the trail. An ordinary user has no reason to be one hop "
               "away from one.",
        "schematic": "pool",
    },
    {
        "type": "fan_in_collector",
        "label": "Fan-in collector",
        "plain": "Hundreds of different wallets paying one address.",
        "why": "The shape a ransomware collection makes: many victims, one destination.",
        "schematic": "fanin",
    },
    {
        "type": "cross_border",
        "label": "Cross-border control",
        "plain": "The same wallet operated from more than one country.",
        "why": "Not suspicious on its own — legitimate services span regions too. It matters "
               "alongside another signal, never instead of one.",
        "schematic": "globe",
    },
    {
        "type": "exchange_like",
        "label": "Exchange or payment processor",
        "plain": "High volume in both directions, with a balanced set of counterparties.",
        "why": "The shape of a lawful service — and the natural place for money to cash out, "
               "which is where an investigation goes next.",
        "schematic": "balanced",
    },
    {
        "type": "ordinary",
        "label": "Ordinary activity",
        "plain": "No structural pattern detected.",
        "why": "Most of any real capture looks like this. It is the honest denominator for "
               "every claim about what was found.",
        "schematic": "plain",
    },
]

# Fast lookup for a single type, built once.
_BY_TYPE = {entry["type"]: entry for entry in ANOMALY_EXPLAINERS}


def explainer_for(anomaly_type: str) -> dict[str, Any] | None:
    """The explanation for one type, or None if it is not a known one."""
    return _BY_TYPE.get(anomaly_type)


def glossary() -> dict[str, Any]:
    """Everything the interface needs to explain its own vocabulary."""
    return {
        "anomalies": ANOMALY_EXPLAINERS,
        "priority_bands": [
            {"band": "critical", "means": "Investigate first"},
            {"band": "high", "means": "Look at in this session"},
            {"band": "medium", "means": "Worth knowing about"},
            {"band": "low", "means": "No action suggested"},
        ],
        "note": (
            "Scores rank groups for review. They are not findings of guilt, and no "
            "figure here establishes one."
        ),
    }
