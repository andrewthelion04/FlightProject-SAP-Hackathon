/* eslint-env browser */

const startBtn = document.getElementById("startBtn");
const resetBtn = document.getElementById("resetBtn");
const alertArea = document.getElementById("alertArea");
const progressFill = document.getElementById("progressFill");
const percentVal = document.getElementById("percentVal");
const dayVal = document.getElementById("dayVal");
const hourVal = document.getElementById("hourVal");
const stepVal = document.getElementById("stepVal");
const stepTotal = document.getElementById("stepTotal");
const runStatus = document.getElementById("runStatus");
const sessionIdEl = document.getElementById("sessionId");
const scoreVal = document.getElementById("scoreVal");
const eventList = document.getElementById("eventList");
const dailyTableBody = document.getElementById("dailyTableBody");
const logStream = document.getElementById("logStream");
const approachSlider = document.getElementById("approachSlider");
const approachDescriptor = document.getElementById("approachDescriptor");
const selectedStrategy = document.getElementById("selectedStrategy");
const welcomeScreen = document.getElementById("welcomeScreen");
const dashboard = document.getElementById("dashboard");
const enterAppBtn = document.getElementById("enterAppBtn");

const state = {
  status: window.initialStatus || {},
  approach: approachSlider ? Number(approachSlider.value) : 50,
  pollHandle: null,
  strategies: Array.isArray(window.strategyOptions) && window.strategyOptions.length ? window.strategyOptions : ["strategy"],
};
const strategyScale = Array.isArray(window.strategyScale) ? window.strategyScale : null;

function formatCurrency(value) {
  const num = Number(value) || 0;
  return new Intl.NumberFormat("de-DE", {
    style: "currency",
    currency: "EUR",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(num);
}

function describeApproach(value) {
  if (value < 20) return "Satisfaction first; costs tolerated to maximize experience.";
  if (value < 40) return "Customer leaning: higher willingness to spend for comfort.";
  if (value < 60) return "Balanced: weighing cost and satisfaction equally.";
  if (value < 80) return "Cost focused with flexibility for demand spikes.";
  return "Strict cost efficiency; purchases only when optimized.";
}

function pickStrategy(pct) {
  if (strategyScale && strategyScale.length) {
    const safePct = Math.min(100, Math.max(0, Number(pct) || 0));
    const found = strategyScale.find((entry) => safePct <= entry.max);
    return { name: found ? found.strategy : strategyScale[strategyScale.length - 1].strategy };
  }
  const list = state.strategies && state.strategies.length ? state.strategies : ["strategy"];
  const segment = 100 / list.length;
  const idx = Math.min(list.length - 1, Math.floor(pct / segment));
  return { name: list[idx], idx };
}

function renderApproach(value) {
  if (!approachSlider) return;
  const pct = Math.min(100, Math.max(0, Number(value) || 0));
  state.approach = pct;

  if (approachDescriptor) approachDescriptor.textContent = describeApproach(pct);

  const chosen = pickStrategy(pct);
  if (selectedStrategy) selectedStrategy.textContent = chosen.name || "strategy";

  // Slider track single-color for contrast.
  const sliderColor = "rgba(42, 64, 104, 0.9)";
  approachSlider.style.background = `linear-gradient(90deg, ${sliderColor} 0%, ${sliderColor} 100%)`;

  // Mood tint on the page (red to blue) but kept subtle for readability.
  const red = { r: 234, g: 76, b: 91 };
  const blue = { r: 72, g: 150, b: 255 };
  const t = pct / 100;
  const mix = (a, b) => Math.round(a + (b - a) * t);
  const r = mix(red.r, blue.r);
  const g = mix(red.g, blue.g);
  const b = mix(red.b, blue.b);
  const bgGradient = `linear-gradient(120deg, rgba(${r},${g},${b},0.12), rgba(${r},${g},${b},0.32))`;
  document.body.style.backgroundColor = "#0b1220";
  document.body.style.backgroundImage = bgGradient;
}

function toggleAlert(message, kind = "error") {
  if (!message) {
    alertArea.classList.add("hidden");
    alertArea.textContent = "";
    return;
  }
  alertArea.textContent = message;
  alertArea.className = `alert ${kind}`;
}

function renderProgress(progress = {}) {
  const pct = progress.percent_complete || 0;
  percentVal.textContent = pct.toFixed(2);
  dayVal.textContent = progress.day ?? 0;
  hourVal.textContent = progress.hour ?? 0;
  stepVal.textContent = progress.step ?? 0;
  stepTotal.textContent = progress.total_steps ?? 0;
  progressFill.style.width = `${Math.min(100, pct)}%`;
}

function renderEvents(events = []) {
  if (!eventList) return;
  eventList.innerHTML = "";
  const latest = events.slice(-20).reverse();
  latest.forEach((evt) => {
    const li = document.createElement("li");
    li.innerHTML = `
      <div class="event-meta">
        <span class="pill">Day ${evt.day} / H${evt.hour}</span>
        <span class="muted">Hourly cost</span>
        <strong>${evt.hourly_cost}</strong>
      </div>
      <p>Purchase: FC ${evt.purchase.first_class}, BC ${evt.purchase.business_class}, PE ${evt.purchase.premium_economy}, EC ${evt.purchase.economy}</p>
      <p class="muted">Cumulative: ${evt.cumulative_cost}</p>
    `;
    eventList.appendChild(li);
  });
}

function renderDaily(dailies = []) {
  if (!dailyTableBody) return;
  dailyTableBody.innerHTML = "";
  const sorted = [...dailies].sort((a, b) => a.day - b.day);
  sorted.forEach((d) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${d.day}</td>
      <td>${d.purchases.first_class}</td>
      <td>${d.purchases.business_class}</td>
      <td>${d.purchases.premium_economy}</td>
      <td>${d.purchases.economy}</td>
      <td>${d.cost}</td>
    `;
    dailyTableBody.appendChild(tr);
  });
}

function renderLogs(logs = []) {
  if (!logStream) return;
  logStream.innerHTML = "";
  const latest = logs.slice(-50);
  latest.forEach((line) => {
    const p = document.createElement("p");
    p.textContent = line;
    logStream.appendChild(p);
  });
  logStream.scrollTop = logStream.scrollHeight;
}

function renderStatus(status = {}) {
  state.status = status;
  renderProgress(status.progress || {});
  renderEvents(status.events || []);
  renderDaily(status.daily || []);
  renderLogs(status.logs || []);

  if (status.strategy && selectedStrategy) {
    selectedStrategy.textContent = status.strategy;
  }
  sessionIdEl.textContent = status.session_id || "not started";
  scoreVal.textContent = formatCurrency(status.final_score ?? 0);

  if (status.error) {
    runStatus.textContent = `Error: ${status.error}`;
    runStatus.className = "error";
    toggleAlert(status.error, "error");
  } else if (status.running) {
    runStatus.textContent = "Running";
    runStatus.className = "success";
    toggleAlert("");
  } else if (status.completed) {
    runStatus.textContent = "Completed";
    runStatus.className = "success";
    toggleAlert("");
  } else {
    runStatus.textContent = "Idle";
    runStatus.className = "";
    toggleAlert("");
  }

  startBtn.disabled = !!status.running;
  resetBtn.disabled = !!status.running;
}

async function fetchStatus() {
  try {
    const res = await fetch("/api/simulation/status");
    if (!res.ok) {
      throw new Error(`Status fetch failed (${res.status})`);
    }
    const json = await res.json();
    renderStatus(json);
  } catch (err) {
    toggleAlert(err.message);
  }
}

async function startSimulation() {
  startBtn.disabled = true;
  toggleAlert("");
  try {
    const chosen = pickStrategy(state.approach);
    const res = await fetch("/api/simulation/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ approach: state.approach, strategy: chosen.name }),
    });
    const json = await res.json();
    if (!res.ok) {
      throw new Error(json.error || "Unable to start");
    }
    renderStatus(json);
    if (!state.pollHandle) {
      state.pollHandle = window.setInterval(fetchStatus, 1200);
    }
  } catch (err) {
    startBtn.disabled = false;
    toggleAlert(err.message);
  }
}

async function resetSimulation() {
  resetBtn.disabled = true;
  toggleAlert("");
  try {
    const res = await fetch("/api/simulation/reset", { method: "POST" });
    const json = await res.json();
    if (!res.ok) {
      throw new Error(json.error || "Unable to reset right now");
    }
    renderStatus(json);
  } catch (err) {
    toggleAlert(err.message);
  } finally {
    resetBtn.disabled = false;
  }
}

function init() {
  renderStatus(state.status);
  renderApproach(state.approach);
  if (!state.pollHandle) {
    state.pollHandle = window.setInterval(fetchStatus, 1200);
  }

  startBtn.addEventListener("click", startSimulation);
  resetBtn.addEventListener("click", resetSimulation);
  if (approachSlider) {
    approachSlider.addEventListener("input", (e) => {
      renderApproach(e.target.value);
      // Strategy selection is purely front-end for now; backend hook can consume state.approach or pickStrategy().
    });
  }

  if (enterAppBtn) {
    enterAppBtn.addEventListener("click", () => {
      if (welcomeScreen) welcomeScreen.classList.add("is-hidden");
      if (dashboard) dashboard.classList.remove("is-hidden");
    });
  }
}

init();
