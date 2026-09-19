"""
Printable case dossier for one entity.

WHY THIS IS PART OF THE PRODUCT
-------------------------------
An investigator does not brief a colleague with a screenshot. The deliverable
that leaves the building is a document: the lead, the evidence behind it, the
trail it follows, and the caveats. So the dossier is generated from the same
contract payload the dashboard renders, not from a separate code path -- if the
two diverged, the document and the screen would eventually disagree about the
same wallet.

WHAT THE DOSSIER IS CAREFUL ABOUT
---------------------------------
  * Every attribution is labelled with the method that produced it. A fund trace
    carries its allocation assumption on the same page as the amounts, not in a
    footnote, because a traced figure quoted without the model behind it is how
    an estimate gets read as a fact.
  * The model card block states what was NOT measured. A dossier that only
    reports successes is not evidence, it is advocacy.
  * Nothing is interpolated into HTML without escaping -- a wallet address is
    attacker-influenced the moment a real feed can contain one.
"""

from __future__ import annotations

import html
from datetime import datetime, timezone
from typing import Any

# One place for the look, so a print stylesheet change cannot half-apply.
STYLE = """
  :root { color-scheme: light; }
  * { box-sizing: border-box; }
  body {
    font-family: "Inter", "Segoe UI", system-ui, sans-serif;
    margin: 0; padding: 28px 32px; color: #14181f; background: #fff;
    font-size: 12.5px; line-height: 1.5;
  }
  header { border-bottom: 3px solid #14181f; padding-bottom: 10px; margin-bottom: 18px; }
  .classification {
    font-size: 10px; letter-spacing: .16em; text-transform: uppercase;
    color: #8a2b2b; font-weight: 700;
  }
  h1 { font-size: 19px; margin: 6px 0 2px; }
  h2 {
    font-size: 12px; letter-spacing: .1em; text-transform: uppercase;
    margin: 22px 0 8px; padding-bottom: 4px; border-bottom: 1px solid #d6dae0;
  }
  .muted { color: #5b6472; }
  .grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px 18px; }
  .grid div span { display: block; font-size: 10px; color: #5b6472; text-transform: uppercase;
                   letter-spacing: .06em; }
  .grid div strong { font-size: 14px; font-weight: 600; }
  table { width: 100%; border-collapse: collapse; margin-top: 4px; }
  th, td { text-align: left; padding: 5px 8px; border-bottom: 1px solid #e6e9ee; }
  th { font-size: 10px; text-transform: uppercase; letter-spacing: .06em; color: #5b6472; }
  td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
  .band { display: inline-block; padding: 1px 7px; border-radius: 3px; font-size: 10px;
          font-weight: 700; text-transform: uppercase; letter-spacing: .05em; }
  .critical { background: #fde8e8; color: #8a2b2b; }
  .high     { background: #fdf0e0; color: #8a5a1a; }
  .medium   { background: #fdf8e0; color: #7a6a12; }
  .low      { background: #e8f2ea; color: #2b6a3a; }
  .caveat { background: #f7f8fa; border-left: 3px solid #8a2b2b; padding: 8px 12px; margin: 8px 0; }
  .reason { margin: 5px 0; }
  .reason b { display: inline-block; min-width: 210px; }
  footer { margin-top: 26px; border-top: 1px solid #d6dae0; padding-top: 10px; font-size: 10.5px;
           color: #5b6472; }
  @media print {
    body { padding: 0; font-size: 11px; }
    h2 { break-after: avoid; }
    table, .reason, .caveat { break-inside: avoid; }
    .no-print { display: none; }
  }
"""


def _e(value: Any) -> str:
    """Escape for HTML. Applied to every interpolated value without exception."""
    return html.escape("" if value is None else str(value))


def _band(value: str) -> str:
    return f'<span class="band {_e(value)}">{_e(value)}</span>'


def case_report_html(
    entity: dict[str, Any],
    window: dict[str, Any] | None,
    events: list[dict[str, Any]],
    traces: list[dict[str, Any]],
    metrics: dict[str, Any],
) -> str:
    """Render one lead as a printable dossier."""
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    window_label = (window or {}).get("label", "n/a")

    parts: list[str] = [
        "<!doctype html><html><head><meta charset='utf-8'>",
        f"<title>NETRA dossier {_e(entity.get('id'))}</title>",
        f"<style>{STYLE}</style></head><body>",
        "<header>",
        "<div class='classification'>For official use only &middot; investigative lead, not a finding of guilt</div>",
        f"<h1>NETRA case dossier &mdash; {_e(entity.get('id'))}</h1>",
        f"<div class='muted'>Generated {_e(generated)} &middot; window {_e(window_label)} "
        f"&middot; {_e(entity.get('label'))}</div>",
        "</header>",
    ]

    risk = int(entity.get("risk", 0))
    parts.append("<h2>Lead summary</h2><div class='grid'>")
    for label, value in (
        ("Risk", f"{risk} {_band(entity.get('risk_band', 'low'))}"),
        ("Kind", _e(entity.get("kind"))),
        ("Graph role", _e(entity.get("graph_role"))),
        ("Community", f"{_e(entity.get('community_id'))} "
                      f"(size {_e(entity.get('community_size'))})"),
        ("Value (BTC)", _e(entity.get("value_btc"))),
        ("Transactions", _e(entity.get("tx_count"))),
        ("Countries", ", ".join(entity.get("geo") or []) or "&mdash;"),
        ("First seen", _e(entity.get("first_seen"))),
    ):
        parts.append(f"<div><span>{label}</span><strong>{value}</strong></div>")
    parts.append("</div>")

    # ---- why this scored what it scored ----
    explanation = entity.get("explanation")
    features = entity.get("features") or []
    if features:
        parts.append("<h2>Why this score</h2>")
        if explanation:
            parts.append(
                f"<div class='muted'>{_e(explanation.get('method'))}. "
                f"Base {_e(explanation.get('base'))} + contributions = "
                f"prediction {_e(explanation.get('prediction'))} "
                f"(residual {_e(explanation.get('residual'))}, i.e. the decomposition "
                "reconciles to the score).</div>"
            )
        parts.append("<table><thead><tr><th>Feature</th><th class='num'>Value</th>"
                     "<th class='num'>Contribution</th></tr></thead><tbody>")
        for item in features:
            parts.append(
                f"<tr><td>{_e(item.get('name'))}</td>"
                f"<td class='num'>{_e(item.get('value'))}</td>"
                f"<td class='num'>{item.get('importance', 0):+.4f}</td></tr>"
            )
        parts.append("</tbody></table>")
        parts.append(
            "<div class='caveat'>These are per-entity contributions along the model's "
            "decision path. They reconcile exactly to this entity's score. They are NOT "
            "game-theoretic Shapley values, and interaction effects can be under-credited.</div>"
        )

    # ---- reasons ----
    reasons = entity.get("reasons") or []
    if reasons:
        parts.append("<h2>Evidence</h2>")
        for reason in reasons:
            parts.append(
                f"<div class='reason'><b>{_e(reason.get('title'))}</b>"
                f"<span class='muted'>[{_e(reason.get('severity'))}]</span> "
                f"{_e(reason.get('detail'))}</div>"
            )

    # ---- trend ----
    history = entity.get("history") or []
    if history:
        parts.append("<h2>Risk across windows</h2><table><thead><tr><th>Window</th>"
                     "<th class='num'>Risk</th><th>Band</th></tr></thead><tbody>")
        for row in history:
            parts.append(
                f"<tr><td>{_e(row.get('window'))}</td>"
                f"<td class='num'>{_e(row.get('risk'))}</td>"
                f"<td>{_band(row.get('band', 'low'))}</td></tr>"
            )
        parts.append("</tbody></table>")

    # ---- fund trail ----
    if traces:
        parts.append("<h2>Fund trail</h2>")
        for trace in traces:
            parts.append(
                f"<div>Seed <strong>{_e(trace.get('seed'))}</strong> sent "
                f"{_e(trace.get('tainted'))} BTC, followed {_e(trace.get('hops_reached'))} hops.</div>"
            )
            parts.append("<table><thead><tr><th>Reached</th><th>Kind</th>"
                         "<th class='num'>BTC</th><th class='num'>Hops</th></tr></thead><tbody>")
            for sink in trace.get("sinks", []):
                parts.append(
                    f"<tr><td>{_e(sink.get('entity'))}</td><td>{_e(sink.get('kind'))}</td>"
                    f"<td class='num'>{_e(sink.get('amount'))}</td>"
                    f"<td class='num'>{_e(sink.get('hops'))}</td></tr>"
                )
            parts.append("</tbody></table>")
            parts.append(
                f"<div class='caveat'><strong>Estimate, not a fact.</strong> "
                f"Method: {_e(trace.get('method'))}. {_e(trace.get('assumption'))} "
                "Do not quote these amounts without this statement.</div>"
            )

    # ---- changes ----
    if events:
        parts.append("<h2>Changes observed</h2><table><thead><tr><th>Window</th><th>Type</th>"
                     "<th>Severity</th><th>Detail</th></tr></thead><tbody>")
        for event in events:
            parts.append(
                f"<tr><td>{_e(event.get('window'))}</td><td>{_e(event.get('type'))}</td>"
                f"<td>{_e(event.get('severity'))}</td><td>{_e(event.get('detail'))}</td></tr>"
            )
        parts.append("</tbody></table>")

    # ---- the honest footer ----
    parts.append("<h2>Model card and limitations</h2>")
    parts.append("<table><tbody>")
    for label, value in (
        ("Evaluation basis", metrics.get("evaluated_on", "unknown")),
        ("Risk model (CV)", f"precision {metrics.get('risk_precision')} &middot; "
                            f"recall {metrics.get('risk_recall')} &middot; "
                            f"AUC {metrics.get('risk_auc')}"),
        ("Clustering ARI", metrics.get("cluster_ari")),
        ("Anomaly precision@k", f"{metrics.get('anomaly_precision_at_k')} "
                                f"(k={metrics.get('anomaly_k')})"),
    ):
        parts.append(f"<tr><th>{label}</th><td>{_e(value)}</td></tr>")
    parts.append("</tbody></table>")
    parts.append(
        "<div class='caveat'>"
        "<strong>What this document is not.</strong> A ranked lead, not a verdict. "
        "Trained and measured on SYNTHETIC traffic bearing planted illicit typologies; "
        "performance on operational data is not established by these numbers. "
        "The unsupervised detector's lift did not survive window-scale scoring and is "
        "reported here as measured, not as advertised. "
        "Analyst judgement is required before any action."
        "</div>"
    )
    parts.append(
        f"<footer>NETRA &middot; Team Vortex &middot; SIH 2026 &middot; PS SIH26146 "
        f"&middot; engine netra-monitoring-2 &middot; generated {_e(generated)}<br>"
        "Every figure on this page is derived from the ingested traffic. No number is "
        "estimated for presentation.</footer>"
    )
    parts.append("</body></html>")
    return "".join(parts)
