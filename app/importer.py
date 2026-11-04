"""Import von Revolut-Kontoauszügen (CSV): Aktien/ETF und Krypto."""
from __future__ import annotations

import csv
import io
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

STOCK_HEADER = {"Date", "Ticker", "Type", "Quantity", "Price per share", "Total Amount", "Currency"}
CRYPTO_HEADER = {"Symbol", "Type", "Quantity", "Price", "Value", "Fees", "Date"}

BUY_WORDS = ("BUY", "KAUF")
SELL_WORDS = ("SELL", "VERKAUF")


def _num(s: str | None) -> float:
    """Liest '1.15888283', 'EUR 8.63', '69.105,34€', '0,00004341'."""
    if s is None:
        return 0.0
    s = re.sub(r"[^\d,.\-]", "", str(s))
    if not s:
        return 0.0
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    return float(s)


def _currency(s: str) -> str:
    m = re.search(r"[A-Z]{3}", s or "")
    if m:
        return m.group(0)
    return "EUR" if "€" in (s or "") else ""


def _date(s: str) -> date:
    s = s.strip()
    for fmt in ("%d.%m.%Y, %H:%M:%S", "%d.%m.%Y %H:%M:%S", "%d.%m.%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return datetime.fromisoformat(s.replace("Z", "+00:00")).date()


class Holding:
    def __init__(self, ident: str, kind: str):
        self.ident = ident
        self.kind = kind          # "security" oder "crypto"
        self.qty = 0.0
        self.cost = 0.0
        self.buys: list[tuple[date, float]] = []
        self.fees = []

    def buy(self, d: date, qty: float, amount: float, fee: float = 0.0):
        self.qty += qty
        self.cost += amount + fee
        self.buys.append((d, amount + fee))
        if fee:
            self.fees.append(fee)

    def sell(self, qty: float):
        if self.qty > 0:
            self.cost *= max(0.0, 1 - qty / self.qty)
        self.qty = max(0.0, self.qty - qty)


def _detect_plan(h: Holding, today: date) -> dict | None:
    """Erkennt einen laufenden Sparplan aus den letzten Käufen."""
    if not h.buys:
        return None
    last = max(d for d, _ in h.buys)
    if (today - last).days > 35:
        return None
    recent = [(d, a) for d, a in h.buys if d > last - timedelta(days=28)]
    days = sorted({d for d, _ in recent})
    amount = Counter(round(a, 2) for _, a in recent).most_common(1)[0][0]
    fee = round(sum(h.fees[-len(recent):]) / len(recent), 2) if h.fees else 0.0
    weekend = any(d.weekday() >= 5 for d in days)
    n = len(days)
    if n >= 12:
        return {"rate": amount, "interval": "daily", "exec_day": 0,
                "trading": "always" if weekend else "exchange", "fee": fee}
    if 3 <= n <= 6:
        wd = Counter(d.weekday() for d in days).most_common(1)[0][0]
        return {"rate": amount, "interval": "weekly", "exec_day": wd,
                "trading": "always" if weekend else "exchange", "fee": fee}
    if n <= 2:
        md = Counter(d.day for d in days).most_common(1)[0][0]
        return {"rate": amount, "interval": "monthly", "exec_day": md,
                "trading": "always" if weekend else "exchange", "fee": fee}
    return None


def parse(contents: list[str], today: date | None = None) -> dict:
    today = today or date.today()
    holdings: dict[tuple, Holding] = {}
    warnings: list[str] = []
    files = []

    for text in contents:
        text = text.lstrip("﻿")
        reader = csv.DictReader(io.StringIO(text))
        header = set(reader.fieldnames or [])
        if STOCK_HEADER <= header:
            fmt = "Revolut Aktien/ETF"
        elif CRYPTO_HEADER <= header:
            fmt = "Revolut Krypto"
        else:
            warnings.append(f"Unbekanntes CSV-Format (Spalten: {', '.join(sorted(header))[:120]})")
            continue
        files.append(fmt)
        skipped = Counter()
        for row in reader:
            typ = (row.get("Type") or "").upper()
            is_buy = any(w in typ for w in BUY_WORDS)
            is_sell = any(w in typ for w in SELL_WORDS)
            if not (is_buy or is_sell):
                if typ and "CASH" not in typ:
                    skipped[typ] += 1
                continue
            if fmt == "Revolut Aktien/ETF":
                ident = (row.get("Ticker") or "").strip().upper()
                key = ("security", ident)
                cur = (row.get("Currency") or _currency(row.get("Total Amount", ""))).upper()
                amount = _num(row.get("Total Amount"))
                fee = 0.0
                if cur and cur != "EUR":
                    fx = _num(row.get("FX Rate")) or 0.0
                    if fx <= 0:
                        skipped[f"{typ} in {cur} ohne Kurs"] += 1
                        continue
                    amount = amount / fx
            else:
                ident = (row.get("Symbol") or "").strip().upper()
                key = ("crypto", ident)
                amount = _num(row.get("Value"))
                fee = _num(row.get("Fees"))
            if not ident:
                continue
            h = holdings.setdefault(key, Holding(ident, key[0]))
            qty = abs(_num(row.get("Quantity")))
            if is_buy:
                h.buy(_date(row["Date"]), qty, amount, fee)
            else:
                h.sell(qty)
        for typ, n in skipped.items():
            warnings.append(f"{fmt}: {n} Zeile(n) vom Typ „{typ}“ nicht berücksichtigt")

    items = []
    for (kind, ident), h in sorted(holdings.items()):
        if h.qty <= 1e-12:
            continue
        items.append({
            "ident": ident,
            "source": kind,
            "shares": round(h.qty, 10),
            "cost_basis": round(h.cost, 2),
            "buys": len(h.buys),
            "first_buy": min(d for d, _ in h.buys).isoformat() if h.buys else None,
            "plan": _detect_plan(h, today),
        })
    return {"files": files, "items": items, "warnings": warnings}
