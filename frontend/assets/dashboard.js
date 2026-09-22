/* Dashboard: the whole picture, one batch at a time.
 *
 * WHY IT IS A REPLAY AND NOT A SNAPSHOT
 * -------------------------------------
 * Every figure on every other page is a statement about the whole capture. That
 * is the right summary but it hides the thing an investigation actually turns on:
 * ORDER. A wallet that only appears on day four says nothing about day two, and a
 * dashboard that always shows the finished picture quietly asserts that it does.
 *
 * So the day selector is not a filter over one payload -- it loads the payload
 * that was true at that point, and everything on screen, the rail and the graph
 * included, is a view of that batch.
 */

"use strict";

const state = {
  windows: [], index: 0, payload: null, selected: null,
  network: null, playing: null,
};

const CARD_TONE = { critical: "crit", high: "high", medium: "med" };

/* ---------------------------------------------------------------- helpers */

<<<<<<< HEAD
/** An amount for a narrow column: "0" for nothing, 2 decimals above 1 BTC,
 *  4 below. `btc()` rounds everything under 1 to four decimals, which prints
 *  zero as "0.0000" and claims precision that is not there. */
const amount = (value) => {
  const number = Number(value) || 0;
  if (number === 0) return "0";
  return btc(number);
};

const leadOf = (payload, id) => (payload.entities || []).find((item) => item.id === id) || null;
=======
const entityOf = (payload, id) => (payload.entities || []).find((item) => item.id === id) || null;
const leadOf = (payload, id) => entityOf(payload, id);
>>>>>>> 472b2bcf7d1dbd02016547b6dff2bf8a7f7f64e9

/** "2026-08-11" -> "08-11", and a merged batch "2026-08-14..2026-08-15" -> "08-14→15".
 *  A day chip has to be narrow enough that four of them fit beside the scrubber,
 *  and the merged label is long enough that the plain form pushed the row off the
 *  end of the bar. */
function shortDay(label) {
  const text = String(label || "").replace("window-", "");
  const [first, second] = text.split("..");
  const left = first.length >= 10 ? first.slice(5) : first;
  return second ? `${left}→${second.slice(8)}` : left;
}

function batchLabel(record, index, total) {
  const day = String(record.label || "").replace("window-", "") || record.label;
  return `Day ${index + 1} of ${total} · ${day}`;
}

/* -------------------------------------------------------------- the rail */

function renderRail(payload) {
  const leads = (payload.entities || [])
    .filter(isLead)
    .sort((a, b) => b.risk - a.risk || a.id.localeCompare(b.id));
  const byEntity = new Map((payload.alerts || []).map((alert) => [alert.entity, alert]));

  document.getElementById("leadCount").textContent = num(leads.length);
  document.getElementById("railList").innerHTML = leads.length
    ? leads.slice(0, 40).map((entity) => {
        const alert = byEntity.get(entity.id);
        const status = alert?.status && alert.status !== "new"
          ? `<span class="mono" style="color:var(--safe)">${esc(alert.status)}</span>` : "";
        return `<div class="alert ${CARD_TONE[entity.risk_band] || ""}"
          data-entity="${esc(entity.id)}" role="button" tabindex="0"
          aria-label="Lead ${esc(entity.id)}, priority ${esc(entity.risk)}">
          <div class="atop">
            <span class="sev ${CARD_TONE[entity.risk_band] || "med"}">${esc(entity.risk_band)}</span>
            <span class="aid">${esc(shortKey(entity.id))}</span>
          </div>
          <div class="atitle">${esc(entity.graph_role || entity.kind)}${
            entity.geo?.length ? ` · ${esc(entity.geo.slice(0, 3).join(" "))}` : ""}</div>
          <div class="adesc">${esc((entity.reasons?.[0]?.title) || "No rule-based signature")}</div>
          <div class="ameta">
            <span>${btc(entity.value_btc)} BTC</span>
            <span>${num(entity.tx_count)} tx</span>
            ${status}
            <span class="score">${esc(entity.risk)}</span>
          </div>
        </div>`;
      }).join("")
    : `<p style="font-size:13px;color:var(--ink-2)">
         No wallet group reached a review band in this batch.</p>`;

  document.querySelectorAll(".alert").forEach((node) => {
    node.onclick = () => select(node.dataset.entity);
    // Enter and Space, because a div with an onclick handler is invisible to a
    // keyboard and this rail is the dashboard's primary control.
    node.onkeydown = (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        select(node.dataset.entity);
      }
    };
  });
}

/* ------------------------------------------------------------- the graph */

function renderGraph(payload) {
  const tokens = themeTokens();
  const entities = payload.entities || [];
  const edges = payload.edges || [];
  const selected = state.selected;
  const traced = state.traced || new Set();

  const roleTone = {
    collector: tokens.crit, distributor: tokens.high, relay: tokens.med,
    "cash-out/exchange": tokens.safe, "mixing service": tokens.crit, wallet: tokens.ink3,
  };

  const visNodes = entities.map((entity) => {
    const isIp = entity.kind === "ip";
    let colour = bandColour(entity.risk_band);
    if (isIp) colour = tokens.accent;                        // network layer, always amber
    else if (entity.kind === "mixer") colour = tokens.crit;
    else if (entity.kind === "exchange") colour = tokens.safe;
    else if (entity.community_id === null) colour = tokens.ink3;
    const onPath = traced.has(entity.id);
    return {
      id: entity.id,
      // Labels are the largest source of clutter. Only what helps: the selected
      // node, the trail, and things big enough to be worth naming.
      label: (entity.id === selected?.id || onPath ||
              (!isIp && (entity.risk >= 85 || entity.kind !== "wallet")))
        ? shortKey(entity.label || entity.id) : undefined,
      shape: isIp ? "box" : "dot",
      size: isIp ? 9 : 6 + Math.min(24, entity.risk / 4.2),
      color: {
        background: colour,
        border: onPath ? tokens.brand : entity.id === selected?.id ? tokens.ink : colour,
        highlight: { background: colour, border: tokens.accent },
      },
      borderWidth: entity.id === selected?.id ? 4 : onPath ? 2.5 : 1,
      font: { color: tokens.ink2, size: 10, face: "Fira Code", strokeWidth: 0 },
      title: `${entity.id} · priority ${entity.risk} · ${entity.graph_role || entity.kind}`,
    };
  });

  const visEdges = edges.map((edge) => {
    const control = edge.kind === "control";
    return {
      from: edge.from, to: edge.to,
      dashes: control,
      arrows: control ? undefined : { to: { enabled: true, scaleFactor: 0.45 } },
      width: control ? 1 : 0.6 + Math.min(3.2, Math.log10((edge.value || 1) + 1)),
      // Full-strength edges over a dense graph become a solid mass that hides the
      // nodes. Opacity is the single biggest readability win.
      color: {
        color: control ? "rgba(217,119,6,0.30)" : "rgba(59,130,246,0.38)",
        highlight: tokens.ink, opacity: 1,
      },
    };
  });

  const data = { nodes: new vis.DataSet(visNodes), edges: new vis.DataSet(visEdges) };
  if (state.network) state.network.destroy();
  state.network = new vis.Network(document.getElementById("graph"), data, {
    nodes: { borderWidth: 1 },
    edges: { smooth: { type: "continuous" } },
    physics: {
      enabled: true,
      stabilization: { iterations: 160, fit: true },
      barnesHut: { gravitationalConstant: -5200, springLength: 95, springConstant: 0.04, damping: 0.6 },
    },
    interaction: { hover: true, tooltipDelay: 220, keyboard: false },
  });
  // Run physics briefly to settle the layout, then FREEZE it. A graph that keeps
  // drifting while you are talking about it is unusable.
  state.network.once("stabilizationIterationsDone", () => {
    state.network?.setOptions({ physics: false });
  });
  state.network.on("click", (params) => {
    if (params.nodes.length) select(params.nodes[0]);
  });

  const wallets = entities.filter((entity) => entity.kind !== "ip").length;
  document.getElementById("gtSub").textContent =
    `${num(wallets)} wallet groups · ${num(entities.length - wallets)} IP addresses · ` +
    `${num(edges.length)} links`;
  document.getElementById("graphEmpty").hidden = edges.length > 0;
  if (!edges.length) {
    document.getElementById("graphEmpty").innerHTML = emptyState(
      "No links in this batch",
      "The graph draws money movement and network control. Neither was observed here.");
  }
}

/* ---------------------------------------------------------- the evidence */

/* ==========================================================================
   THE NODE RECORD

   The graph answers "where is this, and what is it next to". The panel answers
   "what IS it" — for every node, not only the leads.

   Three kinds of node exist in the picture and they are not the same thing:

     wallet group, flagged   -- a scored lead with a decomposition and findings
     wallet group, cleared   -- scored, below the floor, no attribution recorded
     IP address              -- a network endpoint; it has no behaviour of its
                                own, and the panel says so rather than letting
                                its colour imply otherwise

   The connections block is what makes the picture legible: the same edges that
   are DRAWN are also LISTED, so a node's position is a fact you can read rather
   than a shape you have to infer by eye.
   ========================================================================== */

/** Everything the payload knows about a node's edges, grouped by what they mean. */
function connectionsFor(payload, id) {
  const byId = new Map((payload.entities || []).map((item) => [item.id, item]));
  const moneyOut = [], moneyIn = [], controlledFrom = [], controls = [];

  for (const edge of payload.edges || []) {
    if (edge.kind === "flow") {
      if (edge.from === id) moneyOut.push(edge);
      else if (edge.to === id) moneyIn.push(edge);
    } else if (edge.kind === "control") {
      if (edge.to === id) controlledFrom.push(edge);
      else if (edge.from === id) controls.push(edge);
    }
  }
  const byValue = (a, b) => (b.value || 0) - (a.value || 0) || (b.count || 0) - (a.count || 0);
  const byCount = (a, b) => (b.count || 0) - (a.count || 0);
  return {
    moneyOut: moneyOut.sort(byValue), moneyIn: moneyIn.sort(byValue),
    controlledFrom: controlledFrom.sort(byCount), controls: controls.sort(byCount),
    label: (key) => byId.get(key)?.label || key,
    totals: {
      out: moneyOut.reduce((sum, edge) => sum + (edge.value || 0), 0),
      in: moneyIn.reduce((sum, edge) => sum + (edge.value || 0), 0),
      controlObservations: controlledFrom.reduce((sum, edge) => sum + (edge.count || 0), 0),
    },
  };
}

/** One clickable row: the other end of an edge, and the weight of that edge. */
function connectionRow(id, caption, weight) {
  return `<button class="conn" data-goto="${esc(id)}" title="${esc(id)}">
    <span class="cid">${esc(shortKey(id))}</span>
    <span class="cmeta">${esc(caption)}</span>
    <span class="cval">${weight}</span>
  </button>`;
}

function connectionGroup(title, swatch, rows, moreHtml) {
  if (!rows.length) return "";
  return `<div class="conn-group">
    <h6><i class="sw" style="background:${swatch}"></i>${esc(title)}</h6>
    ${rows.join("")}${moreHtml || ""}
  </div>`;
}

function renderConnections(payload, entity) {
  const host = document.getElementById("evConnections");
  const section = document.getElementById("evConnectionsSec");
  const links = connectionsFor(payload, entity.id);
  const limit = 5;

  const out = links.moneyOut.slice(0, limit).map((edge) =>
    connectionRow(edge.to, `${num(edge.count)} transfer${edge.count === 1 ? "" : "s"}`,
                  `${amount(edge.value)} BTC`));
  const into = links.moneyIn.slice(0, limit).map((edge) =>
    connectionRow(edge.from, `${num(edge.count)} transfer${edge.count === 1 ? "" : "s"}`,
                  `${amount(edge.value)} BTC`));
  const from = links.controlledFrom.slice(0, limit).map((edge) =>
    connectionRow(edge.from, "controlled this group", `${num(edge.count)}×`));
  const to = links.controls.slice(0, limit).map((edge) =>
    connectionRow(edge.to, "controlled by this address", `${num(edge.count)}×`));

  const more = (total, shown, noun) => total > shown
    ? `<p class="small muted" style="margin:4px 0 0 8px">+ ${num(total - shown)} more ${noun}</p>`
    : "";

  const html =
    connectionGroup("Money out", "var(--brand-2)", out,
                    more(links.moneyOut.length, limit, "destinations")) +
    connectionGroup("Money in", "var(--brand-2)", into,
                    more(links.moneyIn.length, limit, "sources")) +
    connectionGroup("Controlled from", "var(--accent)", from,
                    more(links.controlledFrom.length, limit, "addresses")) +
    connectionGroup("Wallet groups it controlled", "var(--accent)", to,
                    more(links.controls.length, limit, "groups"));

  section.hidden = !html;
  host.innerHTML = html;
  if (html) {
    const totals = links.totals;
    // For an endpoint the observations are the ones IT made (edges it owns), not
    // the ones pointing at it: counting the wrong direction printed
    // "1 group · 0 observations" beside a row that plainly said "24×".
    const ipObservations = links.controls.reduce((sum, edge) => sum + (edge.count || 0), 0);
    const summary = entity.kind === "ip"
      ? `${num(links.controls.length)} group${links.controls.length === 1 ? "" : "s"} · ` +
        `${num(ipObservations)} observations`
      : `${amount(totals.out)} BTC out · ${amount(totals.in)} BTC in · ` +
        `${num(links.controlledFrom.length)} hosting ` +
        `address${links.controlledFrom.length === 1 ? "" : "es"}`;
    host.insertAdjacentHTML("beforeend", `<p class="conn-summary">${summary}</p>`);
  }

  // Rows navigate. Delegated, so re-rendering the panel never loses handlers.
  host.onclick = (event) => {
    const row = event.target.closest("[data-goto]");
    if (row) select(row.dataset.goto);
  };
}

/** A tiny inline-SVG trend.
 *
 * Drawn rather than charted: a Chart.js instance per selected node would mean a
 * canvas per click for a line of four points. This was deleted once by accident
 * while replacing the function next to it, which broke the whole panel for every
 * node -- a reminder that "replace the function below this one" is a move that
 * needs the surrounding text checked, not just the target.
 */
function sparkline(history, width, height) {
  if (history.length < 2) return "";
  const values = history.map((row) => Number(row.risk) || 0);
  const step = width / (values.length - 1);
  const tokens = themeTokens();
  const y = (value) => (height - (value / 100) * height).toFixed(1);
  return `<svg viewBox="0 0 ${width} ${height}" width="100%" height="${height}"
               preserveAspectRatio="none" style="display:block;margin-bottom:8px">
    <polyline points="${values.map((v, i) => `${(i * step).toFixed(1)},${y(v)}`).join(" ")}"
              fill="none" stroke="${tokens.brand}" stroke-width="2.5"
              stroke-linejoin="round" stroke-linecap="round"/>
    ${values.map((v, i) => `<circle cx="${(i * step).toFixed(1)}" cy="${y(v)}" r="3.5"
        fill="${tokens.surface}" stroke="${tokens.brand}" stroke-width="2.5"/>`).join("")}
  </svg>`;
}

function renderEvidence(payload) {
  const entity = state.selected;
  const sections = document.getElementById("evSections");
  const meter = document.getElementById("evMeter");
  const kicker = document.getElementById("evKicker");
  const identity = document.getElementById("evIdentity");
  const meta = document.getElementById("evMeta");
  const ack = document.getElementById("ackBtn");
  const footnote = document.getElementById("evFootnote");

  if (!entity) {
<<<<<<< HEAD
    // The empty state EXPLAINS THE PICTURE instead of sitting blank. This panel is
    // where a first-time viewer finds out what the graph is.
    kicker.textContent = "Nothing selected";
    identity.textContent = "The picture, explained";
    meta.innerHTML =
      "Each <b>circle</b> is one wallet group — a set of addresses proved to share " +
      "an owner — and its <b>size is its priority</b>. Each <b>square</b> is an IP " +
      "address. <b>Solid lines</b> are money moving between groups; <b>dashed " +
      "lines</b> are an address controlling a group. Click any node, or a lead on " +
      "the left, and its full record appears here.";
=======
    document.getElementById("evIdentity").textContent = "Nothing selected";
    document.getElementById("evMeta").textContent =
      "Click a node in the graph or a lead on the left to inspect its details.";
>>>>>>> 472b2bcf7d1dbd02016547b6dff2bf8a7f7f64e9
    document.getElementById("evKpi").innerHTML = "";
    meter.hidden = true;
    sections.innerHTML = "";
    document.getElementById("evConnectionsSec").hidden = true;
    document.getElementById("evConnections").innerHTML = "";
    document.getElementById("traceBanner").hidden = true;
    ack.disabled = true;
    ack.textContent = "Acknowledge";
    document.getElementById("evCase").href = "#";
    document.getElementById("evDetail").href = "anomalies.html";
    footnote.hidden = true;
    return;
  }
  footnote.hidden = false;

<<<<<<< HEAD
  const isIp = entity.kind === "ip";
  // Named differently from the shared helper on purpose: `const isLead = isLead(...)`
  // shadows the function and reads it inside its own initialiser, which is a
  // temporal-dead-zone ReferenceError rather than a shadowed call.
  const flagged = isLead(entity);
  const links = connectionsFor(payload, entity.id);
=======
  document.getElementById("evIdentity").textContent =
    `${shortKey(entity.id)} · ${entity.graph_role || entity.kind}`;
  document.getElementById("evMeta").textContent =
    `${entity.label || entity.kind || "entity"} — ${num(entity.tx_count || 0)} transactions, first seen ` +
    `${String(entity.first_seen || "").slice(0, 10)}`;
>>>>>>> 472b2bcf7d1dbd02016547b6dff2bf8a7f7f64e9

  // ---- who and what ------------------------------------------------------
  kicker.textContent = isIp ? "Network endpoint" : flagged ? "Lead" : "Scored group";
  identity.textContent = isIp ? entity.label : shortKey(entity.id);
  meta.textContent = isIp
    ? `IP address observed broadcasting transactions for ${num(links.controls.length)} ` +
      `wallet group(s). It has no behaviour of its own — the priority below is the ` +
      `PEAK priority of the groups it controlled.`
    : `${entity.label} — ${entity.role || entity.graph_role || "wallet group"}`;

  // ---- numbers -----------------------------------------------------------
  document.getElementById("evKpi").innerHTML = isIp
    ? `<div><span>Groups controlled</span><b>${num(links.controls.length)}</b></div>
       <div><span>Observations</span><b>${num(entity.tx_count)}</b></div>
       <div><span>Countries</span><b>${num((entity.geo || []).length)}</b></div>`
    : `<div><span>Value moved</span><b>${btc(entity.value_btc)}</b></div>
       <div><span>Group size</span><b>${num(entity.community_size)}</b></div>
       <div><span>Countries</span><b>${num(entity.country_count)}</b></div>`;

  // ---- priority ----------------------------------------------------------
  document.getElementById("evRisk").textContent = entity.risk;
  const band = document.getElementById("evBand");
  band.textContent = entity.risk_band;
  band.className = `sev ${CARD_TONE[entity.risk_band] || "med"}`;
  const note = document.getElementById("evRiskNote");
  if (isIp) {
    note.textContent = "inherited from the wallets";
  } else {
    const history = entity.history || [];
    const peak = history.reduce((best, row) => Math.max(best, row.risk || 0), entity.risk);
    note.textContent = history.length > 1 && peak > entity.risk
      ? `peak ${peak} earlier in the capture`
      : `${num((entity.confidence || 0) * 100, 0)}% of the maximum`;
  }
  meter.hidden = false;
  const fill = document.getElementById("evFill");
  fill.style.width = "0%";
  fill.style.background = bandColour(entity.risk_band);
  requestAnimationFrame(() => { fill.style.width = `${entity.risk}%`; });

  // ---- the edges, listed -------------------------------------------------
  renderConnections(payload, entity);

  // ---- what this node is, in facts ---------------------------------------
  const facts = [];
  if (isIp) {
    facts.push(["Address", `<span class="mono">${esc(entity.label)}</span>`]);
    facts.push(["Entity key", `<span class="mono">${esc(entity.id)}</span>`]);
    for (const fact of entity.facts || []) facts.push([fact.label, esc(fact.value)]);
    facts.push(["Countries seen", (entity.geo || []).map(esc).join(", ") || "—"]);
  } else {
    const addresses = entity.addresses || [];
    facts.push(["Group key", `<span class="mono">${esc(entity.id)}</span>`]);
    facts.push(["Role in the flow", esc(entity.graph_role || entity.role || "—")]);
    facts.push(["Addresses", `${num(addresses.length)} ` +
      `<span class="mono" style="font-size:10.5px;color:var(--ink-3)">` +
      `${addresses.slice(0, 2).map(esc).join(" ")}${addresses.length > 2 ? " …" : ""}</span>`]);
    facts.push(["Community",
      entity.community_id === null || entity.community_id === undefined
        ? "not in one"
        : `#${entity.community_id}, ${num(entity.community_size)} groups`]);
    facts.push(["Countries", (entity.geo || []).map(esc).join(", ") || "no country observed"]);
    facts.push(["Network operators", (entity.asn || []).map(esc).join(", ") || "—"]);
    facts.push(["First seen", esc(String(entity.first_seen || "—").slice(0, 16).replace("T", " "))]);
    facts.push(["Last seen", esc(String(entity.last_seen || "—").slice(0, 16).replace("T", " "))]);
    if (entity.anomaly_score !== undefined && entity.anomaly_score !== null) {
      facts.push(["Unusualness", `${num(entity.anomaly_score, 4)} ` +
        `<span class="small muted">unsupervised, not used to rank</span>`]);
    }
    if ((entity.typology || []).length) {
      facts.push(["Matched patterns", entity.typology.map(esc).join(", ")]);
    }
  }
  const factHtml = `<div class="ev-sec"><h5>What this node is</h5>
    ${facts.map(([key, value]) => `<div class="kv"><span class="k">${esc(key)}</span>
      <span class="v" style="text-align:right">${value}</span></div>`).join("")}</div>`;

<<<<<<< HEAD
  // ---- why it scored, its findings, its history ---------------------------
  const features = (entity.features || []).slice(0, 6);
  const listed = features.reduce((sum, item) => sum + item.importance, 0) * 100;
  const other = (entity.explanation?.other_contribution || 0) * 100;

  const whyHtml = features.length ? `<div class="ev-sec">
=======
  const nodeBits = [
    { label: "Type", value: entity.graph_role || entity.kind || "node" },
    { label: "Risk", value: `${entity.risk ?? 0} (${entity.risk_band || "low"})` },
    { label: "Transactions", value: num(entity.tx_count || 0) },
    { label: "Value moved", value: btc(entity.value_btc || 0) },
    { label: "Countries", value: entity.geo?.length ? entity.geo.join(", ") : "—" },
    { label: "ASN", value: entity.asn?.length ? entity.asn.join(", ") : "—" },
    { label: "Addresses", value: entity.addresses?.length ? entity.addresses.slice(0, 3).join(", ") : "—" },
  ];

  // 1. the factors, compact. The full waterfall is on the anomalies page; here
  //    the analyst needs the shape of the explanation, not the whole chart.
  const features = (entity.features || []).slice(0, 6);
  const listed = features.reduce((sum, item) => sum + item.importance, 0) * 100;
  const other = (entity.explanation?.other_contribution || 0) * 100;
  sections.innerHTML = `
    <div class="ev-sec">
      <h5>Node details</h5>
      ${nodeBits.map((item) => `
        <div class="kv">
          <span class="k">${esc(item.label)}</span>
          <span class="v">${esc(item.value)}</span>
        </div>
      `).join("")}
    </div>

    <div class="ev-sec">
>>>>>>> 472b2bcf7d1dbd02016547b6dff2bf8a7f7f64e9
      <h5>What pushed this score</h5>
      ${features.map((item) => `
        <div class="kv">
          <span class="k">${esc(plainFeature(item.name))}</span>
          <span class="v" style="color:${item.importance >= 0 ? "var(--crit)" : "var(--safe)"}">
            ${item.importance >= 0 ? "+" : "−"}${Math.abs(item.importance * 100).toFixed(1)}</span>
        </div>`).join("")}
      ${entity.explanation?.other_count
        ? `<div class="kv"><span class="k">${entity.explanation.other_count} smaller factors</span>
             <span class="v">${(other >= 0 ? "+" : "−") + Math.abs(other).toFixed(1)}</span></div>` : ""}
      <div class="reconcile" style="margin-top:10px;font-size:11.5px">
        <span>base <b>${(entity.explanation?.base * 100 || 0).toFixed(1)}</b></span>
        <span>+ ${features.length} named <b>${(listed >= 0 ? "+" : "") + listed.toFixed(1)}</b></span>
        ${entity.explanation?.other_count ? `<span>+ ${entity.explanation.other_count} smaller
          <b>${(other >= 0 ? "+" : "") + other.toFixed(1)}</b></span>` : ""}
        <span>= <b>${(entity.explanation?.prediction * 100 || 0).toFixed(1)}</b></span>
        <span class="ok">✓</span>
      </div>
      <a href="anomalies.html?entity=${encodeURIComponent(entity.id)}"
         style="font-size:12px;color:var(--brand);display:inline-block;margin-top:9px">
        See the full evidence and the money trail →</a>
    </div>`
    : isIp ? "" : `<div class="ev-sec"><h5>What pushed this score</h5>
        <p style="font-size:12.5px;color:var(--ink-2)">
          No attribution was recorded for this group in this batch — attributions are
          computed for groups that reached the review floor. It was scored, and its
          priority is above.</p></div>`;

  const reasons = entity.reasons || [];
  const findingsHtml = isIp ? "" : `
    <div class="ev-sec">
      <h5>Findings</h5>
      ${reasons.map((reason) => `
        <div class="reason">
          <div class="rc" style="background:${
            { critical: "var(--crit)", high: "var(--high)", medium: "var(--med)" }[reason.severity]
            || "var(--brand-2)"}">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"
                 stroke-linecap="round" stroke-linejoin="round"><path d="M12 8v5"/><path d="M12 17h.01"/></svg>
          </div>
          <div class="rx"><b>${esc(reason.title)}</b><span>${esc(reason.detail)}</span></div>
        </div>`).join("") || `<p style="font-size:12.5px;color:var(--ink-2)">
          No rule-based signature. What puts it where it is is the structural position
          above, and the connections listed before it.</p>`}
    </div>`;

  const history = entity.history || [];
  const historyHtml = history.length ? `
    <div class="ev-sec">
      <h5>Priority across batches</h5>
      ${sparkline(history, 348, 54)}
      ${history.map((row) => `
        <div class="kv"><span class="k mono">${esc(String(row.window).replace("window-", ""))}</span>
          <span class="v">${esc(row.risk)}
            <span style="color:${bandColour(row.band)}">●</span></span></div>`).join("")}
    </div>` : "";

  sections.innerHTML = factHtml + whyHtml + findingsHtml + historyHtml;

  // ---- actions -----------------------------------------------------------
  const alerts = (payload.alerts || []).find((item) => item.entity === entity.id);
  ack.disabled = isIp || !alerts || alerts.status !== "new";
  ack.textContent = alerts && alerts.status !== "new"
    ? `Acknowledged (${alerts.status})` : "Acknowledge";
  ack.onclick = () => acknowledge(entity, alerts);

  document.getElementById("evCase").href =
    `/report/${encodeURIComponent(entity.id)}?window=${payload.window?.id || ""}`;
  document.getElementById("evDetail").href =
    `anomalies.html?entity=${encodeURIComponent(entity.id)}`;

  // ---- the trail banner --------------------------------------------------
  const traces = (payload.traces || []).filter((trace) => trace.seed === entity.id);
  const banner = document.getElementById("traceBanner");
  if (traces.length) {
    const trace = traces[0];
    const top = (trace.sinks || [])[0];
    banner.hidden = false;
    document.getElementById("traceTitle").textContent =
      `${btc(trace.tainted)} BTC traced, ${trace.hops_reached} hops`;
    document.getElementById("traceSub").textContent =
      `${(trace.sinks || []).length} destinations — estimate, not an observation`;
    document.getElementById("tracePath").innerHTML =
      (top?.path || []).map((hop) => shortKey(hop)).join(" → ");
  } else {
    banner.hidden = true;
  }
}


async function acknowledge(entity, alert) {
  if (!alert) return;
  try {
    await api(`/alerts/${encodeURIComponent(entity.id)}/status`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status: "acknowledged" }),
    });
    toast("Recorded. The score is unchanged — this logs the decision, not an assessment.");
    await load(state.index);
  } catch (error) {
    toast(`Could not record that: ${error.message}`);
  }
}

/* ------------------------------------------------------------- selection */

function select(entityId) {
  const entity = entityOf(state.payload, entityId);
  if (!entity) return;
  state.selected = entity;
  state.traced = new Set();
  (state.payload.traces || [])
    .filter((trace) => trace.seed === entityId)
    .forEach((trace) => (trace.sinks || []).forEach((sink) =>
      (sink.path || []).forEach((id) => state.traced.add(id))));

  document.querySelectorAll(".alert").forEach((node) => {
    node.classList.toggle("sel", node.dataset.entity === entityId);
  });
  // A node's details are on the graph; its neighbourhood is what the graph is for.
  state.network?.selectNodes([entityId]);
  renderGraph(state.payload);
  renderEvidence(state.payload);

  const url = new URL(location.href);
  url.searchParams.set("entity", entityId);
  history.replaceState(null, "", url);
}

/* ------------------------------------------------------------ the replay */

async function load(windowId) {
  showLoading("Reading this batch",
    "The first look at a batch is built on request, then cached on this machine.");
  const payload = await loadPayload(windowId);
  hideLoading();
  state.payload = payload;
  state.index = Math.max(0, state.windows.findIndex((record) => record.id === payload.window.id));
  if (state.index < 0) state.index = 0;

  const scrubber = document.getElementById("scrubber");
  scrubber.value = String(state.index + 1);
  document.getElementById("tpLabel").textContent =
    batchLabel(payload.window, state.index, state.windows.length);
  document.querySelectorAll(".tp-day").forEach((node, index) => {
    node.classList.toggle("on", index === state.index);
  });

  // A lead selected in a previous batch may not exist in this one. Keeping the
  // selection would leave the evidence panel describing a wallet that this batch
  // says nothing about.
  const stillThere = state.selected && leadOf(payload, state.selected.id);
  state.selected = stillThere ? leadOf(payload, state.selected.id) : null;
  state.traced = new Set();

  renderRail(payload);
  renderGraph(payload);
  renderEvidence(payload);

  document.getElementById("tpHint").textContent =
    `${num(payload.meta.transactions)} transactions · ${num(payload.fleet?.open_alerts ?? 0)} open leads`;
  NETRA.setStrip({
    provenance: `engine ${payload.meta.engine_version} · batch ${payload.window.label} · offline · local`,
    generated: `generated ${String(payload.meta.generated_at).replace("T", " ").slice(0, 19)}`,
    state: `${num(payload.entities.filter(isLead).length)} leads in this batch`,
  });
}

function playToggle() {
  if (state.playing) {
    clearInterval(state.playing);
    state.playing = null;
    document.getElementById("playIcon").innerHTML = `<path d="M8 5v14l11-7z"/>`;
    return;
  }
  document.getElementById("playIcon").innerHTML =
    `<path d="M7 5h4v14H7z"/><path d="M13 5h4v14h-4z"/>`;
  state.playing = setInterval(async () => {
    const next = (state.index + 1) % state.windows.length;
    await load(state.windows[next].id);
    // Back to the start when the replay runs off the end, so the story loops
    // rather than stopping on the last frame with the button still lit.
    if (next === state.windows.length - 1) {
      clearInterval(state.playing);
      state.playing = null;
      document.getElementById("playIcon").innerHTML = `<path d="M8 5v14l11-7z"/>`;
    }
  }, 2400);
}

/* ------------------------------------------------------------------ boot */

(async function main() {
  await NETRA.init();
  state.windows = await NETRA.loadWindows();
  if (!state.windows.length) {
    document.getElementById("graphEmpty").innerHTML = emptyState(
      "No analysis in the store yet",
      "Ingest a dataset first; this page replays the batches it produces.");
    document.getElementById("graphEmpty").hidden = false;
    return;
  }

  const scrubber = document.getElementById("scrubber");
  scrubber.max = String(state.windows.length);
  scrubber.disabled = state.windows.length < 2;
  document.getElementById("scrubTicks").innerHTML =
    state.windows.map(() => "<i></i>").join("");
  document.getElementById("tpDays").innerHTML = state.windows.map((record, index) =>
    `<button class="tp-day" data-index="${index}" title="${esc(record.label)}">${
      esc(shortDay(record.label))}</button>`).join("");
  document.querySelectorAll(".tp-day").forEach((node) => {
    node.onclick = () => load(state.windows[Number(node.dataset.index)].id);
  });

  scrubber.oninput = () => {
    const index = Number(scrubber.value) - 1;
    document.getElementById("tpLabel").textContent =
      batchLabel(state.windows[index], index, state.windows.length);
  };
  scrubber.onchange = () => load(state.windows[Number(scrubber.value) - 1].id);
  document.getElementById("playBtn").onclick = playToggle;
  // Space is the convention for transport controls, and it is the one key an
  // operator reaches for without being told.
  document.addEventListener("keydown", (event) => {
    if (event.code === "Space" && !event.target.closest("input,textarea,button")) {
      event.preventDefault();
      playToggle();
    }
  });

  const requestedWindow = new URLSearchParams(location.search).get("window");
  const start = state.windows.find((record) => String(record.id) === requestedWindow);
  await load(start ? start.id : state.windows.at(-1).id);

  const requestedEntity = new URLSearchParams(location.search).get("entity");
  if (requestedEntity && leadOf(state.payload, requestedEntity)) select(requestedEntity);

  document.addEventListener("netra:theme", () => {
    renderGraph(state.payload);
    renderEvidence(state.payload);
  });
})();
