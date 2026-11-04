"""Kursdaten über Yahoo Finance (yfinance). ISIN wird in einen Ticker aufgelöst."""
from __future__ import annotations

import json
import logging
import re
import time

from . import config, db

log = logging.getLogger("market")
ISIN_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")

# Bevorzugte Handelsplätze für EUR-Kurse
PREFERRED_EXCHANGES = ["GER", "FRA", "STU", "MUN", "BER", "DUS", "HAM", "AMS", "PAR", "MIL"]
GERMAN_SUFFIXES = (".DE", ".F", ".SG", ".MU", ".BE", ".DU", ".HM")


def _pick_symbol(quotes: list[dict]) -> dict | None:
    if not quotes:
        return None
    for q in quotes:
        if str(q.get("symbol", "")).endswith(".DE"):
            return q
    for ex in PREFERRED_EXCHANGES:
        for q in quotes:
            if q.get("exchange") == ex:
                return q
    for q in quotes:
        if str(q.get("symbol", "")).endswith(GERMAN_SUFFIXES):
            return q
    return quotes[0]


def resolve_symbol(ident: str, kind: str) -> tuple[str, str | None]:
    """Gibt (Yahoo-Ticker, Name) zurück."""
    ident = ident.strip().upper()
    if kind == "crypto":
        sym = ident if "-" in ident else f"{ident}-EUR"
        return sym, None
    import yfinance as yf
    if not ISIN_RE.match(ident) and "." not in ident:
        # Börsenticker wie bei Revolut (z. B. EDM4): zuerst Xetra probieren
        h = yf.Ticker(f"{ident}.DE").history(period="5d")
        if not h.empty:
            return f"{ident}.DE", None
    res = yf.Search(ident, max_results=10, news_count=0)
    q = _pick_symbol(res.quotes)
    if not q:
        raise LookupError(f"Kein Ticker zu {ident} gefunden")
    return q["symbol"], q.get("longname") or q.get("shortname")


def _fx_to_eur(currency: str) -> float:
    if not currency or currency == "EUR":
        return 1.0
    import yfinance as yf
    h = yf.Ticker(f"{currency}EUR=X").history(period="5d")
    if h.empty:
        raise LookupError(f"Kein Wechselkurs {currency}/EUR")
    return float(h["Close"].iloc[-1])


def _hist_return(symbol: str, max_years: int = 10) -> tuple[float | None, float | None]:
    import yfinance as yf
    h = yf.Ticker(symbol).history(period="max", interval="1mo", auto_adjust=True)
    h = h["Close"].dropna()
    if len(h) < 13:
        return None, None
    last_date, last = h.index[-1], float(h.iloc[-1])
    cutoff = last_date - __import__("pandas").DateOffset(years=max_years)
    window = h[h.index >= cutoff]
    first_date, first = window.index[0], float(window.iloc[0])
    years = (last_date - first_date).days / 365.2425
    if years < 1 or first <= 0:
        return None, None
    cagr = (last / first) ** (1 / years) - 1
    return round(cagr * 100, 2), round(years, 1)


def fetch(ident: str, kind: str, symbol: str | None = None) -> dict:
    import yfinance as yf
    if not symbol:
        symbol, name = resolve_symbol(ident, kind)
    else:
        name = None
    t = yf.Ticker(symbol)
    h = t.history(period="5d")
    if h.empty:
        raise LookupError(f"Keine Kursdaten für {symbol}")
    price = float(h["Close"].iloc[-1])
    currency = None
    try:
        currency = t.fast_info.get("currency")
    except Exception:
        pass
    if currency == "GBp":
        price, currency = price / 100.0, "GBP"
    elif currency == "ZAc":
        price, currency = price / 100.0, "ZAR"
    if currency is None and symbol.endswith("-EUR"):
        currency = "EUR"
    fx = _fx_to_eur(currency or "EUR")
    hist, hist_years = _hist_return(symbol)
    quote_type = None
    try:
        info = t.info
        name = name or info.get("longName") or info.get("shortName")
        quote_type = info.get("quoteType")
    except Exception:
        pass
    return {
        "symbol": symbol,
        "name": name,
        "currency": currency or "EUR",
        "price": round(price, 4),
        "price_eur": round(price * fx, 4),
        "hist_return": hist,
        "hist_years": hist_years,
        "quote_type": quote_type,
    }


def get(ident: str, kind: str, symbol: str | None = None, force: bool = False) -> dict:
    """Kurs aus dem Cache oder frisch von Yahoo."""
    key = f"{kind}:{(ident or symbol).upper()}"
    now = int(time.time())
    with db.tx() as con:
        row = con.execute("SELECT data, fetched_at FROM quotes WHERE key=?", (key,)).fetchone()
    if row and not force and now - row["fetched_at"] < config.QUOTE_CACHE_HOURS * 3600:
        data = json.loads(row["data"])
        data["fetched_at"] = row["fetched_at"]
        return data
    try:
        data = fetch(ident, kind, symbol)
    except Exception as e:  # Netzwerk, unbekannte ISIN, Yahoo-Änderungen
        log.warning("Kursabruf %s fehlgeschlagen: %s", key, e)
        if row:
            data = json.loads(row["data"])
            data["fetched_at"] = row["fetched_at"]
            data["stale"] = True
            return data
        return {"error": str(e)}
    with db.tx() as con:
        con.execute("INSERT OR REPLACE INTO quotes(key, data, fetched_at) VALUES (?,?,?)",
                    (key, json.dumps(data), now))
    data["fetched_at"] = now
    return data


def cached(ident: str | None, kind: str, symbol: str | None) -> dict | None:
    if not (ident or symbol):
        return None
    key = f"{kind}:{(ident or symbol).upper()}"
    with db.tx() as con:
        row = con.execute("SELECT data, fetched_at FROM quotes WHERE key=?", (key,)).fetchone()
    if not row:
        return None
    data = json.loads(row["data"])
    data["fetched_at"] = row["fetched_at"]
    return data
