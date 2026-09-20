/* Dataset page: what is in the data that was read.
 *
 * CHART-FIRST, AND EVERY COLOUR COMES FROM THE THEME.
 * Each band is one question, one visual, at most one caption line. Nothing here
 * is written by hand -- all of it comes from the payload, so the page cannot
 * describe numbers the tool did not produce.
 *
 * Colours are resolved from the CSS custom properties at draw time and every
 * chart is redrawn when the theme changes. Hard-coding them would leave the dark
 * theme drawing pale blue on white, which is the sort of thing nobody notices
 * until it is on a projector.
 */

"use strict";

const charts = {};   // key -> Chart, so a redraw replaces rather than layers

function baseOptions(tokens) {
  return {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { labels: { color: tokens.ink2, font: { size: 13 }, boxWidth: 14 } },
      tooltip: {
        backgroundColor: tokens.ink,
        titleFont: { size: 13 }, bodyFont: { size: 13 },
        padding: 10, cornerRadius: 8, displayColors: false,
      },
    },
  };
}

/* ------------------------------------------------------------------ charts */

function drawDaily(corpus, tokens) {
  const daily = corpus.daily || [];
  const labels = daily.map((row) => String(row.day).slice(5));
  const axis = { grid: { display: false }, ticks: { color: tokens.ink3, font: { size: 13 } } };
  const yaxis = { beginAtZero: true, grid: { color: tokens.grid },
                  ticks: { color: tokens.ink3, font: { size: 13 } } };

  // Two charts rather than one dual-axis chart. Transactions and BTC differ by
  // three orders of magnitude, and overlaying them put the value area across the
  // bars -- the bars came out two-toned and neither series could be read.
  charts.daily?.destroy();
  charts.daily = new Chart(document.getElementById("dailyChart"), {
    type: "bar",
    data: { labels, datasets: [{
      label: "Transactions", data: daily.map((row) => row.transactions),
      backgroundColor: tokens.brand, borderRadius: 6, maxBarThickness: 74,
    }] },
    options: { ...baseOptions(tokens), plugins: { legend: { display: false } },
               scales: { x: axis, y: yaxis } },
  });

  charts.value?.destroy();
  charts.value = new Chart(document.getElementById("valueChart"), {
    type: "line",
    data: { labels, datasets: [{
      label: "BTC moved", data: daily.map((row) => row.value_btc),
      borderColor: tokens.accent,
      backgroundColor: `${tokens.accent}2E`,
      fill: true, tension: 0.32, borderWidth: 2.5, pointRadius: 4,
      pointBackgroundColor: tokens.accent, pointBorderColor: tokens.surface,
      pointBorderWidth: 2,
    }] },
    options: { ...baseOptions(tokens), plugins: { legend: { display: false } },
               scales: { x: axis, y: yaxis } },
  });
}

function drawHourly(corpus, tokens) {
  const hourly = corpus.hourly || [];
  const peak = (corpus.peak || {}).hour;

  charts.hourly?.destroy();
  charts.hourly = new Chart(document.getElementById("hourlyChart"), {
    type: "bar",
    data: {
      labels: hourly.map((row) => String(row.hour).padStart(2, "0")),
      datasets: [{
        label: "Transactions", data: hourly.map((row) => row.transactions),
        // The peak hour is the only bar in the accent colour, so the eye finds it
        // without reading the axis.
        backgroundColor: hourly.map((row) => (row.hour === peak ? tokens.accent : tokens.brand)),
        borderRadius: 4, maxBarThickness: 34,
      }],
    },
    options: { ...baseOptions(tokens), plugins: { legend: { display: false } },
               scales: {
                 x: { grid: { display: false }, ticks: { color: tokens.ink3, font: { size: 12 } },
                      title: { display: true, text: "hour of day", color: tokens.ink3, font: { size: 12 } } },
                 y: { beginAtZero: true, grid: { color: tokens.grid },
                      ticks: { color: tokens.ink3, font: { size: 13 } } },
               } },
  });

  if (peak !== null && peak !== undefined) {
    document.getElementById("peakCaption").textContent =
      `every hour, summed across the capture — busiest at ${String(peak).padStart(2, "0")}:00`;
  }
}

function drawSizes(corpus, tokens) {
  // Only classes that actually contain transactions. An empty row invites the
  // question "why is that there?" and the chart cannot answer it -- in this
  // dataset the largest class is genuinely empty because the generator caps
  // transfer size. A breakdown shows what exists, not what could.
  const rows = (corpus.size_classes || []).filter((row) => row.transactions > 0);
  const label = (row) => String(row.label).split(" (")[0];

  // Two bars per class: share of the count against share of the money. This is
  // the whole argument of the page in one picture, and it needs no reading.
  charts.sizes?.destroy();
  charts.sizes = new Chart(document.getElementById("sizeChart"), {
    type: "bar",
    data: {
      labels: rows.map(label),
      datasets: [
        { label: "Share of transactions", data: rows.map((row) => row.share_of_transactions * 100),
          backgroundColor: tokens.brand, borderRadius: 5 },
        { label: "Share of value moved", data: rows.map((row) => row.share_of_value * 100),
          backgroundColor: tokens.accent, borderRadius: 5 },
      ],
    },
    options: {
      ...baseOptions(tokens),
      indexAxis: "y",
      plugins: {
        legend: { position: "bottom", labels: { color: tokens.ink2, font: { size: 12.5 }, boxWidth: 12 } },
        tooltip: {
          backgroundColor: tokens.ink, padding: 10, cornerRadius: 8,
          callbacks: { label: (item) => `${item.dataset.label}: ${item.parsed.x.toFixed(1)}%` },
        },
      },
      scales: {
        x: { beginAtZero: true, grid: { color: tokens.grid },
             ticks: { color: tokens.ink3, font: { size: 12 },
                      callback: (value) => `${value}%` } },
        y: { grid: { display: false }, ticks: { color: tokens.ink2, font: { size: 12.5 } } },
      },
    },
  });
}

function drawBehaviour(behaviour, tokens) {
  const classes = behaviour.classes || [];
  const palette = [tokens.ink3, tokens.high, tokens.brand2, tokens.crit, tokens.accent];

  charts.behaviour?.destroy();
  charts.behaviour = new Chart(document.getElementById("behaviourChart"), {
    type: "doughnut",
    data: {
      labels: classes.map((row) => `${row.label} — ${pct(row.share, 1)}`),
      datasets: [{
        data: classes.map((row) => row.entities),
        backgroundColor: classes.map((_, index) => palette[index % palette.length]),
        borderColor: tokens.surface, borderWidth: 2,
      }],
    },
    options: {
      ...baseOptions(tokens),
      cutout: "62%",
      plugins: {
        legend: { position: "right", labels: { color: tokens.ink2, font: { size: 12.5 }, boxWidth: 12 } },
        tooltip: {
          backgroundColor: tokens.ink, padding: 10, cornerRadius: 8,
          callbacks: { label: (item) => `${num(item.parsed)} groups` },
        },
      },
    },
  });
}

/* ------------------------------------------------------------------- html */

function heroStats(corpus, behaviour) {
  const coverage = corpus.coverage || {};
  return [
    ["Transactions", num(corpus.transactions), "",
     `${num(corpus.span_hours, 0)} hours of capture`],
    ["Value moved", btc(corpus.total_value_btc), "BTC",
     `median transaction ${btc(corpus.median_value_btc)} BTC`],
    ["Wallet groups", num(corpus.entities), "",
     `${num(corpus.addresses)} addresses`],
    ["Flagged", num(coverage.entities_flagged), "",
     `${pct(coverage.flagged_share, 1)} of groups · ${pct(behaviour.value_share_of_flagged)} of value`],
  ].map(([label, value, unit, note], index) => `
    <div class="stat ${index === 3 ? "c" : ""}">
      <div class="k">${esc(label)}</div>
      <div class="v">${value}${unit ? `<span class="hero-unit">${esc(unit)}</span>` : ""}</div>
      <div class="d">${esc(note)}</div>
    </div>`).join("");
}

function dotGrid(entities) {
  // One square per wallet group. A 533-square grid says "we examined everything"
  // in a way no sentence manages, and the flagged minority is visible from the
  // back of the room.
  return entities.map((entity) =>
    `<i class="${entity.risk_band === "low" ? "" : esc(entity.risk_band)}"
        title="${esc(shortKey(entity.id))} · priority ${esc(entity.risk)}"></i>`).join("");
}

function geoBars(corpus, tokens) {
  const rows = (corpus.countries || []).slice(0, 6);
  const peak = Math.max(...rows.map((row) => row.share), 1e-9);
  return rows.map((row) => {
    // The amber portion sits INSIDE the blue bar, so one length carries both the
    // total and the flagged share instead of two bars that have to be compared
    // by eye. Drawn as a single gradient: two stacked elements inside an
    // overflow-hidden track is a layout that breaks the first time the height
    // changes.
    const total = (row.share / peak) * 100;
    const flagged = row.entities ? (row.flagged / row.entities) * total : 0;
    const fill = flagged > 0
      ? `linear-gradient(90deg,${tokens.accent} 0 ${flagged.toFixed(1)}%,` +
        `${tokens.brand} ${flagged.toFixed(1)}% 100%)`
      : tokens.brand;
    return `<div class="geo-row">
      <!-- No flag emoji: Windows has no glyphs for regional-indicator pairs, so
           a flag renders as the two letters of the country code anyway -- which
           is doubling the label rather than decorating it. The code IS the
           label, and it renders everywhere. -->
      <div class="flag mono" style="font-size:11.5px;font-weight:700">${esc(row.code)}</div>
      <div class="gn">groups controlled from here</div>
      <div class="gbar" title="${num(row.entities)} groups, ${num(row.flagged)} flagged">
        <i class="gf" style="width:${total.toFixed(1)}%;background:${fill}"></i>
      </div>
      <div class="gp">${pct(row.share, 0)}</div>
    </div>
    <div class="mono" style="font-size:11px;color:var(--ink-3);margin:-6px 0 2px 43px">
      ${num(row.entities)} groups${row.flagged
        ? ` · <span style="color:var(--accent);font-weight:700">${num(row.flagged)} flagged</span>`
        : " · none flagged"}</div>`;
  }).join("");
}

/* ------------------------------------------------------------------- main */

function paint(payload) {
  const tokens = themeTokens();
  const { corpus, behaviour } = payload;
  if (!corpus || !behaviour) {
    toast("This payload predates the traffic analysis; re-run the analysis from Ingest.");
    return;
  }

  document.getElementById("summary").textContent = corpus.summary || "";
  // The qualifications, at body size and marked as qualifications. They are
  // facts about the data, not disclaimers, so they get the same treatment as the
  // rest of the page rather than a smaller font in a corner.
  document.getElementById("notes").innerHTML = (corpus.notes || [])
    .map((note) => `<div style="display:flex;gap:9px;align-items:flex-start;
        font-size:13.5px;color:var(--ink-2);margin-bottom:5px">
        <span style="color:var(--accent);font-weight:700;flex-shrink:0">!</span>
        <span>${esc(note)}</span></div>`).join("");
  document.getElementById("scope").innerHTML =
    `Analysis of <b>everything read</b> — ${num(corpus.records)} records` +
    (corpus.span_start
      ? `, ${String(corpus.span_start).slice(0, 10)} to ${String(corpus.span_end).slice(0, 10)}`
      : "") +
    `. The flagged groups are shown throughout as a share of that whole, so a small
     finding cannot be mistaken for a large one.`;

  document.getElementById("heroStats").innerHTML = heroStats(corpus, behaviour);
  document.getElementById("geo").innerHTML = geoBars(corpus, tokens);
  document.getElementById("coverageStats").innerHTML = [
    ["Examined", num(corpus.coverage.entities_scored), ""],
    ["Flagged", num(corpus.coverage.entities_flagged), ""],
    ["Share of value", pct(behaviour.value_share_of_flagged, 0), ""],
  ].map(([label, value], index) => `
    <div class="stat ${index === 1 ? "c" : index === 2 ? "a" : "s"}">
      <div class="k">${esc(label)}</div>
      <div class="v" style="font-size:24px">${value}</div>
    </div>`).join("");

  // One square per WALLET GROUP. IP endpoints are subjects of interest too, but
  // they are not wallet groups and including them would inflate both the total
  // and the flagged count on a chart whose whole job is to be read at a glance.
  const groups = payload.entities.filter((entity) => entity.kind !== "ip");
  const flagged = groups.filter(isLead);
  document.getElementById("dots").innerHTML = dotGrid(groups);
  document.getElementById("dotsCaption").innerHTML =
    `${num(groups.length)} in total, <b style="color:var(--crit)">${num(flagged.length)}</b> raised for review`;

  drawDaily(corpus, tokens);
  drawHourly(corpus, tokens);
  drawSizes(corpus, tokens);
  drawBehaviour(behaviour, tokens);

  document.getElementById("datasetNote").textContent =
    `${num(corpus.distinct_ips)} IP addresses · ${num(corpus.distinct_countries)} countries · ` +
    `${num(corpus.distinct_asns)} network operators`;

  NETRA.setStrip({
    provenance: `engine ${payload.meta.engine_version} · whole-capture analysis · offline · local`,
    generated: `generated ${String(payload.meta.generated_at).replace("T", " ").slice(0, 19)}`,
    state: payload.window?.label || "",
  });
}

(async function main() {
  await NETRA.init();
  const windows = await NETRA.loadWindows();
  if (!windows.length) {
    document.querySelector(".wrap").innerHTML = emptyState(
      "No analysis in the store yet.",
      "Ingest a dataset first; this page reads the result.");
    NETRA.setStrip({ provenance: "no analysis loaded", generated: "", state: "offline · local" });
    return;
  }

  let payload;
  try {
    showLoading("Reading the analysis",
      "The whole-capture view is built on first request, then cached on this machine.");
    payload = await loadPayload("all");     // the complete ingested dataset
    hideLoading();
    paint(payload);
  } catch (error) {
    hideLoading();
    toast(`Could not load the analysis: ${error.message}`);
    return;
  }

  // The theme toggle changes every token the charts were drawn with, so they have
  // to be redrawn or they keep the old palette. The payload is kept, so this is a
  // repaint rather than a refetch.
  document.addEventListener("netra:theme", () => {
    try { paint(payload); } catch (error) { /* the next toggle will try again */ }
  });
})();
