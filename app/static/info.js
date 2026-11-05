"use strict";
// Info-Symbole: erklären Einstellungen und Felder per Antippen.
const INFO = {
  forecast: "Endwerte nach Ablauf des Anlagehorizonts. Netto ist der Wert nach Steuer, wenn am Ende alles verkauft wird. Rendite p. a. ist die jährliche Verzinsung deines Geldes nach Steuer (interner Zinsfuß). Sie berücksichtigt, wann jeder Euro eingezahlt wurde, und ist deshalb mit der erwarteten Rendite der Posten vergleichbar.",
  mode: "Nominal zeigt die Eurobeträge der Zukunft. Real rechnet alles mit der angegebenen Inflation in heutige Kaufkraft um. Jede Einzahlung zählt dabei mit der Kaufkraft, die sie zum Zeitpunkt der Zahlung hat. Die Steuer bleibt nominal.",
  years: "Zeitraum der Prognose ab heute. Am Ende wird ein Verkauf des gesamten Depots angenommen und die Steuer berechnet.",
  best_delta: "Prozentpunkte, die im Best Case auf die erwartete Rendite jedes Postens aufgeschlagen werden. Beispiel: 7 % erwartet und +3 ergibt 10 % p. a.",
  worst_delta: "Prozentpunkte, die im Worst Case von der erwarteten Rendite jedes Postens abgezogen werden. Negativ eintragen, z. B. -4 macht aus 7 % dann 3 % p. a.",
  inflation: "Jährliche Teuerung. Sie wirkt nur in der Ansicht „Real“ und rechnet die Werte in heutige Kaufkraft um.",
  allowance: "Sparerpauschbetrag: 1.000 € für Einzelpersonen, 2.000 € bei Zusammenveranlagung. Vereinfachung: Er wird einmal vom Gewinn am Ende abgezogen, nicht jedes Jahr.",
  church_tax: "Kirchensteuer auf Kapitalerträge. In Bayern und Baden-Württemberg 8 %, sonst 9 %. Die Abgeltungssteuer sinkt dadurch leicht, die Gesamtbelastung steigt.",
  kind: "Art des Postens. Bei Krypto gibst du statt der ISIN das Symbol an (z. B. BTC). Handel ist dann jeden Tag möglich und der Gewinn wird steuerfrei gerechnet.",
  isin: "ISIN des Wertpapiers, z. B. aus der Revolut-App. „Suchen“ ermittelt Ticker, aktuellen Kurs und historische Rendite.",
  name: "Frei wählbare Bezeichnung. Bleibt das Feld leer, wird beim Suchen der offizielle Name eingetragen.",
  shares: "Anzahl der Anteile im Depot. Der Wert ergibt sich aus Stückzahl mal aktuellem Kurs.",
  manual_value: "Aktueller Wert in Euro. Wenn ausgefüllt, wird er statt Stückzahl mal Kurs verwendet, z. B. wenn kein Kurs gefunden wird.",
  cost_basis: "Summe dessen, was du für den aktuellen Bestand bezahlt hast. Bestimmt den steuerpflichtigen Gewinn. Leer bedeutet: aktueller Wert, bisherige Gewinne bleiben also unversteuert.",
  rate: "Betrag je Ausführung des Sparplans in Euro. 0 bedeutet kein Sparplan.",
  interval: "Wie oft gekauft wird. Täglich mit „nur Börsentage“ kauft an jedem Xetra-Handelstag.",
  exec_day: "Wochentag bzw. Tag im Monat der Ausführung. Gibt es den Tag im Monat nicht (z. B. 31.), wird am letzten Tag gekauft. Fällt er auf keinen Börsentag, rückt der Kauf auf den nächsten Handelstag.",
  trading: "Nur Börsentage: Käufe an Wochenenden und Xetra-Feiertagen rücken auf den nächsten Handelstag. Jeden Tag: typisch für Krypto.",
  changes: "Ab dem angegebenen Datum gilt die neue Sparrate, bis zur nächsten Änderung. So lassen sich Erhöhungen planen, ein späterer Start (Sparrate bis dahin 0) oder ein Ende (ab dem Datum 0). Erreichte Änderungen werden automatisch zur aktuellen Sparrate.",
  manual_return: "Erwartete Wertentwicklung pro Jahr. Leer bedeutet: historische Rendite der letzten bis zu 10 Jahre. Vergangene Renditen sind keine Garantie.",
  fee: "Gebühr je Kauf in Euro. Sie wird von der Sparrate abgezogen, zählt aber zum Einstandswert.",
  ter: "Laufende Kosten pro Jahr. Werden nur bei manueller Rendite abgezogen, weil die historische Rendite die Kosten bereits enthält.",
  tax_type: "Bestimmt die Teilfreistellung: Bei Aktienfonds und Aktien-ETFs sind 30 % des Gewinns steuerfrei, bei Mischfonds 15 %. Krypto wird steuerfrei gerechnet.",
};
const NAME_TO_INFO = { exec_day_week: "exec_day", exec_day_month: "exec_day" };

(function () {
  const pop = document.createElement("div");
  pop.className = "infopop";
  pop.setAttribute("role", "tooltip");
  pop.hidden = true;
  document.body.appendChild(pop);
  let current = null;

  const makeIcon = (key) => {
    const i = document.createElement("span");
    i.className = "info";
    i.setAttribute("role", "button");
    i.setAttribute("tabindex", "0");
    i.setAttribute("aria-label", "Erklärung");
    i.dataset.info = key;
    i.textContent = "i";
    return i;
  };

  document.querySelectorAll("label.f").forEach((label) => {
    const field = label.querySelector("input[name], select[name]");
    if (!field) return;
    const key = NAME_TO_INFO[field.name] || field.name;
    if (!INFO[key]) return;
    const first = label.firstChild;
    let text = first;
    if (!(first.nodeType === Node.ELEMENT_NODE && first.tagName === "SPAN")) {
      text = document.createElement("span");
      text.textContent = first.textContent.trim();
    }
    const row = document.createElement("div");
    row.className = "lrow";
    first.replaceWith(row);
    row.append(text, makeIcon(key));
    label.classList.add("has-info");
  });
  document.querySelectorAll("[data-info-slot]").forEach((el) => el.appendChild(makeIcon(el.dataset.infoSlot)));

  function hide() { pop.hidden = true; current = null; }
  function show(icon) {
    if (current === icon) { hide(); return; }
    current = icon;
    pop.textContent = INFO[icon.dataset.info];
    pop.hidden = false;
    const host = icon.closest("dialog") || document.body;
    host.appendChild(pop);
    const r = icon.getBoundingClientRect();
    const w = Math.min(300, window.innerWidth - 24);
    pop.style.width = `${w}px`;
    let left = Math.min(Math.max(12, r.left + r.width / 2 - w / 2), window.innerWidth - w - 12);
    const hr = host === document.body ? { left: -window.scrollX, top: -window.scrollY } : host.getBoundingClientRect();
    const scrollTop = host === document.body ? 0 : host.scrollTop;
    pop.style.left = `${left - hr.left}px`;
    pop.style.top = `${r.bottom - hr.top + scrollTop + 6}px`;
  }

  document.addEventListener("click", (e) => {
    const icon = e.target.closest(".info");
    if (icon) { e.preventDefault(); e.stopPropagation(); show(icon); return; }
    if (!e.target.closest(".infopop")) hide();
  }, true);
  document.addEventListener("keydown", (e) => {
    const icon = e.target.closest && e.target.closest(".info");
    if (icon && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); show(icon); }
    if (e.key === "Escape") hide();
  });
  window.addEventListener("resize", hide);
  document.addEventListener("scroll", hide, true);
})();
