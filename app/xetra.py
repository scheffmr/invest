"""Handelskalender Xetra: Wochenenden und die festen Xetra-Feiertage."""
from datetime import date, timedelta
from functools import lru_cache


def easter(year: int) -> date:
    # Anonymer gregorianischer Algorithmus
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)


@lru_cache(maxsize=None)
def holidays(year: int) -> frozenset:
    e = easter(year)
    return frozenset({
        date(year, 1, 1),            # Neujahr
        e - timedelta(days=2),       # Karfreitag
        e + timedelta(days=1),       # Ostermontag
        date(year, 5, 1),            # Tag der Arbeit
        date(year, 12, 24),          # Heiligabend
        date(year, 12, 25),          # 1. Weihnachtstag
        date(year, 12, 26),          # 2. Weihnachtstag
        date(year, 12, 31),          # Silvester
    })


def is_trading_day(d: date) -> bool:
    return d.weekday() < 5 and d not in holidays(d.year)


def next_trading_day(d: date) -> date:
    while not is_trading_day(d):
        d += timedelta(days=1)
    return d
