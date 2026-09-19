/* Ingest page: run the analysis, or inspect a file before spending time on it. */

"use strict";

async function renderState() {
  const host = document.getElementById("stateStats");
  try {
    const health = await api("/health");
    if (!health.store?.exists) {
      host.innerHTML = emptyState(
        "No analysis in the store yet.",
        "Run the built-in dataset, or upload a file, and the other pages will fill in."
      );
      return;
    }
    const data = await api("/windows");
    const windows = data.windows || [];
    const latest = windows[windows.length - 1];
    host.className = "";
    host.innerHTML = `
      <div class="statRow"><span>Batches processed</span><strong>${num(windows.length)}</strong></div>
      <div class="statRow"><span>Latest batch</span><strong>${esc(latest ? latest.label : "—")}</strong></div>
      <div class="statRow"><span>Records read in it</span><strong>${num(latest?.transactions)}</strong></div>
      <div class="statRow"><span>Wallet groups indexed</span><strong>${num(data.store?.entities)}</strong></div>
      <div class="statRow"><span>Updates detected on wallets</span><strong>${num(data.store?.events)}</strong></div>
      <div class="statRow"><span>Leads open</span><strong>${num(data.store?.open_alerts)}</strong></div>
      <div style="margin-top:10px">
        <a class="btn primary" href="traffic.html">See what is in the data &rarr;</a>
      </div>`;
  } catch (error) {
    host.innerHTML = emptyState("The analysis store is unreachable.", error.message);
  }
}

async function runAnalysis() {
  const button = document.getElementById("demoBtn");
  button.disabled = true;
  button.textContent = "Reading the traffic…";
  try {
    const job = await api("/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode: "replay" }),
    });
    let status = "queued";
    while (status === "queued" || status === "running") {
      await new Promise((resolve) => setTimeout(resolve, 1200));
      const state = await api(`/job/${job.job_id}`);
      status = state.status;
      const last = (state.log || [])[state.log.length - 1];
      if (last) button.textContent = String(last).slice(0, 48);
    }
    if (status === "error") throw new Error("the analysis failed; see the job log");
    toast("Analysis complete");
    location.href = "traffic.html";
  } catch (error) {
    toast(`Analysis failed: ${error.message}`);
    button.disabled = false;
    button.textContent = "Run on the built-in dataset";
  }
}

async function uploadFile(file) {
  const body = new FormData();
  body.append("file", file);
  try {
    const result = await api("/upload", { method: "POST", body });
    const report = result.report;
    document.getElementById("gate").hidden = false;
    document.getElementById("gateGrid").innerHTML = `
      <div><span>Rows read</span><strong class="mono">${num(report.total)}</strong></div>
      <div><span>Usable</span><strong class="mono">${num(report.accepted)}</strong></div>
      <div><span>Rejected</span><strong class="mono">${num(report.rejected)}</strong></div>
      <div><span>Format</span><strong class="mono">${esc(report.format)}</strong></div>`;

    const reasons = Object.entries(report.rejections || {});
    const notes = Object.entries(report.notes || {});
    document.getElementById("gateReasons").innerHTML =
      (reasons.length
        ? `<p>Why rows were rejected — we report these rather than dropping them silently:</p><ul>` +
          reasons.map(([why, count]) => `<li><code>${num(count)}</code> × ${esc(why)}</li>`).join("") +
          `</ul>`
        : `<p>Every row parsed. Nothing was rejected.</p>`) +
      (notes.length
        ? `<p>Worth knowing: ${notes.map(([label, count]) => `${num(count)} ${esc(label)}`).join(", ")}.</p>`
        : "");
    toast(`${num(report.accepted)} rows ready to analyse`);
  } catch (error) {
    toast(`Upload failed: ${error.message}`);
  }
}

(async function main() {
  await NETRA.init();
  document.getElementById("demoBtn").onclick = runAnalysis;
  document.getElementById("fileInput").onchange = (event) => {
    const file = event.target.files?.[0];
    if (file) uploadFile(file);
  };
  await renderState();
})();
