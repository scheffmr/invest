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


def test_revolut_import():
    from app.importer import parse
    stocks = ("Date,Ticker,Type,Quantity,Price per share,Total Amount,Currency,FX Rate\n"
              "2026-10-01T08:00:00Z,,CASH TOP-UP,,,EUR 10,EUR,1.0000\n"
              "2026-10-01T08:00:01Z,ABC,BUY - MARKET,2,EUR 5,EUR 10,EUR,1.0000\n"
              "2026-10-08T08:00:01Z,ABC,BUY - MARKET,2,EUR 5,EUR 10,EUR,1.0000\n"
              "2026-10-15T08:00:01Z,ABC,BUY - MARKET,2,EUR 5,EUR 10,EUR,1.0000\n"
              "2026-10-20T08:00:01Z,ABC,SELL - MARKET,3,EUR 6,EUR 18,EUR,1.0000\n")
    crypto = ('Symbol,Type,Quantity,Price,Value,Fees,Date\n'
              'BTC,Kaufen,"0,001","70.000,00€","70,00€","0,50€","01.11.2026, 10:00:00"\n')
    r = parse([stocks, crypto], date(2026, 10, 22))
    abc = next(i for i in r["items"] if i["ident"] == "ABC")
    assert abc["shares"] == 3 and abs(abc["cost_basis"] - 15) < 1e-9
    assert abc["plan"]["interval"] == "weekly" and abc["plan"]["exec_day"] == 3
    btc = next(i for i in r["items"] if i["ident"] == "BTC")
    assert btc["shares"] == 0.001 and btc["cost_basis"] == 70.5


def test_irr_matches_expected_return():
    p = Pos(value=1000, basis=1000, rate=100, interval="monthly", exec_day=15, trading="always", ret=7)
    r = simulate([p], Settings(years=20, best_delta=3, worst_delta=-4, inflation=2, allowance=0),
                 date(2026, 11, 4))
    sc = r["scenarios"]
    assert abs(sc["expected"]["irr_pct"] - 7) < 0.05
    assert abs(sc["best"]["irr_pct"] - 10) < 0.05
    assert sc["expected"]["irr_net_pct"] < sc["expected"]["irr_pct"]
    assert abs(sc["expected"]["irr_net_real_pct"] - ((1 + sc["expected"]["irr_net_pct"] / 100) / 1.02 - 1) * 100) < 0.01


def test_paid_in_real():
    p = Pos(value=1000, basis=1000, rate=100, interval="monthly", exec_day=1, trading="always", ret=5)
    r0 = simulate([p], Settings(years=10, inflation=0), date(2026, 11, 4))
    assert r0["paid_in_real"] == r0["paid_in"]
    r = simulate([p], Settings(years=10, inflation=2), date(2026, 11, 4))
    assert r["paid_in_real"][0] == r["paid_in"][0] == 1000
    assert r["paid_total_real"] < r["paid_total"]
    # letzte Einzahlung nach ~10 Jahren zählt real nur noch ca. 100 / 1,02^10
    inc_real = r["paid_in_real"][-1] - r["paid_in_real"][-2]
    assert abs(inc_real - 100 / 1.02 ** 10) < 1


def test_rate_changes():
    start = date(2026, 11, 4)
    base = dict(value=0, basis=0, interval="monthly", exec_day=1, trading="always", ret=0)
    # 0 € bis 2027, dann 100 €, ab 2028 wieder 0 €: genau 12 Einzahlungen
    p = Pos(rate=0, changes=[(date(2027, 1, 1), 100.0), (date(2028, 1, 1), 0.0)], **base)
    r = simulate([p], Settings(years=5, inflation=0), start)
    assert r["paid_total"] == 1200
    # Erhöhung: 50 € bis Ende 2026 (Dez.), danach 100 € bis Nov. 2027
    q = Pos(rate=50, changes=[(date(2027, 1, 1), 100.0)], **base)
    r = simulate([q], Settings(years=1, inflation=0), start)
    assert r["paid_total"] == 50 + 11 * 100


def test_fold_changes():
    from app.main import _fold_changes
    rate, fut = _fold_changes(3, [{"from_date": "2027-01-01", "rate": 5}, {"from_date": "2026-01-01", "rate": 4}],
                              date(2026, 11, 5))
    assert rate == 4 and fut == [{"from_date": "2027-01-01", "rate": 5.0}]
