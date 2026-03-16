"""
db.py — SQLite storage cho scan results
"""
import sqlite3
import json
import os
from datetime import datetime, timezone

DB_PATH = os.environ.get("DB_PATH", "scanner.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS scan_runs (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        started_at TEXT,
        ended_at   TEXT,
        total_syms INTEGER,
        status     TEXT DEFAULT 'running'
    );

    CREATE TABLE IF NOT EXISTS signals (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id     INTEGER,
        scanned_at TEXT,
        symbol     TEXT,
        timeframe  TEXT,
        close      REAL,
        signal     TEXT,
        net        INTEGER,
        bull       INTEGER,
        bear       INTEGER,
        rsi        REAL,
        adx        REAL,
        delta_pct  REAL,
        above_cloud INTEGER,
        below_cloud INTEGER,
        bull_env   INTEGER,
        bear_env   INTEGER,
        vol24      REAL,
        FOREIGN KEY(run_id) REFERENCES scan_runs(id)
    );

    CREATE INDEX IF NOT EXISTS idx_signals_tf     ON signals(timeframe);
    CREATE INDEX IF NOT EXISTS idx_signals_net    ON signals(net);
    CREATE INDEX IF NOT EXISTS idx_signals_sym    ON signals(symbol);
    CREATE INDEX IF NOT EXISTS idx_signals_run    ON signals(run_id);
    CREATE INDEX IF NOT EXISTS idx_signals_scanned ON signals(scanned_at);
    """)
    conn.commit()
    conn.close()


def start_run(total_syms: int) -> int:
    conn = get_conn()
    cur  = conn.execute(
        "INSERT INTO scan_runs (started_at, total_syms, status) VALUES (?,?,?)",
        (utcnow(), total_syms, "running")
    )
    run_id = cur.lastrowid
    conn.commit()
    conn.close()
    return run_id


def end_run(run_id: int, status="done"):
    conn = get_conn()
    conn.execute(
        "UPDATE scan_runs SET ended_at=?, status=? WHERE id=?",
        (utcnow(), status, run_id)
    )
    conn.commit()
    conn.close()


def save_signals(run_id: int, results: list[dict]):
    now  = utcnow()
    conn = get_conn()
    rows = [
        (run_id, now, r["symbol"], r["timeframe"], r["close"],
         r["signal"], r["net"], r["bull"], r["bear"],
         r["rsi"], r["adx"], r["delta_pct"],
         int(r["above_cloud"]), int(r["below_cloud"]),
         int(r["bull_env"]), int(r["bear_env"]), r["vol24"])
        for r in results
    ]
    conn.executemany("""
        INSERT INTO signals
        (run_id, scanned_at, symbol, timeframe, close, signal, net, bull, bear,
         rsi, adx, delta_pct, above_cloud, below_cloud, bull_env, bear_env, vol24)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, rows)
    conn.commit()
    conn.close()


def get_latest_signals(timeframe: str = None, min_net: int = 0,
                       limit: int = 100) -> list[dict]:
    conn  = get_conn()
    query = """
        SELECT s.*
        FROM signals s
        JOIN scan_runs r ON s.run_id = r.id
        WHERE r.status = 'done'
        AND s.run_id = (
            SELECT MAX(id) FROM scan_runs WHERE status='done'
        )
    """
    params = []
    if timeframe:
        query += " AND s.timeframe = ?"
        params.append(timeframe)
    if min_net > 0:
        query += " AND s.net >= ?"
        params.append(min_net)
    elif min_net < 0:
        query += " AND s.net <= ?"
        params.append(min_net)

    query += " ORDER BY ABS(s.net) DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_scan_history(limit=10) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM scan_runs ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_symbol_history(symbol: str, timeframe: str, limit=50) -> list[dict]:
    conn = get_conn()
    rows = conn.execute("""
        SELECT * FROM signals
        WHERE symbol=? AND timeframe=?
        ORDER BY scanned_at DESC LIMIT ?
    """, (symbol, timeframe, limit)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
