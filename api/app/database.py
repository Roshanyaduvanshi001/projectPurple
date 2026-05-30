
"""
database.py — Database layer using aiosqlite (async SQLite).
 
Schema
──────
events          Raw event store (idempotent by event_id)
sessions        Derived: one row per visitor session (for funnel)
pos_transactions POS data loaded from CSV
 
Uses WAL mode for concurrent reads during analytics queries.
For production scale: swap to asyncpg + PostgreSQL — same interface.
"""
 
from __future__ import annotations
 
import csv
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator, Optional
 
import aiosqlite
 
log = logging.getLogger("db")
 
DB_PATH = os.getenv("DB_PATH", "/data/store_intelligence.db")
 
 
# ──────────────────────────────────────────────────────────────────────────────
# Schema DDL
# ──────────────────────────────────────────────────────────────────────────────
 
_DDL = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA foreign_keys=ON;
 
CREATE TABLE IF NOT EXISTS events (
    event_id    TEXT PRIMARY KEY,
    store_id    TEXT NOT NULL,
    camera_id   TEXT NOT NULL,
    visitor_id  TEXT NOT NULL,
    event_type  TEXT NOT NULL,
    ts          REAL NOT NULL,          -- Unix epoch
    timestamp   TEXT NOT NULL,          -- ISO-8601 original
    zone_id     TEXT,
    dwell_ms    INTEGER NOT NULL DEFAULT 0,
    is_staff    INTEGER NOT NULL DEFAULT 0,
    confidence  REAL NOT NULL,
    queue_depth INTEGER,
    sku_zone    TEXT,
    session_seq INTEGER NOT NULL DEFAULT 0,
    ingested_at REAL NOT NULL DEFAULT (unixepoch('now'))
);
 
CREATE INDEX IF NOT EXISTS idx_events_store_ts
    ON events(store_id, ts);
CREATE INDEX IF NOT EXISTS idx_events_visitor
    ON events(visitor_id, ts);
CREATE INDEX IF NOT EXISTS idx_events_type
    ON events(store_id, event_type, ts);
 
CREATE TABLE IF NOT EXISTS sessions (
    session_key  TEXT PRIMARY KEY,      -- store_id + ':' + visitor_id
    store_id     TEXT NOT NULL,
    visitor_id   TEXT NOT NULL,
    entry_ts     REAL,
    exit_ts      REAL,
    zones_visited TEXT,                 -- JSON array
    reached_billing INTEGER DEFAULT 0,
    converted       INTEGER DEFAULT 0,
    is_staff        INTEGER DEFAULT 0,
    reentry_count   INTEGER DEFAULT 0
);
 
CREATE INDEX IF NOT EXISTS idx_sessions_store
    ON sessions(store_id, entry_ts);
 
CREATE TABLE IF NOT EXISTS pos_transactions (
    transaction_id  TEXT PRIMARY KEY,
    store_id        TEXT NOT NULL,
    ts              REAL NOT NULL,
    timestamp       TEXT NOT NULL,
    basket_value_inr REAL NOT NULL
);
 
CREATE INDEX IF NOT EXISTS idx_pos_store_ts
    ON pos_transactions(store_id, ts);
"""
 
 
# ──────────────────────────────────────────────────────────────────────────────
# Connection pool (simple singleton for SQLite)
# ──────────────────────────────────────────────────────────────────────────────
 
_conn: Optional[aiosqlite.Connection] = None
 
 
async def init_db() -> None:
    global _conn
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    _conn = await aiosqlite.connect(DB_PATH, check_same_thread=False)
    _conn.row_factory = aiosqlite.Row
    await _conn.executescript(_DDL)
    await _conn.commit()
    log.info("Database initialised: %s", DB_PATH)
 
 
async def close_db() -> None:
    global _conn
    if _conn:
        await _conn.close()
        _conn = None
 
 
def get_db() -> aiosqlite.Connection:
    if _conn is None:
        raise RuntimeError("Database not initialised — call init_db() first")
    return _conn
 
 
@asynccontextmanager
async def db_transaction() -> AsyncIterator[aiosqlite.Connection]:
    """Context manager that provides a connection and commits on exit."""
    conn = get_db()
    try:
        yield conn
        await conn.commit()
    except Exception:
        await conn.rollback()
        raise
 
 
# ──────────────────────────────────────────────────────────────────────────────
# POS loader
# ──────────────────────────────────────────────────────────────────────────────
 
async def load_pos_csv(csv_path: Path) -> int:
    """Load pos_transactions.csv into the pos_transactions table. Idempotent."""
    if not csv_path.exists():
        log.warning("POS CSV not found: %s", csv_path)
        return 0
 
    rows = []
    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                ts_str = row["timestamp"].strip()
                ts = datetime.fromisoformat(
                    ts_str.replace("Z", "+00:00")
                ).timestamp()
                rows.append((
                    row["transaction_id"].strip(),
                    row["store_id"].strip(),
                    ts,
                    ts_str,
                    float(row["basket_value_inr"]),
                ))
            except (KeyError, ValueError) as e:
                log.warning("Skipping bad POS row: %s — %s", row, e)
 
    conn = get_db()
    await conn.executemany(
        """INSERT OR IGNORE INTO pos_transactions
           (transaction_id, store_id, ts, timestamp, basket_value_inr)
           VALUES (?,?,?,?,?)""",
        rows,
    )
    await conn.commit()
    log.info("Loaded %d POS transactions from %s", len(rows), csv_path)
    return len(rows)
 
 
# ──────────────────────────────────────────────────────────────────────────────
# Session maintenance (called after ingest)
# ──────────────────────────────────────────────────────────────────────────────
 
async def refresh_session(store_id: str, visitor_id: str) -> None:
    """
    Upsert the sessions table row for a given visitor.
    Called after every event batch ingest.
    """
    conn = get_db()
    session_key = f"{store_id}:{visitor_id}"
 
    # Gather relevant events
    async with conn.execute(
        """SELECT event_type, ts, zone_id, is_staff, dwell_ms
           FROM events
           WHERE store_id=? AND visitor_id=?
           ORDER BY ts""",
        (store_id, visitor_id),
    ) as cur:
        rows = await cur.fetchall()
 
    if not rows:
        return
 
    import json
 
    entry_ts    = None
    exit_ts     = None
    zones       = set()
    billing     = 0
    is_staff    = 0
    reentries   = 0
 
    for r in rows:
        et = r["event_type"]
        if et == "ENTRY" and entry_ts is None:
            entry_ts = r["ts"]
        elif et == "EXIT":
            exit_ts  = r["ts"]
        elif et in ("ZONE_ENTER", "ZONE_DWELL") and r["zone_id"]:
            zones.add(r["zone_id"])
        elif et == "BILLING_QUEUE_JOIN":
            billing = 1
        elif et == "REENTRY":
            reentries += 1
        if r["is_staff"]:
            is_staff = 1
 
    # Conversion: was there a POS transaction within 5 min of billing entry?
    converted = 0
    if billing:
        async with conn.execute(
            """SELECT COUNT(*) FROM pos_transactions
               WHERE store_id=? AND ts BETWEEN ? AND ?""",
            (store_id,
             (entry_ts or 0),
             (exit_ts or 9999999999)),
        ) as cur:
            row = await cur.fetchone()
            converted = 1 if (row and row[0] > 0) else 0
 
    await conn.execute(
        """INSERT INTO sessions
           (session_key, store_id, visitor_id, entry_ts, exit_ts,
            zones_visited, reached_billing, converted, is_staff, reentry_count)
           VALUES (?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(session_key) DO UPDATE SET
               exit_ts=excluded.exit_ts,
               zones_visited=excluded.zones_visited,
               reached_billing=excluded.reached_billing,
               converted=excluded.converted,
               is_staff=excluded.is_staff,
               reentry_count=excluded.reentry_count""",
        (
            session_key, store_id, visitor_id,
            entry_ts, exit_ts,
            json.dumps(sorted(zones)),
            billing, converted, is_staff, reentries,
        ),
    )