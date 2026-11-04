from datetime import date

from app.simulate import Pos, Settings, execution_dates, simulate, tax_rate
from app.xetra import easter, is_trading_day, next_trading_day


def test_easter():
    assert easter(2026) == date(2026, 4, 5)
    assert easter(2027) == date(2027, 3, 28)


def test_trading_days():
    assert not is_trading_day(date(2026, 12, 24))
    assert not is_trading_day(date(2026, 4, 3))      # Karfreitag
    assert not is_trading_day(date(2026, 11, 7))     # Samstag
    assert next_trading_day(date(2026, 12, 24)) == date(2026, 12, 28)


def test_tax_rate():
    assert abs(tax_rate(0) - 0.26375) < 1e-9
    assert abs(tax_rate(8) - 0.278186) < 1e-5


def test_monthly_shift_to_trading_day():
    p = Pos(value=0, basis=0, rate=100, interval="monthly", exec_day=1, trading="exchange", ret=0)
    ex = execution_dates(p, date(2026, 11, 4), date(2027, 2, 28))
    # 1.12. Di, 1.1. Feiertag -> 4.1. (Mo), 1.2. Mo
    assert sorted(ex) == [date(2026, 12, 1), date(2027, 1, 4), date(2027, 2, 1)]


def test_daily_crypto_vs_exchange():
    a = Pos(value=0, basis=0, rate=1, interval="daily", exec_day=0, trading="always", ret=0)
    b = Pos(value=0, basis=0, rate=1, interval="daily", exec_day=0, trading="exchange", ret=0)
    s, e = date(2026, 1, 1), date(2026, 12, 31)
    assert sum(execution_dates(a, s, e).values()) == 364
    assert sum(execution_dates(b, s, e).values()) < 260


def test_zero_return_equals_paid_in():
    p = Pos(value=1000, basis=1000, rate=100, interval="monthly", exec_day=15, trading="exchange", ret=0)
    r = simulate([p], Settings(years=10, best_delta=0, worst_delta=0, inflation=0), date(2026, 11, 4))
    sc = r["scenarios"]["expected"]
    assert sc["gross"] == r["paid_total"] == 1000 + 120 * 100
    assert sc["tax"] == 0


def test_compound_growth_and_tax():
    p = Pos(value=10000, basis=10000, rate=0, interval="monthly", exec_day=1, trading="exchange", ret=7,
            tax_type="equity_fund")
    r = simulate([p], Settings(years=10, best_delta=3, worst_delta=-4, inflation=2, allowance=1000),
                 date(2026, 11, 4))
    exp = r["scenarios"]["expected"]
    assert abs(exp["gross"] - 10000 * 1.07 ** 10) < 5
    gain = exp["gross"] - 10000
    assert abs(exp["tax"] - (gain * 0.7 - 1000) * 0.26375) < 1
    assert r["scenarios"]["best"]["gross"] > exp["gross"] > r["scenarios"]["worst"]["gross"]
    assert len(r["labels"]) == len(r["paid_in"]) == len(exp["series"])
