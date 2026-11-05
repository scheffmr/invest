"""Depot-Simulation: tagesgenau, drei Szenarien, Steuer am Ende."""
from __future__ import annotations

import calendar
from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta

from .xetra import is_trading_day, next_trading_day

DAYS_PER_YEAR = 365.2425

# Teilfreistellung je Steuerart (Anteil des Gewinns, der steuerfrei ist)
PARTIAL_EXEMPTION = {
    "equity_fund": 0.30,   # Aktienfonds / Aktien-ETF
    "mixed_fund": 0.15,    # Mischfonds
    "other_fund": 0.0,     # sonstige Fonds (z. B. Renten-ETF)
    "stock": 0.0,          # Einzelaktie
    "crypto": 1.0,         # vereinfachend steuerfrei (Haltedauer > 1 Jahr)
}


@dataclass
class Pos:
    value: float          # aktueller Wert EUR
    basis: float          # Einstandswert EUR
    rate: float           # Sparrate je Ausführung EUR
    interval: str         # daily, weekly, monthly
    exec_day: int         # 0..6 (Mo..So) bzw. 1..31
    trading: str          # exchange, always
    ret: float            # erwartete Rendite p.a. in %
    fee: float = 0.0      # Gebühr je Ausführung EUR
    ter: float = 0.0      # laufende Kosten p.a. in %
    tax_type: str = "equity_fund"


@dataclass
class Settings:
    years: int = 20
    best_delta: float = 3.0
    worst_delta: float = -4.0
    inflation: float = 2.0
    allowance: float = 1000.0
    church_tax: float = 0.0   # 0, 8 oder 9 (%)


def tax_rate(church_pct: float) -> float:
    """Abgeltungssteuer inkl. Soli und ggf. Kirchensteuer (§ 32d EStG)."""
    k = church_pct / 100.0
    base = 0.25 / (1 + 0.25 * k)        # = 1 / (4 + k)
    return base * (1 + 0.055 + k)


def execution_dates(p: Pos, start: date, end: date) -> Counter:
    """Ausführungstage im Intervall (start, end]."""
    out: Counter = Counter()
    if p.rate <= 0:
        return out
    exch = p.trading == "exchange"
    d = start + timedelta(days=1)
    if p.interval == "daily":
        while d <= end:
            if not exch or is_trading_day(d):
                out[d] += 1
            d += timedelta(days=1)
        return out
    if p.interval == "weekly":
        wd = max(0, min(6, int(p.exec_day)))
        d += timedelta(days=(wd - d.weekday()) % 7)
        while d <= end:
            x = next_trading_day(d) if exch else d
            if x <= end:
                out[x] += 1
            d += timedelta(days=7)
        return out
    # monthly
    md = max(1, min(31, int(p.exec_day)))
    y, m = d.year, d.month
    while True:
        last = calendar.monthrange(y, m)[1]
        sched = date(y, m, min(md, last))
        if sched > end:
            break
        if sched >= d:
            x = next_trading_day(sched) if exch else sched
            if x <= end:
                out[x] += 1
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def _run(positions: list[Pos], schedules: list[Counter], start: date, end: date,
         delta: float, sample_days: set[date], infl: float = 0.0):
    n = len(positions)
    values = [p.value for p in positions]
    basis = [p.basis for p in positions]
    paid = sum(basis)
    factors = []
    for p in positions:
        r = max(-0.99, (p.ret + delta) / 100.0)
        net = (1 + r) * (1 - p.ter / 100.0) - 1
        factors.append((1 + net) ** (1 / DAYS_PER_YEAR))

    paid_real = paid
    day_infl = (1 + infl) ** (1 / DAYS_PER_YEAR)
    deflator = 1.0
    series_val, series_paid, series_paid_real = [sum(values)], [paid], [paid_real]
    d = start
    while d < end:
        d += timedelta(days=1)
        deflator *= day_infl
        for i in range(n):
            values[i] *= factors[i]
            c = schedules[i].get(d)
            if c:
                p = positions[i]
                values[i] += c * max(0.0, p.rate - p.fee)
                basis[i] += c * p.rate
                paid += c * p.rate
                paid_real += c * p.rate / deflator
        if d in sample_days:
            series_val.append(sum(values))
            series_paid.append(paid)
            series_paid_real.append(paid_real)
    return values, basis, paid, series_val, (series_paid, series_paid_real)


def _pct(x):
    return None if x is None else round(x * 100, 2)


def _real(r, infl):
    return None if r is None else (1 + r) / (1 + infl) - 1


def irr(flows: dict[date, float], start: date) -> float | None:
    """Jährliche Rendite (XIRR) für Zahlungsströme. Auszahlungen negativ, Endwert positiv."""
    items = [((d - start).days / DAYS_PER_YEAR, v) for d, v in flows.items() if v]
    if not any(v < 0 for _, v in items) or not any(v > 0 for _, v in items):
        return None

    def npv(r):
        return sum(v / (1 + r) ** t for t, v in items)

    lo, hi = -0.99, 10.0
    if npv(lo) * npv(hi) > 0:
        return None
    for _ in range(100):
        mid = (lo + hi) / 2
        if npv(lo) * npv(mid) <= 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def simulate(positions: list[Pos], s: Settings, start: date | None = None) -> dict:
    start = start or date.today()
    years = max(1, min(60, int(s.years)))
    try:
        end = start.replace(year=start.year + years)
    except ValueError:   # 29. Februar
        end = start.replace(year=start.year + years, day=28)

    # Stützstellen: jedes Monatsende und das Enddatum
    sample_days, labels = set(), [start.strftime("%Y-%m")]
    d = start
    while True:
        last = date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])
        if last >= end:
            break
        if last > start:
            sample_days.add(last)
            labels.append(last.strftime("%Y-%m"))
        d = last + timedelta(days=1)
    sample_days.add(end)
    labels.append(end.strftime("%Y-%m"))
    sample_dates = [start] + sorted(sample_days)

    schedules = [execution_dates(p, start, end) for p in positions]
    flows: dict[date, float] = Counter()
    flows[start] -= sum(p.value for p in positions)
    for p, sch in zip(positions, schedules):
        for d, c in sch.items():
            # auf Wochenraster zusammenfassen, beschleunigt die Renditeberechnung stark
            wk = start + timedelta(days=(d - start).days // 7 * 7)
            flows[wk] -= c * p.rate
    rate = tax_rate(s.church_tax)
    infl = s.inflation / 100.0
    deflators = [(1 + infl) ** ((x - start).days / DAYS_PER_YEAR) for x in sample_dates]
    end_deflator = deflators[-1]

    result = {"labels": labels, "scenarios": {}, "start": start.isoformat(), "end": end.isoformat()}
    paid_series = None
    for key, delta in (("expected", 0.0), ("best", s.best_delta), ("worst", s.worst_delta)):
        vals, basis, paid, sv, (sp, sp_real) = _run(positions, schedules, start, end, delta, sample_days, infl)
        paid_series = sp
        taxable = 0.0
        for p, v, b in zip(positions, vals, basis):
            tf = PARTIAL_EXEMPTION.get(p.tax_type, 0.0)
            taxable += (v - b) * (1 - tf)
        taxable = max(0.0, taxable - s.allowance)
        tax = taxable * rate
        gross = sum(vals)
        net = gross - tax
        result["scenarios"][key] = {
            "return_delta": delta,
            "series": [round(x, 2) for x in sv],
            "series_real": [round(x / f, 2) for x, f in zip(sv, deflators)],
            "gross": round(gross, 2),
            "tax": round(tax, 2),
            "net": round(net, 2),
            "gross_real": round(gross / end_deflator, 2),
            "net_real": round(net / end_deflator, 2),
            "gain": round(gross - paid, 2),
            "gain_net": round(net - paid, 2),
            "return_pct": round((gross - paid) / paid * 100, 2) if paid > 0 else None,
            "return_net_pct": round((net - paid) / paid * 100, 2) if paid > 0 else None,
            "irr_pct": _pct(irr({**flows, end: flows.get(end, 0) + gross}, start)),
            "irr_net_pct": _pct(irr_net := irr({**flows, end: flows.get(end, 0) + net}, start)),
            "irr_net_real_pct": _pct(_real(irr_net, infl)),
        }
    result["paid_in"] = [round(x, 2) for x in paid_series]
    result["paid_total"] = round(paid_series[-1], 2)
    result["paid_in_real"] = [round(x, 2) for x in sp_real]
    result["paid_total_real"] = round(sp_real[-1], 2)
    result["start_value"] = round(sum(p.value for p in positions), 2)
    result["tax_rate"] = round(rate * 100, 3)
    return result
