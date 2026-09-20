"""
The printable reports: the artefacts that leave the building.

WHY THESE ARE SERVER-RENDERED
-----------------------------
A screenshot is not a deliverable. An investigator briefs a colleague with a
document, and every number in it has to be traceable to the same payload the
screen renders -- so these are generated from the contract payload, not from a
second code path. If the two diverged, the document and the screen would
eventually disagree about the same wallet, and the document is the one that gets
quoted back.

WHY THE STYLESHEET IS IN HERE
-----------------------------
The on-screen interface links its theme from `/assets/theme.css`. These reports
deliberately do NOT: a printed document that depends on a network request for its
appearance is a document that can arrive unstyled, and the report is the copy
that has to survive being emailed as a file. The palette below is the same one the
interface uses -- light always, because a dark theme burns toner and photocopies
to mud -- and the reasoning is repeated here so the next person knows it was a
decision rather than an oversight.

Each report opens in the browser and uses the browser's own print-to-PDF. That
means real vector text and vector charts, no PDF library, and nothing to install
on a host that cannot reach a package registry.

WHAT EVERY REPORT IS CAREFUL ABOUT
----------------------------------
  * Every attribution names the method that produced it. A fund trail carries its
    allocation assumption beside the amounts, never in a footnote, because a
    traced figure quoted without the model behind it is how an estimate gets read
    as a fact.
  * The limitations section states what was NOT measured. A report that only
    reports successes is not evidence, it is advocacy.
  * Nothing is interpolated into HTML without escaping -- a wallet address is
    attacker-influenced the moment a real feed can contain one.
"""

from __future__ import annotations

import html
from datetime import datetime, timezone
from typing import Any

ENGINE_VERSION = "netra-monitoring-2"

# The interface's tokens, pinned here. See the module docstring for why this is a
# copy rather than a link.
PRINT_STYLE = """
  :root {
    --ink: #0F1E3D; --ink-2: #3F4A5F; --ink-3: #6B7688;
    --brand: #1E40AF; --brand-2: #3B82F6; --accent: #D97706;
    --safe: #0E9F6E; --med: #C77700; --high: #DD6B20; --crit: #DC2626;
    --line: #C9D3E2; --line-2: #E3E9F2; --wash: #F4F6FA;
  }
  @page { size: A4 portrait; margin: 13mm 11mm; }
  * { box-sizing: border-box; }
  html, body { background: #fff; }
  body {
    margin: 0; padding: 0; color: var(--ink);
    font-family: "Fira Sans", "Segoe UI", system-ui, sans-serif;
    font-size: 10.5pt; line-height: 1.5;
  }
  .sheet { max-width: 188mm; margin: 0 auto; padding: 14px 6px 40px; }

  /* ---- masthead ---- */
  .mast { display: flex; align-items: baseline; gap: 12px; border-bottom: 2.5px solid var(--ink);
          padding-bottom: 7px; margin-bottom: 14px; }
  .mast b { font-size: 17pt; letter-spacing: .06em; }
  .mast span { font-family: "Fira Code", monospace; font-size: 8.5pt; color: var(--ink-3); }
  .mast .right { margin-left: auto; text-align: right; }
  .classify { font-size: 8pt; letter-spacing: .14em; text-transform: uppercase; font-weight: 700;
              color: #8A2B2B; margin-bottom: 6px; }

  h1 { font-size: 15pt; margin: 4px 0 3px; letter-spacing: -.01em; }
  h2 { font-size: 9pt; letter-spacing: .11em; text-transform: uppercase; color: var(--ink-3);
       margin: 20px 0 9px; padding-bottom: 4px; border-bottom: 1px solid var(--line); }
  h3 { font-size: 10.5pt; margin: 0 0 3px; }
  p { margin: 0 0 8px; }
  .muted { color: var(--ink-2); }
  .small { font-size: 8.5pt; color: var(--ink-3); }
  .mono { font-family: "Fira Code", monospace; }
  .lede { font-size: 15pt; font-weight: 700; line-height: 1.28; letter-spacing: -.015em;
          max-width: 150mm; margin: 0 0 8px; }

  /* ---- figures ---- */
  .figs { display: grid; grid-template-columns: repeat(4, 1fr); gap: 9px; margin: 12px 0 4px; }
  .fig { border: 1px solid var(--line-2); border-left: 3px solid var(--brand);
         border-radius: 6px; padding: 9px 10px; break-inside: avoid; }
  .fig.a { border-left-color: var(--accent); }
  .fig.s { border-left-color: var(--safe); }
  .fig.c { border-left-color: var(--crit); }
  .fig .k { font-size: 7.5pt; color: var(--ink-3); text-transform: uppercase; letter-spacing: .05em; }
  .fig .v { font-family: "Fira Code", monospace; font-size: 17pt; font-weight: 700; line-height: 1.15; }
  .fig .d { font-size: 7.5pt; color: var(--ink-2); }

  table { width: 100%; border-collapse: collapse; margin-top: 4px; }
  th, td { text-align: left; padding: 4px 7px; border-bottom: 1px solid var(--line-2);
           vertical-align: top; }
  th { font-size: 7.5pt; text-transform: uppercase; letter-spacing: .06em; color: var(--ink-3);
       border-bottom: 1px solid var(--line); }
  td.num, th.num { text-align: right; font-family: "Fira Code", monospace; }
  /* An entity key is one token. Allowed to wrap, "E-031925182" breaks after the
     dash and the table's most important column reads as two lines of noise. */
  td.mono, th.mono { font-family: "Fira Code", monospace; white-space: nowrap; }
  tbody tr { break-inside: avoid; }

  .band { display: inline-block; padding: 1px 6px; border-radius: 4px; font-size: 7.5pt;
          font-weight: 700; text-transform: uppercase; letter-spacing: .04em; }
  .critical { background: #FDE8E8; color: #8A2B2B; }
  .high     { background: #FDF0E0; color: #8A5A1A; }
  .medium   { background: #FDF6E0; color: #7A6A12; }
  .low      { background: #E8F2EA; color: #2B6A3A; }

  /* ---- charts, drawn as CSS and inline SVG so they are vector on paper ---- */
  .chart { border: 1px solid var(--line-2); border-radius: 6px; padding: 11px 13px 9px;
           break-inside: avoid; margin-bottom: 10px; }
  .chart .ct { font-size: 9pt; font-weight: 700; margin-bottom: 2px; }
  .chart .cs { font-size: 8pt; color: var(--ink-3); margin-bottom: 10px; }
  .bars { display: flex; align-items: flex-end; gap: 8px; height: 34mm; }
  .bars .col { flex: 1; display: flex; flex-direction: column; justify-content: flex-end;
               align-items: center; height: 100%; }
  .bars .col i { display: block; width: 100%; background: var(--brand); border-radius: 3px 3px 0 0; }
  .bars .col i.peak { background: var(--accent); }
  .bars .col b { font-family: "Fira Code", monospace; font-size: 7pt; margin-bottom: 3px; }
  .bars .col span { font-size: 7.5pt; color: var(--ink-3); margin-top: 4px;
                    font-family: "Fira Code", monospace; }
  .hbars { display: flex; flex-direction: column; gap: 7px; }
  .hbars .row { display: flex; align-items: center; gap: 9px; }
  .hbars .row .lb { width: 40mm; font-size: 8.5pt; }
  .hbars .row .tr { flex: 1; height: 7px; background: var(--wash); border-radius: 99px;
                    overflow: hidden; }
  .hbars .row .tr i { display: block; height: 100%; border-radius: 99px; }
  .hbars .row .vl { width: 20mm; text-align: right; font-family: "Fira Code", monospace;
                    font-size: 8pt; }
  .dotgrid { display: flex; flex-wrap: wrap; gap: 2.2px; margin: 4px 0 8px; }
  .dotgrid i { width: 4.2mm; height: 4.2mm; border-radius: 1px; background: #C8D0DC; display: block; }
  .dotgrid i.high { background: var(--high); } .dotgrid i.medium { background: var(--med); }
  .dotgrid i.critical { background: var(--crit); }
  .waterfall { display: flex; flex-direction: column; gap: 6px; margin: 8px 0; }
  .wf { display: grid; grid-template-columns: 52mm 1fr 14mm; align-items: center; gap: 7px; }
  .wf .n { font-size: 8pt; }
  .wf .t { position: relative; height: 7px; background: var(--wash); border-radius: 99px; }
  .wf .t::after { content: ''; position: absolute; left: 50%; top: -2px; bottom: -2px;
                  width: 1px; background: var(--line); }
  .wf .t i { position: absolute; top: 0; bottom: 0; }
  .wf .t i.pos { left: 50%; background: var(--crit); border-radius: 0 99px 99px 0; }
  .wf .t i.neg { right: 50%; background: var(--safe); border-radius: 99px 0 0 99px; }
  .wf .v { font-family: "Fira Code", monospace; font-size: 8pt; text-align: right; }
  .chainpath { font-family: "Fira Code", monospace; font-size: 8.5pt; line-height: 2; }
  .chainpath span.hop { border: 1px solid var(--line); border-radius: 5px; padding: 2px 6px; }
  .chainpath span.hop.end { border-color: var(--safe); color: var(--safe); font-weight: 700; }
  .chainpath span.hop.mix { border-color: var(--crit); color: var(--crit); font-weight: 700; }

  .caveat { background: var(--wash); border-left: 3px solid var(--crit); padding: 8px 11px;
            margin: 8px 0; break-inside: avoid; font-size: 8.5pt; }
  .note { background: var(--wash); border-left: 3px solid var(--accent); padding: 8px 11px;
          margin: 8px 0; break-inside: avoid; font-size: 8.5pt; }
  .reconcile { font-family: "Fira Code", monospace; font-size: 8pt; background: var(--wash);
               border: 1px dashed var(--line); border-radius: 5px; padding: 7px 10px;
               margin-top: 6px; }
  .explainer { border: 1px solid var(--line-2); border-radius: 6px; padding: 9px 11px;
               break-inside: avoid; margin-bottom: 8px; }
  .explainer h3 { font-size: 9.5pt; }
  .explainer .why { font-size: 8pt; color: var(--ink-3); margin-top: 4px;
                    border-top: 1px dashed var(--line-2); padding-top: 4px; }
  footer { margin-top: 18px; border-top: 1px solid var(--line); padding-top: 7px;
           font-size: 7.5pt; color: var(--ink-3); font-family: "Fira Code", monospace; }
  .pgbreak { break-before: page; }

  /* ---- the toolbar, which is not part of the document ---- */
  .toolbar { position: sticky; top: 0; z-index: 5; display: flex; align-items: center; gap: 10px;
             background: #0F1E3D; color: #fff; padding: 9px 14px; margin: 0 -6px 16px; }
  .toolbar b { font-size: 10pt; letter-spacing: .04em; }
  .toolbar span { font-size: 8.5pt; color: #A9B8D4; }
  .toolbar .sp { margin-left: auto; }
  .toolbar button, .toolbar a { font: inherit; font-size: 9pt; cursor: pointer;
    background: rgba(255,255,255,.12); color: #fff; border: 1px solid rgba(255,255,255,.28);
    border-radius: 7px; padding: 7px 13px; text-decoration: none; }
  .toolbar button:hover, .toolbar a:hover { background: rgba(255,255,255,.22); }
  @media print { .toolbar { display: none !important; } .sheet { padding: 0; max-width: none; } }
"""


def _e(value: Any) -> str:
    """Escape for HTML. Applied to every interpolated value without exception."""
    return html.escape("" if value is None else str(value))


def _num(value: Any, digits: int = 0) -> str:
    if value is None:
        return "&mdash;"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return _e(value)
    return f"{number:,.{digits}f}"


def _band(value: str) -> str:
    key = value if value in ("critical", "high", "medium", "low") else "low"
    return f'<span class="band {key}">{_e(key)}</span>'


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _masthead(title: str, subtitle: str, classification: str | None = None) -> str:
    parts = ["<div class='mast'>",
             "<div><b>NETRA</b><br><span>Team Vortex &middot; SIH 2026 &middot; PS SIH26146</span></div>",
             f"<div class='right'><span>{_e(subtitle)}</span></div>",
             "</div>"]
    if classification:
        parts.append(f"<div class='classify'>{_e(classification)}</div>")
    parts.append(f"<h1>{_e(title)}</h1>")
    return "".join(parts)


def _shell(title: str, subtitle: str, body: list[str], *, classification: str | None = None,
           report: str = "", generated: str | None = None) -> str:
    """One A4 document: masthead, body, honest footer, and a toolbar for printing."""
    stamp = generated or _now()
    head = (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        f"<title>NETRA — {_e(title)}</title>"
        f"<style>{PRINT_STYLE}</style></head><body>"
    )
    toolbar = (
        "<div class='toolbar'>"
        f"<b>{_e(report or 'Report')}</b>"
        f"<span>{_e(stamp)}</span>"
        "<span class='sp'></span>"
        "<button onclick='window.print()'>Save as PDF / Print</button>"
        "<a href='javascript:history.back()'>&larr; Back</a>"
        "</div>"
    )
    footer = (
        f"<footer>NETRA &middot; Team Vortex &middot; SIH 2026 &middot; PS SIH26146 &middot; "
        f"engine {ENGINE_VERSION} &middot; generated {_e(stamp)}<br>"
        "Every figure in this document is derived from the ingested traffic. Nothing is "
        "estimated for presentation, and every estimate is labelled where it appears."
        "</footer>"
    )
    return (head + toolbar + "<div class='sheet'>" + _masthead(title, subtitle, classification)
            + "".join(body) + footer + "</div></body></html>")


def _limitations() -> str:
    return (
        "<h2>Model card and limitations</h2>"
        "<table><tbody>"
        "<tr><th>Evaluation basis</th><td>Synthetic traffic bearing planted illicit "
        "typologies. Performance on operational data is NOT established by these numbers.</td></tr>"
        "<tr><th>Explanation method</th><td>Exact decision-path contributions (Saabas), not "
        "Shapley values. The contributions reconcile exactly to each score; interaction "
        "effects can be under-credited.</td></tr>"
        "<tr><th>Unsupervised detector</th><td>Reported as measured. Its lift did not survive "
        "window-scale scoring, so it is not used to rank leads.</td></tr>"
        "<tr><th>Fund trails</th><td>Proportional allocation, not observation. Bitcoin is "
        "fungible: once value is mixed, no method can say which coin went where.</td></tr>"
        "<tr><th>What this document is</th><td>A ranked, explainable investigative lead. Not a "
        "finding of guilt. Analyst judgement is required before any action.</td></tr>"
        "</tbody></table>"
    )


PLAIN_FEATURE = {
    "address_count": "Wallets in the group", "tx_count": "Transactions involved in",
    "tx_sent": "Transactions it sent", "tx_received": "Transactions it received",
    "log_value_btc": "Total value moved", "value_per_tx": "Average value per transaction",
    "fan_in": "Wallets that paid it", "fan_out": "Wallets it paid",
    "in_out_ratio": "Imbalance between paying and receiving",
    "distinct_counterparties": "Different wallets it dealt with",
    "ip_count": "Different IP addresses seen", "country_count": "Countries it was controlled from",
    "asn_count": "Different network operators", "active_days": "Days it was active",
    "burst_score": "How machine-like its timing is",
    "change_ratio": "Value sent straight back to itself", "peel_score": "Peel-chain signature",
    "output_uniformity": "How equal its payments are", "mixer_score": "Mixing-service behaviour",
    "mixer_interaction": "Touches a mixing service", "collector_score": "Many pay in, few go out",
    "exchange_score": "Behaves like an exchange", "round_amount_ratio": "Round-number payments",
    "mean_payment_btc": "Average payment size", "pagerank": "Centrality in the money flow",
    "betweenness": "How often money passes through it", "community_size": "Size of its group",
    "net_flow_ratio": "Whether it takes in more than it pays out",
}


# --------------------------------------------------------------------------
# Shared chart primitives, drawn as CSS and inline SVG
# --------------------------------------------------------------------------
def _bar_chart(caption: str, subtitle: str, labels: list[str], values: list[float],
               peak_index: int | None = None, unit: str = "") -> str:
    top = max(values) if values else 1
    top = top or 1
    columns = "".join(
        "<div class='col'>"
        f"<b>{_num(value, 0)}</b>"
        f"<i class='{'peak' if index == peak_index else ''}' "
        f"style='height:{max(2.0, (value / top) * 88):.1f}%'></i>"
        f"<span>{_e(label)}</span></div>"
        for index, (label, value) in enumerate(zip(labels, values))
    )
    return (
        f"<div class='chart'><div class='ct'>{_e(caption)}</div>"
        f"<div class='cs'>{_e(subtitle)}</div><div class='bars'>{columns}</div></div>"
    )


def _area_chart(caption: str, subtitle: str, labels: list[str], values: list[float],
                unit: str = "BTC") -> str:
    top = max(values) if values else 1
    top = top or 1
    # The drawing area is inset from the viewBox, so the first and last x labels
    # are centred INSIDE the frame instead of hanging off its edge: "08-11" at
    # x=0 lost its first two characters and rendered as "11", which reads as a
    # missing day rather than as a layout problem.
    width, height, pad = 720.0, 150.0, 34.0
    step = (width - pad * 2) / max(len(values) - 1, 1)
    points = [(pad + index * step, height - (value / top) * (height - 18))
              for index, value in enumerate(values)]
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    area = f"{pad:.1f},{height} " + line + f" {width - pad:.1f},{height}"
    dots = "".join(
        f"<circle cx='{x:.1f}' cy='{y:.1f}' r='4' fill='#FFFFFF' stroke='#D97706' stroke-width='2.5'/>"
        for x, y in points
    )
    axis = "".join(
        f"<text x='{x:.1f}' y='{height + 14:.1f}' font-size='11' fill='#6B7688' "
        f"text-anchor='middle' font-family=\"Fira Code, monospace\">{_e(label)}</text>"
        for (x, _), label in zip(points, labels)
    )
    return (
        f"<div class='chart'><div class='ct'>{_e(caption)}</div>"
        f"<div class='cs'>{_e(subtitle)} &middot; peak {_num(max(values), 1)} {_e(unit)}</div>"
        # No fixed height and no `preserveAspectRatio='none'`: the SVG scales from
        # its own viewBox, so the labels keep their proportions instead of being
        # stretched sideways by a chart box that does not match the coordinate
        # space.
        f"<svg viewBox='0 0 {width:.0f} {height + 22:.0f}' width='100%' "
        f"style='display:block'>"
        f"<polygon points='{area}' fill='rgba(217,119,6,0.16)'/>"
        f"<polyline points='{line}' fill='none' stroke='#D97706' stroke-width='3'/>"
        f"{dots}{axis}</svg></div>"
    )


def _paired_bars(caption: str, subtitle: str, rows: list[tuple[str, float, float]]) -> str:
    body = ""
    for label, count_share, value_share in rows:
        body += (
            f"<div class='row'><div class='lb'>{_e(label)}</div>"
            f"<div class='tr' title='share of transactions'><i style='width:"
            f"{max(0.6, count_share * 100):.2f}%;background:#1E40AF'></i></div>"
            f"<div class='vl'>{count_share * 100:.1f}%</div></div>"
            f"<div class='row'><div class='lb small'>of the money</div>"
            f"<div class='tr'><i style='width:{max(0.6, value_share * 100):.2f}%;"
            f"background:#D97706'></i></div>"
            f"<div class='vl'>{value_share * 100:.1f}%</div></div>"
        )
    return (f"<div class='chart'><div class='ct'>{_e(caption)}</div>"
            f"<div class='cs'>{_e(subtitle)}</div><div class='hbars'>{body}</div></div>")


def _geo_bars(caption: str, countries: list[dict[str, Any]]) -> str:
    if not countries:
        return ""
    peak = max((row.get("share") or 0) for row in countries) or 1
    body = ""
    for row in countries:
        total = (row.get("share") or 0) / peak
        flagged = (row.get("flagged") or 0) / row["entities"] * total if row.get("entities") else 0
        fill = ("linear-gradient(90deg,#D97706 0 {f:.2f}%,#1E40AF {f:.2f}% 100%)".format(f=flagged * 100)
                if flagged else "#1E40AF")
        body += (
            f"<div class='row'><div class='lb mono'>{_e(row.get('code'))}</div>"
            f"<div class='tr'><i style='width:{max(0.8, total * 100):.2f}%;background:{fill}'></i></div>"
            f"<div class='vl'>{_num(row.get('entities'))} groups, {_num(row.get('flagged'))} flagged</div>"
            "</div>"
        )
    return (f"<div class='chart'><div class='ct'>{_e(caption)}</div>"
            "<div class='cs'>The amber part of each bar is the share raised for review."
            "</div><div class='hbars'>" + body + "</div></div>")


def _dotgrid(entities: list[dict[str, Any]]) -> str:
    groups = [entity for entity in entities if entity.get("kind") != "ip"]
    flagged = [entity for entity in groups if entity.get("risk_band") != "low"]
    squares = "".join(
        f"<i class='{_e(entity.get('risk_band'))}'></i>" for entity in groups
    )
    return (
        "<div class='chart'><div class='ct'>Every wallet group examined</div>"
        f"<div class='cs'>One square per wallet group &mdash; {_num(len(groups))} in total, "
        f"{_num(len(flagged))} raised for review. The flagged groups carry "
        "the stated share of the value moved.</div>"
        f"<div class='dotgrid'>{squares}</div></div>"
    )


def _waterfall(entity: dict[str, Any]) -> str:
    """The same decomposition the interface draws, as vector bars."""
    explanation = entity.get("explanation")
    features = entity.get("features") or []
    if not explanation or not features:
        return ""
    other = float(explanation.get("other_contribution") or 0)
    ceiling = max([abs(float(item.get("importance") or 0)) for item in features] + [abs(other), 1e-9])

    rows = ""
    for item in features:
        contribution = float(item.get("importance") or 0)
        side = min(50.0, abs(contribution) / ceiling * 50.0)
        rows += (
            f"<div class='wf'><div class='n'>{_e(PLAIN_FEATURE.get(item.get('name'), item.get('name')))}</div>"
            f"<div class='t'><i class='{'pos' if contribution >= 0 else 'neg'}' "
            f"style='width:{side:.2f}%'></i></div>"
            f"<div class='v'>{('+' if contribution >= 0 else '−')}"
            f"{abs(contribution * 100):.1f}</div></div>"
        )
    if explanation.get("other_count"):
        side = min(50.0, abs(other) / ceiling * 50.0)
        rows += (
            f"<div class='wf'><div class='n'>{int(explanation['other_count'])} smaller factors</div>"
            f"<div class='t'><i class='{'pos' if other >= 0 else 'neg'}' "
            f"style='width:{side:.2f}%'></i></div>"
            f"<div class='v'>{('+' if other >= 0 else '−')}{abs(other * 100):.1f}</div></div>"
        )

    base = float(explanation.get("base") or 0) * 100
    prediction = float(explanation.get("prediction") or 0) * 100
    listed = sum(float(item.get("importance") or 0) for item in features) * 100
    reconcile = (
        f"base {base:.1f} + {len(features)} named factors "
        f"{('+' if listed >= 0 else '−')}{abs(listed):.1f}"
        + (f" + {int(explanation['other_count'])} smaller factors "
           f"{('+' if other >= 0 else '−')}{abs(other * 100):.1f}"
           if explanation.get("other_count") else "")
        + f" = {prediction:.1f} points &middot; reconciles exactly "
          f"(residual {float(explanation.get('residual') or 0):.2e})"
    )
    return (
        "<div class='chart'><div class='ct'>What pushed this score</div>"
        f"<div class='cs'>{_e(explanation.get('method'))} &middot; right argues for, "
        "left argues against. Contributions are in score points.</div>"
        f"<div class='waterfall'>{rows}</div>"
        f"<div class='reconcile'>{reconcile}</div></div>"
    )


def _chain(trace: dict[str, Any]) -> str:
    sinks = (trace.get("sinks") or [])[:6]
    if not sinks:
        return ""
    blocks = ""
    for sink in sinks:
        path = sink.get("path") or []
        hops = ""
        for index, hop in enumerate(path):
            cls = "hop"
            if index == len(path) - 1:
                cls += " mix" if sink.get("kind") == "mixer" else " end"
            hops += f"<span class='{cls}'>{_e(hop)}</span>"
            if index < len(path) - 1:
                hops += " &rarr; "
        blocks += (
            f"<div style='margin-bottom:6px'><span class='mono small'>"
            f"{_e(sink.get('kind', 'destination')).upper()}</span> &middot; "
            f"{_num(sink.get('amount'), 4)} BTC over {_num(sink.get('hops'))} hops<br>"
            f"<span class='chainpath'>{hops}</span></div>"
        )
    return (
        "<div class='chart'><div class='ct'>Money trail</div>"
        f"<div class='cs'>Seed {_e(trace.get('seed'))} sent {_num(trace.get('tainted'), 4)} BTC, "
        f"followed {_num(trace.get('hops_reached'))} hops to "
        f"{_num(len(trace.get('sinks') or []))} destinations.</div>"
        f"{blocks}"
        "<div class='caveat'><b>Estimate, not an observation.</b> "
        f"Method: {_e(trace.get('method'))}. {_e(trace.get('assumption'))} "
        "Do not quote these amounts without this statement.</div></div>"
    )


# --------------------------------------------------------------------------
# 1 · The dataset report
# --------------------------------------------------------------------------
def dataset_report_html(payload: dict[str, Any]) -> str:
    corpus = payload.get("corpus") or {}
    behaviour = payload.get("behaviour") or {}
    meta = payload.get("meta") or {}
    coverage = corpus.get("coverage") or {}
    daily = corpus.get("daily") or []
    hourly = corpus.get("hourly") or []
    peak_hour = (corpus.get("peak") or {}).get("hour")

    body: list[str] = []
    if corpus.get("summary"):
        body.append(f"<div class='lede'>{_e(corpus['summary'])}</div>")
    for note in corpus.get("notes") or []:
        body.append(f"<div class='note'>{_e(note)}</div>")
    body.append(
        f"<p class='muted small'>Analysis of <b>everything read</b> &mdash; "
        f"{_num(meta.get('records') or corpus.get('records'))} records from "
        f"{_e(meta.get('source_file') or 'the ingested dataset')}, "
        f"{_e(str(corpus.get('span_start') or '')[:10])} to {_e(str(corpus.get('span_end') or '')[:10])}. "
        "The flagged groups are shown throughout as a share of that whole, so a small "
        "finding cannot be mistaken for a large one.</p>"
    )

    body.append(
        "<div class='figs'>"
        f"<div class='fig'><div class='k'>Transactions</div><div class='v'>{_num(corpus.get('transactions'))}</div>"
        f"<div class='d'>{_num(corpus.get('span_hours'), 0)} hours of capture</div></div>"
        f"<div class='fig a'><div class='k'>Value moved</div>"
        f"<div class='v'>{_num(corpus.get('total_value_btc'), 0)}<span class='small'> BTC</span></div>"
        f"<div class='d'>median transaction {_num(corpus.get('median_value_btc'), 3)} BTC</div></div>"
        f"<div class='fig'><div class='k'>Wallet groups</div><div class='v'>{_num(corpus.get('entities'))}</div>"
        f"<div class='d'>{_num(corpus.get('addresses'))} addresses</div></div>"
        f"<div class='fig c'><div class='k'>Raised for review</div>"
        f"<div class='v'>{_num(coverage.get('entities_flagged'))}</div>"
        f"<div class='d'>{_num((coverage.get('flagged_share') or 0) * 100, 1)}% of groups &middot; "
        f"{_num((behaviour.get('value_share_of_flagged') or 0) * 100, 0)}% of value moved</div></div>"
        "</div>"
    )

    body.append("<div class='pgbreak'></div><h2>What the days look like</h2>")
    if daily:
        body.append(_bar_chart(
            "Transactions per day", "How many", [str(row.get("day"))[5:] for row in daily],
            [row.get("transactions") or 0 for row in daily]))
        body.append(_area_chart(
            "Value moved per day", "How much", [str(row.get("day"))[5:] for row in daily],
            [row.get("value_btc") or 0 for row in daily]))
    if hourly:
        body.append(_bar_chart(
            "Activity by hour of day",
            f"Every hour, summed across the capture. Busiest at {int(peak_hour or 0):02d}:00.",
            [f"{row.get('hour'):02d}" for row in hourly],
            [row.get("transactions") or 0 for row in hourly],
            peak_index=next((index for index, row in enumerate(hourly)
                             if row.get("hour") == peak_hour), None)))

    body.append("<div class='pgbreak'></div><h2>Where the value sits</h2>")
    sizes = [row for row in (corpus.get("size_classes") or []) if (row.get("transactions") or 0) > 0]
    if sizes:
        body.append(_paired_bars(
            "Small transactions, large value",
            "Most transactions are small. Most value is not.",
            [(str(row.get("label", "")).split(" (")[0],
              row.get("share_of_transactions") or 0, row.get("share_of_value") or 0)
             for row in sizes]))
    body.append(_dotgrid(payload.get("entities") or []))
    body.append(_geo_bars("Where the groups were controlled from",
                          (corpus.get("countries") or [])[:8]))

    body.append("<h2>How the groups behave</h2>")
    rows = "".join(
        "<tr>"
        f"<td>{_e(row.get('label'))}</td>"
        f"<td class='num'>{_num(row.get('entities'))}</td>"
        f"<td class='num'>{_num((row.get('share') or 0) * 100, 1)}%</td>"
        f"<td>{_e(row.get('explanation'))}</td>"
        "</tr>"
        for row in (behaviour.get("classes") or [])
    )
    body.append(
        "<table><thead><tr><th>Behaviour</th><th class='num'>Groups</th>"
        "<th class='num'>Share</th><th>What that means</th></tr></thead><tbody>"
        f"{rows}</tbody></table>"
        "<p class='small'>Every group counted exactly once, under the first behaviour it "
        "matches. A group can show several, so counting them separately would sum past 100% "
        "and mislead.</p>"
    )

    body.append(_limitations())
    return _shell(
        "Whole-capture dataset report",
        f"batch {_e((payload.get('window') or {}).get('label'))} · {_e(meta.get('engine_version'))}",
        body, report="NETRA — dataset report",
        generated=str(meta.get("generated_at", "")).replace("T", " ")[:19] + " UTC")


# --------------------------------------------------------------------------
# 2 · The anomalies report
# --------------------------------------------------------------------------
def anomalies_report_html(payload: dict[str, Any], explainers: list[dict[str, Any]]) -> str:
    meta = payload.get("meta") or {}
    entities = [entity for entity in (payload.get("entities") or []) if entity.get("lead")]
    entities.sort(key=lambda entity: (-int(entity.get("risk") or 0), str(entity.get("id"))))
    drift = (payload.get("fleet") or {}).get("drift") or {}
    traces = {trace.get("seed"): trace for trace in (payload.get("traces") or [])}

    body: list[str] = [
        f"<p class='muted small'>Every wallet group in the capture was scored. "
        f"{_num(len(entities))} of them reached a review band. They are listed most serious "
        "first, and the highest-priority lead is decomposed in full. A score ranks a group for "
        "review; it is not a finding of guilt.</p>"
    ]

    if drift.get("drifted_count"):
        body.append(
            "<div class='note'><b>This data is outside what the model was trained on.</b> "
            f"{_e(drift.get('verdict'))} The scores below are still the model's output, but its "
            "measured accuracy does not transfer to a distribution it has not seen, so treat the "
            "ranking as a starting point for review rather than a calibrated probability.</div>"
        )

    body.append("<h2>Leads</h2>")
    rows = "".join(
        "<tr>"
        f"<td class='num'>{index + 1}</td>"
        f"<td class='mono'>{_e(entity.get('id'))}</td>"
        f"<td class='num'>{_num(entity.get('risk'))}</td>"
        f"<td>{_band(entity.get('risk_band'))}</td>"
        f"<td>{_e(entity.get('graph_role') or entity.get('kind'))}</td>"
        f"<td class='num'>{_num(entity.get('value_btc'), 2)}</td>"
        f"<td class='num'>{_num(entity.get('tx_count'))}</td>"
        f"<td>{_e(', '.join(entity.get('geo') or []) or '—')}</td>"
        f"<td>{_e((entity.get('reasons') or [{}])[0].get('title', '—'))}</td>"
        "</tr>"
        for index, entity in enumerate(entities[:40])
    )
    body.append(
        "<table><thead><tr><th class='num'>#</th><th>Group</th><th class='num'>Priority</th>"
        "<th>Band</th><th>Role</th><th class='num'>BTC</th><th class='num'>Tx</th>"
        "<th>Countries</th><th>Strongest finding</th></tr></thead><tbody>"
        f"{rows}</tbody></table>"
    )
    if len(entities) > 40:
        body.append(f"<p class='small'>{_num(len(entities) - 40)} further leads are in the "
                    "machine-readable payload.</p>")

    if entities:
        top = entities[0]
        body.append("<div class='pgbreak'></div>")
        body.append(f"<h2>Lead 1 in full &mdash; {_e(top.get('id'))}</h2>")
        body.append(
            "<div class='figs'>"
            f"<div class='fig'><div class='k'>Priority</div><div class='v'>{_num(top.get('risk'))}</div>"
            f"<div class='d'>{_band(top.get('risk_band'))}</div></div>"
            f"<div class='fig a'><div class='k'>Value moved</div>"
            f"<div class='v'>{_num(top.get('value_btc'), 2)}</div><div class='d'>BTC</div></div>"
            f"<div class='fig'><div class='k'>Transactions</div><div class='v'>{_num(top.get('tx_count'))}</div>"
            f"<div class='d'>{_num(len(top.get('addresses') or []))} addresses</div></div>"
            f"<div class='fig {'c' if (top.get('country_count') or 0) >= 2 else 's'}'>"
            f"<div class='k'>Controlled from</div><div class='v'>{_num(top.get('country_count'))}</div>"
            f"<div class='d'>{_e(', '.join(top.get('geo') or []) or 'no country observed')}</div></div>"
            "</div>"
        )
        body.append(_waterfall(top))

        reasons = top.get("reasons") or []
        if reasons:
            body.append("<div class='chart'><div class='ct'>Findings</div>"
                        "<div class='cs'>Including anything that argues against suspicion.</div>"
                        "<table><tbody>"
                        + "".join(
                            f"<tr><th>{_e(reason.get('title'))} "
                            f"<span class='small'>[{_e(reason.get('severity'))}]</span></th>"
                            f"<td>{_e(reason.get('detail'))}</td></tr>"
                            for reason in reasons)
                        + "</tbody></table></div>")
        if traces.get(top.get("id")):
            body.append(_chain(traces[top["id"]]))

    body.append("<div class='pgbreak'></div><h2>In plain words</h2>")
    body.append(
        "<p class='muted small'>The vocabulary this tool uses, in the same sentences the "
        "interface shows. The first line says what a pattern IS; the second says why it "
        "MATTERS.</p>"
    )
    for item in explainers:
        body.append(
            "<div class='explainer'>"
            f"<h3>{_e(item.get('label'))}</h3>"
            f"<p>{_e(item.get('plain'))}</p>"
            f"<p class='why'>{_e(item.get('why'))}</p></div>"
        )
    body.append(_limitations())

    return _shell(
        "Anomaly and lead report",
        f"batch {_e((payload.get('window') or {}).get('label'))} · {_num(len(entities))} leads",
        body, classification="For official use only · investigative leads, not findings of guilt",
        report="NETRA — anomaly report",
        generated=str(meta.get("generated_at", "")).replace("T", " ")[:19] + " UTC")


# --------------------------------------------------------------------------
# 3 · The case dossier
# --------------------------------------------------------------------------
def case_report_html(entity: dict[str, Any], window: dict[str, Any] | None,
                     events: list[dict[str, Any]], traces: list[dict[str, Any]],
                     metrics: dict[str, Any]) -> str:
    body: list[str] = []
    window_label = (window or {}).get("label", "n/a")
    body.append("<div class='figs'>"
                f"<div class='fig'><div class='k'>Priority</div>"
                f"<div class='v'>{_num(entity.get('risk'))}</div>"
                f"<div class='d'>{_band(entity.get('risk_band', 'low'))}</div></div>"
                f"<div class='fig'><div class='k'>Kind</div>"
                f"<div class='v' style='font-size:12pt'>{_e(entity.get('kind'))}</div>"
                f"<div class='d'>{_e(entity.get('graph_role'))}</div></div>"
                f"<div class='fig'><div class='k'>Value moved</div>"
                f"<div class='v'>{_num(entity.get('value_btc'), 2)}</div><div class='d'>BTC</div></div>"
                f"<div class='fig'><div class='k'>Transactions</div>"
                f"<div class='v'>{_num(entity.get('tx_count'))}</div>"
                f"<div class='d'>{_num(len(entity.get('addresses') or []))} addresses</div></div>"
                "</div>")
    body.append(
        "<table><tbody>"
        f"<tr><th>Group</th><td class='mono'>{_e(entity.get('label'))}</td></tr>"
        f"<tr><th>Community</th><td>{_e(entity.get('community_id'))} "
        f"(size {_num(entity.get('community_size'))})</td></tr>"
        f"<tr><th>Countries</th><td>{_e(', '.join(entity.get('geo') or []) or '—')}</td></tr>"
        f"<tr><th>Network operators</th><td>{_e(', '.join(entity.get('asn') or []) or '—')}</td></tr>"
        f"<tr><th>First seen</th><td>{_e(entity.get('first_seen'))}</td></tr>"
        f"<tr><th>Last seen</th><td>{_e(entity.get('last_seen'))}</td></tr>"
        f"<tr><th>Batch</th><td>{_e(window_label)}</td></tr>"
        "</tbody></table>"
    )
    body.append(_waterfall(entity))

    reasons = entity.get("reasons") or []
    if reasons:
        body.append("<h2>Findings</h2><table><tbody>" + "".join(
            f"<tr><th>{_e(reason.get('title'))} "
            f"<span class='small'>[{_e(reason.get('severity'))}]</span></th>"
            f"<td>{_e(reason.get('detail'))}</td></tr>" for reason in reasons)
            + "</tbody></table>")

    history = entity.get("history") or []
    if history:
        body.append("<h2>Risk across batches</h2><table><thead><tr><th>Batch</th>"
                    "<th class='num'>Priority</th><th>Band</th></tr></thead><tbody>"
                    + "".join(f"<tr><td class='mono'>{_e(row.get('window'))}</td>"
                              f"<td class='num'>{_num(row.get('risk'))}</td>"
                              f"<td>{_band(row.get('band', 'low'))}</td></tr>" for row in history)
                    + "</tbody></table>")

    for trace in traces:
        body.append(_chain(trace))

    if events:
        body.append("<h2>Changes observed</h2><table><thead><tr><th>Batch</th><th>Type</th>"
                    "<th>Severity</th><th>Detail</th></tr></thead><tbody>"
                    + "".join(f"<tr><td class='mono'>{_e(event.get('window'))}</td>"
                              f"<td>{_e(event.get('type'))}</td>"
                              f"<td>{_e(event.get('severity'))}</td>"
                              f"<td>{_e(event.get('detail'))}</td></tr>" for event in events)
                    + "</tbody></table>")

    body.append("<h2>Measured scorecard</h2><table><tbody>")
    for label, value in (
        ("Evaluation basis", metrics.get("evaluated_on", "unknown")),
        ("Risk model (cross-validated)",
         f"precision {metrics.get('risk_precision')} &middot; recall {metrics.get('risk_recall')} "
         f"&middot; AUC {metrics.get('risk_auc')}"),
        ("Clustering agreement", metrics.get("cluster_ari")),
        ("Unsupervised detector",
         f"precision@k {metrics.get('anomaly_precision_at_k')} (k={metrics.get('anomaly_k')})"),
    ):
        body.append(f"<tr><th>{_e(label)}</th><td>{_e(value)}</td></tr>")
    body.append("</tbody></table>")
    body.append(_limitations())

    return _shell(
        f"Case dossier — {_e(entity.get('id'))}",
        f"{_e(entity.get('label'))} · batch {_e(window_label)}",
        body,
        classification="For official use only · investigative lead, not a finding of guilt",
        report="NETRA — case dossier",
    )
