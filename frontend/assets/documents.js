/* Documents page: the written record, rendered in the app.
 *
 * The markdown renderer lives in assets/api.js. It is deliberately small: a full
 * parser is a dependency, and on an air-gapped machine a dependency is a thing
 * that can fail. Anything it does not understand passes through as plain text
 * rather than disappearing.
 */

"use strict";

async function openDoc(file, node) {
  try {
    const response = await fetch(`/documents/${file}`);
    if (!response.ok) throw new Error(`${response.status}`);
    const text = await response.text();
    document.getElementById("docBody").innerHTML = renderMarkdown(text);
    document.getElementById("docBody").scrollIntoView({ block: "start" });
    document.querySelectorAll("#docList li").forEach((item) =>
      item.classList.toggle("on", item === node));
    history.replaceState(null, "", `?doc=${encodeURIComponent(file)}`);
    NETRA.setStrip({ state: file });
  } catch (error) {
    toast(`Could not open ${file}: ${error.message}`);
  }
}

(async function main() {
  await NETRA.init();
  let index;
  try {
    index = await api("/documents/index.json");
  } catch (error) {
    document.getElementById("docList").innerHTML =
      `<li style="color:var(--ink-3);border-style:dashed">No documents found on this machine.</li>`;
    return;
  }

  const documents = index.documents || [];
  document.getElementById("docList").innerHTML = documents.map((doc) =>
    `<li data-file="${esc(doc.file)}" title="${esc(doc.description)}">${esc(doc.title)}</li>`
  ).join("");

  const items = document.querySelectorAll("#docList li");
  items.forEach((node) => { node.onclick = () => openDoc(node.dataset.file, node); });

  NETRA.setCounters([{ label: "documents", value: num(documents.length) }]);
  NETRA.setStrip({
    provenance: "served from this machine · no external requests",
    generated: "",
    state: "",
  });

  const requested = new URLSearchParams(location.search).get("doc");
  const first = documents.find((doc) => doc.file === requested) || documents[0];
  if (first) {
    const node = [...items].find((item) => item.dataset.file === first.file);
    openDoc(first.file, node);
  }
})();
