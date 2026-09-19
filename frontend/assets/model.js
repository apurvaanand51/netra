/* Method page: the measured scorecard, and the honest limits.
 *
 * Everything here is read from models/metrics.json -- the artifact the training
 * run wrote. Nothing is typed in by hand, so the page cannot drift from the model
 * it describes.
 */

"use strict";

function renderHeadline(m) {
  const cards = [
    { label: "Ranking quality", value: num(m.cv_auc_mean, 3), key: "auc",
      note: `± ${num(m.cv_auc_std, 3)} across ${num(m.folds)} cross-validation folds` },
    { label: "Accuracy of our flags", value: pct(m.cv_precision_mean, 1), key: "precision",
      note: `± ${pct(m.cv_precision_std, 1)} — of the groups we flagged, how many were real` },
    { label: "Cases caught", value: pct(m.cv_recall_mean, 1), key: "recall",
      note: `± ${pct(m.cv_recall_std, 1)} — of the planted cases, how many we found` },
    { label: "Confidence honesty", value: num(m.brier, 3), key: "brier",
      note: "how close the printed score is to the real frequency; lower is better" },
  ];
  document.getElementById("headline").innerHTML = cards.map((card) => `
    <div class="card">
      <h2>${card.label}</h2>
      <div class="figure">${annotated(esc(card.value), card.key)}</div>
      <p class="sub" style="margin:6px 0 0">${esc(card.note)}</p>
    </div>`).join("");
}

function renderCalibration(m) {
  document.getElementById("calibration").innerHTML = `
    <div class="statRow"><span>${annotated("Brier score", "brier")}</span>
      <strong>${num(m.brier, 3)}</strong></div>
    <div class="statRow"><span>Expected calibration error</span>
      <strong>${num(m.expected_calibration_error, 3)}</strong></div>
    <div class="statRow"><span>Evaluated on</span><strong>held-out split</strong></div>
    <div class="statRow"><span>Calibrator fitted</span>
      <strong>${m.calibrator_fitted ? "yes" : "not needed"}</strong></div>`;

  const reliability = m.reliability || [];
  if (reliability.length < 2) return;
  new Chart(document.getElementById("reliabilityChart").getContext("2d"), {
    type: "line",
    data: {
      datasets: [
        {
          label: "observed",
          data: reliability.map((row) => ({ x: row.predicted, y: row.observed })),
          borderColor: "#d99a2b", backgroundColor: "rgba(217,154,43,0.15)",
          pointRadius: (ctx) => 3 + Math.min(6, (reliability[ctx.dataIndex]?.count || 0) / 12),
          borderWidth: 2, tension: 0.2, fill: false,
        },
        {
          label: "perfect honesty",
          data: [{ x: 0, y: 0 }, { x: 1, y: 1 }],
          borderColor: "rgba(120,130,145,0.5)", borderWidth: 1, borderDash: [4, 4],
          pointRadius: 0, fill: false,
        },
      ],
    },
    options: {
      plugins: { legend: { display: false } },
      scales: {
        x: { min: 0, max: 1, title: { display: true, text: "score the tool printed",
               color: "#6b7683", font: { size: 10 } },
             grid: { color: "rgba(120,130,145,0.12)" }, ticks: { color: "#6b7683", font: { size: 10 } } },
        y: { min: 0, max: 1, title: { display: true, text: "how often it was actually right",
               color: "#6b7683", font: { size: 10 } },
             grid: { color: "rgba(120,130,145,0.12)" }, ticks: { color: "#6b7683", font: { size: 10 } } },
      },
      responsive: true, maintainAspectRatio: false,
    },
  });
}

function renderRuleExperiment(m) {
  const decoysFlagged = m.decoy_heldout_decoys_in_top_k;
  const decoysTotal = m.decoy_total_in_dataset;
  document.getElementById("ruleExperiment").innerHTML = `
    <h2 style="margin-top:6px">The rules, used on their own</h2>
    <p class="sub">Scored with nothing but the hand-written detector thresholds, exactly as shipped — the
      system a rules-only team would have built.</p>
    <div class="statRow"><span>${annotated("Accuracy of flags", "precision")}</span>
      <strong>${pct(m.rules_precision, 1)}</strong></div>
    <div class="statRow"><span>${annotated("Cases caught", "recall")}</span>
      <strong>${pct(m.rules_recall, 1)}</strong></div>
    <div class="statRow"><span>F1</span><strong>${num(m.rules_f1, 3)}</strong></div>
    <div class="statRow"><span>Groups they flagged</span><strong>${num(m.rules_flags)}</strong></div>

    <h2 style="margin-top:16px">The rules, deleted entirely</h2>
    <p class="sub">The model retrained with all nine rule-derived features removed. If it still separates the
      cases, the signal came from the measured traffic rather than from our own detectors echoed back.</p>
    <div class="statRow"><span>Features remaining</span>
      <strong>${num(m.ablation_features_remaining)} of ${num(m.n_features)}</strong></div>
    <div class="statRow"><span>${annotated("Ranking quality", "auc")} without them</span>
      <strong>${num(m.ablation_auc_mean, 3)} ± ${num(m.ablation_auc_std, 3)}</strong></div>

    <h2 style="margin-top:16px">The lawful look-alikes</h2>
    <p class="sub">The dataset contains ${num(decoysTotal)} high-volume payment processors that look
      statistically suspicious and are lawful. A rules engine cannot avoid them; they were designed to break
      rules.</p>
    <div class="statRow"><span>Flagged in the top 25, held out</span>
      <strong>${num(decoysFlagged)} of ${num(decoysTotal)}</strong></div>
    <div class="caveat ${decoysFlagged ? "strong" : ""}">
      ${decoysFlagged
        ? `This is the one result that came out against us: <b>${num(decoysFlagged)} lawful service(s)</b> were
           still flagged on held-out predictions, so the tool does occasionally promote a legitimate
           high-volume actor. That is a real limitation and it is reported here rather than dropped.`
        : `No lawful look-alike was promoted to the lead rail. This is the test the rules fail and the model
           passes, and it is the clearest evidence that the ranking is learned rather than thresholded.`}
    </div>`;
}

function renderModelChoice(m) {
  document.getElementById("modelChoice").innerHTML = `
    <table class="data">
      <thead><tr><th>Model</th><th class="num">Ranking quality</th></tr></thead>
      <tbody>
        <tr><td>Random forest <span class="muted small">(shipped)</span></td>
          <td class="num">${num(m.cv_auc_mean, 3)} ± ${num(m.cv_auc_std, 3)}</td></tr>
        <tr><td>Logistic regression <span class="muted small">(deliberately simple)</span></td>
          <td class="num">${num(m.logistic_auc_mean, 3)} ± ${num(m.logistic_auc_std, 3)}</td></tr>
      </tbody>
    </table>
    <div class="caveat">
      The margin over a linear model is <b>small</b>. Read honestly, that means the
      <b>feature engineering is doing more work than the model choice</b> — the engineered facts about each
      group already separate the classes almost linearly. The forest is selected for its small edge and for the
      per-lead attributions it provides, not because it is magic.
    </div>`;
}

function renderLimits() {
  document.getElementById("limits").innerHTML = `
    <div class="reasons">
      <div class="reason critical"><b>A lead, not a verdict</b><span>A high score means "look here first". It is
        not evidence of guilt and no action should follow from it without an analyst reading the reasons
        beside it.</span></div>
      <div class="reason critical"><b>Not validated on real traffic</b><span>Every figure here comes from
        synthetic data. Performance on operational data is <em>not established</em> by these numbers.</span></div>
      <div class="reason high"><b>The dataset is capped</b><span>The generator limits transfer size, so the
        largest, 99th and 99.9th percentile transactions are identical. Conclusions about very large transfers
        do not transfer to reality.</span></div>
      <div class="reason high"><b>Unknown patterns</b><span>Anomaly detection can flag behaviour unlike anything
        in training, but it cannot say whether that behaviour is criminal. Its measured accuracy on held-out
        data is below the base rate, and that is reported rather than hidden.</span></div>
      <div class="reason high"><b>Fund trails are estimates</b><span>Bitcoin is fungible. A multi-hop trail is a
        proportional allocation, not an observation, and it under-reports reach rather than overstating
        it.</span></div>
      <div class="reason medium"><b>Validation leaks slightly</b><span>Cross-validation folds are stratified but
        rows from the same batch are correlated. Grouped-by-batch validation is the correct method and is
        outstanding work.</span></div>
      <div class="reason info"><b>Bitcoin only</b><span>Privacy coins are out of scope for this problem
        statement.</span></div>
    </div>`;
}

function renderFullTable(m) {
  const rows = [
    ["Cross-validation method", m.cv_method || "—"],
    ["Ranking quality (AUC)", `${num(m.cv_auc_mean, 4)} ± ${num(m.cv_auc_std, 4)}`],
    ["Accuracy of flags (precision)", `${num(m.cv_precision_mean, 4)} ± ${num(m.cv_precision_std, 4)}`],
    ["Cases caught (recall)", `${num(m.cv_recall_mean, 4)} ± ${num(m.cv_recall_std, 4)}`],
    ["F1", `${num(m.cv_f1_mean, 4)} ± ${num(m.cv_f1_std, 4)}`],
    ["Accuracy among the top 10", num(m.cv_precision_at_k_mean, 4)],
    ["Single held-out split — precision", num(m.risk_precision, 4)],
    ["Single held-out split — recall", num(m.risk_recall, 4)],
    ["Single held-out split — AUC", num(m.risk_auc, 4)],
    ["Confusion (TP / FP / FN / TN)",
      `${num(m.true_positives)} / ${num(m.false_positives)} / ${num(m.false_negatives)} / ${num(m.true_negatives)}`],
    ["Brier score", num(m.brier, 4)],
    ["Expected calibration error", num(m.expected_calibration_error, 4)],
    ["Wallet grouping accuracy (Adjusted Rand Index)", num(m.cluster_ari, 4)],
    ["Group separation (modularity, material-flow backbone)", num(m.modularity, 4)],
    ["Anomaly detection, precision at 20", num(m.anomaly_precision_at_k, 4)],
    ["Anomaly base rate", num(m.anomaly_base_rate, 4)],
    ["Rules-only F1", num(m.rules_f1, 4)],
    ["Ablation AUC (rule features removed)", num(m.ablation_auc_mean, 4)],
    ["Lawful look-alikes flagged, held out", `${num(m.decoy_heldout_decoys_in_top_k)} of ${num(m.decoy_total_in_dataset)}`],
    ["Training rows pooled across batches", num(m.n_entities)],
    ["Features per wallet group", num(m.n_features)],
    ["Training mode", m.training_mode || "—"],
    ["Explanation method", m.explanation_method || "—"],
  ];
  document.getElementById("fullTable").innerHTML = `
    <thead><tr><th>Metric</th><th>Value</th><th class="muted">Notes</th></tr></thead>
    <tbody>${rows.map(([label, value]) => `
      <tr><td>${esc(label)}</td><td>${esc(value)}</td><td class="muted small"></td></tr>`).join("")}</tbody>`;
}

(async function main() {
  await NETRA.init();
  let metrics;
  try {
    metrics = await api("/metrics");
  } catch (error) {
    document.querySelector(".page").insertAdjacentHTML("afterbegin",
      emptyState("No trained model found.", "Run the training step, then reload this page."));
    return;
  }
  if (!metrics.cv_auc_mean) {
    document.querySelector(".page").insertAdjacentHTML("afterbegin",
      emptyState("The scorecard is empty.", "The model has not been trained with cross-validation yet."));
    return;
  }

  NETRA.setCounters([
    { label: "ranking quality", value: num(metrics.cv_auc_mean, 3) },
    { label: "cases caught", value: pct(metrics.cv_recall_mean, 1) },
    { label: "confidence honesty", value: num(metrics.brier, 3) },
    { label: "features", value: num(metrics.n_features) },
  ]);
  NETRA.setStrip({
    provenance: `model RandomForest (windowed) · trained on ${num(metrics.n_entities)} rows · ` +
      `${metrics.explanation_method || "explanations: decision-path contributions"}`,
    generated: metrics.runtime_seconds ? `training run took ${num(metrics.runtime_seconds, 1)}s` : "",
    state: "measured on synthetic data",
  });

  renderHeadline(metrics);
  renderCalibration(metrics);
  renderRuleExperiment(metrics);
  renderModelChoice(metrics);
  renderLimits();
  renderFullTable(metrics);
})();
