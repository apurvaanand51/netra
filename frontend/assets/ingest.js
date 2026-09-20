/* Ingest page: take a file, or run the built-in dataset, and report honestly what
 * was read.
 *
 * WHY THIS PAGE EXISTS AT ALL
 * ---------------------------
 * The obvious design is a drop zone that silently starts the analysis. We do the
 * opposite: the run does not begin until the operator has seen the quality gate —
 * rows read, rows usable, rows rejected and the reason for each. In an
 * investigation a dropped row is a missing fact, and "we used 96% of your file"
 * is a claim that has to be checkable rather than taken on trust.
 */

"use strict";

// The four things that actually happen, in order. Shown as a checklist so a
// viewer watching over a shoulder can see the work rather than a spinner.
const STAGES = [
  { label: "Reading traffic", note: "parsing rows, checking each field" },
  { label: "Grouping wallets", note: "addresses proved to share an owner" },
  { label: "Matching IP addresses to wallets", note: "which network controlled whom" },
  { label: "Scoring and explaining", note: "ranking, then decomposing each score" },
];

/* ------------------------------------------------------------------ gate --- */

function statTile(label, value, note, tone) {
  return `<div class="stat ${tone || ""}">
    <div class="k">${esc(label)}</div>
    <div class="v hero-num sm">${value}</div>
    ${note ? `<div class="d">${esc(note)}</div>` : ""}
  </div>`;
}

/** Which dataset the gate is describing, and therefore what `Analyse` will run on.
 *
 * This is the whole point of the page: the operator uploads a file, sees what we
 * made of it, and then asks for the analysis OF THAT FILE. Before this, the
 * button after the gate jumped to the dataset page and showed whatever had been
 * analysed previously -- the gate described one file and the report showed
 * another, which is the most damaging kind of wrong for a tool whose claim is
 * "we read your data".
 */
const run = { dataset: null, label: "" };

function showGate(report, source) {
  document.getElementById("gate-none").hidden = true;
  document.getElementById("progress").hidden = true;
  document.getElementById("gate").hidden = false;

  if (source) {
    run.dataset = source.dataset;
    run.label = source.label;
  }
  document.getElementById("gateGoLabel").textContent =
    run.label === "built-in" ? "Analyse the built-in dataset" : "Analyse this file";
  // The last two path segments, not the absolute path: on screen, a full local
  // path is mostly the operator's own username, and it says nothing about what
  // is being analysed. The full path stays available on hover for the operator
  // who needs to be sure which file this is.
  const BACKSLASH = String.fromCharCode(92);   // avoids escape ambiguity entirely
  const relative = (path) => String(path || "")
    .split(BACKSLASH).join("/").split("/").slice(-2).join("/");
  const sourceLine = document.getElementById("gateSource");
  sourceLine.textContent = run.dataset ? `will run on ${relative(run.dataset)}, on this machine` : "";
  sourceLine.title = run.dataset || "";

  const rejected = report.rejected || 0;
  document.getElementById("gateStats").innerHTML =
    statTile("Rows read", num(report.total), "everything in the file") +
    statTile("Usable", num(report.accepted), "carried into the analysis") +
    statTile("Rejected", num(rejected),
             rejected ? "each with a reason, alongside" : "nothing was rejected",
             rejected ? "c" : "s") +
    statTile("Format", esc(report.format).toUpperCase(), "detected from the file itself");

  // Rejections are ranked by count: the largest reason is the one worth acting on.
  const reasons = Object.entries(report.rejections || {})
    .filter(([, count]) => count > 0)
    .sort((a, b) => b[1] - a[1]);
  document.getElementById("gateReasons").innerHTML = reasons.length
    ? reasons.map(([why, count]) => {
        const share = report.total ? (count / report.total) * 100 : 0;
        const width = Math.max(1.5, Math.min(100, share * 6));
        return `<div class="geo-row" style="margin-bottom:9px">
          <div class="flag mono" style="width:auto;min-width:54px;padding:0 8px;
               font-size:12.5px;font-weight:700">${num(count)}</div>
          <div class="gn" style="width:auto;flex:1;font-size:12.5px;color:var(--ink-2)">
            ${esc(why)}</div>
          <div class="gbar" style="max-width:150px">
            <i class="gf" style="width:${width}%;background:var(--crit)"></i></div>
          <div class="gp">${share < 1 ? share.toFixed(1) : Math.round(share)}%</div>
        </div>`;
      }).join("")
    : `<p style="font-size:13px;color:var(--ink-2)">
         Every row parsed and carried through. Nothing was rejected.</p>`;

  // `notes` are things worth knowing that are not errors — a truncated export, a
  // field we had to infer. They are shown rather than buried in a log.
  const notes = Object.entries(report.notes || {});
  document.getElementById("gateNotes").innerHTML = notes.length
    ? notes.map(([label, count]) =>
        `<div class="kv"><span class="k">${esc(label)}</span>
         <span class="v">${num(count)}</span></div>`).join("")
    : `<p style="font-size:13px;color:var(--ink-2)">
         Nothing unusual about this file.</p>`;

  window.scrollTo({ top: 0, behavior: "smooth" });
}

/* -------------------------------------------------------------- the run --- */

function renderStages(done) {
  document.getElementById("stageList").innerHTML = STAGES.map((stage, index) => {
    const state = index < done ? "ok" : index === done ? "" : "";
    const colour = index < done ? "var(--safe)"
                 : index === done ? "var(--brand)" : "var(--ink-3)";
    const mark = index < done
      ? `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"
              stroke-linecap="round" stroke-linejoin="round"><path d="M20 6L9 17l-5-5"/></svg>`
      : index === done
        ? `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4"
                stroke-linecap="round" stroke-linejoin="round">
             <path d="M21 12a9 9 0 1 1-6.2-8.6"/></svg>`
        : `<span style="font-family:var(--mono);font-size:12.5px">${index + 1}</span>`;
    return `<div class="fpill ${state}" style="opacity:${index > done ? ".55" : "1"}">
      <div class="fi" style="color:${colour}">${mark}</div>
      <div><div class="fn" style="font-family:var(--sans);font-size:13.5px;font-weight:600">
        ${esc(stage.label)}</div>
        <div style="font-size:11.5px;color:var(--ink-3)">${esc(stage.note)}</div></div>
    </div>`;
  }).join("");
}

async function runAnalysis() {
  document.getElementById("gate-none").hidden = true;
  document.getElementById("gate").hidden = true;
  document.getElementById("progress").hidden = false;

  const stage = document.getElementById("progressStage");
  const pct = document.getElementById("progressPct");
  const bar = document.getElementById("progressBar");
  const log = document.getElementById("progressLog");
  let shown = 0;
  renderStages(0);

  const appendLog = (line) => {
    const node = document.createElement("div");
    node.className = "l";
    node.innerHTML = `<span class="t">${String(shown).padStart(2, "0")}</span> ${esc(line)}`;
    log.appendChild(node);
    log.scrollTop = log.scrollHeight;
    shown += 1;
  };
  appendLog(run.dataset
    ? `job queued — analysing ${run.dataset}`
    : "job queued — analysis runs on this machine");

  try {
    const job = await api("/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(run.dataset ? { mode: "replay", dataset: run.dataset }
                                       : { mode: "replay" }),
    });

    let status = "queued";
    let seen = 0;
    while (status === "queued" || status === "running") {
      await new Promise((resolve) => setTimeout(resolve, 900));
      const state = await api(`/job/${job.job_id}`);
      status = state.status;
      const progress = state.progress || 0;
      const current = Math.min(STAGES.length - 1, Math.floor(progress * STAGES.length));
      stage.textContent = `${STAGES[current].label}…`;
      bar.style.width = `${Math.round(progress * 100)}%`;
      pct.textContent = `${Math.round(progress * 100)}% · stage ${current + 1} of ${STAGES.length}`;
      renderStages(current);

      // The backend's own log, appended as it arrives rather than re-rendered, so
      // lines do not re-animate on every poll.
      const lines = state.log || [];
      for (const line of lines.slice(seen)) appendLog(String(line).slice(0, 150));
      seen = lines.length;
    }

    if (status === "error") throw new Error("the analysis failed — see the pipeline log");
    stage.textContent = "Done.";
    bar.style.width = "100%";
    pct.textContent = "100%";
    renderStages(STAGES.length);
    appendLog("complete — opening the dataset summary");
    setTimeout(() => { location.href = "dataset.html"; }, 650);
  } catch (error) {
    stage.textContent = "Something went wrong.";
    appendLog(`error: ${error.message}`);
    toast(`Analysis failed: ${error.message}`);
  }
}

/* ------------------------------------------------------------- uploads --- */

function filePill(name, size) {
  return `<div class="fpill" id="pill">
    <div class="fi">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
           stroke-linecap="round" stroke-linejoin="round">
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
        <path d="M14 2v6h6"/></svg></div>
    <div><div class="fn">${esc(name)}</div></div>
    <div class="fs">${size}</div>
    <div class="fc">read</div>
  </div>`;
}

async function uploadFile(file) {
  const list = document.getElementById("fileList");
  list.innerHTML = filePill(file.name, humanSize(file.size));
  const pill = document.getElementById("pill");
  try {
    const body = new FormData();
    body.append("file", file);
    const result = await api("/upload", { method: "POST", body });
    pill.classList.add("ok");
    setTimeout(() => showGate(result.report, {
      dataset: result.stored_as, label: file.name,
    }), 420);
    toast(`${num(result.report.accepted)} rows ready to analyse`);
  } catch (error) {
    list.innerHTML = "";
    toast(`Could not read that file: ${error.message}`);
  }
}

function humanSize(bytes) {
  if (!bytes) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

/* ---------------------------------------------------------------- boot --- */

(async function main() {
  const health = await NETRA.init();
  const again = document.getElementById("againBtn");

  if (health?.store?.exists) {
    document.getElementById("demoBtn").textContent = "Re-run the built-in dataset";
    document.getElementById("demoBtn").className = "btn btn-primary";
    again.hidden = false;
  }

  const drop = document.getElementById("drop");
  const input = document.getElementById("fileInput");
  const choose = () => input.click();
  document.getElementById("chooseBtn").onclick = choose;
  drop.onclick = (event) => { if (event.target.closest("button")) return; choose(); };
  input.onchange = (event) => {
    const file = event.target.files?.[0];
    if (file) uploadFile(file);
  };

  // Dragging a file anywhere on a page navigates away by default, which loses the
  // page instead of loading the file.
  ["dragover", "dragenter", "drop"].forEach((name) =>
    document.addEventListener(name, (event) => event.preventDefault()));
  ["dragover", "dragenter"].forEach((name) =>
    drop.addEventListener(name, () => drop.classList.add("busy")));
  ["dragleave", "drop"].forEach((name) =>
    drop.addEventListener(name, () => drop.classList.remove("busy")));
  drop.addEventListener("drop", (event) => {
    const file = event.dataTransfer?.files?.[0];
    if (file) uploadFile(file);
  });

  // The built-in dataset goes through the SAME gate as an uploaded file. It used
  // to skip it, which meant the demo -- the path a judge actually watches --
  // never showed the one screen that answers "did you use my data?".
  document.getElementById("demoBtn").onclick = async () => {
    const button = document.getElementById("demoBtn");
    button.disabled = true;
    try {
      const result = await api("/ingest-report");
      showGate(result.report, { dataset: result.dataset, label: "built-in" });
    } catch (error) {
      toast(`Could not read the built-in dataset: ${error.message}`);
    } finally {
      button.disabled = false;
    }
  };

  document.getElementById("gateGo").onclick = runAnalysis;
  again.onclick = () => {
    document.getElementById("gate").hidden = true;
    document.getElementById("gate-none").hidden = false;
    document.getElementById("fileList").innerHTML = "";
    window.scrollTo({ top: 0, behavior: "smooth" });
  };
})();
