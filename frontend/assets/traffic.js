/* Traffic page: analysis of the WHOLE capture.
 *
 * This page exists because the problem statement asks to analyse Bitcoin
 * transaction traffic -- not to detect fraud. The flagged groups are one output
 * of that analysis, and this page shows them as a share of everything read so a
 * reader can judge whether a lead is remarkable in context.
 */

"use strict";

function renderHeadline(corpus, behaviour) {
  const coverage = corpus.coverage || {};
  const cards = [
    {
      label: "Traffic read",
      value: num(corpus.records),
      note: `${num(corpus.transactions)} distinct transactions · ` +
            `${corpus.span_hours ? num(corpus.span_hours, 1) : "—"} hours of capture`,
    },
    {
      label: "Value moved",
      value: annotated(`${btc(corpus.total_value_btc)} <span style="font-size:13px">BTC</span>`, "corpus"),
      note: `median transaction ${btc(corpus.median_value_btc)} BTC ` +
            `&middot; average ${btc(corpus.mean_value_btc)} BTC`,
    },
    {
      label: "Wallet groups",
      value: num(corpus.entities),
      note: `${num(corpus.addresses)} addresses · ${num(corpus.distinct_ips)} IP addresses · ` +
            `${num(corpus.distinct_countries)} countries`,
    },
    {
      label: "Raised for review",
      value: annotated(`${num(coverage.entities_flagged)}`, "coverage"),
      note: `${pct(coverage.flagged_share)} of groups · ` +
            `${pct(behaviour.value_share_of_flagged)} of all value`,
    },
  ];
  document.getElementById("headline").innerHTML = cards.map((card) => `
    <div class="card">
      <h2>${card.label}</h2>
      <div class="figure">${typeof card.value === "string" ? card.value : esc(card.value)}</div>
      <p class="sub" style="margin:6px 0 0">${card.note}</p>
    </div>`).join("");
}

function renderValueShape(corpus) {
  const classes = corpus.size_classes || [];
  if (!classes.length) {
    document.getElementById("valueShape").innerHTML =
      emptyState("No transactions to size.", "This batch contained no parseable transfers.");
    return;
  }

  // Stacked bar: width by share of TRANSACTIONS, with the value share written on
  // each. The gap between the two is the finding -- many small payments carrying
  // almost no value, and few large ones carrying most of it.
  const palette = ["#3f4a58", "#5aa9e6", "#d99a2b", "#e08a52", "#e05252"];
  const stack = classes.map((row, index) =>
    `<i style="width:${(row.share_of_transactions * 100).toFixed(2)}%;background:${palette[index % palette.length]}"
        title="${esc(row.label)}"></i>`).join("");

  // Shares below 1% are printed with two decimals. Rounding a real but small
  // share to "0%" states something false, and "dust moved nothing" is exactly
  // the kind of conclusion a reader would draw from it.
  const share = (value) => pct(value, Math.abs(value) < 0.01 ? 2 : 0);

  const rows = classes.map((row, index) => `
    <div class="barRow">
      <span class="lbl"><i style="display:inline-block;width:8px;height:8px;background:${palette[index % palette.length]};margin-right:6px"></i>${esc(row.label)}</span>
      <span class="barTrack"><i class="warm" style="width:${(row.share_of_value * 100).toFixed(2)}%"></i></span>
      <em>${share(row.share_of_value)}</em>
    </div>
    <div class="muted small" style="margin:-1px 0 6px 126px">
      ${num(row.transactions)} transactions (${share(row.share_of_transactions)} of all) move
      ${btc(row.value_btc)} BTC
    </div>`).join("");

  const percentiles = (corpus.value_percentiles || []).map((row) => `
    <div class="statRow">
      <span>${row.percentile === 100 ? "largest transaction" : `${row.percentile}% of transactions are below`}</span>
      <strong>${btc(row.value_btc)} BTC</strong>
    </div>`).join("");

  document.getElementById("valueShape").innerHTML = `
    <div class="stack">${stack}</div>
    <div class="muted small" style="margin:6px 0 14px">
      bar width = share of transactions; the bar beside each row below = share of VALUE
    </div>
    ${rows}
    <h2 style="margin-top:16px">Value percentiles</h2>
    <p class="sub">Reported as percentiles rather than an average, because one whale would otherwise define the summary.</p>
    ${percentiles}`;

  // A capped tail is a data-realism limitation, and it is visible from the
  // percentiles alone -- so it is stated rather than left for a reader to notice.
  const values = (corpus.value_percentiles || []).map((row) => row.value_btc);
  const capped = values.length >= 3 &&
    values[values.length - 1] === values[values.length - 2] &&
    values[values.length - 2] === values[values.length - 3];
  const host = document.getElementById("trafficCaveat");
  host.innerHTML = `
    <b>What this page is, and what it is not.</b> It describes the traffic that was
    <em>read</em>. On a synthetic dataset that means the generator's own choices shape the
    statistics: planted illicit patterns, decoy services built to look suspicious, and
    diluted signatures so the classes are not trivially separable.
    ${capped ? `<br><br><b>A visible limitation:</b> the 99th, 99.9th and maximum transaction
    values are identical, which means the generator caps transfer size. The value tail here is
    therefore artificial, and any conclusion about very large transfers does not transfer to
    real traffic.` : ""}`;
}

function renderGeography(corpus) {
  const rows = corpus.countries || [];
  if (!rows.length) {
    document.getElementById("geoAll").innerHTML =
      emptyState("No location data.", "No wallet group in this batch had network records attached.");
    return;
  }
  const peak = Math.max(...rows.map((row) => row.share), 1e-9);
  document.getElementById("geoAll").innerHTML = rows.map((row) => `
    <div class="barRow">
      <span class="lbl">${flagEmoji(row.code)} ${esc(row.code)}</span>
      <span class="barTrack" style="position:relative">
        <i style="width:${((row.share / peak) * 100).toFixed(1)}%"></i>
        ${row.flagged ? `<i class="hot" style="left:0;width:${((row.flagged / row.entities) * (row.share / peak) * 100).toFixed(1)}%;opacity:.9"></i>` : ""}
      </span>
      <em>${pct(row.share, 0)}</em>
    </div>
    <div class="muted small" style="margin:-1px 0 6px 126px">
      ${num(row.entities)} groups${row.flagged ? `, of which <b>${num(row.flagged)} flagged</b>` : ", none flagged"}
    </div>`).join("");
}

function renderBehaviour(behaviour) {
  const classes = behaviour.classes || [];
  const palette = {
    mixing_service: "#e07c9a", exchange_like: "#8f7ce0", fan_in_collector: "#e05252",
    peel_chain: "#e08a52", multi_country: "#d9c04a", ordinary: "#4a5563",
  };
  const stack = classes.map((row) =>
    `<i style="width:${(row.share * 100).toFixed(3)}%;background:${palette[row.class] || "#5b6472"}"
        title="${esc(row.label)}"></i>`).join("");

  const legend = classes.map((row) => `
    <div class="legendRow" style="grid-template-columns:10px 1fr auto">
      <i style="background:${palette[row.class] || "#5b6472"}"></i>
      <span>${esc(row.label)}
        <span class="muted small">— ${esc(row.explanation)}</span></span>
      <strong>${num(row.entities)} (${pct(row.share, 1)})</strong>
    </div>`).join("");

  const empty = classes.filter((row) => row.entities === 0).map((row) => row.label);
  document.getElementById("behaviour").innerHTML = `
    <div class="stack">${stack}</div>
    <div class="legend">${legend}</div>
    ${empty.length ? `<p class="muted small" style="margin-top:10px">
      <b>${esc(empty.join(", "))}</b> shows no groups because everything that would qualify was
      already counted under an earlier class — a partition counts each group once. An empty class
      is the precedence working, not a fault.</p>` : ""}`;
}

function renderCoverage(corpus, behaviour) {
  const coverage = corpus.coverage || {};
  const bands = behaviour.score_distribution || [];
  const total = bands.reduce((sum, row) => sum + row.entities, 0) || 1;
  const stack = bands.map((row) =>
    `<i style="width:${(row.share * 100).toFixed(2)}%;background:${BAND_COLOUR[row.band]}"
        title="${esc(row.band)}"></i>`).join("");

  document.getElementById("coverage").innerHTML = `
    <div class="statRow"><span>Wallet groups scored</span><strong>${num(coverage.entities_scored)}</strong></div>
    <div class="statRow"><span>Raised for review</span><strong>${num(coverage.entities_flagged)} (${pct(coverage.flagged_share)})</strong></div>
    <div class="statRow"><span>Records accepted</span><strong>${num(coverage.records_accepted)}</strong></div>
    <div class="statRow"><span>${annotated("Records rejected", "rejected")}</span>
      <strong>${num(coverage.records_rejected)}</strong></div>
    <h2 style="margin-top:16px">Every group by priority</h2>
    <div class="stack" style="height:12px">${stack}</div>
    <div class="legend">${bands.map((row) => `
      <div class="legendRow" style="grid-template-columns:10px 1fr auto">
        <i style="background:${BAND_COLOUR[row.band]}"></i>
        <span>${annotated(esc(row.band), "band")}</span>
        <strong>${num(row.entities)} (${pct(row.share, 1)})</strong>
      </div>`).join("")}</div>
    <p class="muted small" style="margin-top:10px">
      The cleared groups are shown deliberately. A tool that reported only its suspects would be
      asking you to trust that nothing was missed.</p>`;
}

function renderTopActors(corpus) {
  const rows = corpus.top_entities || [];
  if (!rows.length) {
    document.getElementById("topActors").innerHTML =
      emptyState("No actors to rank.", "This batch produced no wallet groups with flows.");
    return;
  }
  document.getElementById("topActors").innerHTML = `
    <table class="data">
      <thead><tr><th>Actor</th><th class="num">Value (BTC)</th><th class="num">Share</th>
        <th class="num">Transactions</th><th>Status</th></tr></thead>
      <tbody>${rows.map((row) => `
        <tr>
          <td class="mono">${esc(shortKey(row.entity))}</td>
          <td class="num">${btc(row.value_btc)}</td>
          <td class="num">${pct(row.share_of_value)}</td>
          <td class="num">${num(row.tx_count)}</td>
          <td>${row.flagged
            ? `<span class="band critical">flagged</span>`
            : `<span class="muted">cleared</span>`}</td>
        </tr>`).join("")}</tbody>
    </table>
    <p class="muted small" style="margin-top:8px">
      The largest actors in a capture are usually lawful services. If most of the top row is flagged,
      the scoring is probably just measuring size.</p>`;
}

(async function main() {
  await NETRA.init();
  const windows = await NETRA.loadWindows();
  const requested = new URLSearchParams(location.search).get("window");

  if (!windows.length) {
    document.querySelector(".page").innerHTML = emptyState(
      "No analysis in the store yet.",
      "Run the analysis from the Ingest page; this page reads the result."
    );
    return;
  }

  // "All batches" is the DEFAULT, because the problem statement asks to analyse
  // the traffic that was ingested -- and one slice of it is not that. A single
  // batch is available for drilling in.
  const active = requested || "all";
  document.getElementById("windowPicker").innerHTML =
    `<a class="chip ${active === "all" ? "on" : ""}" href="?window=all">All batches (${windows.length})</a>` +
    NETRA.windowSwitcher(windows, active);

  try {
    // Fetch the view the picker is SHOWING as active, rather than letting the
    // API fall back to the latest batch -- otherwise the page says "All batches"
    // over one batch's numbers, which is the kind of mismatch that looks fine.
    const payload = await loadPayload(active);
    const corpus = payload.corpus;
    const behaviour = payload.behaviour;
    if (!corpus || !behaviour) {
      toast("This payload predates the traffic analysis; rebuild it from Ingest.");
      return;
    }

    NETRA.setCounters([
      { label: "traffic read", value: num(corpus.records) },
      { label: "value moved (BTC)", value: btc(corpus.total_value_btc) },
      { label: "wallet groups", value: num(corpus.entities) },
      { label: "raised for review", value: num(corpus.coverage.entities_flagged) },
    ]);
    NETRA.setStrip({
      provenance: `engine ${payload.meta.engine_version} · ` +
        (active === "all" ? "whole-capture analysis" : "single batch"),
      generated: `generated ${String(payload.meta.generated_at).replace("T", " ").slice(0, 19)}`,
      state: payload.window.label,
    });

    renderHeadline(corpus, behaviour);
    renderValueShape(corpus);
    renderGeography(corpus);
    renderBehaviour(behaviour);
    renderCoverage(corpus, behaviour);
    renderTopActors(corpus);
  } catch (error) {
    toast(`Could not load the analysis: ${error.message}`);
  }
})();
