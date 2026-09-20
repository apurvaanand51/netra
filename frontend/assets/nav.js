/* Shared chrome, in the NETRA theme's own vocabulary.
 *
 * Renders the theme's topbar (brand mark, nav, theme and explain controls) into
 * `#topbar`, and the provenance strip into `#strip`. One implementation rather
 * than five: the strip states where every number came from, which is the worst
 * possible place to discover a page has grown its own version of the truth.
 */

"use strict";

const NETRA = (() => {
  // The order is the order of the argument: here is the data, here is what is in
  // it, here is what looks wrong and why, here is the whole picture, and here is
  // how it was built. Every page answers one question and links to the next.
  const PAGES = [
    { href: "index.html", label: "Cover" },
    { href: "ingest.html", label: "Ingest" },
    { href: "dataset.html", label: "Dataset" },
    { href: "anomalies.html", label: "Anomalies" },
    { href: "dashboard.html", label: "Dashboard" },
    { href: "documents.html", label: "Documents" },
  ];

  let counters = [];
  let strip = { provenance: "no analysis loaded", generated: "", state: "" };

  const currentPage = () => location.pathname.split("/").pop() || "index.html";

  function renderChrome() {
    const here = currentPage();
    const host = document.getElementById("topbar");
    if (host) {
      host.className = "topbar";
      host.innerHTML = `
        <div class="brand">
          <div class="brand-mark">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                 stroke-linecap="round" stroke-linejoin="round">
              <path d="M3 20h18"/><path d="M6 20V10"/><path d="M12 20V4"/><path d="M18 20v-7"/>
            </svg>
          </div>
          <div>
            <div class="brand-name">NETRA</div>
            <div class="brand-sub">SIH 2026 · PS SIH26146</div>
          </div>
        </div>
        <nav class="pipeline">
          ${PAGES.map((page, index) => `
            <a class="stage ${page.href === here ? "active" : ""}" href="${page.href}">
              <span class="dot"></span>${page.label}</a>
            ${index < PAGES.length - 1 ? '<span class="stage-sep"></span>' : ""}`
          ).join("")}
        </nav>
        <div class="top-right">
          <div id="counters" style="display:flex;gap:14px;align-items:center"></div>
          <div class="tb-controls">
            <button class="tb-btn" id="explainBtn" title="Plain-language notes for every term">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                   stroke-linecap="round" stroke-linejoin="round">
                <circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>
              </svg>Explain
            </button>
            <button class="tb-btn ico" id="themeBtn" title="Light / dark">
              <svg class="sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                   stroke-linecap="round" stroke-linejoin="round">
                <circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M6.3 17.7l-1.4 1.4M19.1 4.9l-1.4 1.4"/>
              </svg>
              <svg class="moon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                   stroke-linecap="round" stroke-linejoin="round">
                <path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9z"/>
              </svg>
            </button>
          </div>
        </div>`;

      document.getElementById("themeBtn").onclick = () => {
        toggleTheme();
        document.dispatchEvent(new CustomEvent("netra:theme"));
      };
      const explain = document.getElementById("explainBtn");
      explain.onclick = () => {
        const on = !document.body.classList.contains("explain-on");
        document.body.classList.toggle("explain-on", on);
        explain.classList.toggle("on", on);
        toast(on ? "Explain mode on — click any underlined term" : "Explain mode off");
        document.dispatchEvent(new CustomEvent("netra:explain"));
      };
    }

    const stripHost = document.getElementById("strip");
    if (stripHost) {
      stripHost.className = "strip";
      stripHost.style.cssText =
        "display:flex;align-items:center;gap:12px;flex-wrap:wrap;padding:9px 22px;" +
        "font-size:11.5px;color:var(--ink-3);border-top:1px solid var(--border-2);" +
        "background:var(--surface);font-family:var(--mono)";
      stripHost.innerHTML = `
        <span id="stripProvenance"></span>
        <span style="flex:1"></span>
        <span id="stripGenerated"></span>
        <button class="tb-btn" id="reloadBtn" style="height:28px;padding:0 10px;font-size:11.5px">
          Reload state</button>
        <span id="stripState"></span>`;
      document.getElementById("reloadBtn").onclick = async () => {
        try {
          const result = await api("/reload", { method: "POST" });
          toast(`Reloaded — ${result.cleared_caches} cached view(s) dropped`);
          location.reload();
        } catch (error) {
          toast(`Reload failed: ${error.message}`);
        }
      };
    }

    if (!document.getElementById("tip")) {
      const tip = document.createElement("div");
      tip.id = "tip";
      tip.className = "tip";
      document.body.appendChild(tip);
    }
    if (!document.getElementById("toast")) {
      const node = document.createElement("div");
      node.id = "toast";
      node.className = "toast";
      document.body.appendChild(node);
    }
    renderCounters();
    renderStrip();
  }

  const setCounters = (list) => { counters = list || []; renderCounters(); };

  function renderCounters() {
    const host = document.getElementById("counters");
    if (!host) return;
    host.innerHTML = counters.map((item) => `
      <div style="line-height:1.15;text-align:right">
        <div style="font-size:10px;letter-spacing:.08em;text-transform:uppercase;color:var(--ink-3)">
          ${esc(item.label)}</div>
        <div class="mono" style="font-size:14px;font-weight:700">${item.value}</div>
      </div>`).join("");
  }

  const setStrip = (values) => { strip = { ...strip, ...(values || {}) }; renderStrip(); };

  function renderStrip() {
    const p = document.getElementById("stripProvenance");
    const g = document.getElementById("stripGenerated");
    const s = document.getElementById("stripState");
    if (p) p.textContent = strip.provenance;
    if (g) g.textContent = strip.generated;
    if (s) s.textContent = strip.state;
  }

  async function loadWindows() {
    try {
      return (await api("/windows")).windows || [];
    } catch (error) {
      return [];
    }
  }

  async function init() {
    initTheme();
    initExplain();
    renderChrome();
    try {
      const health = await api("/health");
      strip.provenance = `engine ${health.engine_version} · offline · local`;
      strip.state = health.store?.exists
        ? `${health.store.windows} batch(es) analysed`
        : "no analysis yet";
      renderStrip();
      return health;
    } catch (error) {
      strip.provenance = "backend unreachable";
      renderStrip();
      return null;
    }
  }

  return { PAGES, init, setCounters, setStrip, renderStrip, loadWindows, currentPage };
})();
