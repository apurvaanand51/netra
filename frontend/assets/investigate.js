/* Investigation console: which groups need attention, and why.
 *
 * Presentation only. Nothing here decides whether a wallet is suspicious -- it
 * renders what the backend already measured. If a number is not in the payload it
 * is not on this screen, because in an investigative tool a number is evidence.
 */

"use strict";

const V = {
  payload: null,
  windows: [],
  active: null,
  selected: null,
  mode: "risk",
  network: null,
  chart: null,
  tracesBySeed: {},
};

const bandOf = (score) => (score >= 85 ? "critical" : score >= 70 ? "high" : score >= 50 ? "medium" : "low");

/* ------------------------------------------------------------------- rail */
function renderRail() {
  const alerts = (V.payload.alerts || []).slice();
  const host = document.getElementById("rail");
  document.getElementById("railEmpty").hidden = alerts.length > 0;
  const flagged = V.payload.meta.flagged_entities || 0;
  document.getElementById("railSub").innerHTML =
    `${alerts.length} leads shown · ${num(flagged)} groups at or above the alerting floor ` +
    `out of ${num(V.payload.corpus?.entities ?? V.payload.meta.entities)} examined.`;

  host.innerHTML = alerts.map((alert) => {
    const changes = (alert.changes || [])
      .slice(0, 2)
      .map((item) => `${item.label.toLowerCase()} ${compact(item.from)} → ${compact(item.to)}`)
      .join(", ");
    return `<div class="lead ${esc(alert.severity)}" data-entity="${esc(alert.entity)}">
      <div class="score">${num(alert.score)}</div>
      <div style="min-width:0">
        <div class="who">${esc(shortKey(alert.entity))}</div>
        <div class="why">${esc(changes || alert.description || "")}</div>
        <div class="statusChip">${esc(alert.status)}${alert.peak_risk > alert.score
          ? ` · peak ${num(alert.peak_risk)}` : ""}</div>
      </div>
    </div>`;
  }).join("");

  host.querySelectorAll(".lead").forEach((node) => {
    node.onclick = () => selectLead(node.dataset.entity);
  });
}

/* -------------------------------------------------------------------- map */
function renderGraph() {
  if (typeof vis === "undefined" || !V.payload) return;
  const nodes = V.payload.entities || [];
  const edges = V.payload.edges || [];

  // In "money trail" mode, highlight the path the selected lead's value took.
  const tracePath = new Set();
  if (V.mode === "trace" && V.selected) {
    (V.tracesBySeed[V.selected] || []).forEach((trace) =>
      (trace.sinks || []).forEach((sink) => (sink.path || []).forEach((id) => tracePath.add(id))));
  }

  const groupPalette = ["#5aa9e6", "#d99a2b", "#8f7ce0", "#4fb3a5", "#e07c9a", "#a3b545", "#c98a5a", "#6f9ed9"];
  const roleColour = {
    collector: "#e05252", distributor: "#e08a52", relay: "#d99a2b",
    "cash-out/exchange": "#8f7ce0", "mixing service": "#e07c9a", wallet: "#5b6472",
  };

  const visNodes = nodes.map((entity) => {
    const isIp = entity.kind === "ip";
    let colour = BAND_COLOUR[entity.risk_band] || "#5b6472";
    if (S_modeCommunity(entity)) colour = groupPalette[(entity.community_id ?? 0) % groupPalette.length];
    if (V.mode === "role") colour = roleColour[entity.graph_role] || "#5b6472";
    if (isIp) colour = "#5aa9e6";
    const traced = tracePath.has(entity.id);
    return {
      id: entity.id,
      label: traced || (!isIp && (entity.risk >= 70 || entity.kind === "mixer" || entity.kind === "exchange"))
        ? shortKey(entity.label || entity.id) : undefined,
      shape: isIp ? "box" : "dot",
      size: isIp ? 9 : 7 + Math.min(22, entity.risk / 4.5),
      color: {
        background: colour,
        border: traced ? "#d99a2b" : (entity.id === V.selected ? "#ffffff" : colour),
        highlight: { background: colour, border: "#d99a2b" },
      },
      borderWidth: traced || entity.id === V.selected ? 3 : 1,
      font: { color: "#c9d1db", size: 10, face: "Fira Code" },
      title: `${entity.id} · priority ${entity.risk}`,
    };
  });

  const visEdges = edges.map((edge) => ({
    from: edge.from, to: edge.to,
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

  const data = { nodes: new vis.DataSet(visNodes), edges: new vis.DataSet(visEdges) };
  if (V.network) V.network.destroy();
  V.network = new vis.Network(document.getElementById("graph"), data, {
    nodes: { borderWidth: 1 },
    edges: { smooth: { type: "continuous" } },
    physics: {
      enabled: true,
      stabilization: { iterations: 150, fit: true },
      barnesHut: { gravitationalConstant: -5200, springLength: 95, springConstant: 0.04, damping: 0.6 },
    },
    interaction: { hover: true, tooltipDelay: 220, keyboard: false },
  });
  // Run physics briefly to settle the layout, then FREEZE it. A graph that keeps
  // drifting while you are talking about it is unusable.
  V.network.once("stabilizationIterationsDone", () => V.network.setOptions({ physics: false }));
  V.network.on("click", (params) => { if (params.nodes.length) selectLead(params.nodes[0]); });

  const wallets = nodes.filter((node) => node.kind !== "ip").length;
  document.getElementById("graphNote").textContent =
    `${wallets} wallet groups, ${nodes.length - wallets} IP addresses, ${edges.length} links`;
  document.getElementById("graphEmpty").hidden = edges.length > 0;
}
const S_modeCommunity = (entity) => V.mode === "community";

/* ----------------------------------------------------------------- detail */
function selectLead(entityId) {
  V.selected = entityId;
  document.querySelectorAll(".lead").forEach((node) =>
    node.classList.toggle("sel", node.dataset.entity === entityId));
  renderDetail();
  if (V.network) renderGraph();
}

function renderDetail() {
  const entity = (V.payload?.entities || []).find((item) => item.id === V.selected);
  document.getElementById("leadEmpty").hidden = Boolean(entity);
  document.getElementById("lead").hidden = !entity;
  if (!entity) return;

  const alert = (V.payload.alerts || []).find((item) => item.entity === entity.id);
  document.getElementById("leadRisk").innerHTML = annotated(num(entity.risk), "risk");
  const band = document.getElementById("leadBand");
  band.className = `band ${entity.risk_band}`;
  band.innerHTML = annotated(esc(entity.risk_band), "band");
  document.getElementById("leadLabel").textContent = entity.label || entity.id;
  document.getElementById("leadRoleLine").textContent =
    `${ROLE_PLAIN[entity.graph_role] || entity.graph_role || "wallet group"} · ` +
    (entity.community_id === null || entity.community_id === undefined
      ? "no money-flow group" : `group ${entity.community_id}, ${entity.community_size} members`);
  document.getElementById("leadGeo").textContent =
    (entity.geo?.length
      ? `Controlled from ${entity.geo.map((code) => `${flagEmoji(code)} ${code}`).join(", ")}`
      : "No location data") +
    ` · ${num(entity.tx_count)} transactions · ${btc(entity.value_btc)} BTC`;

  renderWaterfall(entity);
  renderReasons(entity);
  renderHistory(entity);
  renderTraces(entity);

  document.getElementById("ackState").textContent = alert ? `status: ${alert.status}` : "";
  document.getElementById("ackBtn").disabled = !alert;
}

function renderWaterfall(entity) {
  const features = entity.features || [];
  const explanation = entity.explanation;
  const host = document.getElementById("waterfall");
  if (!features.length) {
    host.innerHTML = emptyState(
      "No breakdown for this group.",
      "Breakdowns are computed for the ranked leads, not for every group — a full decomposition costs real time and nobody opens the quiet ones."
    );
    document.getElementById("reconcile").textContent = "";
    return;
  }
  const peak = Math.max(...features.map((item) => Math.abs(item.importance)), 1e-9);
  host.innerHTML = features.map((item) => {
    const width = Math.max(2, (Math.abs(item.importance) / peak) * 48);
    const positive = item.importance >= 0;
    return `<div class="wf">
      <div class="wfLabel"><span class="wfName" title="${esc(item.name)}">${esc(plainFeature(item.name))}
        <em>${num(item.value, Math.abs(item.value) < 10 ? 2 : 0)}</em></span></div>
      <div class="wfTrack"><u></u>
        <i class="${positive ? "pos" : "neg"}" style="width:${width}%"></i></div>
    </div>`;
  }).join("");

  if (explanation) {
    document.getElementById("reconcile").innerHTML =
      `${annotated("starting point", "base")} ${num(explanation.base, 3)} + ` +
      `${annotated("contributions", "contribution")} = ${num(explanation.prediction, 3)} ` +
      `(${annotated("left over", "residual")} ${Number(explanation.residual).toExponential(2)})`;
  }
}

function renderReasons(entity) {
  const reasons = entity.reasons || [];
  document.getElementById("reasons").innerHTML = reasons.length
    ? reasons.map((reason) => `<div class="reason ${esc(reason.severity)}">
        <b>${esc(reason.title)}</b><span>${esc(reason.detail)}</span></div>`).join("")
    : emptyState("No notes.", "Nothing to add for this group.");
}

function renderHistory(entity) {
  const history = entity.history || [];
  const canvas = document.getElementById("historyChart");
  const note = document.getElementById("historyNote");
  if (V.chart) { V.chart.destroy(); V.chart = null; }

  // Fewer than two points is not a trend. Drawing an empty chart frame looks
  // like a broken panel, and calling a single point a "trend" would be worse.
  if (history.length < 2) {
    canvas.hidden = true;
    note.hidden = false;
    note.innerHTML = `<b>No trend yet.</b> This group has been scored in only
      ${history.length} batch${history.length === 1 ? "" : "es"}, and a trend needs at least two.`;
    return;
  }
  canvas.hidden = false;
  note.hidden = true;

  V.chart = new Chart(canvas.getContext("2d"), {
    type: "line",
    data: {
      labels: history.map((row) => String(row.window).replace(/^window-/, "").slice(5)),
      datasets: [{
        data: history.map((row) => row.risk),
        borderColor: "#d99a2b", backgroundColor: "rgba(217,154,43,0.14)",
        fill: true, tension: 0.25, pointRadius: 3, borderWidth: 2,
      }],
    },
    options: {
      plugins: { legend: { display: false } },
      scales: {
        y: { min: 0, max: 100, grid: { color: "rgba(120,130,145,0.14)" },
             ticks: { color: "#6b7683", font: { size: 10 } } },
        x: { grid: { display: false }, ticks: { color: "#6b7683", font: { size: 10 } } },
      },
      responsive: true, maintainAspectRatio: false,
    },
  });
}

function renderTraces(entity) {
  const traces = V.tracesBySeed[entity.id] || [];
  const host = document.getElementById("traces");
  if (!traces.length) {
    host.innerHTML = emptyState(
      "No trail found.",
      "Either the money did not reach a known cash-out or mixing service within four hops, or this group sent nothing outward in this batch."
    );
    return;
  }
  host.innerHTML = traces.map((trace) => `
    <div class="trace">
      <span class="est">&#8776; estimate — not an observation</span>
      <div class="muted small" style="margin-top:4px">Sent out <b class="mono">${btc(trace.tainted)} BTC</b>,
        followed <b class="mono">${num(trace.hops_reached)}</b> hops.</div>
      <table>
        <thead><tr><th>Reached</th><th>Kind</th><th class="num">BTC</th><th class="num">Hops</th></tr></thead>
        <tbody>${(trace.sinks || []).map((sink) => `
          <tr><td class="mono">${esc(shortKey(sink.entity))}</td>
            <td>${sink.kind === "mixer" ? "mixing service" : "cash-out / exchange"}</td>
            <td class="num">${btc(sink.amount)}</td><td class="num">${num(sink.hops)}</td></tr>
          <tr><td colspan="4" class="path">${esc((sink.path || []).map(shortKey).join(" → "))}</td></tr>
        `).join("")}</tbody>
      </table>
    </div>`).join("");
}

/* ------------------------------------------------------------------- wire */
function wire() {
  document.querySelectorAll("[data-mode]").forEach((chip) => {
    chip.onclick = () => {
      document.querySelectorAll("[data-mode]").forEach((other) => other.classList.remove("on"));
      chip.classList.add("on");
      V.mode = chip.dataset.mode;
      renderGraph();
    };
  });

  document.getElementById("reportBtn").onclick = () => {
    if (!V.selected) return;
    document.getElementById("modalFrame").src = `/report/${encodeURIComponent(V.selected)}`;
    document.getElementById("modal").hidden = false;
  };
  document.getElementById("modalClose").onclick = () => {
    document.getElementById("modal").hidden = true;
    document.getElementById("modalFrame").src = "about:blank";
  };
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") document.getElementById("modalClose").click();
  });

  document.getElementById("ackBtn").onclick = async () => {
    if (!V.selected) return;
    try {
      await api(`/alerts/${encodeURIComponent(V.selected)}/status`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: "acknowledged" }),
      });
      const refreshed = await api("/alerts");
      const match = (refreshed.alerts || []).find((item) => item.entity_key === V.selected);
      const alert = (V.payload.alerts || []).find((item) => item.entity === V.selected);
      if (alert && match) alert.status = match.status;
      renderRail();
      renderDetail();
      toast("Marked acknowledged; the system remembers that between runs");
    } catch (error) {
      toast(`Could not update: ${error.message}`);
    }
  };
}

/* ------------------------------------------------------------------- main */
(async function main() {
  await NETRA.init();
  V.windows = await NETRA.loadWindows();
  if (!V.windows.length) {
    document.querySelector(".work").innerHTML = emptyState(
      "No analysis in the store yet.",
      "Run the analysis from the Ingest page; this page reads the result."
    );
    return;
  }

  // Investigation is a per-batch activity -- the deltas only mean something
  // against a previous batch -- so the default is a single batch rather than the
  // whole capture. But NOT the newest one: a capture usually ends mid-period, so
  // the last batch is often a fragment with almost nothing in it. Default to the
  // busiest batch, which is the one worth looking at.
  const requested = new URLSearchParams(location.search).get("window");
  const busiest = V.windows.reduce(
    (best, item) => (item.transactions > best.transactions ? item : best), V.windows[0]);
  V.active = requested || String(busiest.id);
  document.getElementById("windowPicker").innerHTML =
    `<a class="chip ${V.active === "all" ? "on" : ""}" href="?window=all">All batches</a>` +
    NETRA.windowSwitcher(V.windows, V.active);

  wire();

  try {
    V.payload = await loadPayload(V.active);
  } catch (error) {
    toast(`Could not load the batch: ${error.message}`);
    return;
  }

  (V.payload.traces || []).forEach((trace) => {
    (V.tracesBySeed[trace.seed] = V.tracesBySeed[trace.seed] || []).push(trace);
  });

  NETRA.setCounters([
    { label: "batch", value: V.payload.window.label.replace(/^window-/, "") },
    { label: "groups examined", value: num(V.payload.corpus?.entities ?? V.payload.meta.entities) },
    { label: "leads", value: num((V.payload.alerts || []).length) },
    { label: "raised for review", value: num(V.payload.meta.flagged_entities) },
  ]);
  NETRA.setStrip({
    provenance: `engine ${V.payload.meta.engine_version} · RandomForest (windowed) · ` +
      `explanations: ${V.payload.metrics ? "decision-path contributions" : "—"}`,
    generated: `generated ${String(V.payload.meta.generated_at).replace("T", " ").slice(0, 19)}`,
    state: V.payload.window.label,
  });

  renderRail();
  renderGraph();
  const first = (V.payload.alerts || [])[0];
  if (first) selectLead(first.entity);
})();
