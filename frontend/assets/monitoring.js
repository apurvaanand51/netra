/* Monitoring page: the deltas, the lifecycle, and how fast detection happens.
 *
 * The transport replays the batches in order, in place — no page reload, so the
 * feed visibly changes batch by batch. Nothing is simulated: each step fetches
 * the same payload the batch produced when it ran.
 */

"use strict";

const M = {
  summary: null,
  batches: [],
  index: 0,
  payload: null,
  playing: false,
  timer: null,
  filter: "",
};

/* ------------------------------------------------------------------ render */
function renderHeadline() {
  const summary = M.summary;
  const detection = summary.time_to_detection || {};
  const cards = [
    { label: "Batches processed", value: num(M.batches.length),
      note: `${num(summary.store?.entities)} wallet groups indexed · ${num(summary.store?.merged_entities)} merges found` },
    { label: "Changes detected", value: num(summary.store?.events),
      note: Object.entries(summary.event_types || {}).slice(0, 3)
        .map(([type, count]) => `${EVENT_PLAIN[type] || type} ${count}`).join(" · ") || "none yet" },
    { label: "Leads open", value: num(summary.open_alerts),
      note: Object.entries(summary.alert_status || {})
        .map(([status, count]) => `${status.replace(/_/g, " ")} ${count}`).join(" · ") || "none" },
    { label: "Median batches to first flag", value: detection.median_window === null || detection.median_window === undefined
        ? "—" : num(detection.median_window, 1),
      note: detection.planted_entities
        ? `${num(detection.detected)} of ${num(detection.planted_entities)} planted cases caught`
        : "not measurable on this data" },
  ];
  document.getElementById("headline").innerHTML = cards.map((card) => `
    <div class="card">
      <h2>${card.label}</h2>
      <div class="figure">${typeof card.value === "string" ? esc(card.value) : esc(card.value)}</div>
      <p class="sub" style="margin:6px 0 0">${esc(card.note)}</p>
    </div>`).join("");
}

function renderTransport() {
  const batch = M.batches[M.index];
  if (!batch) return;
  document.getElementById("batchLabel").innerHTML =
    `Batch <b class="mono">${batch.index}</b> of <b class="mono">${batch.total}</b> &nbsp;` +
    `<span class="muted mono">${esc(String(batch.label).replace(/^window-/, ""))}</span>`;
  const ratio = batch.total > 1 ? (batch.index - 1) / (batch.total - 1) : 1;
  document.getElementById("scrub").innerHTML = `<i style="width:${ratio * 100}%"></i>`;
  document.getElementById("firstBtn").disabled = M.index === 0;
  document.getElementById("prevBtn").disabled = M.index === 0;
  document.getElementById("nextBtn").disabled = M.index >= M.batches.length - 1;
}

function renderFilters() {
  const events = M.payload?.events || [];
  const types = [...new Set(events.map((event) => event.type))];
  document.getElementById("filters").innerHTML = types.length > 1
    ? `<button class="chip on" data-filter="">All</button>` +
      types.map((type) => `<button class="chip" data-filter="${type}">${EVENT_PLAIN[type] || type}</button>`).join("")
    : "";
  document.querySelectorAll("#filters .chip").forEach((chip) => {
    chip.onclick = () => {
      document.querySelectorAll("#filters .chip").forEach((other) => other.classList.remove("on"));
      chip.classList.add("on");
      M.filter = chip.dataset.filter;
      renderFeed();
    };
  });
}

function renderFeed() {
  const all = M.payload?.events || [];
  const events = M.filter ? all.filter((event) => event.type === M.filter) : all;
  document.getElementById("eventCount").textContent = `${all.length} event(s)`;
  document.getElementById("feedEmpty").hidden = events.length > 0;

  document.getElementById("feed").innerHTML = events.map((event) => {
    const hasDelta = event.risk_from !== null && event.risk_from !== undefined && event.risk_to !== null;
    const delta = hasDelta
      ? `<span class="delta ${event.risk_to > event.risk_from ? "up" : "down"}">` +
        `${esc(event.risk_from)} &rarr; ${esc(event.risk_to)}</span>` : "";
    const why = event.detail
      ? `<div class="why">${esc(event.detail)}</div>`
      : (event.absorbed?.length
        ? `<div class="why"><span class="muted">absorbed</span> ${esc(event.absorbed.map(shortKey).join(", "))}</div>`
        : `<div class="why muted">${esc(event.title || "")}</div>`);
    const clickable = event.type !== "CLUSTER_MERGE";
    return `<div class="ev ${esc(event.severity)}">
      <div><span class="type">${esc(EVENT_PLAIN[event.type] || event.type)}</span>
        <span class="ent">${esc(shortKey(event.entity))}</span> ${delta}</div>
      ${why}
      ${clickable ? `<div style="margin-top:5px"><a class="btn sm"
        href="investigate.html?window=${M.payload.window.id}#${esc(event.entity)}">Open lead</a></div>` : ""}
    </div>`;
  }).join("");
}

function renderBatchTable() {
  document.getElementById("batchTable").innerHTML = `
    <thead><tr><th>Batch</th><th class="num">Transactions</th><th class="num">Groups</th>
      <th class="num">Changes</th></tr></thead>
    <tbody>${M.batches.map((batch) => `
      <tr style="${batch.index === M.index + 1 ? "background:var(--panel-2)" : ""}">
        <td><a href="#" data-jump="${batch.index - 1}">${esc(String(batch.label).replace(/^window-/, ""))}</a></td>
        <td class="num">${num(batch.transactions)}</td>
        <td class="num">${num(batch.entities)}</td>
        <td class="num">${num(batch.events)}</td>
      </tr>`).join("")}</tbody>`;
  document.querySelectorAll("[data-jump]").forEach((link) => {
    link.onclick = (event) => {
      event.preventDefault();
      stop();
      showBatch(Number(link.dataset.jump));
    };
  });
}

function renderLifecycle() {
  const statuses = M.summary.alert_status || {};
  const severity = M.summary.event_severity || {};
  const statusColour = {
    new: "var(--crit)", acknowledged: "var(--high)", investigating: "var(--med)",
    closed_false_positive: "var(--low)", closed_escalated: "var(--low)",
  };
  const total = Object.values(statuses).reduce((sum, value) => sum + value, 0) || 1;
  const stack = Object.entries(statuses).map(([status, count]) =>
    `<i style="width:${(count / total * 100).toFixed(2)}%;background:${statusColour[status] || "var(--ink-3)"}"
        title="${esc(status)}"></i>`).join("");

  document.getElementById("lifecycle").innerHTML = `
    <div class="stack" style="height:12px">${stack}</div>
    <div class="legend">${Object.entries(statuses).map(([status, count]) => `
      <div class="legendRow" style="grid-template-columns:10px 1fr auto">
        <i style="background:${statusColour[status] || "var(--ink-3)"}"></i>
        <span>${esc(status.replace(/_/g, " "))}</span><strong>${num(count)}</strong>
      </div>`).join("")}</div>
    <h2 style="margin-top:16px">Changes by severity</h2>
    <div class="legend">${Object.entries(severity).map(([level, count]) => `
      <div class="legendRow" style="grid-template-columns:10px 1fr auto">
        <i style="background:${BAND_COLOUR[level] || "var(--ink-3)"}"></i>
        <span>${esc(level)}</span><strong>${num(count)}</strong>
      </div>`).join("")}</div>
    <p class="muted small" style="margin-top:10px">An acknowledged lead keeps its row; the decision is stored,
      so the next batch does not ask you to look at it again as though it were new.</p>`;
}

function renderDetection() {
  const detection = M.summary.time_to_detection || {};
  if (!detection.planted_entities) {
    document.getElementById("detection").innerHTML = emptyState(
      "Not measurable on this data.",
      "Time-to-detection needs a known answer key; this dataset has none matching the ingested batches."
    );
    return;
  }
  document.getElementById("detection").innerHTML = `
    <div class="figure"><strong>${num(detection.median_window, 1)}</strong>
      <span>batches, median, to first flag a planted case</span></div>
    <div class="statRow" style="margin-top:10px"><span>Planted cases in the data</span>
      <strong>${num(detection.planted_entities)}</strong></div>
    <div class="statRow"><span>Caught</span><strong>${num(detection.detected)}</strong></div>
    <div class="statRow"><span>Never flagged</span><strong>${num(detection.never_detected)}</strong></div>
    <div class="statRow"><span>Caught in the first batch</span>
      <strong>${num(detection.detected_in_first_window)}</strong></div>
    <div class="caveat">Detection speed is only quotable because the cases were <b>planted by us</b>. On real
      traffic nobody knows the answer key, so this figure would not exist — which is exactly why we generate
      the data.</div>`;
}

function renderAlerts() {
  const alerts = M.summary.alerts || [];
  if (!alerts.length) {
    document.getElementById("alertTable").innerHTML =
      emptyState("No leads open.", "Nothing crossed the alerting floor in any batch.");
    return;
  }
  document.getElementById("alertTable").innerHTML = `
    <table class="data">
      <thead><tr><th>Group</th><th class="num">Now</th><th class="num">Peak</th><th>Status</th></tr></thead>
      <tbody>${alerts.slice(0, 12).map((alert) => `
        <tr><td><a href="investigate.html?window=${M.payload.window.id}#${esc(alert.entity_key)}"
              class="mono">${esc(shortKey(alert.entity_key))}</a></td>
          <td class="num">${num(alert.current_risk)}</td>
          <td class="num">${num(alert.peak_risk)}</td>
          <td><span class="band ${bandOf(alert.current_risk)}">${esc(alert.status.replace(/_/g, " "))}</span></td>
        </tr>`).join("")}</tbody>
    </table>`;
}

/* --------------------------------------------------------------- transport */
function stop() {
  M.playing = false;
  document.getElementById("playBtn").innerHTML = "&#9654;";
  clearInterval(M.timer);
  M.timer = null;
}

function play() {
  if (M.playing) return stop();
  if (M.index >= M.batches.length - 1) M.index = 0;
  M.playing = true;
  document.getElementById("playBtn").innerHTML = "&#10073;&#10073;";
  M.timer = setInterval(() => {
    if (M.index >= M.batches.length - 1) return stop();
    showBatch(M.index + 1);
  }, 2400);
}

async function showBatch(index) {
  if (!M.batches.length) return;
  M.index = Math.max(0, Math.min(M.batches.length - 1, index));
  const batch = M.batches[M.index];

  // Building a batch's payload re-correlates it (graph included), which takes
  // seconds the first time. Without a sign of life, clicking Next looks like a
  // broken button for ten seconds -- and the presenter is the one staring at it.
  const label = document.getElementById("batchLabel");
  const previousHtml = label.innerHTML;
  label.innerHTML = `<span class="muted">building batch ${batch.index}…</span>`;
  for (const id of ["firstBtn", "prevBtn", "nextBtn", "playBtn"]) {
    document.getElementById(id).disabled = true;
  }

  try {
    M.payload = await loadPayload(String(batch.id));
  } catch (error) {
    toast(`Could not load batch ${batch.id}: ${error.message}`);
    label.innerHTML = previousHtml;
    return;
  } finally {
    for (const id of ["firstBtn", "prevBtn", "nextBtn", "playBtn"]) {
      document.getElementById(id).disabled = false;
    }
  }

  history.replaceState(null, "", `?window=${batch.id}`);
  M.filter = "";
  renderTransport();
  renderFilters();
  renderFeed();
  renderBatchTable();
  renderAlerts();
  NETRA.setStrip({ state: M.payload.window.label });
}

/* ------------------------------------------------------------------- main */
(async function main() {
  await NETRA.init();
  try {
    M.summary = await api("/monitoring");
  } catch (error) {
    document.querySelector(".work").innerHTML = emptyState(
      "No monitoring history yet.", "Run the analysis from the Ingest page first."
    );
    return;
  }
  M.summary.alerts = (await api("/alerts")).alerts || [];
  M.batches = M.summary.batches || [];
  if (!M.batches.length) {
    document.querySelector(".work").innerHTML = emptyState("No batches recorded.", "Nothing to replay.");
    return;
  }

  const requested = Number(new URLSearchParams(location.search).get("window"));
  M.index = M.batches.findIndex((batch) => batch.id === requested);
  if (M.index < 0) M.index = M.batches.length - 1;

  renderHeadline();
  renderTransport();
  renderLifecycle();
  renderDetection();

  document.getElementById("firstBtn").onclick = () => { stop(); showBatch(0); };
  document.getElementById("prevBtn").onclick = () => { stop(); showBatch(M.index - 1); };
  document.getElementById("nextBtn").onclick = () => { stop(); showBatch(M.index + 1); };
  document.getElementById("playBtn").onclick = play;
  document.getElementById("scrub").onclick = (event) => {
    const rect = event.currentTarget.getBoundingClientRect();
    stop();
    showBatch(Math.round(((event.clientX - rect.left) / rect.width) * (M.batches.length - 1)));
  };
  document.addEventListener("keydown", (event) => {
    if (document.activeElement?.tagName === "INPUT") return;
    if (event.key === "ArrowRight") document.getElementById("nextBtn").click();
    if (event.key === "ArrowLeft") document.getElementById("prevBtn").click();
    if (event.key === " ") { event.preventDefault(); play(); }
  });

  await showBatch(M.index);
})();
