/* NETRA console.
 *
 * One rule shapes this file: ANALYSIS LIVES IN THE BACKEND; PRESENTATION LIVES
 * HERE. Nothing in this file decides whether a wallet is suspicious. It fetches
 * a payload, translates it into something a person can read, and draws it. If a
 * number is not in the payload it is not on the screen -- there are no invented
 * statistics, because in an investigative tool a number is evidence.
 *
 * The second rule is that this console is for EVERYONE in the room, not only for
 * the engineer. Every technical term is either replaced with a plain phrase or
 * carries a plain explanation in GLOSSARY, surfaced by Explain mode. A tool that
 * can only be read by the person who built it has not been delivered.
 */

"use strict";

/* ------------------------------------------------------------------ state */
const S = {
  windows: [],
  index: 0,          // index into S.windows
  payload: null,
  alerts: [],
  selected: null,
  mode: "risk",
  explain: false,
  playing: false,
  playTimer: null,
  historyChart: null,
  network: null,
  currentDoc: null,
};

const $ = (id) => document.getElementById(id);

/* --------------------------------------------------------------- glossary
 * The plain-language layer. Each entry is a sentence a non-specialist can act
 * on. If a term appears in the UI without an entry here, it is jargon that
 * leaked, and that is a bug in this file rather than a gap in the glossary.
 */
const GLOSSARY = {
  risk: ["Priority score", "0 to 100. It is the model's estimate of how likely this wallet group is to be part of a laundering operation. It ranks groups; it is not a verdict."],
  band: ["Priority band", "The score grouped into four levels — critical, high, medium, low — so a long list can be triaged at a glance."],
  wallet_group: ["Wallet group", "Several Bitcoin addresses we have proved belong to one owner, because they were spent together in one transaction. You must sign for every address you spend, so spending them together means one person controls them."],
  ip_node: ["IP address", "A network endpoint that broadcast this wallet's transactions. It is shown as a node because an investigator needs to know where a wallet was controlled from, not only what it moved."],
  control_edge: ["Controlled from", "A dashed link meaning this IP address sent transactions for that wallet. This is the join between the network records and the blockchain records."],
  flow_edge: ["Money moved", "A solid link meaning value moved from one wallet group to another. Change returning to the sender is excluded, because a payment that comes straight back is not a payment."],
  contribution: ["Contribution", "How much one fact about this wallet pushed its score up or down. These add up exactly to the score, so the explanation always reconciles with the number on screen."],
  base: ["Starting point", "The score before looking at any single fact — the average across the training data. Contributions move it from here to the final number."],
  residual: ["Left over", "The gap between the contributions and the final score. It should be zero. We print it so you can check rather than trust."],
  anomaly: ["Unusualness", "From a model that never saw any labelled example. It flags what looks statistically odd, which is the honest answer to 'what if criminals do something we never planted?'."],
  modularity: ["How clearly groups separate", "0 means no discernible grouping, 1 means very clear. Measured on the large transfers only — small payments are close to random and drown the pattern."],
  ari: ["Grouping accuracy", "How closely our automatic wallet grouping matched the known truth, corrected for the agreement you would get by chance. 1.0 is perfect."],
  precision: ["Accuracy of our flags", "Of the wallet groups we flagged, the share that really were planted illicit cases."],
  recall: ["Cases caught", "Of the planted illicit cases, the share we flagged. A low number here means criminals were missed, which is the more dangerous error."],
  auc: ["Ranking quality", "How reliably the model puts an illicit wallet above an innocent one. 0.5 is a coin toss."],
  brier: ["Confidence honesty", "Measures whether the score means what it says. If we print 90, is it right about 90% of the time? Lower is better."],
  time_to_detection: ["How fast we noticed", "How many batches, on average, before a planted case was first flagged."],
  estimate: ["Estimate", "Bitcoin is fungible: once money is mixed, no one can say which coin went where. This figure is a proportional estimate, not an observation."],
  rejected: ["Rejected rows", "Records we could not parse. They are reported with a reason rather than quietly dropped — silent data loss in a criminal case is indefensible."],
  merge: ["Merged groups", "Two wallet groups that turned out to be one, because a later transaction spent addresses from both. Two operations being linked is a finding, not a bookkeeping problem."],
};

/* Plain names for model features. Keys mirror the backend's FEATURE_COLUMNS. */
const FEATURE_PLAIN = {
  address_count: "Wallets in the group",
  tx_count: "Transactions involved in",
  tx_sent: "Transactions it sent",
  tx_received: "Transactions it received",
  log_value_btc: "Total value moved",
  value_per_tx: "Average value per transaction",
  fan_in: "Wallets that paid it",
  fan_out: "Wallets it paid",
  in_out_ratio: "Imbalance between paying and receiving",
  distinct_counterparties: "Different wallets it dealt with",
  ip_count: "Different IP addresses seen",
  country_count: "Countries it was controlled from",
  asn_count: "Different network operators",
  active_days: "Days it was active",
  burst_score: "How machine-like its timing is",
  change_ratio: "Value sent straight back to itself",
  peel_score: "Peel-chain signature",
  output_uniformity: "How equal its payments are",
  mixer_score: "Mixing-service behaviour",
  mixer_interaction: "Touches a mixing service",
  collector_score: "Many pay in, few go out",
  exchange_score: "Behaves like an exchange",
  round_amount_ratio: "Round-number payments",
  mean_payment_btc: "Average payment size",
  pagerank: "Centrality in the money flow",
  betweenness: "How often money passes through it",
  community_size: "Size of its group",
  net_flow_ratio: "Whether it takes in more than it pays out",
};

/* Plain names for event types. */
const EVENT_PLAIN = {
  NEW_ENTITY: "Never seen before",
  ESCALATION: "Got riskier",
  DE_ESCALATION: "Got safer",
  DORMANT: "Went quiet",
  RESURGENT: "Active again",
  CLUSTER_GROWTH: "Grew",
  BEHAVIOUR_SHIFT: "Behaviour changed",
  CLUSTER_MERGE: "Two groups merged",
};

const ROLE_PLAIN = {
  collector: "Collects from many wallets",
  distributor: "Pays out to many wallets",
  relay: "Money passes through it",
  "cash-out/exchange": "Likely a cash-out service",
  "mixing service": "Mixing service",
  wallet: "Ordinary wallet group",
};

/* ------------------------------------------------------------------ utils */
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => (
  { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
));
const num = (v, digits = 0) => (v === null || v === undefined || Number.isNaN(v))
  ? "—" : Number(v).toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });
const btc = (v) => (v === null || v === undefined) ? "—" : `${num(v, v < 1 ? 4 : 2)}`;
const plainFeature = (name) => FEATURE_PLAIN[name] || name.replace(/_/g, " ");
const shortKey = (key) => {
  const text = String(key || "");
  // Stable ids are opaque hashes by design. Show enough to identify, not all of it.
  return text.length > 14 ? `${text.slice(0, 9)}…${text.slice(-4)}` : text;
};
const flag = (code) => {
  if (!code || code.length !== 2) return "";
  return String.fromCodePoint(...[...code.toUpperCase()].map((c) => 127397 + c.charCodeAt(0)));
};

/** Attach a plain-language note to an element, for Explain mode. */
function annotated(text, key) {
  return S.explain && GLOSSARY[key]
    ? `<span data-explain="${key}">${text}</span>`
    : text;
}

function toast(message) {
  const node = $("toast");
  node.textContent = message;
  node.hidden = false;
  clearTimeout(node._timer);
  node._timer = setTimeout(() => { node.hidden = true; }, 3200);
}

function go(view) {
  document.querySelectorAll(".view").forEach((v) => v.classList.toggle("on", v.id === `v-${view}`));
}

/* --------------------------------------------------------------------- api */
async function api(path, options) {
  const response = await fetch(path, options);
  // fetch does NOT reject on HTTP errors — a 404 resolves normally. Without
  // this check the error handling below would silently never run.
  if (!response.ok) {
    let detail = `${response.status}`;
    try { detail = (await response.json()).detail || detail; } catch (e) { /* not json */ }
    throw new Error(detail);
  }
  return response.json();
}

/* ------------------------------------------------------------------ render */
function renderCounters() {
  const p = S.payload;
  if (!p) return;
  $("counters").hidden = false;
  $("cRecords").textContent = num(p.meta.records);
  $("cEntities").textContent = num(p.meta.entities);
  const flagged = p.meta.flagged_entities;
  $("cFlagged").innerHTML = annotated(num(flagged), "risk");
}

function renderWindowLabel() {
  const p = S.payload;
  if (!p || !p.window) return;
  const w = p.window;
  $("transport").hidden = false;
  $("windowLabel").innerHTML =
    `Batch <b class="mono">${w.index}</b> of <b class="mono">${w.total}</b>` +
    ` <span class="muted mono">${esc(String(w.label).replace(/^window-/, ""))}</span>`;
  const pct = w.total > 1 ? ((w.index - 1) / (w.total - 1)) * 100 : 100;
  $("scrub").innerHTML = `<i style="width:${pct}%"></i>`;
}

function renderFleet() {
  const f = S.payload?.fleet;
  if (!f) return;
  const rows = [
    ["Records read", num(f.transactions)],
    ["Wallet groups", num(f.entities)],
    ["New this batch", num(f.new_entities)],
    ["Groups merged", annotated(num(f.merged_entities), "merge")],
    ["Rows rejected", f.rows_rejected ? `<span class="warn">${num(f.rows_rejected)}</span>` : "0"],
    ["Events", num(f.events)],
    ["Leads open", num(f.open_alerts)],
  ];
  $("fleet").innerHTML = rows.map(([label, value]) =>
    `<div class="stat"><span>${label}</span><strong>${value}</strong></div>`
  ).join("");
}

function renderFeed() {
  const events = S.payload?.events || [];
  $("eventCount").textContent = events.length ? `${events.length}` : "";

  const types = [...new Set(events.map((e) => e.type))];
  $("eventFilters").innerHTML = types.length > 1
    ? `<button class="chip on" data-filter="">All</button>` +
      types.map((t) => `<button class="chip" data-filter="${t}">${EVENT_PLAIN[t] || t}</button>`).join("")
    : "";
  $("eventFilters").querySelectorAll(".chip").forEach((chip) => {
    chip.onclick = () => {
      $("eventFilters").querySelectorAll(".chip").forEach((c) => c.classList.remove("on"));
      chip.classList.add("on");
      drawFeed(chip.dataset.filter);
    };
  });

  drawFeed("");
}

function drawFeed(filter) {
  const events = (S.payload?.events || []).filter((e) => !filter || e.type === filter);
  const feed = $("feed");
  $("feedEmpty").hidden = events.length > 0;
  if (!events.length) { feed.innerHTML = ""; return; }

  feed.innerHTML = events.map((event) => {
    const hasDelta = event.risk_from !== null && event.risk_to !== null && event.risk_from !== undefined;
    const delta = hasDelta
      ? `<span class="delta ${event.risk_to > event.risk_from ? "up" : "down"}">` +
        `${esc(event.risk_from)} &rarr; ${esc(event.risk_to)}</span>`
      : "";
    const why = event.detail
      ? `<div class="why">${esc(event.detail)}</div>`
      : (event.absorbed?.length
          ? `<div class="why"><em>absorbed</em> ${esc(event.absorbed.map(shortKey).join(", "))}</div>`
          : "");
    return `<div class="ev ${esc(event.severity)}" data-entity="${esc(event.entity)}">
        <div><span class="type">${esc(EVENT_PLAIN[event.type] || event.type)}</span>
        <span class="ent">${esc(shortKey(event.entity))}</span></div>
        ${delta}${why}
      </div>`;
  }).join("");

  feed.querySelectorAll(".ev").forEach((node) => {
    node.onclick = () => selectEntity(node.dataset.entity, true);
  });
}

function renderGraph() {
  const payload = S.payload;
  if (!payload || typeof vis === "undefined") return;

  const nodes = payload.entities;
  const edges = payload.edges;

  // Colour by the active mode. In "trace" mode we highlight the path a lead's
  // money actually took, which is the one view that answers "and then what?".
  const tracePath = new Set();
  if (S.mode === "trace" && S.selected) {
    const trace = (payload.traces || []).find((t) => t.seed === S.selected);
    (trace?.sinks || []).forEach((sink) => (sink.path || []).forEach((id) => tracePath.add(id)));
  }

  const bandColour = { critical: "#e05252", high: "#e08a52", medium: "#d9c04a", low: "#5aa96e" };
  const groupPalette = ["#5aa9e6", "#d99a2b", "#8f7ce0", "#4fb3a5", "#e07c9a", "#a3b545", "#c98a5a", "#6f9ed9"];
  const roleColour = {
    collector: "#e05252", distributor: "#e08a52", relay: "#d99a2b",
    "cash-out/exchange": "#8f7ce0", "mixing service": "#e07c9a", wallet: "#5b6472",
  };

  const visNodes = nodes.map((entity) => {
    const isIp = entity.kind === "ip";
    let colour = bandColour[entity.risk_band] || "#5b6472";
    if (S.mode === "community") colour = groupPalette[(entity.community_id ?? 0) % groupPalette.length];
    if (S.mode === "role") colour = roleColour[entity.graph_role] || "#5b6472";
    if (isIp) colour = "#5aa9e6";
    const traced = tracePath.has(entity.id);
    return {
      id: entity.id,
      label: traced || (!isIp && (entity.risk >= 70 || entity.kind === "mixer" || entity.kind === "exchange"))
        ? shortKey(entity.label || entity.id) : undefined,
      shape: isIp ? "box" : "dot",
      size: isIp ? 9 : 7 + Math.min(24, entity.risk / 4),
      color: {
        background: colour,
        border: traced ? "#d99a2b" : (entity.id === S.selected ? "#ffffff" : colour),
        highlight: { background: colour, border: "#d99a2b" },
      },
      borderWidth: traced || entity.id === S.selected ? 3 : 1,
      font: { color: "#c9d1db", size: 10, face: "Fira Code" },
      title: `${entity.id} · priority ${entity.risk}`,
    };
  });

  const visEdges = edges.map((edge) => ({
    from: edge.from,
    to: edge.to,
    dashes: edge.kind === "control",
    arrows: edge.kind === "flow" ? { to: { enabled: true, scaleFactor: 0.4 } } : undefined,
    width: edge.kind === "control" ? 1 : 0.6 + Math.min(3, Math.log10((edge.value || 1) + 1)),
    // Full-strength edges over a dense graph become a solid mass that hides the
    // nodes. Opacity is the single biggest readability win.
    color: {
      color: edge.kind === "control" ? "rgba(90,169,230,0.30)" : "rgba(217,154,43,0.42)",
      highlight: "#ffffff",
    },
  }));

  const container = $("graph");
  const data = { nodes: new vis.DataSet(visNodes), edges: new vis.DataSet(visEdges) };
  const options = {
    nodes: { borderWidth: 1 },
    edges: { smooth: { type: "continuous" } },
    physics: {
      enabled: true,
      stabilization: { iterations: 160, fit: true },
      barnesHut: { gravitationalConstant: -5200, springLength: 95, springConstant: 0.04, damping: 0.6 },
    },
    interaction: { hover: true, tooltipDelay: 220, navigationButtons: false, keyboard: false },
  };

  if (S.network) S.network.destroy();
  S.network = new vis.Network(container, data, options);
  // Run physics briefly to settle the layout, then FREEZE it. A graph that keeps
  // drifting while you are talking about it is unusable.
  S.network.once("stabilizationIterationsDone", () => S.network.setOptions({ physics: false }));
  S.network.on("click", (params) => {
    if (params.nodes.length) selectEntity(params.nodes[0], false);
  });

  const shown = nodes.filter((n) => n.kind !== "ip").length;
  $("graphNote").textContent =
    `${shown} wallet groups, ${nodes.length - shown} IP addresses, ${edges.length} links`;
  $("graphEmpty").hidden = edges.length > 0;
}

function renderLead() {
  const payload = S.payload;
  const entity = payload?.entities.find((e) => e.id === S.selected);
  $("leadEmpty").hidden = Boolean(entity);
  $("lead").hidden = !entity;
  if (!entity) return;

  $("leadId").textContent = shortKey(entity.id);
  $("leadRisk").innerHTML = annotated(num(entity.risk), "risk");
  $("leadBand").className = `band ${entity.risk_band}`;
  $("leadBand").innerHTML = annotated(esc(entity.risk_band), "band");
  $("leadLabel").textContent = entity.label || entity.id;
  $("leadRoleLine").textContent =
    `${ROLE_PLAIN[entity.graph_role] || entity.graph_role || "wallet group"} · ` +
    `${entity.community_id === null || entity.community_id === undefined
        ? "no money-flow group" : `group ${entity.community_id}, ${entity.community_size} members`}`;
  $("leadGeo").textContent =
    (entity.geo?.length ? `Controlled from ${entity.geo.map((c) => `${flag(c)} ${c}`).join(", ")}` : "No location data")
    + ` · ${num(entity.tx_count)} transactions · ${btc(entity.value_btc)} BTC`;

  renderWaterfall(entity);
  renderReasons(entity);
  renderHistory(entity);
  renderTraces(entity);

  const alert = S.alerts.find((a) => a.entity === entity.id);
  $("ackState").textContent = alert ? `status: ${alert.status}` : "";
  $("ackBtn").disabled = !alert;
}

function renderWaterfall(entity) {
  const features = entity.features || [];
  const explanation = entity.explanation;
  const host = $("waterfall");

  if (!features.length) {
    host.innerHTML = `<div class="empty"><b>No breakdown for this group.</b>
      <span>Breakdowns are computed for the ranked leads, not for every group in the
      batch — a full decomposition costs real time and nobody opens the quiet ones.</span></div>`;
    $("reconcile").textContent = "";
    return;
  }

  const peak = Math.max(...features.map((f) => Math.abs(f.importance)), 1e-9);
  host.innerHTML = features.map((item) => {
    const width = Math.max(2, (Math.abs(item.importance) / peak) * 48);
    const positive = item.importance >= 0;
    return `<div class="wf">
      <div class="wfLabel">
        <span class="wfName" title="${esc(item.name)}">${esc(plainFeature(item.name))}
          <em>${num(item.value, Math.abs(item.value) < 10 ? 2 : 0)}</em></span>
      </div>
      <div class="wfTrack">
        <u></u>
        <i class="${positive ? "pos" : "neg"}" style="width:${width}%"></i>
      </div>
    </div>`;
  }).join("");

  if (explanation) {
    $("reconcile").innerHTML =
      `${annotated("starting point", "base")} ${num(explanation.base, 3)} + ` +
      `${annotated("contributions", "contribution")} = ${num(explanation.prediction, 3)} ` +
      `(${annotated("left over", "residual")} ${Number(explanation.residual).toExponential(2)})`;
  }
}

function renderReasons(entity) {
  const reasons = entity.reasons || [];
  $("reasons").innerHTML = reasons.map((reason) =>
    `<div class="reason ${esc(reason.severity)}">
       <b>${esc(reason.title)}</b><span>${esc(reason.detail)}</span>
     </div>`
  ).join("") || `<div class="empty"><b>No notes.</b><span>Nothing to add.</span></div>`;
}

function renderHistory(entity) {
  const history = entity.history || [];
  const context = $("historyChart").getContext("2d");
  if (S.historyChart) { S.historyChart.destroy(); S.historyChart = null; }
  if (history.length < 2) return;

  S.historyChart = new Chart(context, {
    type: "line",
    data: {
      labels: history.map((h) => String(h.window).replace(/^window-/, "").slice(5)),
      datasets: [{
        data: history.map((h) => h.risk),
        borderColor: "#d99a2b",
        backgroundColor: "rgba(217,154,43,0.14)",
        fill: true,
        tension: 0.25,
        pointRadius: 3,
        borderWidth: 2,
      }],
    },
    options: {
      plugins: { legend: { display: false } },
      scales: {
        y: { min: 0, max: 100, grid: { color: "rgba(120,130,145,0.14)" },
             ticks: { color: "#6b7683", font: { size: 10 } } },
        x: { grid: { display: false }, ticks: { color: "#6b7683", font: { size: 10 } } },
      },
      responsive: true,
      maintainAspectRatio: false,
    },
  });
}

function renderTraces(entity) {
  const traces = (S.payload?.traces || []).filter((t) => t.seed === entity.id);
  const host = $("traces");
  if (!traces.length) {
    host.innerHTML = `<div class="empty"><b>No trail found.</b>
      <span>Either the money did not reach a known cash-out or mixing service within
      four hops, or this group sent nothing outward in this batch.</span></div>`;
    return;
  }
  host.innerHTML = traces.map((trace) => `
    <div class="trace">
      <span class="est">&#8776; estimate — not an observation</span>
      <div class="muted small" style="margin-top:4px">
        Sent out <b class="mono">${btc(trace.tainted)} BTC</b>, followed
        <b class="mono">${num(trace.hops_reached)}</b> hops.
      </div>
      <table>
        <thead><tr><th>Reached</th><th>Kind</th><th class="num">BTC</th><th class="num">Hops</th></tr></thead>
        <tbody>${(trace.sinks || []).map((sink) => `
          <tr>
            <td class="mono">${esc(shortKey(sink.entity))}</td>
            <td>${sink.kind === "mixer" ? "mixing service" : "cash-out / exchange"}</td>
            <td class="num">${btc(sink.amount)}</td>
            <td class="num">${num(sink.hops)}</td>
          </tr>
          <tr><td colspan="4" class="path">${esc((sink.path || []).map(shortKey).join(" → "))}</td></tr>
        `).join("")}</tbody>
      </table>
    </div>
  `).join("");
}

function renderGeo() {
  const rows = S.payload?.geo_breakdown || [];
  $("geo").innerHTML = rows.length
    ? rows.map((row) => `
        <div class="geoRow">
          <span>${flag(row.code)} <span class="mono">${esc(row.code)}</span></span>
          <span class="geoBar"><i style="width:${Math.round(row.share * 100)}%"></i></span>
          <span class="mono">${Math.round(row.share * 100)}%</span>
        </div>`).join("")
    : `<div class="empty"><b>No location data.</b>
        <span>No flagged group in this batch had IP records attached.</span></div>`;
}

function renderMetrics() {
  const m = S.payload?.metrics || {};
  const rows = [];
  const push = (label, value, key, note) => {
    if (value === null || value === undefined) return;
    rows.push(`<div class="stat"><span>${label}${note ? ` <span class="muted small">${note}</span>` : ""}</span>
      <strong>${annotated(value, key)}</strong></div>`);
  };
  const pct = (v) => (v === null || v === undefined ? null : `${Math.round(v * 100)}%`);

  push("Flag accuracy", pct(m.risk_precision), "precision");
  push("Cases caught", pct(m.risk_recall), "recall");
  push("Ranking quality", num(m.risk_auc, 3), "auc");
  push("Confidence honesty", num(m.brier, 3), "brier");
  push("Grouping accuracy", num(m.cluster_ari, 3), "ari");

  const graph = S.payload?.fleet && S.payload?.clusters;
  if (graph) push("Distinct groups found", num(S.payload.clusters.length), "modularity");

  $("metrics").innerHTML = rows.join("") +
    `<div class="muted small" style="margin-top:8px">Measured on a synthetic dataset
     carrying planted cases, so these are results rather than claims. The dataset is
     synthetic, so performance on operational data is not established by them.</div>`;
}

function renderStrip() {
  const m = S.payload?.meta;
  $("stripProvenance").textContent = m
    ? `engine ${esc(m.engine_version)} · ${esc(m.model || "RandomForest (windowed)")} · ` +
      `explanations: decision-path contributions`
    : "no analysis loaded";
  $("stripGenerated").textContent = m ? `generated ${esc(String(m.generated_at).replace("T", " ").slice(0, 19))}` : "";
}

/* --------------------------------------------------------------- selection */
async function selectEntity(entityId, fromFeed) {
  S.selected = entityId;
  renderLead();
  if (!fromFeed) drawFeed($("eventFilters")?.querySelector(".chip.on")?.dataset.filter || "");
  if (S.network) renderGraph();
  // Scroll the feed to the matching card so the two panels stay in step.
  const card = [...document.querySelectorAll(".ev")].find((n) => n.dataset.entity === entityId);
  document.querySelectorAll(".ev").forEach((n) => n.classList.toggle("sel", n === card));
  if (card) card.scrollIntoView({ block: "nearest" });
}

/* ------------------------------------------------------------ window loads */
async function loadWindow(index) {
  if (!S.windows.length) return;
  S.index = Math.max(0, Math.min(S.windows.length - 1, index));
  const target = S.windows[S.index];
  try {
    S.payload = await api(`/results?window=${target.id}`);
  } catch (error) {
    toast(`Could not load batch ${target.id}: ${error.message}`);
    return;
  }
  renderCounters();
  renderWindowLabel();
  renderFleet();
  renderFeed();
  renderGeo();
  renderMetrics();
  renderStrip();

  // Keep the selection if it survives into this window's entities; otherwise
  // fall back to the top lead rather than showing an empty panel.
  const ids = new Set(S.payload.entities.map((e) => e.id));
  if (!S.selected || !ids.has(S.selected)) {
    S.selected = S.payload.alerts?.[0]?.entity || S.payload.entities?.[0]?.id || null;
  }
  renderGraph();
  renderLead();
  $("v-console").dataset.window = String(target.id);
}

function startReplay() {
  if (S.playing) return stopReplay();
  S.playing = true;
  $("playBtn").innerHTML = "&#10073;&#10073;";
  S.playTimer = setInterval(() => {
    if (S.index >= S.windows.length - 1) return stopReplay();
    loadWindow(S.index + 1);
  }, 2600);
}

function stopReplay() {
  S.playing = false;
  $("playBtn").innerHTML = "&#9654;";
  clearInterval(S.playTimer);
  S.playTimer = null;
}

/* ------------------------------------------------------------------ upload */
async function runAnalysis() {
  go("start");
  $("demoBtn").disabled = true;
  $("demoBtn").textContent = "Analysing…";
  try {
    const job = await api("/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode: "replay" }),
    });
    let status = "queued";
    while (status === "queued" || status === "running") {
      await new Promise((r) => setTimeout(r, 1200));
      const state = await api(`/job/${job.job_id}`);
      status = state.status;
      const last = state.log?.[state.log.length - 1];
      if (last) $("demoBtn").textContent = String(last).slice(0, 46);
    }
    if (status === "error") throw new Error("the analysis failed — see the log");
    await bootstrap();
    go("console");
    toast("Analysis complete");
  } catch (error) {
    toast(`Analysis failed: ${error.message}`);
  } finally {
    $("demoBtn").disabled = false;
    $("demoBtn").textContent = "Run on the built-in dataset";
  }
}

async function uploadFile(file) {
  const body = new FormData();
  body.append("file", file);
  try {
    const result = await api("/upload", { method: "POST", body });
    const report = result.report;
    $("gate").hidden = false;
    $("gateGrid").innerHTML = `
      <div><span>Rows read</span><strong>${num(report.total)}</strong></div>
      <div><span>Usable</span><strong>${num(report.accepted)}</strong></div>
      <div><span>Rejected</span><strong>${num(report.rejected)}</strong></div>
      <div><span>Format</span><strong>${esc(report.format)}</strong></div>`;
    const reasons = Object.entries(report.rejections || {});
    const notes = Object.entries(report.notes || {});
    $("gateReasons").innerHTML =
      (reasons.length
        ? `<p>Why rows were rejected — we report these rather than dropping them silently:</p><ul>` +
          reasons.map(([why, count]) => `<li><code>${num(count)}</code> × ${esc(why)}</li>`).join("") + `</ul>`
        : `<p class="muted">Every row parsed. Nothing was rejected.</p>`) +
      (notes.length
        ? `<p class="muted">Worth knowing: ` +
          notes.map(([label, count]) => `${num(count)} ${esc(label)}`).join(", ") + `.</p>`
        : "");
    toast(`${num(report.accepted)} rows ready`);
  } catch (error) {
    toast(`Upload failed: ${error.message}`);
  }
}

/* -------------------------------------------------------------------- docs */
async function loadDocList() {
  try {
    const index = await api("/documents/index.json");
    $("docList").innerHTML = index.documents.map((doc) =>
      `<li data-file="${esc(doc.file)}" title="${esc(doc.description)}">${esc(doc.title)}</li>`
    ).join("");
    $("docList").querySelectorAll("li").forEach((node) => {
      node.onclick = () => openDoc(node.dataset.file, node);
    });
  } catch (error) {
    $("docList").innerHTML = `<li class="muted">No documents found.</li>`;
  }
}

async function openDoc(file, node) {
  try {
    const text = await (await fetch(`/documents/${file}`)).text();
    $("docBody").innerHTML = renderMarkdown(text);
    $("docBody").scrollTop = 0;
    $("docList").querySelectorAll("li").forEach((item) => item.classList.toggle("on", item === node));
    S.currentDoc = file;
  } catch (error) {
    toast(`Could not open ${file}`);
  }
}

/** A deliberately small markdown renderer.
 *  A full parser is a dependency, and a dependency is a thing that can fail on
 *  an air-gapped machine. This handles the subset our own documents use, and
 *  anything it does not understand falls through as plain text rather than
 *  disappearing.
 */
function renderMarkdown(text) {
  const lines = String(text).replace(/\r\n/g, "\n").split("\n");
  const out = [];
  let inCode = false, inTable = false, inList = false;
  const inline = (s) => esc(s)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
    .replace(/(^|\s)\*([^*]+)\*/g, "$1<i>$2</i>")
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, "$1");
  const closeList = () => { if (inList) { out.push("</ul>"); inList = false; } };
  const closeTable = () => { if (inTable) { out.push("</tbody></table>"); inTable = false; } };

  for (const raw of lines) {
    const line = raw.replace(/\s+$/, "");
    if (/^```/.test(line)) {
      closeList(); closeTable();
      out.push(inCode ? "</code></pre>" : "<pre><code>");
      inCode = !inCode;
      continue;
    }
    if (inCode) { out.push(esc(raw)); continue; }

    if (/^\s*$/.test(line)) { closeList(); closeTable(); continue; }

    let match;
    if ((match = line.match(/^(#{1,4})\s+(.*)$/))) {
      closeList(); closeTable();
      const level = match[1].length;
      out.push(`<h${level}>${inline(match[2])}</h${level}>`);
      continue;
    }
    if (/^(---|\*\*\*|___)\s*$/.test(line)) { closeList(); closeTable(); out.push("<hr>"); continue; }
    if ((match = line.match(/^>\s?(.*)$/))) {
      closeList(); closeTable();
      out.push(`<blockquote>${inline(match[1])}</blockquote>`);
      continue;
    }
    if (/^\|.*\|\s*$/.test(line)) {
      closeList();
      if (/^\|[\s:|-]+\|\s*$/.test(line)) continue;      // the separator row
      const cells = line.slice(1, -1).split("|").map((c) => c.trim());
      if (!inTable) { out.push("<table><tbody>"); inTable = true; }
      out.push("<tr>" + cells.map((c) => `<td>${inline(c)}</td>`).join("") + "</tr>");
      continue;
    }
    if ((match = line.match(/^\s*[-*]\s+(.*)$/))) {
      if (!inList) { out.push("<ul>"); inList = true; }
      out.push(`<li>${inline(match[1])}</li>`);
      continue;
    }
    closeList(); closeTable();
    out.push(`<p>${inline(line)}</p>`);
  }
  closeList(); closeTable();
  if (inCode) out.push("</code></pre>");
  return out.join("\n");
}

/* ------------------------------------------------------------------- tour */
const TOUR = [
  ["What changed", "This feed lists only what is NEW. A wallet that is high-risk but unchanged is not news; one that just became high-risk is. Each card names the reason in plain words."],
  ["How it fits together", "Solid lines are money moving. Dashed lines are IP addresses that controlled a wallet — that join is what gives a wallet a country to be investigated in."],
  ["Why this one", "The evidence behind the selected lead. Every bar is one measurable fact, and the bars add up exactly to the score, so the explanation always reconciles with the number."],
  ["Is the data sound", "What was read, what was rejected and why, and how well the models do against cases we planted ourselves — so these are results, not claims."],
  ["Replay", "Press play and the console walks through each batch in order, the way it would have happened live. Nothing is faked: the same code runs on each batch."],
];
/* -1 means "no tour running". It must NOT start at 0: the resize handler rebuilds
 * the tour whenever tourIndex >= 0, so initialising it to 0 meant any window
 * resize -- including the one the browser fires during first layout -- popped
 * the tour open on a fresh page with nobody having asked for it. */
let tourIndex = -1;

function startTour() {
  tourIndex = 0;
  renderTour();
}
function endTour() {
  tourIndex = -1;
  $("tourRing").hidden = true;
  $("tourPop").hidden = true;
}
function renderTour() {
  if (tourIndex < 0) return;
  const step = TOUR[tourIndex];
  const columns = document.querySelectorAll(".cols > .col");
  const anchor = columns[Math.min(tourIndex, columns.length - 1)];
  const rect = anchor.getBoundingClientRect();

  $("tourRing").hidden = false;
  Object.assign($("tourRing").style, {
    left: `${rect.left - 4}px`, top: `${rect.top - 4}px`,
    width: `${rect.width + 8}px`, height: `${rect.height + 8}px`,
  });
  $("tourTitle").textContent = step[0];
  $("tourBody").textContent = step[1];
  $("tourStep").textContent = `${tourIndex + 1} / ${TOUR.length}`;
  $("tourBack").disabled = tourIndex === 0;
  $("tourNext").hidden = tourIndex === TOUR.length - 1;
  $("tourEnd").hidden = tourIndex !== TOUR.length - 1;
  $("tourPop").hidden = false;
  const popLeft = Math.min(rect.left + 24, window.innerWidth - 360);
  const popTop = Math.min(rect.top + 40, window.innerHeight - 240);
  Object.assign($("tourPop").style, { left: `${popLeft}px`, top: `${popTop}px` });
}

/* ------------------------------------------------------------------ wiring */
function showPop(target, key) {
  const entry = GLOSSARY[key];
  if (!entry) return;
  const rect = target.getBoundingClientRect();
  $("pop").innerHTML = `<b>${esc(entry[0])}</b><span>${esc(entry[1])}</span>`;
  $("pop").hidden = false;
  const left = Math.max(8, Math.min(rect.left, window.innerWidth - 348));
  $("pop").style.left = `${left}px`;
  $("pop").style.top = `${Math.max(8, rect.bottom + 8)}px`;
}
function hidePop() { $("pop").hidden = true; }

async function bootstrap() {
  const health = await api("/health");
  $("stripApi").textContent = health.store?.exists ? "offline · local" : "no state";

  let data;
  try {
    data = await api("/windows");
  } catch (error) {
    // No monitoring state yet: the start view is the whole app until an
    // analysis has run.
    $("stripProvenance").textContent = "no analysis yet — run one to begin";
    return false;
  }
  S.windows = data.windows || [];
  S.alerts = (await api("/alerts")).alerts || [];
  if (!S.windows.length) return false;
  await loadWindow(0);
  return true;
}

function wire() {
  $("demoBtn").onclick = runAnalysis;
  $("fileInput").onchange = (event) => {
    const file = event.target.files?.[0];
    if (file) uploadFile(file);
  };

  $("playBtn").onclick = startReplay;
  $("firstBtn").onclick = () => { stopReplay(); loadWindow(0); };
  $("prevBtn").onclick = () => { stopReplay(); loadWindow(S.index - 1); };
  $("nextBtn").onclick = () => { stopReplay(); loadWindow(S.index + 1); };
  $("scrub").onclick = (event) => {
    const rect = $("scrub").getBoundingClientRect();
    const ratio = (event.clientX - rect.left) / rect.width;
    stopReplay();
    loadWindow(Math.round(ratio * (S.windows.length - 1)));
  };

  $("explainBtn").onclick = () => {
    S.explain = !S.explain;
    document.body.classList.toggle("explain", S.explain);
    $("explainBtn").classList.toggle("on", S.explain);
    toast(S.explain
      ? "Explain mode on — click any underlined number or term"
      : "Explain mode off");
    if (S.payload) { renderCounters(); renderLead(); renderMetrics(); }
  };

  $("graphChips").querySelectorAll(".chip").forEach((chip) => {
    chip.onclick = () => {
      $("graphChips").querySelectorAll(".chip").forEach((c) => c.classList.remove("on"));
      chip.classList.add("on");
      S.mode = chip.dataset.mode;
      renderGraph();
    };
  });

  $("themeBtn").onclick = () => {
    const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("netra-theme", next); } catch (e) { /* private mode */ }
    if (S.payload) renderGraph();
  };

  $("tourBtn").onclick = startTour;
  $("tourNext").onclick = () => { tourIndex += 1; renderTour(); };
  $("tourBack").onclick = () => { tourIndex -= 1; renderTour(); };
  $("tourEnd").onclick = endTour;

  $("reportBtn").onclick = () => {
    if (!S.selected) return;
    $("modalFrame").src = `/report/${encodeURIComponent(S.selected)}`;
    $("modal").hidden = false;
  };
  $("modalClose").onclick = () => { $("modal").hidden = true; $("modalFrame").src = "about:blank"; };

  $("ackBtn").onclick = async () => {
    if (!S.selected) return;
    try {
      await api(`/alerts/${encodeURIComponent(S.selected)}/status`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: "acknowledged" }),
      });
      S.alerts = (await api("/alerts")).alerts || [];
      renderLead();
      toast("Marked acknowledged — the system will remember that between runs");
    } catch (error) {
      toast(`Could not update: ${error.message}`);
    }
  };

  $("docsBtn").onclick = () => { go("docs"); loadDocList(); };
  $("backBtn").onclick = () => go("console");

  $("reloadBtn").onclick = async () => {
    try {
      const result = await api("/reload", { method: "POST" });
      await bootstrap();
      toast(`Reloaded — ${result.cleared_caches} cached views dropped`);
    } catch (error) {
      toast(`Reload failed: ${error.message}`);
    }
  };

  // Explain mode: delegate so it works for elements rendered later.
  document.addEventListener("click", (event) => {
    const target = event.target.closest("[data-explain]");
    if (target && S.explain) { event.stopPropagation(); showPop(target, target.dataset.explain); }
    else hidePop();
  });

  document.addEventListener("keydown", (event) => {
    if ($("modal").hidden === false && event.key === "Escape") $("modalClose").click();
    if (document.activeElement?.tagName === "INPUT") return;
    if (event.key === "ArrowRight") $("nextBtn").click();
    if (event.key === "ArrowLeft") $("prevBtn").click();
    if (event.key === " ") { event.preventDefault(); $("playBtn").click(); }
  });

  window.addEventListener("resize", () => { if (tourIndex >= 0) renderTour(); });
}

async function main() {
  try {
    const saved = localStorage.getItem("netra-theme");
    if (saved) document.documentElement.dataset.theme = saved;
  } catch (e) { /* private mode */ }

  wire();
  const ready = await bootstrap();
  if (ready) go("console");
}

main();
