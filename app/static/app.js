"use strict";

const $ = (s, el = document) => el.querySelector(s);
const eur = new Intl.NumberFormat("de-DE", { style: "currency", currency: "EUR", maximumFractionDigits: 0 });
const eur2 = new Intl.NumberFormat("de-DE", { style: "currency", currency: "EUR", maximumFractionDigits: 2 });
const pct = (v) => (v == null ? "–" : `${v.toLocaleString("de-DE", { maximumFractionDigits: 1 })} %`);
const num = (v) => {
  if (v == null) return null;
  const s = String(v).trim().replace(/\./g, (m, i, str) => (str.includes(",") ? "" : m)).replace(",", ".");
  if (s === "") return null;
  const n = Number(s);
  return Number.isFinite(n) ? n : NaN;
};
const fmtIn = (v) => (v == null ? "" : String(v).replace(".", ","));
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

async function api(method, url, body) {
  const r = await fetch(url, {
    method,
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
    credentials: "same-origin",
  });
  if (r.status === 401) { location.href = "/login"; throw new Error("Nicht angemeldet"); }
  let data = null;
  try { data = await r.json(); } catch (_) { /* leer */ }
  if (!r.ok) {
    let d = data && data.detail;
    if (Array.isArray(d)) d = d.map((x) => x.msg).join(", ");
    throw new Error(d || `Fehler ${r.status}`);
  }
  return data;
}

const state = { positions: [], settings: null, sim: null, mode: "nominal", chart: null, editing: null };

// ---------------- Prognose ----------------
const SCEN = [
  ["expected", "Erwartet"],
  ["best", "Best Case"],
  ["worst", "Worst Case"],
];

function renderTiles() {
  const sim = state.sim;
  const real = state.mode === "real";
  if (!sim) return;
  $("#forecast-title").textContent = `Prognose bis ${new Date(sim.end).toLocaleDateString("de-DE", { month: "2-digit", year: "numeric" })}`;
  $("#tiles").innerHTML = SCEN.map(([k, label]) => {
    const s = sim.scenarios[k];
    const net = real ? s.net_real : s.net;
    const gross = real ? s.gross_real : s.gross;
    const delta = s.return_delta ? ` (${s.return_delta > 0 ? "+" : ""}${s.return_delta.toLocaleString("de-DE")} Pkt.)` : "";
    return `<div class="card tile ${k}">
      <div class="label"><i class="swatch ${k === "expected" ? "" : "dash"}"></i>${label}${esc(delta)}</div>
      <div class="big">${eur.format(net)}</div><div class="label">${real ? "netto, heutige Kaufkraft" : "netto nach Steuern"}</div>
      <dl>${real ? `
        <dt>Brutto real</dt><dd>${eur.format(gross)}</dd>
        <dt>Netto nominal</dt><dd>${eur.format(s.net)}</dd>
        <dt>Steuer nominal</dt><dd>${eur.format(s.tax)}</dd>` : `
        <dt>Brutto</dt><dd>${eur.format(gross)}</dd>
        <dt>Steuer</dt><dd>${eur.format(s.tax)}</dd>
        <dt>Gewinn netto</dt><dd>${eur.format(s.gain_net)}</dd>
        <dt>Rendite gesamt</dt><dd>${pct(s.return_net_pct)}</dd>`}
      </dl>
    </div>`;
  }).join("");
  $("#paidline").innerHTML =
    `<span>Eingezahlt gesamt <b>${eur.format(sim.paid_total)}</b></span>` +
    `<span>Depot heute <b>${eur.format(sim.start_value)}</b></span>` +
    `<span>Steuersatz <b>${pct(sim.tax_rate)}</b></span>` +
    (real ? `<span>Real = in heutiger Kaufkraft</span>` : "");
  $("#warnings").innerHTML = (sim.warnings || []).map(esc).join("<br>");
}

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function renderChart() {
  const sim = state.sim;
  if (!sim) return;
  const key = state.mode === "real" ? "series_real" : "series";
  const accent = cssVar("--accent");
  const soft = cssVar("--accent-soft");
  const paid = cssVar("--paid");
  const text2 = cssVar("--text-2");
  const grid = cssVar("--border");
  const labels = sim.labels.map((l) => { const [y, m] = l.split("-"); return `${m}/${y}`; });

  const data = {
    labels,
    datasets: [
      { label: "Best Case", data: sim.scenarios.best[key], borderColor: accent, borderWidth: 1.5, borderDash: [5, 4], pointRadius: 0, fill: false },
      { label: "Worst Case", data: sim.scenarios.worst[key], borderColor: accent, borderWidth: 1.5, borderDash: [5, 4], pointRadius: 0, fill: "-1", backgroundColor: soft },
      { label: "Erwartet", data: sim.scenarios.expected[key], borderColor: accent, borderWidth: 2.5, pointRadius: 0, fill: false },
      { label: "Eingezahlt", data: sim.paid_in, borderColor: paid, borderWidth: 2, borderDash: [3, 3], pointRadius: 0, fill: false },
    ],
  };
  const options = {
    responsive: true,
    maintainAspectRatio: false,
    animation: false,
    interaction: { mode: "index", intersect: false },
    plugins: {
      legend: { display: false },
      tooltip: {
        itemSort: (a, b) => [2, 0, 1, 3].indexOf(a.datasetIndex) - [2, 0, 1, 3].indexOf(b.datasetIndex),
        callbacks: { label: (c) => ` ${c.dataset.label}: ${eur.format(c.parsed.y)}` },
      },
    },
    scales: {
      x: { grid: { display: false }, ticks: { color: text2, maxRotation: 0, autoSkip: true, maxTicksLimit: 7, callback(v) { return this.getLabelForValue(v).split("/")[1]; } } },
      y: {
        grid: { color: grid }, border: { display: false },
        ticks: { color: text2, maxTicksLimit: 6, callback: (v) => (Math.abs(v) >= 1e6 ? `${(v / 1e6).toLocaleString("de-DE", { maximumFractionDigits: 1 })} Mio €` : `${(Math.round(v / 1000) || 0).toLocaleString("de-DE")} T€`) },
      },
    },
  };
  if (state.chart) { state.chart.data = data; state.chart.options = options; state.chart.update(); }
  else state.chart = new Chart($("#chart"), { type: "line", data, options });
}

async function loadSimulation() {
  state.sim = await api("GET", "/api/simulate");
  renderTiles();
  renderChart();
}

document.querySelectorAll(".seg button").forEach((b) =>
  b.addEventListener("click", () => {
    state.mode = b.dataset.mode;
    document.querySelectorAll(".seg button").forEach((x) => x.classList.toggle("on", x === b));
    renderTiles();
    renderChart();
  }));
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => { if (state.chart) { state.chart.destroy(); state.chart = null; renderChart(); } });

// ---------------- Einstellungen ----------------
const sForm = $("#settings");
let sTimer = null;

function fillSettings() {
  const s = state.settings;
  for (const k of ["years", "best_delta", "worst_delta", "inflation", "allowance"]) sForm.elements[k].value = fmtIn(s[k]);
  sForm.elements.church_tax.value = String(Math.round(s.church_tax));
}

sForm.addEventListener("input", () => {
  clearTimeout(sTimer);
  $("#settings-status").textContent = "";
  sTimer = setTimeout(saveSettings, 600);
});
sForm.addEventListener("submit", (e) => e.preventDefault());

async function saveSettings() {
  const body = {};
  for (const k of ["years", "best_delta", "worst_delta", "inflation", "allowance", "church_tax"]) {
    const v = num(sForm.elements[k].value);
    if (v == null || Number.isNaN(v)) { $("#settings-status").textContent = "Bitte alle Felder mit Zahlen füllen."; return; }
    body[k] = v;
  }
  body.years = Math.round(body.years);
  try {
    state.settings = await api("PUT", "/api/settings", body);
    $("#settings-status").textContent = "Gespeichert";
    await loadSimulation();
  } catch (e) {
    $("#settings-status").textContent = e.message;
  }
}

// ---------------- Posten ----------------
const INTERVAL = { daily: "täglich", weekly: "wöchentlich", monthly: "monatlich" };
const WEEKDAY = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"];
const KIND = { etf: "ETF", fund: "Fonds", stock: "Aktie", crypto: "Krypto" };

function planText(p) {
  if (!p.rate) return "kein Sparplan";
  let when = "";
  if (p.interval === "weekly") when = `, ${WEEKDAY[p.exec_day] || ""}`;
  if (p.interval === "monthly") when = `, am ${p.exec_day}.`;
  return `${eur2.format(p.rate)} ${INTERVAL[p.interval]}${when}`;
}

function renderPositions() {
  const el = $("#positions");
  if (!state.positions.length) {
    el.innerHTML = `<div class="card empty">Noch keine Posten. Lege mit „+ Posten“ deinen ersten Sparplan an.</div>`;
    return;
  }
  el.innerHTML = state.positions.map((p) => {
    const q = p.quote;
    const valSrc = p.value_src === "manual" ? `<span class="chip manual">Wert manuell</span>`
      : p.value_src === "online" ? `<span class="chip">${esc(p.shares.toLocaleString("de-DE"))} Stk × ${eur2.format(q.price_eur)}</span>`
      : `<span class="chip">kein Wert</span>`;
    const retSrc = p.ret_src === "manual" ? `<span class="chip manual">${pct(p.ret)} p. a. manuell</span>`
      : p.ret_src === "online" ? `<span class="chip">${pct(p.ret)} p. a. (hist. ${q.hist_years} J.)</span>`
      : `<span class="chip">Rendite fehlt</span>`;
    const stale = q && q.stale ? `<span class="chip">Kurs veraltet</span>` : "";
    return `<div class="card pos">
      <div><div class="name">${esc(p.name)}</div>
        <div class="id">${esc(KIND[p.kind])}${p.isin ? " · " + esc(p.isin) : ""}${p.symbol ? " · " + esc(p.symbol) : ""}</div></div>
      <div class="val">${eur.format(p.value)}</div>
      <div class="meta">${valSrc}${retSrc}<span class="chip">${esc(planText(p))}</span>
        <span class="chip">${p.trading === "always" ? "jeden Tag" : "Börsentage"}</span>${stale}</div>
      <div class="actions">
        ${p.isin ? `<button class="btn small" data-refresh="${p.id}">Kurs abrufen</button>` : ""}
        <button class="btn small" data-edit="${p.id}">Bearbeiten</button>
      </div>
    </div>`;
  }).join("");
}

$("#positions").addEventListener("click", async (e) => {
  const r = e.target.closest("[data-refresh]");
  const ed = e.target.closest("[data-edit]");
  if (ed) openDialog(state.positions.find((p) => p.id === Number(ed.dataset.edit)));
  if (r) {
    r.disabled = true; r.textContent = "Lädt …";
    try {
      const upd = await api("POST", `/api/positions/${r.dataset.refresh}/refresh`);
      state.positions = state.positions.map((p) => (p.id === upd.id ? upd : p));
      renderPositions();
      await loadSimulation();
    } catch (err) { alert(err.message); r.disabled = false; r.textContent = "Kurs abrufen"; }
  }
});

$("#refresh-all").addEventListener("click", async (e) => {
  const b = e.currentTarget;
  b.disabled = true; b.textContent = "Lädt …";
  const errors = [];
  for (const p of state.positions.filter((x) => x.isin)) {
    try { await api("POST", `/api/positions/${p.id}/refresh`); } catch (err) { errors.push(`${p.name}: ${err.message}`); }
  }
  await loadPositions();
  await loadSimulation();
  b.disabled = false; b.textContent = "Kurse aktualisieren";
  if (errors.length) alert(errors.join("\n"));
});

async function loadPositions() {
  state.positions = await api("GET", "/api/positions");
  renderPositions();
}

// ---------------- Dialog ----------------
const dlg = $("#dlg");
const f = $("#pos-form");

function syncDialog() {
  const crypto = f.elements.kind.value === "crypto";
  $("#ident-label span").textContent = crypto ? "Symbol (z. B. BTC)" : "ISIN";
  const iv = f.elements.interval.value;
  $("#day-label").hidden = iv === "daily";
  f.elements.exec_day_week.hidden = iv !== "weekly";
  f.elements.exec_day_month.hidden = iv !== "monthly";
}

f.elements.kind.addEventListener("change", () => {
  if (f.elements.kind.value === "crypto") { f.elements.trading.value = "always"; f.elements.tax_type.value = "crypto"; }
  else if (f.elements.tax_type.value === "crypto") {
    f.elements.trading.value = "exchange";
    f.elements.tax_type.value = f.elements.kind.value === "stock" ? "stock" : "equity_fund";
  }
  syncDialog();
});
f.elements.interval.addEventListener("change", syncDialog);

function openDialog(p) {
  state.editing = p || null;
  $("#dlg-title").textContent = p ? "Posten bearbeiten" : "Neuer Posten";
  $("#delete").hidden = !p;
  $("#dlg-msg").textContent = "";
  $("#lookup-info").hidden = true;
  const d = p || { kind: "etf", interval: "monthly", exec_day: 1, trading: "exchange", tax_type: "equity_fund", rate: 0, fee: 0, ter: 0 };
  f.elements.kind.value = d.kind;
  f.elements.isin.value = d.isin || "";
  f.elements.name.value = d.name || "";
  for (const k of ["shares", "manual_value", "cost_basis", "rate", "manual_return", "fee", "ter"]) f.elements[k].value = fmtIn(d[k]);
  f.elements.interval.value = d.interval;
  f.elements.exec_day_week.value = String(Math.min(6, d.exec_day));
  f.elements.exec_day_month.value = String(Math.max(1, d.exec_day));
  f.elements.trading.value = d.trading;
  f.elements.tax_type.value = d.tax_type;
  $("#ret-hint").textContent = p && p.quote && p.quote.hist_return != null
    ? `leer = historisch ${pct(p.quote.hist_return)}` : "leer = historisch";
  syncDialog();
  dlg.showModal();
}

$("#add").addEventListener("click", () => openDialog(null));
$("#cancel").addEventListener("click", () => dlg.close());

$("#lookup").addEventListener("click", async () => {
  const ident = f.elements.isin.value.trim();
  const info = $("#lookup-info");
  if (!ident) return;
  info.hidden = false;
  info.textContent = "Suche …";
  try {
    const q = await api("GET", `/api/lookup?ident=${encodeURIComponent(ident)}&kind=${f.elements.kind.value}`);
    info.innerHTML = `<b>${esc(q.name || q.symbol)}</b> · ${esc(q.symbol)} · ${eur2.format(q.price_eur)}` +
      (q.hist_return != null ? ` · historisch ${pct(q.hist_return)} p. a. (${q.hist_years} J.)` : "");
    if (!f.elements.name.value && q.name) f.elements.name.value = q.name.slice(0, 80);
    $("#ret-hint").textContent = q.hist_return != null ? `leer = historisch ${pct(q.hist_return)}` : "leer = historisch";
  } catch (e) {
    info.textContent = e.message;
  }
});

f.addEventListener("submit", async (e) => {
  e.preventDefault();
  const iv = f.elements.interval.value;
  const body = {
    name: f.elements.name.value.trim(),
    kind: f.elements.kind.value,
    isin: f.elements.isin.value.trim() || null,
    symbol: state.editing ? state.editing.symbol : null,
    interval: iv,
    exec_day: iv === "weekly" ? Number(f.elements.exec_day_week.value)
      : iv === "monthly" ? Math.round(num(f.elements.exec_day_month.value) || 1) : 0,
    trading: f.elements.trading.value,
    tax_type: f.elements.tax_type.value,
  };
  for (const k of ["shares", "manual_value", "cost_basis", "manual_return"]) body[k] = num(f.elements[k].value);
  for (const k of ["rate", "fee", "ter"]) body[k] = num(f.elements[k].value) ?? 0;
  const bad = Object.entries(body).find(([, v]) => typeof v === "number" && Number.isNaN(v));
  if (bad) { $("#dlg-msg").textContent = "Bitte nur Zahlen in die Zahlenfelder eintragen."; return; }
  if (iv === "monthly" && (body.exec_day < 1 || body.exec_day > 31)) { $("#dlg-msg").textContent = "Ausführungstag muss zwischen 1 und 31 liegen."; return; }
  try {
    let saved;
    if (state.editing) saved = await api("PUT", `/api/positions/${state.editing.id}`, body);
    else saved = await api("POST", "/api/positions", body);
    dlg.close();
    if (saved.isin && !saved.quote) {
      try { await api("POST", `/api/positions/${saved.id}/refresh`); } catch (_) { /* Kurs später abrufen */ }
    }
    await loadPositions();
    await loadSimulation();
  } catch (err) {
    $("#dlg-msg").textContent = err.message;
  }
});

$("#delete").addEventListener("click", async () => {
  if (!state.editing || !confirm(`„${state.editing.name}“ wirklich löschen?`)) return;
  await api("DELETE", `/api/positions/${state.editing.id}`);
  dlg.close();
  await loadPositions();
  await loadSimulation();
});

$("#logout").addEventListener("click", async () => {
  await api("POST", "/api/auth/logout");
  location.href = "/login";
});

// ---------------- Start ----------------
(async function init() {
  state.settings = await api("GET", "/api/settings");
  fillSettings();
  await loadPositions();
  await loadSimulation();
})();
