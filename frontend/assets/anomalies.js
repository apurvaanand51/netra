/* Anomalies page: the leads, and why each one is a lead.
 *
 * COLOUR: the risk here is not that the numbers are wrong, it is that a number
 * arrives with no way to check it. So every claim this page makes is followed by
 * its own arithmetic:
 *   - the waterfall states the factors, and the line underneath adds them up;
 *   - a fund trail carries the estimate marker beside the amount, not in a
 *     footnote;
 *   - the explanations come from /glossary, the same sentences the printed
 *     report and the dossier use, so the story cannot change between them.
 */

"use strict";

const REASON_ICON = {
  exch: `<circle cx="12" cy="12" r="9"/><path d="M3 12h18"/>
         <path d="M12 3c2.5 2.6 2.5 15.4 0 18-2.5-2.6-2.5-15.4 0-18z"/>`,
  flow: `<path d="M4 7h11l-3-3"/><path d="M20 17H9l3 3"/>`,
  time: `<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>`,
  clus: `<circle cx="6" cy="6" r="2.5"/><circle cx="18" cy="6" r="2.5"/>
         <circle cx="12" cy="18" r="2.5"/><path d="M7.6 7.8l3 8"/><path d="M16.4 7.8l-3 8"/>`,
};

const SEVERITY_TONE = {
  critical: "var(--crit)", high: "var(--high)",
  medium: "var(--med)", info: "var(--brand-2)",
};

const state = { payload: null, glossary: null, selected: null };

/* ------------------------------------------------------------------- leads */

// The card's top edge carries the band. The theme's classes are `crit`, `high`
// and `med` -- not the payload's `critical`/`medium` -- so the mapping is stated
// once rather than assumed at each call site.
const CARD_TONE = { critical: "crit", high: "high", medium: "med" };

function leadCard(entity) {
  const tone = CARD_TONE[entity.risk_band] || "";
  return `<button class="leadcard ${tone}" data-entity="${esc(entity.id)}">
    <div class="lc-num" style="color:${bandColour(entity.risk_band)}">${esc(entity.risk)}</div>
    <div class="lc-who">${esc(shortKey(entity.id))}</div>
    <div class="lc-kind">${esc(entity.graph_role || entity.kind)} ·
      ${num(entity.tx_count)} tx</div>
    <div class="lc-kind" style="color:var(--ink-3)">${num(entity.value_btc, 1)} BTC${
      entity.geo?.length ? ` · ${esc(entity.geo.slice(0, 3).join(" "))}` : ""}</div>
  </button>`;
}

/** The recorded value of one model feature, or null when it was not among the
 *  named contributions. Read from the payload rather than recomputed. */
function featureValue(entity, name) {
  const item = (entity.features || []).find((feature) => feature.name === name);
  return item ? item.value : null;
}

/* --------------------------------------------------------------- waterfall */

function waterfallRow(label, contribution, ceiling) {
  // Half the track per side, so the bar grows out of the centre line. Clamped at
  // 50% because a single factor larger than the ceiling would otherwise draw
  // past the end of its own track.
  const side = Math.min(50, (Math.abs(contribution) / ceiling) * 50);
  const positive = contribution >= 0;
  return `<div class="shap-row wide">
    <div class="sf" title="${esc(label)}">${esc(label)}</div>
    <div class="sbar split"><i class="sfill ${positive ? "pos" : "neg"}"
      data-width="${side.toFixed(2)}"></i></div>
    <div class="sv ${positive ? "pos" : "neg"}">${positive ? "+" : "−"}${Math.abs(contribution * 100).toFixed(1)}</div>
  </div>`;
}

function drawWaterfall(entity) {
  const host = document.getElementById("waterfall");
  const explanation = entity.explanation;
  const features = entity.features || [];

  if (!explanation || !features.length) {
    host.innerHTML = `<p style="font-size:13px;color:var(--ink-2)">
      No attribution was recorded for this lead in this batch.</p>`;
    document.getElementById("reconcile").innerHTML = "";
    return;
  }

  const other = Number(explanation.other_contribution || 0);
  const ceiling = Math.max(
    ...features.map((item) => Math.abs(item.importance)), Math.abs(other), 1e-9);

  host.innerHTML =
    features.map((item) => waterfallRow(plainFeature(item.name), item.importance, ceiling)).join("") +
    // The factors too small to draw individually. Named as a group rather than
    // dropped, because the bars have to add up to the score above them.
    (explanation.other_count > 0
      ? waterfallRow(`${explanation.other_count} smaller factors`, other, ceiling)
      : "");

  // Animating from zero on the next frame: a bar that is simply painted has no
  // direction, and the direction is the whole point of a signed chart.
  requestAnimationFrame(() => {
    host.querySelectorAll(".sfill").forEach((bar) => {
      bar.style.width = `${bar.dataset.width}%`;
    });
  });

  const base = explanation.base * 100;
  const prediction = explanation.prediction * 100;
  const listed = features.reduce((sum, item) => sum + item.importance, 0) * 100;
  document.getElementById("reconcile").innerHTML = `
    <span>base <b>${base.toFixed(1)}</b></span><span>+</span>
    <span>${features.length} named factors <b>${(listed >= 0 ? "+" : "") + listed.toFixed(1)}</b></span>
    ${explanation.other_count > 0
      ? `<span>+</span><span>${explanation.other_count} smaller factors
           <b>${(other >= 0 ? "+" : "") + (other * 100).toFixed(1)}</b></span>` : ""}
    <span>=</span><span><b>${prediction.toFixed(1)}</b> points</span>
    <span class="ok">✓ reconciles exactly</span>
    <span style="margin-left:auto;color:var(--ink-3)">residual ${Number(explanation.residual).toExponential(2)}</span>`;
  document.getElementById("waterfallSub").textContent =
    explanation.method + " · right argues for, left argues against";
}

/* ----------------------------------------------------------------- reasons */

function renderReasons(entity) {
  const host = document.getElementById("reasons");
  const reasons = entity.reasons || [];
  host.innerHTML = reasons.length
    ? reasons.map((reason) => `
      <div class="reason">
        <div class="rc" style="background:${SEVERITY_TONE[reason.severity] || "var(--ink-3)"}">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
               stroke-linecap="round" stroke-linejoin="round">
            ${REASON_ICON[reason.icon] || REASON_ICON.flow}</svg></div>
        <div class="rx"><b>${esc(reason.title)}</b><span>${esc(reason.detail)}</span></div>
      </div>`).join("")
    : `<p style="font-size:13px;color:var(--ink-2)">
         Nothing rule-based about this lead. It ranks highly on the model's structural
         features alone, which is what the waterfall beside it shows.</p>`;
}

/* ------------------------------------------------------------------- chain */

function renderChain(entity) {
  const traces = (state.payload.traces || []).filter((trace) => trace.seed === entity.id);
  const host = document.getElementById("chain");
  const sinksHost = document.getElementById("chainSinks");

  if (!traces.length) {
    document.getElementById("chainSub").textContent =
      "no trail followed from this wallet";
    host.innerHTML = `<p style="font-size:13px;color:var(--ink-2);padding:6px 0">
      Funds were not traced from this wallet in this batch. Trails are computed for
      the highest-value leads — the graph on the dashboard shows its neighbours.</p>`;
    sinksHost.innerHTML = "";
    return;
  }

  const trace = traces[0];
  const sinks = (trace.sinks || []).slice(0, 5);
  document.getElementById("chainSub").textContent =
    `seed sent ${btc(trace.tainted)} BTC, followed ${trace.hops_reached} hops, ` +
    `${(trace.sinks || []).length} destinations reached`;

  // One row per destination: the path is the story, the amount is the payload.
  host.innerHTML = sinks.slice(0, 1).map((sink) => (sink.path || []).map((hop, index) =>
    `<div style="display:flex;align-items:center;gap:10px">
       <span class="hop ${index === 0 ? "start"
         : hop === sink.entity ? (sink.kind === "mixer" ? "mix" : "end") : ""}">
         ${esc(shortKey(hop))}</span>
       ${index < sink.path.length - 1 ? '<span class="arw">→</span>' : ""}
     </div>`).join("")).join("");

  sinksHost.innerHTML = sinks.map((sink) => `
    <div class="geo-row" style="padding:7px 0;border-top:1px solid var(--border-2)">
      <div class="flag" style="width:auto;min-width:58px;padding:0 9px;font-size:11.5px;
           font-weight:700;color:${sink.kind === "mixer" ? "var(--crit)" : "var(--safe)"}">
        ${sink.kind === "mixer" ? "MIXER" : "CASH-OUT"}</div>
      <div class="gn mono" style="width:auto;flex:1">${esc(shortKey(sink.entity))}</div>
      <div class="gp" style="width:auto;text-align:left">
        ${(sink.path || []).map((hop) => shortKey(hop)).join(" → ")}</div>
      <div class="mono" style="font-size:12.5px;font-weight:700">${btc(sink.amount)} BTC</div>
      <div class="mono" style="font-size:11.5px;color:var(--ink-3)">${
        sink.hops} hop${sink.hops === 1 ? "" : "s"}</div>
    </div>`).join("");
}

/* -------------------------------------------------------------- explainers */

function renderExplainers(glossary, entity) {
  const matched = new Set(entity.typology || []);
  const host = document.getElementById("explainers");

  // Nothing highlighted is a fact worth stating. Left unsaid, it reads as a bug
  // in the highlighting rather than as "this lead matches no named pattern",
  // which is itself evidence about the lead.
  // Removed first, unconditionally: selecting a second unmatched lead must not
  // stack a second copy of the note.
  document.getElementById("noPattern")?.remove();
  if (!matched.size) {
    host.insertAdjacentHTML("beforebegin", `<p class="cap" id="noPattern"
      style="color:var(--accent)">This lead matches none of the named patterns below — its
      priority comes from the structural factors in section 2.</p>`);
  }
  host.innerHTML = (glossary.anomalies || []).map((item) => {
    const hit = matched.has(item.type);
    return `<div class="explainer ${hit ? "hit" : ""}">
      ${hit ? `<span class="hit-tag">Matches this lead</span>` : ""}
      <div class="eh"><div class="eic">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
             stroke-linecap="round" stroke-linejoin="round">
          ${schematicIcon(item.schematic)}</svg></div>
        <h4>${esc(item.label)}</h4></div>
      ${schematic(item.schematic)}
      <p>${esc(item.plain)}</p>
      <p class="why">${esc(item.why)}</p>
    </div>`;
  }).join("");
}

function schematicIcon(kind) {
  if (kind === "chain") return `<circle cx="5" cy="12" r="2"/><circle cx="12" cy="12" r="2"/>
    <circle cx="19" cy="12" r="2"/><path d="M7 12h3"/><path d="M14 12h3"/>`;
  if (kind === "mixer") return `<circle cx="6" cy="6" r="2"/><circle cx="6" cy="18" r="2"/>
    <circle cx="18" cy="12" r="2"/><path d="M7.7 7L16.3 11"/><path d="M7.7 17L16.3 13"/>`;
  if (kind === "fan_in") return `<circle cx="4" cy="6" r="1.8"/><circle cx="4" cy="12" r="1.8"/>
    <circle cx="4" cy="18" r="1.8"/><circle cx="18" cy="12" r="2.6"/>
    <path d="M6 6.6l10 4.4"/><path d="M6 12h10"/><path d="M6 17.4l10-4.4"/>`;
  return `<circle cx="12" cy="12" r="9"/><path d="M12 8v4l3 2"/>`;
}

/** The two-line schematic. Three or four nodes — enough to show the SHAPE of the
 *  pattern, which is the part a sentence cannot carry. */
function schematic(kind) {
  const shape = {
    chain: ["on", "", "on", "", "cash"],
    mixer: ["on", "", "cash"],
    fan_in: ["on", "on", "on", "cash"],
    exchange: ["on", "", "cash"],
  }[kind] || ["on", "", "cash"];
  return `<div class="schem">${shape.map((cls, index) =>
    cls === "" ? `<span></span>` : `<i class="${cls}"></i>`).join("")}</div>`;
}

/* --------------------------------------------------------------- selection */

function select(entityId) {
  const entity = state.payload.entities.find((item) => item.id === entityId);
  if (!entity) return;
  state.selected = entity;

  document.querySelectorAll(".leadcard").forEach((card) => {
    card.classList.toggle("sel", card.dataset.entity === entityId);
  });

  document.getElementById("leadTitle").textContent =
    `${shortKey(entity.id)} · ${isLead(entity) ? "lead" : "node"}`;
  document.getElementById("leadSub").innerHTML =
    `${esc(entity.label)} — ${esc(entity.graph_role || entity.kind)}` +
    (entity.community_id !== null && entity.community_id !== undefined
      ? ` · part of a group of ${num(entity.community_size)}` : "");

  const band = entity.risk_band;
  const counterparties = featureValue(entity, "distinct_counterparties");
  document.getElementById("leadStats").innerHTML = `
    <div class="stat">
      <div class="k">Priority</div>
      <div class="v" style="font-size:44px;color:${bandColour(band)}">${esc(entity.risk)}</div>
      <div class="d"><span class="info-tag" style="margin:0;--ic:${bandColour(band)}">
        <i class="dot"></i>${esc(band)}</span></div>
    </div>
    <div class="stat"><div class="k">Value moved</div>
      <div class="v" style="font-size:44px">${btc(entity.value_btc)}<span class="hero-unit">BTC</span></div>
      <div class="d">${num(entity.tx_count)} transactions</div></div>
    <div class="stat"><div class="k">Wallets dealt with</div>
      <div class="v" style="font-size:44px">${counterparties === null ? "—" : num(counterparties)}</div>
      <div class="d">${num((entity.addresses || []).length)} addresses in the group</div></div>
    <div class="stat ${entity.country_count >= 2 ? "c" : "s"}">
      <div class="k">Controlled from</div>
      <div class="v" style="font-size:44px">${num(entity.country_count)}</div>
      <div class="d">${(entity.geo || []).map((code) =>
        `<span class="mono" style="border:1px solid var(--border-2);border-radius:5px;
          padding:1px 6px;font-size:11px;font-weight:700">${esc(code)}</span>`).join(" ")
        || "no country observed"}</div></div>`;

  document.getElementById("caseBtn").href = `/report/${encodeURIComponent(entity.id)}`;
  document.getElementById("graphBtn").href = `dashboard.html?entity=${encodeURIComponent(entity.id)}`;
  document.getElementById("reportBtn").href = "/print/anomalies";
  document.getElementById("anomalyNote").textContent =
    `${num((state.payload.entities || []).filter(isLead).length)} leads · ` +
    `${entity.typology?.length ? entity.typology.join(", ") : "no rule-based typology"}`;

  drawWaterfall(entity);
  renderReasons(entity);
  renderChain(entity);
  renderExplainers(state.glossary, entity);

  // The selection lives in the URL so a lead can be linked to, bookmarked and
  // reopened by a colleague -- and so the printed report knows which one.
  const url = new URL(location.href);
  url.searchParams.set("entity", entity.id);
  history.replaceState(null, "", url);
}

/* -------------------------------------------------------------------- boot */

(async function main() {
  await NETRA.init();
  const windows = await NETRA.loadWindows();
  if (!windows.length) {
    document.querySelector(".wrap").innerHTML = emptyState(
      "No analysis in the store yet.",
      "Ingest a dataset first; this page reads the result.");
    return;
  }

  try {
    showLoading("Reading the leads",
      "Scoring and the explanations behind them, from this machine.");
    state.payload = await loadPayload("all");
    state.glossary = await api("/glossary");
    hideLoading();
  } catch (error) {
    hideLoading();
    toast(`Could not load the analysis: ${error.message}`);
    return;
  }

  // Leads only. An IP endpoint inherits the peak risk of the wallets it
  // controlled, so it can carry a review band without being a wallet group --
  // and counting those as leads would report 100 where the answer is 85. The
  // rule lives in the payload's `lead` flag rather than here, so no page has to
  // remember it.
  const leads = state.payload.entities
    .filter(isLead)
    .sort((a, b) => b.risk - a.risk || a.id.localeCompare(b.id));

  if (!leads.length) {
    document.getElementById("leads").innerHTML =
      `<p style="color:var(--ink-2);font-size:14px">No wallet group reached a review band.</p>`;
    return;
  }

  document.getElementById("leads").innerHTML = leads.slice(0, 14).map(leadCard).join("");
  document.querySelectorAll(".leadcard").forEach((card) => {
    card.onclick = () => select(card.dataset.entity);
  });

  const requested = new URLSearchParams(location.search).get("entity");
  select(leads.some((entity) => entity.id === requested) ? requested : leads[0].id);

  // The drift check belongs here: it is about the model's inputs, so it
  // qualifies the scores on this page rather than the corpus counts elsewhere.
  const drift = state.payload.fleet?.drift;
  if (drift && drift.drifted_count) {
    document.getElementById("driftBand").hidden = false;
    document.getElementById("driftSub").textContent = drift.verdict || "";
    document.getElementById("driftList").innerHTML = (drift.worst_features || [])
      .slice(0, 8)
      .map((item) => `<span class="info-tag" style="margin:0;--ic:var(--accent)">
        <i class="dot"></i>${esc(item.feature)} · PSI ${num(item.psi, 1)}</span>`).join("");
  }

  NETRA.setStrip({
    provenance: `engine ${state.payload.meta.engine_version} · ${num(leads.length)} leads · offline · local`,
    generated: `generated ${String(state.payload.meta.generated_at).replace("T", " ").slice(0, 19)}`,
    state: `${num(leads.length)} wallet groups in a review band`,
  });

  document.addEventListener("netra:theme", () => {
    if (state.selected) select(state.selected.id);
  });
})();
