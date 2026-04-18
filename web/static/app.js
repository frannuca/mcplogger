// ── state ─────────────────────────────────────────────────────────────────────
let currentMode = "local";
let logFiles = ["/Users/fran/mcps/mcplogger/test_app.log"];
let pieChart = null;
let clusterData = null;  // holds semantic_analysis response for word cloud
let activeHourMin = null;  // null means no hour filter active
let activeHourMax = null;
let activeDateStart = null;  // null means no date filter; ISO string e.g. "2026-04-18"
let activeDateEnd = null;
let pendingAction = null;    // "semantic" or "analyze" — which action the modal was opened for

// ── tab switching ────────────────────────────────────────────────────────────
document.querySelectorAll(".tab-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach(p => p.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById("panel" + capitalize(btn.dataset.tab)).classList.add("active");
  });
});
function capitalize(s) { return s.charAt(0).toUpperCase() + s.slice(1); }

// ── mode selection ───────────────────────────────────────────────────────────
function selectMode(mode) {
  currentMode = mode;
  document.querySelectorAll(".mode-option").forEach(o => {
    o.classList.toggle("selected", o.dataset.mode === mode);
  });
  document.getElementById("localFields").classList.toggle("hidden", mode !== "local");
  document.getElementById("remoteFields").classList.toggle("hidden", mode !== "remote");
}

// ── log file tags ────────────────────────────────────────────────────────────
function renderLogTags() {
  const el = document.getElementById("logFileTags");
  el.innerHTML = logFiles.map((f, i) =>
    `<span class="tag">📄 ${f} <span class="remove" onclick="removeLogFile(${i})">✕</span></span>`
  ).join("");
}
function addLogFile() {
  const inp = document.getElementById("logFileInput");
  const v = inp.value.trim();
  if (v && !logFiles.includes(v)) {
    logFiles.push(v);
    renderLogTags();
    inp.value = "";
  }
}
function removeLogFile(i) {
  logFiles.splice(i, 1);
  renderLogTags();
}
// enter key in log file input
document.getElementById("logFileInput").addEventListener("keydown", e => {
  if (e.key === "Enter") { e.preventDefault(); addLogFile(); }
});

// ── build config object ──────────────────────────────────────────────────────
function buildConfig() {
  const cfg = { mode: currentMode, log_files: logFiles };
  if (currentMode === "local") {
    cfg.llm_url = document.getElementById("llmUrl").value.trim();
    cfg.embedding_url = document.getElementById("embeddingUrl").value.trim();
    cfg.model = document.getElementById("localModel").value.trim() || "local";
  } else {
    cfg.api_key = document.getElementById("apiKey").value.trim();
    cfg.model = document.getElementById("remoteModel").value.trim() || "gpt-4o-mini";
  }
  return cfg;
}

// ── server control ───────────────────────────────────────────────────────────
async function startServer() {
  const cfg = buildConfig();
  if (cfg.log_files.length === 0) {
    toast("Add at least one log file", "error");
    return;
  }
  if (cfg.mode === "remote" && !cfg.api_key) {
    toast("API key is required for remote mode", "error");
    return;
  }

  document.getElementById("btnStart").disabled = true;
  const res = await api("/api/start", cfg);
  if (res.ok) {
    setRunning(true);
    toast(`Server started (PID ${res.pid}, ${res.tools} tools)`, "success");
    // auto-switch to analysis tab
    document.querySelector('[data-tab="analysis"]').click();
  } else {
    toast(res.error || "Failed to start", "error");
    document.getElementById("btnStart").disabled = false;
  }
}

async function stopServer() {
  await api("/api/stop", {});
  setRunning(false);
  toast("Server stopped", "success");
}

async function resetCache() {
  const res = await api("/api/reset_cache", {});
  if (res.error) toast(res.error, "error");
  else toast("File cache cleared — next query re-reads from disk", "success");
}

function setRunning(running) {
  const badge = document.getElementById("statusBadge");
  const text = document.getElementById("statusText");
  badge.className = "status-badge " + (running ? "running" : "stopped");
  text.textContent = running ? "Running" : "Stopped";
  document.getElementById("btnStart").disabled = running;
  document.getElementById("btnStop").disabled = !running;
  document.getElementById("btnReset").disabled = !running;
  document.getElementById("tabAnalysis").disabled = !running;
}

// ── attach active time/date filters to a request body ────────────────────────
function applyTimeFilters(body) {
  if (activeHourMin !== null) {
    body.hour_min = activeHourMin;
    body.hour_max = activeHourMax;
  }
  if (activeDateStart) {
    body.time_start = activeDateStart + "T00:00:00";
  }
  if (activeDateEnd) {
    body.time_end = activeDateEnd + "T23:59:59";
  }
  return body;
}

// ── analysis: search ─────────────────────────────────────────────────────────
async function submitQuery() {
  const prompt = document.getElementById("promptInput").value.trim();
  if (!prompt) { toast("Enter a question", "error"); return; }
  openTimeModal("search");
}

async function _doSearch() {
  const prompt = document.getElementById("promptInput").value.trim();
  showSpinner(true);
  clearResults();
  hideWordCloud();

  const searchBody = applyTimeFilters({ prompt, max_matches: 50, context_lines: 2 });
  const data = await api("/api/search", searchBody);
  showSpinner(false);

  if (data.error) { toast(data.error, "error"); return; }

  // show results
  showResultsGrid(true);
  document.getElementById("statMatches").textContent = data.total_matches ?? "—";
  const buffered = data.lines_buffered || {};
  const totalLines = Object.values(buffered).reduce((a, b) => a + b, 0);
  document.getElementById("statTotal").textContent = totalLines.toLocaleString();
  document.getElementById("statErrors").textContent = data.total_matches ?? "—";
  document.getElementById("statRate").textContent = totalLines > 0
    ? ((data.total_matches / totalLines) * 100).toFixed(2) + "%"
    : "—";

  renderSummary(data.human_summary || "(no summary)");
  renderMatches(data.matches || []);

  // For search results, we don't get pattern_counts — do a quick analyze for the chart
  const analysis = await api("/api/analyze", applyTimeFilters({}));
  if (analysis && analysis.pattern_counts) {
    renderPieChart(analysis.pattern_counts);
    // update stat boxes from analysis
    document.getElementById("statTotal").textContent = (analysis.total_lines ?? 0).toLocaleString();
    document.getElementById("statErrors").textContent = (analysis.error_lines ?? 0).toLocaleString();
    document.getElementById("statRate").textContent =
      ((analysis.error_rate ?? 0) * 100).toFixed(1) + "%";
  }
}

// ── analysis: full analyze ───────────────────────────────────────────────────
async function runAnalyze() {
  openTimeModal("analyze");
}

// ── open shared time-filter modal ────────────────────────────────────────────
function openTimeModal(action) {
  pendingAction = action;
  document.getElementById("twHourMin").value = 0;
  document.getElementById("twHourMax").value = 23;
  document.getElementById("twDateStart").value = "";
  document.getElementById("twDateEnd").value = "";
  document.getElementById("twDateDetails").removeAttribute("open");
  updateHourLabels();
  // set contextual button label
  const labels = { search: "🔍 Apply & Search", analyze: "📊 Apply & Analyze", semantic: "☁️ Apply & Cluster" };
  document.getElementById("twApplyBtn").innerHTML = labels[action] || "✅ Apply & Run";
  document.getElementById("timeWindowModal").style.display = "flex";
}

async function _doAnalyze() {
  showSpinner(true);
  clearResults();
  hideWordCloud();

  const analyzeBody = applyTimeFilters({ max_samples: 50 });
  const data = await api("/api/analyze", analyzeBody);
  showSpinner(false);

  if (data.error) { toast(data.error, "error"); return; }

  showResultsGrid(true);
  document.getElementById("statTotal").textContent = (data.total_lines ?? 0).toLocaleString();
  document.getElementById("statErrors").textContent = (data.error_lines ?? 0).toLocaleString();
  document.getElementById("statRate").textContent =
    ((data.error_rate ?? 0) * 100).toFixed(1) + "%";
  document.getElementById("statMatches").textContent = data.error_lines ?? "—";

  renderSummary(data.human_summary || "(no summary)");

  // render sample errors as matches
  const sampleMatches = (data.sample_error_lines || []).map((line, i) => ({
    file: (data.log_files || [""])[0],
    line_number: i + 1,
    line: line,
    context: line,
  }));
  renderMatches(sampleMatches);

  if (data.pattern_counts) {
    renderPieChart(data.pattern_counts);
  }
}

// ── rendering helpers ────────────────────────────────────────────────────────
function renderSummary(text) {
  document.getElementById("summaryBox").textContent = text;
}

function renderMatches(matches) {
  const el = document.getElementById("matchList");
  document.getElementById("matchCount").textContent = `(${matches.length} shown)`;
  if (matches.length === 0) {
    el.innerHTML = '<p style="color:var(--text2);">No matching lines found.</p>';
    return;
  }
  el.innerHTML = matches.map((m, i) => {
    const sim = m.similarity != null ? `<span class="sim">sim ${m.similarity.toFixed(3)}</span>` : "";
    return `
      <div class="match-item">
        <div class="match-header">
          <span>${escHtml(m.file)}:${m.line_number}</span>
          ${sim}
          <button class="btn-explain" onclick="explainError(this)" data-line="${escAttr(m.line || m.context)}">🔬 Explain</button>
        </div>
        <pre>${escHtml(m.context || m.line)}</pre>
      </div>`;
  }).join("");
}

const CHART_COLORS = [
  "#6c8cff", "#ff5c5c", "#ffa94d", "#3dd68c", "#c084fc",
  "#f472b6", "#38bdf8", "#facc15", "#a3e635", "#e879f9",
];

function renderPieChart(patternCounts) {
  const labels = Object.keys(patternCounts);
  const values = Object.values(patternCounts);
  const total = values.reduce((a, b) => a + b, 0);

  const ctx = document.getElementById("pieChart").getContext("2d");
  if (pieChart) pieChart.destroy();

  pieChart = new Chart(ctx, {
    type: "doughnut",
    data: {
      labels: labels.map((l, i) => `${l} (${((values[i]/total)*100).toFixed(1)}%)`),
      datasets: [{
        data: values,
        backgroundColor: CHART_COLORS.slice(0, labels.length),
        borderWidth: 0,
        hoverOffset: 8,
      }],
    },
    options: {
      responsive: true,
      cutout: "55%",
      plugins: {
        legend: {
          position: "bottom",
          labels: { color: "#e4e6f0", font: { size: 12 }, padding: 14 },
        },
        tooltip: {
          callbacks: {
            label: ctx => {
              const v = ctx.parsed;
              const pct = ((v / total) * 100).toFixed(1);
              return ` ${ctx.label}: ${v} (${pct}%)`;
            },
          },
        },
      },
    },
  });
}

function clearResults() {
  document.getElementById("summaryBox").textContent = "Waiting for results…";
  document.getElementById("matchList").innerHTML = "";
  document.getElementById("matchCount").textContent = "";
  ["statTotal","statErrors","statRate","statMatches"].forEach(id =>
    document.getElementById(id).textContent = "—"
  );
}

function showResultsGrid(show) {
  document.getElementById("statRow").style.display = show ? "" : "none";
  document.getElementById("resultsGrid").style.display = show ? "" : "none";
}

function showSpinner(show) {
  document.getElementById("spinner").classList.toggle("visible", show);
}

// ── utilities ────────────────────────────────────────────────────────────────
async function api(url, body) {
  try {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    return await res.json();
  } catch (err) {
    return { error: err.message };
  }
}

function toast(msg, type = "") {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.className = "toast visible " + type;
  clearTimeout(el._timer);
  el._timer = setTimeout(() => { el.classList.remove("visible"); }, 4000);
}

function escHtml(s) {
  const d = document.createElement("div");
  d.textContent = s || "";
  return d.innerHTML;
}

function escAttr(s) {
  return (s || "").replace(/&/g,"&amp;").replace(/"/g,"&quot;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
}

// ── error explanation ────────────────────────────────────────────────────────
let currentExplainLine = "";

async function explainError(btn) {
  const line = btn.dataset.line;
  if (!line) return;
  currentExplainLine = line;

  const section = document.getElementById("explainSection");
  section.style.display = "block";
  section.scrollIntoView({ behavior: "smooth", block: "start" });

  document.getElementById("explainLine").textContent = line;
  document.getElementById("explainBox").textContent = "🌐 Searching the web and asking LLM…";
  document.getElementById("explainSpinner").classList.add("visible");
  document.getElementById("explainWebResults").innerHTML = "";

  const data = await api("/api/explain", { error_line: line });
  document.getElementById("explainSpinner").classList.remove("visible");

  if (data.error) {
    document.getElementById("explainBox").textContent = "Error: " + data.error;
    return;
  }
  document.getElementById("explainBox").textContent = data.explanation || "(no explanation)";

  // render web search results
  const webResults = data.web_results || [];
  const webEl = document.getElementById("explainWebResults");
  if (webResults.length > 0) {
    webEl.innerHTML = "<h3>🌐 Web Search Results</h3>" + webResults.map(r =>
      `<div class="web-result">
        <a href="${escAttr(r.url)}" target="_blank" rel="noopener">${escHtml(r.title)}</a>
        <p>${escHtml(r.body)}</p>
      </div>`
    ).join("");
  } else {
    webEl.innerHTML = '<p style="color:var(--text2);font-size:12px;">No web results found.</p>';
  }
}

function hideExplain() {
  document.getElementById("explainSection").style.display = "none";
}

function _extractSearchTerms() {
  // Extract the error type / key message from the log line for searching
  const line = currentExplainLine;
  // Remove timestamp prefix and common log prefixes
  const cleaned = line
    .replace(/^\d{4}[-/]\d{2}[-/]\d{2}[T ]\d{2}:\d{2}:\d{2}\s*/, "")
    .replace(/^(ERROR|WARN|CRITICAL|FATAL|INFO|DEBUG)\s*/i, "")
    .replace(/^\[[\w\-]+\]\s*/, "")
    .replace(/^\[[\w\-]+\]\s*/, "")
    .trim();
  // Take first 120 chars to keep the query reasonable
  return cleaned.substring(0, 120);
}

function searchGoogle() {
  const q = _extractSearchTerms();
  window.open("https://www.google.com/search?q=" + encodeURIComponent(q), "_blank");
}

function searchStackOverflow() {
  const q = _extractSearchTerms();
  window.open("https://stackoverflow.com/search?q=" + encodeURIComponent(q), "_blank");
}

// ── keyboard shortcut: Ctrl+Enter to submit ──────────────────────────────────
document.getElementById("promptInput").addEventListener("keydown", e => {
  if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
    e.preventDefault();
    submitQuery();
  }
});

// ── semantic analysis / word cloud ───────────────────────────────────────────

const CLOUD_COLORS = [
  "#6c8cff", "#ff5c5c", "#ffa94d", "#3dd68c", "#c084fc",
  "#f472b6", "#38bdf8", "#facc15", "#a3e635", "#e879f9",
  "#fb923c", "#67e8f9", "#d946ef", "#4ade80", "#f87171",
  "#a78bfa", "#fbbf24", "#34d399", "#f43f5e", "#818cf8",
];

async function runSemanticAnalysis() {
  openTimeModal("semantic");
}

function updateHourLabels() {
  const min = parseInt(document.getElementById("twHourMin").value);
  const max = parseInt(document.getElementById("twHourMax").value);
  document.getElementById("twMinLabel").textContent = String(min).padStart(2, "0") + ":00";
  document.getElementById("twMaxLabel").textContent = String(max).padStart(2, "0") + ":00";
  const wraps = min > max;
  const hint = wraps
    ? `Showing lines from <b>${String(min).padStart(2,"0")}:00</b> to <b>23:59</b> and <b>00:00</b> to <b>${String(max).padStart(2,"0")}:59</b>`
    : `Showing lines from <b>${String(min).padStart(2,"0")}:00</b> to <b>${String(max).padStart(2,"0")}:59</b>`;
  document.getElementById("twRangeHint").innerHTML = hint;
}

function cancelTimeWindow() {
  document.getElementById("timeWindowModal").style.display = "none";
}

async function confirmTimeWindow(useFilter) {
  document.getElementById("timeWindowModal").style.display = "none";

  if (useFilter) {
    activeHourMin = parseInt(document.getElementById("twHourMin").value);
    activeHourMax = parseInt(document.getElementById("twHourMax").value);
    activeDateStart = document.getElementById("twDateStart").value || null;
    activeDateEnd = document.getElementById("twDateEnd").value || null;
    if (activeDateStart && !activeDateEnd) {
      activeDateEnd = new Date().toISOString().slice(0, 10);
    }
  } else {
    activeHourMin = null;
    activeHourMax = null;
    activeDateStart = null;
    activeDateEnd = null;
  }

  if (pendingAction === "analyze") {
    await _doAnalyze();
  } else if (pendingAction === "search") {
    await _doSearch();
  } else {
    await _doSemanticAnalysis();
  }
}

async function _doSemanticAnalysis() {
  let prompt = document.getElementById("promptInput").value.trim() || "what are the main error categories";

  showSpinner(true);
  hideSearchResults();
  hideWordCloud();

  const body = applyTimeFilters({ prompt, max_clusters: 20 });

  const data = await api("/api/semantic_analyze", body);
  showSpinner(false);

  if (data.error) { toast(data.error, "error"); return; }
  if (!data.clusters || data.clusters.length === 0) {
    toast("No error clusters found. Make sure the log has error lines.", "error");
    return;
  }

  clusterData = data;
  renderWordCloud(data);
}

function renderWordCloud(data) {
  const section = document.getElementById("wordCloudSection");
  section.style.display = "block";

  // info
  const tw = data.time_window ? ` (window: ${data.time_window})` : "";
  document.getElementById("cloudInfo").textContent =
    `— ${data.total_error_lines} errors in ${data.total_lines.toLocaleString()} lines${tw}`;

  // build cloud
  const container = document.getElementById("wordCloud");
  container.innerHTML = "";

  const maxSize = Math.max(...data.clusters.map(c => c.size));
  const minFont = 14;
  const maxFont = 64;

  data.clusters.forEach((cluster, i) => {
    const ratio = cluster.size / maxSize;
    const fontSize = Math.round(minFont + ratio * (maxFont - minFont));
    const color = CLOUD_COLORS[i % CLOUD_COLORS.length];
    const opacity = 0.5 + ratio * 0.5;

    const span = document.createElement("span");
    span.className = "cloud-word";
    span.style.fontSize = fontSize + "px";
    span.style.color = color;
    span.style.opacity = opacity;
    span.textContent = cluster.label;
    span.title = `${cluster.size} errors (${cluster.percentage}%) — click for details`;
    span.dataset.idx = i;

    // badge with count
    const badge = document.createElement("span");
    badge.className = "cloud-badge";
    badge.textContent = cluster.size;
    span.appendChild(badge);

    span.addEventListener("click", () => showClusterDetail(i));
    container.appendChild(span);
  });

  // show AI summary
  if (data.human_summary) {
    document.getElementById("cloudSummaryCard").style.display = "block";
    document.getElementById("cloudSummaryBox").textContent = data.human_summary;
  } else {
    document.getElementById("cloudSummaryCard").style.display = "none";
  }

  // auto-select the largest cluster
  showClusterDetail(0);
}

function showClusterDetail(idx) {
  if (!clusterData || !clusterData.clusters[idx]) return;
  const cluster = clusterData.clusters[idx];

  // highlight selected word
  document.querySelectorAll(".cloud-word").forEach(el => {
    el.classList.toggle("selected", parseInt(el.dataset.idx) === idx);
  });

  // show detail panel
  const panel = document.getElementById("clusterDetail");
  panel.style.display = "block";

  document.getElementById("detailLabel").textContent = cluster.label;
  document.getElementById("detailMeta").textContent =
    `— ${cluster.size} lines (${cluster.percentage}%) — cohesion: ${cluster.centroid_similarity}`;

  // keywords as tags
  const kwContainer = document.getElementById("detailKeywords");
  kwContainer.innerHTML = cluster.keywords.map(k =>
    `<span class="tag">🏷️ ${escHtml(k)}</span>`
  ).join("");

  // sample lines
  const lineContainer = document.getElementById("detailLines");
  if (cluster.sample_lines.length === 0) {
    lineContainer.innerHTML = '<p style="color:var(--text2);">No sample lines.</p>';
  } else {
    lineContainer.innerHTML = cluster.sample_lines.map(line =>
      `<div class="match-item">
        <div class="match-header" style="justify-content:flex-end;">
          <button class="btn-explain" onclick="explainError(this)" data-line="${escAttr(line)}">🔬 Explain</button>
        </div>
        <pre>${escHtml(line)}</pre>
      </div>`
    ).join("");
  }
}

function hideWordCloud() {
  document.getElementById("wordCloudSection").style.display = "none";
  document.getElementById("clusterDetail").style.display = "none";
  document.getElementById("cloudSummaryCard").style.display = "none";
  clusterData = null;
}

function hideSearchResults() {
  showResultsGrid(false);
}

// ── init: check server status ────────────────────────────────────────────────
(async function init() {
  renderLogTags();
  try {
    const res = await fetch("/api/status");
    const data = await res.json();
    setRunning(data.running);
  } catch (e) { /* ignore */ }
})();

