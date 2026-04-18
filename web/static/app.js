// ── state ─────────────────────────────────────────────────────────────────────
let currentMode = "local";
let logFiles = [];
let pieChart = null;

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

// ── analysis: search ─────────────────────────────────────────────────────────
async function submitQuery() {
  const prompt = document.getElementById("promptInput").value.trim();
  if (!prompt) { toast("Enter a question", "error"); return; }
  showSpinner(true);
  clearResults();

  const data = await api("/api/search", { prompt, max_matches: 50, context_lines: 2 });
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
  const analysis = await api("/api/analyze", {});
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
  showSpinner(true);
  clearResults();

  const data = await api("/api/analyze", { max_samples: 50 });
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
  el.innerHTML = matches.map(m => {
    const sim = m.similarity != null ? `<span class="sim">sim ${m.similarity.toFixed(3)}</span>` : "";
    return `
      <div class="match-item">
        <div class="match-header">
          <span>${escHtml(m.file)}:${m.line_number}</span>
          ${sim}
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

// ── keyboard shortcut: Ctrl+Enter to submit ──────────────────────────────────
document.getElementById("promptInput").addEventListener("keydown", e => {
  if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
    e.preventDefault();
    submitQuery();
  }
});

// ── init: check server status ────────────────────────────────────────────────
(async function init() {
  try {
    const res = await fetch("/api/status");
    const data = await res.json();
    setRunning(data.running);
  } catch (e) { /* ignore */ }
})();

