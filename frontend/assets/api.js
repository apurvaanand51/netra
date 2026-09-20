/* Shared layer for every page: fetching, formatting, and the plain-language
 * glossary.
 *
 * TWO RULES LIVE HERE.
 *
 * 1. ANALYSIS LIVES IN THE BACKEND; PRESENTATION LIVES HERE. Nothing in this
 *    file decides whether a wallet is suspicious. If a number is not in the
 *    payload it does not appear on screen -- there are no invented statistics,
 *    because in an investigative tool a number is evidence.
 *
 * 2. THE CONSOLE IS FOR EVERYONE IN THE ROOM, not only the engineer. Every
 *    technical term is either replaced with a plain phrase (FEATURE_PLAIN) or
 *    carries an explanation that Explain mode reveals (GLOSSARY). A term that
 *    appears in the interface without an entry here is jargon that leaked, and
 *    that is a bug in this file rather than a gap in the glossary.
 */

"use strict";

/* ------------------------------------------------------------------ glossary */
const GLOSSARY = {
  risk: ["Priority score", "0 to 100. It is the model's estimate of how likely this wallet group is to be part of a laundering operation. It ranks groups. It is not a verdict."],
  band: ["Priority band", "The score grouped into four levels, so a long list can be triaged at a glance."],
  wallet_group: ["Wallet group", "Several Bitcoin addresses we have proved belong to one owner, because they were spent together in one transaction. You must sign for every address you spend, so spending them together means one person controls them."],
  ip_node: ["IP address", "A network endpoint that broadcast this wallet's transactions. Shown as a node because an investigator needs to know where a wallet was controlled from, not only what it moved."],
  control_edge: ["Controlled from", "A dashed link meaning this IP address sent transactions for that wallet. This is the join between the network records and the blockchain records, and it is what gives a wallet a country."],
  flow_edge: ["Money moved", "A solid link meaning value moved from one wallet group to another. Change returning to the sender is excluded: a payment that comes straight back is not a payment."],
  contribution: ["Contribution", "How much one fact about this wallet pushed its score up or down. These add up exactly to the score, so the explanation always reconciles with the number on screen."],
  base: ["Starting point", "The score before looking at any single fact, and the average across the training data. Contributions move it from here to the final number."],
  residual: ["Left over", "The gap between the contributions and the final score. It should be zero. We print it so you can check rather than trust."],
  anomaly: ["Unusualness", "From a model that never saw a labelled example. It flags what looks statistically odd, which is the honest answer to 'what if criminals do something we never planted?'."],
  modularity: ["How clearly groups separate", "0 means no discernible grouping, 1 means very clear. Measured on the large transfers only, because small payments are close to random and drown the pattern."],
  ari: ["Grouping accuracy", "How closely our automatic wallet grouping matched the known truth, corrected for the agreement you would get by chance. 1.0 is perfect."],
  precision: ["Accuracy of our flags", "Of the wallet groups we flagged, the share that really were planted illicit cases."],
  recall: ["Cases caught", "Of the planted illicit cases, the share we flagged. A low number here means cases were missed, which is the more dangerous error."],
  auc: ["Ranking quality", "How reliably the model puts an illicit wallet above an innocent one. 0.5 is a coin toss."],
  brier: ["Confidence honesty", "Whether the score means what it says: if we print 90, is it right about 90% of the time? Lower is better."],
  time_to_detection: ["How fast we noticed", "How many batches, on average, before a planted case was first flagged."],
  estimate: ["Estimate", "Bitcoin is fungible. Once money is mixed, no one can say which coin went where. This figure is a proportional estimate, not an observation."],
  rejected: ["Rejected rows", "Records we could not parse. They are reported with a reason rather than quietly dropped, because silent data loss in a criminal case is indefensible."],
  merge: ["Merged groups", "Two wallet groups that turned out to be one, because a later transaction spent addresses from both. Two operations being linked is a finding, not a bookkeeping problem."],
  corpus: ["Whole capture", "Everything we read, not only the part we flagged. The flagged groups are a small share of it, and the share is the honest measure of what was found."],
  partition: ["Behaviour breakdown", "Every wallet group counted exactly once, under the first behaviour it matches. One group can show several behaviours, so counting them separately would sum past 100% and mislead."],
  size_class: ["Transaction size", "Transactions bucketed by value. Bitcoin values span nine orders of magnitude, so an average describes nobody. The buckets show where the value actually sits."],
  coverage: ["Coverage", "How much of the traffic was examined. Stated so that 'nothing found here' can be told apart from 'not examined'."],
  window: ["Batch", "One slice of time. Everything in this tool is measured over a batch, and each batch is compared against the one before it."],
  trace: ["Fund trail", "An estimate of where a wallet's money ended up. See the note on every trail: it is a proportional allocation, not an observation."],
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

// The theme's risk palette, read at draw time from the CSS custom properties so
// charts cannot hold a colour the stylesheet has stopped using. The literal
// values below are only a fallback for the milliseconds before the stylesheet
// resolves.
const BAND_FALLBACK = { critical: "#DC2626", high: "#DD6B20", medium: "#C77700", low: "#0E9F6E" };
const BAND_ORDER = ["critical", "high", "medium", "low"];

/** Every colour a chart needs, read from the live theme. */
function themeTokens() {
  const style = getComputedStyle(document.documentElement);
  const read = (name, fallback) => (style.getPropertyValue(name) || "").trim() || fallback;
  return {
    ink: read("--ink", "#0F1E3D"),
    ink2: read("--ink-2", "#3F4A5F"),
    ink3: read("--ink-3", "#6B7688"),
    brand: read("--brand", "#1E40AF"),
    brand2: read("--brand-2", "#3B82F6"),
    accent: read("--accent", "#D97706"),
    safe: read("--safe", "#0E9F6E"),
    med: read("--med", "#C77700"),
    high: read("--high", "#DD6B20"),
    crit: read("--crit", "#DC2626"),
    border: read("--border-2", "#DBEAFE"),
    surface: read("--surface-2", "#F1F5F9"),
    // Canvas gridlines have to be a wash of the ink colour rather than a fixed
    // grey, or they are invisible on one of the two themes.
    grid: "rgba(120,130,145,0.18)",
  };
}

/** The colour for a priority band, from the theme, with a safe fallback. */
function bandColour(band) {
  const key = { critical: "crit", high: "high", medium: "med", low: "safe" }[band];
  return key ? themeTokens()[key] : BAND_FALLBACK[band] || themeTokens().ink3;
}

/** Is this entity an investigative LEAD, or a node drawn to make the graph
 *  readable?
 *
 *  The producer decides this and states it in the payload, because the answer is
 *  the difference between "85 wallet groups flagged" and "100": an IP endpoint
 *  inherits the peak risk of the wallets it controlled, so it can carry a review
 *  band without being a wallet group. The fallback covers a payload generated
 *  before the flag existed -- it is the same rule, evaluated here rather than
 *  silently reporting zero leads because a field was absent.
 */
function isLead(entity) {
  if (typeof entity?.lead === "boolean") return entity.lead;
  return entity?.kind !== "ip" && entity?.risk_band !== "low";
}

/* -------------------------------------------------------------------- format */
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => (
  { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
));
const num = (v, digits = 0) => (v === null || v === undefined || Number.isNaN(Number(v)))
  ? "—"
  : Number(v).toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });
const btc = (v) => (v === null || v === undefined)
  ? "—" : `${num(v, Math.abs(Number(v)) < 1 ? 4 : 2)}`;
const pct = (v, digits = 1) => (v === null || v === undefined) ? "—" : `${(Number(v) * 100).toFixed(digits)}%`;
const plainFeature = (name) => FEATURE_PLAIN[name] || String(name).replace(/_/g, "_");
/** A number with no trailing zeros, for reading inside a sentence. */
const compact = (value, digits = 4) => {
  const number = Number(value);
  if (!Number.isFinite(number)) return "—";
  return number === 0 ? "0" : String(Number(number.toFixed(digits)));
};
const shortKey = (key) => {
  const text = String(key ?? "");
  return text.length > 14 ? `${text.slice(0, 9)}…${text.slice(-4)}` : text;
};
const flagEmoji = (code) => {
  if (!code || String(code).length !== 2) return "";
  return String.fromCodePoint(...[...String(code).toUpperCase()].map((c) => 127397 + c.charCodeAt(0)));
};

/** Attach a clickable explanation dot, but only when Explain mode is on.
 *
 * A dot that is always present turns the interface into a field of question
 * marks; one that appears on request keeps the reading view clean and still
 * answers "what does that word mean?" without leaving the page.
 */
function annotated(text, key) {
  return (document.body.classList.contains("explain-on") && GLOSSARY[key])
    ? `${text}<span class="qdot inline" data-explain="${key}" title="What does this mean?">?</span>`
    : text;
}

/* ----------------------------------------------------------------------- api */
async function api(path, options) {
  const response = await fetch(path, options);
  // fetch does NOT reject on HTTP errors -- a 404 resolves normally. Without
  // this check every caller's error handling would silently never run.
  if (!response.ok) {
    let detail = `${response.status}`;
    try { detail = (await response.json()).detail || detail; } catch (e) { /* not json */ }
    throw new Error(detail);
  }
  return response.json();
}

/** The window selector from the URL: a batch id, "all", or null (latest). */
function windowParam() {
  const value = new URLSearchParams(location.search).get("window");
  // Returned as a raw string, not a Number: "all" is a valid value and
  // Number("all") is NaN, which would be sent to the API as `window=NaN`.
  return value || null;
}

/** Fetch the payload for an explicit selector, the URL's, or the latest batch.
 *
 * `selector` is deliberately accepted as an argument: a page whose default view
 * is NOT the latest batch must be able to say so. Without it, the traffic page
 * highlighted "All batches" while its request went to the latest batch, so the
 * label and the data disagreed -- and the numbers looked plausible either way.
 */
async function loadPayload(selector) {
  const id = selector !== undefined ? selector : windowParam();
  return api(id ? `/results?window=${encodeURIComponent(id)}` : "/results");
}

/* --------------------------------------------------------------------- toast */
function toast(message, ms = 3400) {
  let node = document.getElementById("toast");
  if (!node) {
    node = document.createElement("div");
    node.id = "toast";
    node.className = "toast";
    document.body.appendChild(node);
  }
  node.textContent = message;
  node.hidden = false;
  clearTimeout(node._timer);
  node._timer = setTimeout(() => { node.hidden = true; }, ms);
}

/* -------------------------------------------------------------------- theme */
function initTheme() {
  try {
    const saved = localStorage.getItem("netra-theme");
    if (saved) document.documentElement.dataset.theme = saved;
  } catch (e) { /* private browsing */ }
}
function toggleTheme() {
  const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem("netra-theme", next); } catch (e) { /* ignore */ }
  document.dispatchEvent(new CustomEvent("netra:theme"));
}

/* ---------------------------------------------------------- explain mode */
function initExplain() {
  const close = () => document.getElementById("tip")?.classList.remove("on");

  // A fixed-position popover does not follow the element it describes, so a scroll
  // leaves it pointing at nothing. Closing on scroll is the honest alternative to
  // chasing the anchor.
  window.addEventListener("scroll", close, true);
  window.addEventListener("resize", close);

  document.addEventListener("click", (event) => {
    const node = document.getElementById("tip");
    if (!node) return;
    if (event.target.closest(".tip-x")) { close(); return; }
    const target = event.target.closest("[data-explain]");
    if (!target || !document.body.classList.contains("explain-on")) { close(); return; }

    const entry = GLOSSARY[target.dataset.explain];
    if (!entry) return;
    node.innerHTML = `
      <button class="tip-x" title="Close">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4"
             stroke-linecap="round"><path d="M18 6L6 18"/><path d="M6 6l12 12"/></svg>
      </button>
      <div class="th">
        <div class="ei">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
               stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="10"/><path d="M9.1 9a3 3 0 1 1 4 2.8c-.7.3-1.1 1-1.1 1.7v.5"/>
            <path d="M12 17h.01"/></svg></div>
        <div><span class="tk">In plain words</span><b>${esc(entry[0])}</b></div>
      </div>
      <div class="analogy">${esc(entry[1])}</div>
      ${entry[2] ? `<div class="why"><b>Why it matters:</b> ${esc(entry[2])}</div>` : ""}`;

    node.classList.add("on");
    const rect = target.getBoundingClientRect();
    const width = node.offsetWidth || 300;
    const height = node.offsetHeight || 170;
    const left = Math.max(10, Math.min(rect.left + rect.width / 2 - width / 2,
                                      window.innerWidth - width - 10));
    // Below the term unless there is no room, in which case above it.
    let top = rect.bottom + 10;
    if (top + height > window.innerHeight - 10) top = Math.max(10, rect.top - height - 10);
    node.style.left = `${left}px`;
    node.style.top = `${top}px`;
  });
}

/* ------------------------------------------------------------ empty states */
function emptyState(title, detail) {
  return `<div class="empty"><b>${esc(title)}</b><span>${esc(detail)}</span></div>`;
}

/* ---------------------------------------------------------------- loading */
/** Say what the machine is doing while it does it.
 *
 * The first request for the whole-capture payload BUILDS it -- about ten seconds
 * for the bundled dataset, and on the demo path that is guaranteed, because the
 * replay job clears the cache and the browser is redirected straight to a page
 * that needs it. A blank chart area for ten seconds reads as a broken page, and
 * no caption afterwards repairs that impression.
 */
function showLoading(title, detail) {
  const host = document.getElementById("loading");
  if (!host) return;
  host.className = "loading";
  host.hidden = false;
  host.innerHTML = `<div class="spinner"></div>
    <div><b>${esc(title)}</b><span>${esc(detail || "")}</span></div>`;
}

function hideLoading() {
  const host = document.getElementById("loading");
  if (!host) return;
  host.hidden = true;
  host.innerHTML = "";
}

/* ------------------------------------------------------- markdown (for docs) */
/** A deliberately small markdown renderer.
 *  A full parser is a dependency, and on an air-gapped machine a dependency is
 *  a thing that can fail. This handles the subset our own documents use;
 *  anything it does not understand passes through as plain text rather than
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
      out.push(`<h${match[1].length}>${inline(match[2])}</h${match[1].length}>`);
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
      if (/^\|[\s:|-]+\|\s*$/.test(line)) continue;      // separator row
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
