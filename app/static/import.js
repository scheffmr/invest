"use strict";
// Revolut-CSV-Import (nutzt Helfer aus app.js)
(function () {
  const dlg = $("#imp");
  const list = $("#imp-list");
  const msg = $("#imp-msg");
  const applyBtn = $("#imp-apply");
  const fileInput = $("#imp-files");
  let items = [];

  const WD = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"];
  const planText = (p) => {
    if (!p) return "kein laufender Sparplan erkannt";
    const when = p.interval === "daily" ? "täglich" : p.interval === "weekly" ? `wöchentlich (${WD[p.exec_day]})` : `monatlich (am ${p.exec_day}.)`;
    return `${eur2.format(p.rate)} ${when}, ${p.trading === "always" ? "jeden Tag" : "Börsentage"}`;
  };
  const qty = (n) => n.toLocaleString("de-DE", { maximumFractionDigits: 8 });

  $("#import").addEventListener("click", () => {
    items = [];
    list.innerHTML = "";
    msg.className = "msg";
    msg.textContent = "";
    fileInput.value = "";
    applyBtn.disabled = true;
    dlg.showModal();
  });
  $("#imp-cancel").addEventListener("click", () => dlg.close());

  fileInput.addEventListener("change", async () => {
    const files = [...fileInput.files];
    if (!files.length) return;
    msg.className = "msg ok";
    msg.textContent = "Lese Dateien und rufe Kurse ab …";
    list.innerHTML = "";
    applyBtn.disabled = true;
    try {
      const texts = await Promise.all(files.map((f) => f.text()));
      const res = await api("POST", "/api/import/preview", { files: texts });
      items = res.items;
      msg.className = "msg";
      msg.textContent = items.length ? "" : "Keine Bestände gefunden.";
      render(res.warnings || []);
      applyBtn.disabled = !items.length;
    } catch (e) {
      msg.className = "msg";
      msg.textContent = e.message;
    }
  });

  function render(warnings) {
    list.innerHTML = items.map((it, i) => {
      const value = it.price_eur ? ` · ca. ${eur2.format(it.shares * it.price_eur)}` : "";
      const target = it.match_id ? `aktualisiert „${esc(it.match_name)}“` : "wird neu angelegt";
      const kindSel = it.source === "crypto" ? "" : `
        <select data-kind="${i}">
          ${[["etf", "ETF"], ["fund", "Fonds"], ["stock", "Aktie"]].map(([v, l]) => `<option value="${v}" ${it.kind === v ? "selected" : ""}>${l}</option>`).join("")}
        </select>`;
      return `<div class="imp-item">
        <div class="top"><input type="checkbox" data-use="${i}" checked aria-label="übernehmen">
          <div><div class="t">${esc(it.name)}</div>
          <div class="sub">${esc(it.ident)}${it.symbol ? " · " + esc(it.symbol) : ""} · ${target}</div></div></div>
        <div>${qty(it.shares)} Stk · Einstand ${eur2.format(it.cost_basis)}${value} · ${it.buys} Käufe seit ${new Date(it.first_buy).toLocaleDateString("de-DE")}</div>
        ${it.quote_error ? `<div class="sub">Kein Online-Kurs gefunden. Wert und Rendite bitte danach manuell prüfen.</div>` : ""}
        <div class="row2">${kindSel}
          <label class="chk"><input type="checkbox" data-plan="${i}" ${it.plan ? "checked" : "disabled"}> Sparplan: ${esc(planText(it.plan))}</label>
        </div>
      </div>`;
    }).join("") + (warnings.length ? `<div class="warnlist">${warnings.map(esc).join("<br>")}</div>` : "");
  }

  list.addEventListener("change", (e) => {
    const k = e.target.dataset.kind;
    if (k !== undefined) {
      items[k].kind = e.target.value;
      items[k].tax_type = e.target.value === "stock" ? "stock" : "equity_fund";
    }
  });

  $("#imp-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const chosen = items
      .map((it, i) => ({ it, i }))
      .filter(({ i }) => $(`[data-use="${i}"]`, list).checked)
      .map(({ it, i }) => ({
        ident: it.ident, source: it.source, name: it.name.slice(0, 80), kind: it.kind, tax_type: it.tax_type,
        symbol: it.symbol, shares: it.shares, cost_basis: it.cost_basis, match_id: it.match_id,
        plan: it.plan, use_plan: !!(it.plan && $(`[data-plan="${i}"]`, list).checked),
      }));
    if (!chosen.length) { dlg.close(); return; }
    applyBtn.disabled = true;
    try {
      await api("POST", "/api/import/apply", chosen);
      dlg.close();
      await loadPositions();
      await loadSimulation();
    } catch (err) {
      msg.textContent = err.message;
      applyBtn.disabled = false;
    }
  });
})();
