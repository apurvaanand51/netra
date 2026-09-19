/* Shared chrome: the page nav, the live counters, and the honesty strip.
 *
 * Why this is one file rather than markup repeated in six documents: the nav, the
 * theme toggle and the provenance strip must be IDENTICAL on every page. If each
 * page carried its own copy, they would drift, and the strip -- which exists to
 * state honestly where every number came from -- is the worst place to discover a
 * page has quietly grown its own version of the truth.
 *
 * Pages call NETRA.setCounters(...) and NETRA.setStrip(...) after they load data;
 * everything else is automatic.
 */

"use strict";

const NETRA = (() => {
  const PAGES = [
    { href: "index.html", label: "Ingest", ready: true },
    { href: "traffic.html", label: "Traffic", ready: true },
    { href: "investigate.html", label: "Investigate", ready: true },
    { href: "monitoring.html", label: "Monitoring", ready: true },
    { href: "model.html", label: "Method", ready: true },
    { href: "documents.html", label: "Documents", ready: true },
  ];

  let counters = [];
  let strip = { provenance: "no analysis loaded", generated: "", state: "" };

  function currentPage() {
    const file = location.pathname.split("/").pop() || "index.html";
    return file === "" ? "index.html" : file;
  }

  function renderChrome() {
    const here = currentPage();

    const topbar = document.getElementById("topbar");
    if (topbar) {
      topbar.innerHTML = `
        <div class="brand">
          <span class="wordmark">NETRA</span>
          <span class="sub">Team Vortex · SIH 2026 · PS SIH26146</span>
        </div>
        <nav class="nav">
          ${PAGES.map((page) => page.ready
            ? `<a href="${page.href}" class="${page.href === here ? "on" : ""}">${page.label}</a>`
            : `<a class="soon" title="Not built yet">${page.label}</a>`
          ).join("")}
        </nav>
        <div class="spacer"></div>
        <div class="counters" id="counters"></div>
        <button class="btn" id="explainBtn" title="Turn on plain-language notes for every number">
          <span class="dot"></span> Explain mode
        </button>
        <button class="btn icon" id="themeBtn" title="Light / dark">&#9681;</button>
      `;
      document.getElementById("themeBtn").onclick = () => {
        toggleTheme();
        renderStrip();
      };
      const explainBtn = document.getElementById("explainBtn");
      explainBtn.onclick = () => {
        const on = !document.body.classList.contains("explain");
        document.body.classList.toggle("explain", on);
        explainBtn.classList.toggle("on", on);
        toast(on ? "Explain mode on: click any underlined term" : "Explain mode off");
        document.dispatchEvent(new CustomEvent("netra:explain"));
      };
    }

    const stripHost = document.getElementById("strip");
    if (stripHost) {
      stripHost.innerHTML = `
        <span class="mono" id="stripProvenance"></span>
        <span class="spacer"></span>
        <span class="mono" id="stripGenerated"></span>
        <button class="btn sm" id="reloadBtn">Reload state</button>
        <span class="mono" id="stripState"></span>
      `;
      document.getElementById("reloadBtn").onclick = async () => {
        try {
          const result = await api("/reload", { method: "POST" });
          toast(`Reloaded: ${result.cleared_caches} cached view(s) dropped`);
          location.reload();
        } catch (error) {
          toast(`Reload failed: ${error.message}`);
        }
      };
    }

    if (!document.getElementById("pop")) {
      const pop = document.createElement("div");
      pop.id = "pop";
      pop.className = "pop";
      pop.hidden = true;
      document.body.appendChild(pop);
    }
    if (!document.getElementById("toast")) {
      const node = document.createElement("div");
      node.id = "toast";
      node.className = "toast";
      node.hidden = true;
      document.body.appendChild(node);
    }

    renderCounters();
    renderStrip();
  }

  function setCounters(list) {
    counters = list || [];
    renderCounters();
  }

  function renderCounters() {
    const host = document.getElementById("counters");
    if (!host) return;
    host.innerHTML = counters.map((item) =>
      `<div><span>${esc(item.label)}</span><strong class="mono">${item.value}</strong></div>`
    ).join("");
  }

  function setStrip(values) {
    strip = { ...strip, ...(values || {}) };
    renderStrip();
  }

  function renderStrip() {
    const provenance = document.getElementById("stripProvenance");
    const generated = document.getElementById("stripGenerated");
    const state = document.getElementById("stripState");
    if (provenance) provenance.textContent = strip.provenance;
    if (generated) generated.textContent = strip.generated;
    if (state) state.textContent = strip.state;
  }

  /** Load the window list and expose it, so pages do not each fetch it. */
  async function loadWindows() {
    try {
      const data = await api("/windows");
      return data.windows || [];
    } catch (error) {
      return [];
    }
  }

  /** A small window switcher. Compares as strings because the selector may be a
   *  batch id, "all", or absent -- and Number("all") is NaN, so a numeric
   *  comparison would silently highlight nothing. */
  function windowSwitcher(windows, activeId) {
    if (!windows.length) return "";
    return windows.map((item) =>
      `<a class="chip ${String(item.id) === String(activeId) ? "on" : ""}" href="?window=${item.id}">` +
      `${esc(String(item.label).replace(/^window-/, ""))}</a>`
    ).join("");
  }

  async function init() {
    initTheme();
    initExplain();
    renderChrome();
    try {
      const health = await api("/health");
      const models = health.models || {};
      strip.provenance = models.metrics
        ? `engine ${health.engine_version} · RandomForest (windowed) · explanations: decision-path contributions`
        : "model not trained";
      strip.state = health.store?.exists ? "offline · local" : "no analysis yet";
      renderStrip();
      return health;
    } catch (error) {
      strip.provenance = "backend unreachable";
      renderStrip();
      return null;
    }
  }

  return { PAGES, init, setCounters, setStrip, renderStrip, loadWindows, windowSwitcher, currentPage };
})();
