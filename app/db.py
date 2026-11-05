import os
import sqlite3
from contextlib import contextmanager

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    handle BLOB NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS credentials (
    id TEXT PRIMARY KEY,              -- base64url credential id
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    public_key BLOB NOT NULL,
    sign_count INTEGER NOT NULL DEFAULT 0,
    label TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_used TEXT
);
CREATE TABLE IF NOT EXISTS invites (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at INTEGER NOT NULL,
    challenge BLOB,
    used INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS challenges (
    id TEXT PRIMARY KEY,
    challenge BLOB NOT NULL,
    expires_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    years INTEGER NOT NULL DEFAULT 20,
    best_delta REAL NOT NULL DEFAULT 3.0,
    worst_delta REAL NOT NULL DEFAULT -4.0,
    inflation REAL NOT NULL DEFAULT 2.0,
    allowance REAL NOT NULL DEFAULT 1000.0,
    church_tax REAL NOT NULL DEFAULT 0.0
);
CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'etf',          -- etf, fund, stock, crypto
    isin TEXT,                                 -- ISIN oder Krypto-Symbol
    symbol TEXT,                               -- aufgelöster Yahoo-Ticker
    shares REAL,                               -- Stückzahl (optional)
    manual_value REAL,                         -- manueller Wert in EUR (optional)
    cost_basis REAL,                           -- Einstandswert in EUR (optional)
    rate REAL NOT NULL DEFAULT 0,              -- Sparrate EUR je Ausführung
    interval TEXT NOT NULL DEFAULT 'monthly',  -- daily, weekly, monthly
    exec_day INTEGER NOT NULL DEFAULT 1,       -- Wochentag 0..6 oder Monatstag 1..31
    trading TEXT NOT NULL DEFAULT 'exchange',  -- exchange, always
    manual_return REAL,                        -- erwartete Rendite p.a. in %, überschreibt historische
    fee REAL NOT NULL DEFAULT 0,               -- Gebühr je Ausführung EUR
    ter REAL NOT NULL DEFAULT 0,               -- laufende Kosten p.a. in %
    tax_type TEXT NOT NULL DEFAULT 'equity_fund', -- equity_fund, mixed_fund, other_fund, stock, crypto
    sort INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS quotes (
    key TEXT PRIMARY KEY,
    data TEXT NOT NULL,
    fetched_at INTEGER NOT NULL
);
"""


def connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(config.DB_PATH) or ".", exist_ok=True)
    con = sqlite3.connect(config.DB_PATH, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA journal_mode = WAL")
    return con


@contextmanager
def tx():
    con = connect()
    try:
        yield con
        con.commit()
    finally:
        con.close()


MIGRATIONS = {
    "positions": {"changes": "TEXT NOT NULL DEFAULT '[]'"},  # geplante Sparratenänderungen (JSON)
}


def init():
    with tx() as con:
        con.executescript(SCHEMA)
        for table, cols in MIGRATIONS.items():
            have = {r["name"] for r in con.execute(f"PRAGMA table_info({table})")}
            for col, ddl in cols.items():
                if col not in have:
                    con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
