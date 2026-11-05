from __future__ import annotations

import json
import os
from datetime import date
from typing import Literal, Optional

from fastapi import Body, Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import auth, db, importer, market
from .simulate import Pos, Settings, simulate

STATIC = os.path.join(os.path.dirname(__file__), "static")

app = FastAPI(title="Depotplaner", docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.on_event("startup")
def _startup():
    db.init()


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
    if request.url.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


# ---------- Seiten ----------
@app.get("/")
def index(request: Request):
    if not auth.user_from_request(request):
        return RedirectResponse("/login", 303)
    return FileResponse(os.path.join(STATIC, "index.html"))


@app.get("/login")
def login_page():
    return FileResponse(os.path.join(STATIC, "login.html"))


@app.get("/register")
def register_page():
    return FileResponse(os.path.join(STATIC, "register.html"))


# ---------- Auth ----------
@app.post("/api/auth/register/options", dependencies=[Depends(auth.rate_limit)])
def register_options(body: dict = Body(...)):
    return Response(auth.registration_options(body.get("token", "")), media_type="application/json")


@app.post("/api/auth/register/verify", dependencies=[Depends(auth.rate_limit)])
def register_verify(body: dict = Body(...)):
    uid = auth.registration_verify(body.get("token", ""), body.get("credential") or {}, body.get("label"))
    resp = JSONResponse({"ok": True})
    auth.create_session(resp, uid)
    return resp


@app.post("/api/auth/login/options", dependencies=[Depends(auth.rate_limit)])
def login_options():
    return auth.login_options()


@app.post("/api/auth/login/verify", dependencies=[Depends(auth.rate_limit)])
def login_verify(body: dict = Body(...)):
    uid = auth.login_verify(body.get("challengeId", ""), body.get("credential") or {})
    resp = JSONResponse({"ok": True})
    auth.create_session(resp, uid)
    return resp


@app.post("/api/auth/logout")
def logout(request: Request):
    resp = JSONResponse({"ok": True})
    auth.logout(request, resp)
    return resp


@app.get("/api/me")
def me(user=Depends(auth.require_user)):
    return user


# ---------- Einstellungen ----------
class SettingsIn(BaseModel):
    years: int = Field(ge=1, le=60)
    best_delta: float = Field(ge=-50, le=50)
    worst_delta: float = Field(ge=-50, le=50)
    inflation: float = Field(ge=-10, le=50)
    allowance: float = Field(ge=0, le=100000)
    church_tax: float = Field(ge=0, le=9)


def _settings(con, uid) -> dict:
    row = con.execute("SELECT * FROM settings WHERE user_id=?", (uid,)).fetchone()
    if not row:
        con.execute("INSERT INTO settings(user_id) VALUES (?)", (uid,))
        row = con.execute("SELECT * FROM settings WHERE user_id=?", (uid,)).fetchone()
    d = dict(row)
    d.pop("user_id", None)
    return d


@app.get("/api/settings")
def get_settings(user=Depends(auth.require_user)):
    with db.tx() as con:
        return _settings(con, user["id"])


@app.put("/api/settings")
def put_settings(s: SettingsIn, user=Depends(auth.require_user)):
    with db.tx() as con:
        _settings(con, user["id"])
        con.execute("UPDATE settings SET years=?, best_delta=?, worst_delta=?, inflation=?, allowance=?, "
                    "church_tax=? WHERE user_id=?",
                    (s.years, s.best_delta, s.worst_delta, s.inflation, s.allowance, s.church_tax, user["id"]))
        return _settings(con, user["id"])


# ---------- Posten ----------
class RateChange(BaseModel):
    from_date: date
    rate: float = Field(ge=0)


class PositionIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    kind: Literal["etf", "fund", "stock", "crypto"] = "etf"
    isin: Optional[str] = Field(default=None, max_length=20)
    symbol: Optional[str] = Field(default=None, max_length=30)
    shares: Optional[float] = Field(default=None, ge=0)
    manual_value: Optional[float] = Field(default=None, ge=0)
    cost_basis: Optional[float] = Field(default=None, ge=0)
    rate: float = Field(default=0, ge=0)
    interval: Literal["daily", "weekly", "monthly"] = "monthly"
    exec_day: int = Field(default=1, ge=0, le=31)
    trading: Literal["exchange", "always"] = "exchange"
    manual_return: Optional[float] = Field(default=None, ge=-99, le=500)
    fee: float = Field(default=0, ge=0)
    ter: float = Field(default=0, ge=0, le=10)
    tax_type: Literal["equity_fund", "mixed_fund", "other_fund", "stock", "crypto"] = "equity_fund"
    changes: list[RateChange] = Field(default_factory=list, max_length=50)


def _fold_changes(rate: float, changes: list[dict], today: date | None = None) -> tuple[float, list[dict]]:
    """Vergangene Änderungen in die aktuelle Sparrate übernehmen, künftige sortiert zurückgeben."""
    today = today or date.today()
    by_date = {}
    for c in changes:
        d = c["from_date"] if isinstance(c["from_date"], date) else date.fromisoformat(c["from_date"])
        by_date[d] = float(c["rate"])
    future = []
    for d in sorted(by_date):
        if d <= today:
            rate = by_date[d]
        else:
            future.append({"from_date": d.isoformat(), "rate": by_date[d]})
    return rate, future


FIELDS = list(PositionIn.model_fields.keys())


def _enrich(row) -> dict:
    p = dict(row)
    p["rate"], p["changes"] = _fold_changes(p["rate"], json.loads(p.get("changes") or "[]"))
    q = market.cached(p["isin"], p["kind"], p["symbol"])
    p["quote"] = q if q and "error" not in q else None
    price = p["quote"]["price_eur"] if p["quote"] else None
    if p["manual_value"] is not None:
        value, value_src = p["manual_value"], "manual"
    elif p["shares"] and price:
        value, value_src = p["shares"] * price, "online"
    elif p["shares"] and p["cost_basis"]:
        value, value_src = p["cost_basis"], "basis"
    else:
        value, value_src = 0.0, "none"
    if p["manual_return"] is not None:
        ret, ret_src = p["manual_return"], "manual"
    elif p["quote"] and p["quote"].get("hist_return") is not None:
        ret, ret_src = p["quote"]["hist_return"], "online"
    else:
        ret, ret_src = 0.0, "none"
    p.update(value=round(value, 2), value_src=value_src, ret=ret, ret_src=ret_src,
             basis=round(p["cost_basis"] if p["cost_basis"] is not None else value, 2))
    return p


def _rows(con, uid):
    return con.execute("SELECT * FROM positions WHERE user_id=? ORDER BY sort, id", (uid,)).fetchall()


@app.get("/api/positions")
def list_positions(user=Depends(auth.require_user)):
    with db.tx() as con:
        return [_enrich(r) for r in _rows(con, user["id"])]


def _clean(p: PositionIn) -> dict:
    d = p.model_dump()
    d["isin"] = (d["isin"] or "").strip().upper() or None
    d["symbol"] = (d["symbol"] or "").strip().upper() or None
    if d["kind"] == "crypto":
        d["tax_type"] = "crypto"
    d["rate"], future = _fold_changes(d["rate"], d["changes"])
    d["changes"] = json.dumps(future)
    return d


@app.post("/api/positions")
def create_position(p: PositionIn, user=Depends(auth.require_user)):
    d = _clean(p)
    with db.tx() as con:
        cur = con.execute(
            f"INSERT INTO positions(user_id, {', '.join(FIELDS)}) VALUES (?{', ?' * len(FIELDS)})",
            [user["id"]] + [d[f] for f in FIELDS])
        row = con.execute("SELECT * FROM positions WHERE id=?", (cur.lastrowid,)).fetchone()
    return _enrich(row)


def _own(con, pid, uid):
    row = con.execute("SELECT * FROM positions WHERE id=? AND user_id=?", (pid, uid)).fetchone()
    if not row:
        raise HTTPException(404, "Posten nicht gefunden")
    return row


@app.put("/api/positions/{pid}")
def update_position(pid: int, p: PositionIn, user=Depends(auth.require_user)):
    d = _clean(p)
    with db.tx() as con:
        old = _own(con, pid, user["id"])
        if (old["isin"] or "") != (d["isin"] or "") and d["symbol"] == old["symbol"]:
            d["symbol"] = None  # ISIN geändert, Ticker neu auflösen
        con.execute(f"UPDATE positions SET {', '.join(f + '=?' for f in FIELDS)} WHERE id=?",
                    [d[f] for f in FIELDS] + [pid])
        row = _own(con, pid, user["id"])
    return _enrich(row)


@app.delete("/api/positions/{pid}")
def delete_position(pid: int, user=Depends(auth.require_user)):
    with db.tx() as con:
        _own(con, pid, user["id"])
        con.execute("DELETE FROM positions WHERE id=?", (pid,))
    return {"ok": True}


@app.post("/api/positions/{pid}/refresh")
def refresh_position(pid: int, user=Depends(auth.require_user)):
    with db.tx() as con:
        row = dict(_own(con, pid, user["id"]))
    if not row["isin"]:
        raise HTTPException(400, "Keine ISIN bzw. kein Symbol hinterlegt.")
    q = market.get(row["isin"], row["kind"], row["symbol"], force=True)
    if "error" in q:
        raise HTTPException(502, f"Kursabruf fehlgeschlagen: {q['error']}")
    with db.tx() as con:
        con.execute("UPDATE positions SET symbol=? WHERE id=?", (q["symbol"], pid))
        if row["name"] in ("", row["isin"]) and q.get("name"):
            con.execute("UPDATE positions SET name=? WHERE id=?", (q["name"][:80], pid))
        return _enrich(_own(con, pid, user["id"]))


@app.get("/api/lookup")
def lookup(ident: str, kind: str = "etf", user=Depends(auth.require_user)):
    q = market.get(ident.strip().upper(), kind)
    if "error" in q:
        raise HTTPException(502, f"Nichts gefunden: {q['error']}")
    return q


# ---------- Simulation ----------
@app.get("/api/simulate")
def run_simulation(user=Depends(auth.require_user)):
    with db.tx() as con:
        s = _settings(con, user["id"])
        rows = [_enrich(r) for r in _rows(con, user["id"])]
    positions = [Pos(value=r["value"], basis=r["basis"], rate=r["rate"], interval=r["interval"],
                     exec_day=r["exec_day"], trading=r["trading"], ret=r["ret"], fee=r["fee"],
                     ter=r["ter"] if r["ret_src"] == "manual" else 0.0,
                     tax_type=r["tax_type"],
                     changes=[(date.fromisoformat(c["from_date"]), c["rate"]) for c in r["changes"]])
                 for r in rows]
    result = simulate(positions, Settings(**s))
    result["warnings"] = [f"{r['name']}: keine erwartete Rendite, es wird mit 0 % gerechnet"
                          for r in rows if r["ret_src"] == "none"]
    return result


# ---------- Import (Revolut-CSV) ----------
QUOTE_KIND = {"ETF": "etf", "EQUITY": "stock", "MUTUALFUND": "fund", "CRYPTOCURRENCY": "crypto"}
KIND_TAX = {"etf": "equity_fund", "fund": "equity_fund", "stock": "stock", "crypto": "crypto"}


def _match(rows, item, symbol):
    ident = item["ident"].upper()
    for r in rows:
        if item["source"] == "crypto":
            if r["kind"] == "crypto" and (r["isin"] or "").upper() == ident:
                return r
            continue
        if r["kind"] == "crypto":
            continue
        sym = (r["symbol"] or "").upper()
        if (r["isin"] or "").upper() == ident or (symbol and sym == symbol.upper()) or sym.split(".")[0] == ident:
            return r
    return None


@app.post("/api/import/preview")
def import_preview(body: dict = Body(...), user=Depends(auth.require_user)):
    files = body.get("files") or []
    if not isinstance(files, list) or not files or sum(len(f) for f in files) > 5_000_000:
        raise HTTPException(400, "Bitte eine oder mehrere CSV-Dateien (max. 5 MB) wählen.")
    result = importer.parse([str(f) for f in files])
    with db.tx() as con:
        rows = [dict(r) for r in _rows(con, user["id"])]
    for it in result["items"]:
        kind_hint = "crypto" if it["source"] == "crypto" else "etf"
        q = market.get(it["ident"], kind_hint)
        ok = "error" not in q
        kind = "crypto" if it["source"] == "crypto" else QUOTE_KIND.get(q.get("quote_type") if ok else None, "etf")
        it.update(
            symbol=q.get("symbol") if ok else None,
            name=(q.get("name") if ok else None) or it["ident"],
            kind=kind,
            tax_type=KIND_TAX[kind],
            price_eur=q.get("price_eur") if ok else None,
            quote_error=None if ok else q.get("error"),
        )
        m = _match(rows, it, it["symbol"])
        it["match_id"] = m["id"] if m else None
        it["match_name"] = m["name"] if m else None
    return result


class ImportItem(BaseModel):
    ident: str = Field(min_length=1, max_length=20)
    source: Literal["security", "crypto"]
    name: str = Field(min_length=1, max_length=80)
    kind: Literal["etf", "fund", "stock", "crypto"]
    tax_type: Literal["equity_fund", "mixed_fund", "other_fund", "stock", "crypto"]
    symbol: Optional[str] = Field(default=None, max_length=30)
    shares: float = Field(ge=0)
    cost_basis: float = Field(ge=0)
    match_id: Optional[int] = None
    plan: Optional[dict] = None
    use_plan: bool = False


@app.post("/api/import/apply")
def import_apply(items: list[ImportItem], user=Depends(auth.require_user)):
    done = 0
    with db.tx() as con:
        for it in items:
            plan = it.plan if it.use_plan and it.plan else None
            fields = {"shares": it.shares, "cost_basis": it.cost_basis, "manual_value": None}
            if plan:
                fields.update(rate=float(plan.get("rate", 0)), interval=plan.get("interval", "monthly"),
                              exec_day=int(plan.get("exec_day", 1)), trading=plan.get("trading", "exchange"),
                              fee=float(plan.get("fee", 0)))
                if fields["interval"] not in ("daily", "weekly", "monthly") or \
                        fields["trading"] not in ("exchange", "always"):
                    raise HTTPException(400, "Ungültiger Sparplan im Import.")
            if it.match_id:
                _own(con, it.match_id, user["id"])
                cur = dict(_own(con, it.match_id, user["id"]))
                if not cur["isin"]:
                    fields["isin"] = it.ident.upper()
                if not cur["symbol"] and it.symbol:
                    fields["symbol"] = it.symbol.upper()
                con.execute(f"UPDATE positions SET {', '.join(k + '=?' for k in fields)} WHERE id=?",
                            list(fields.values()) + [it.match_id])
            else:
                fields.update(name=it.name, kind=it.kind, tax_type=it.tax_type, isin=it.ident.upper(),
                              symbol=(it.symbol or "").upper() or None)
                if it.kind == "crypto":
                    fields.setdefault("trading", "always")
                cols = ", ".join(fields)
                con.execute(f"INSERT INTO positions(user_id, {cols}) VALUES (?{', ?' * len(fields)})",
                            [user["id"]] + list(fields.values()))
            done += 1
    return {"ok": True, "count": done}
