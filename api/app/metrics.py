"""
metrics.py — Real-time store metrics computation.
 
All queries run against the live database — no stale caches.
Zero-traffic periods return safe defaults (not null, not 500).
"""
 
from __future__ import annotations
 
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
 
from app.database import get_db
from app.models import MetricsResponse, ZoneDwellStat
 
log = logging.getLogger("metrics")
 
SECONDS_PER_DAY = 86_400
 
 
def _today_window() -> tuple[float, float]:
    """Return (start_ts, end_ts) for today UTC as Unix timestamps."""
    now   = datetime.now(tz=timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start.timestamp(), now.timestamp()
 
 
def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
 
 
async def get_store_metrics(store_id: str) -> MetricsResponse:
    conn             = get_db()
    start_ts, end_ts = _today_window()
 
    # ── Unique customer visitors (exclude staff, deduplicate re-entries) ──────
    async with conn.execute(
        """SELECT COUNT(DISTINCT visitor_id) as uv
           FROM sessions
           WHERE store_id=? AND is_staff=0
             AND entry_ts BETWEEN ? AND ?""",
        (store_id, start_ts, end_ts),
    ) as cur:
        row       = await cur.fetchone()
        unique_v  = int(row["uv"]) if row else 0
 
    # ── Conversion rate via sessions.converted ────────────────────────────────
    async with conn.execute(
        """SELECT
             COUNT(*) as total,
             SUM(converted) as conv
           FROM sessions
           WHERE store_id=? AND is_staff=0
             AND entry_ts BETWEEN ? AND ?""",
        (store_id, start_ts, end_ts),
    ) as cur:
        row       = await cur.fetchone()
        total_s   = int(row["total"] or 0)
        converted = int(row["conv"] or 0)
 
    conv_rate = round(converted / total_s, 4) if total_s else 0.0
 
    # ── Average basket value (POS) ────────────────────────────────────────────
    async with conn.execute(
        """SELECT AVG(basket_value_inr) as avg_basket
           FROM pos_transactions
           WHERE store_id=? AND ts BETWEEN ? AND ?""",
        (store_id, start_ts, end_ts),
    ) as cur:
        row        = await cur.fetchone()
        avg_basket = round(float(row["avg_basket"]), 2) if row and row["avg_basket"] else None
 
    # ── Live queue depth: billing-zone visitors right now (last 5 min) ────────
    async with conn.execute(
        """SELECT MAX(queue_depth) as qd
           FROM events
           WHERE store_id=? AND event_type='BILLING_QUEUE_JOIN'
             AND ts > ? AND is_staff=0""",
        (store_id, end_ts - 300),
    ) as cur:
        row         = await cur.fetchone()
        queue_depth = int(row["qd"] or 0) if row else 0
 
    # ── Abandonment rate ──────────────────────────────────────────────────────
    async with conn.execute(
        """SELECT
             COUNT(*) as total_billing,
             SUM(CASE WHEN event_type='BILLING_QUEUE_ABANDON' THEN 1 ELSE 0 END) as abandoned
           FROM events
           WHERE store_id=? AND ts BETWEEN ? AND ? AND is_staff=0
             AND event_type IN ('BILLING_QUEUE_JOIN','BILLING_QUEUE_ABANDON')""",
        (store_id, start_ts, end_ts),
    ) as cur:
        row            = await cur.fetchone()
        total_billing  = int(row["total_billing"] or 0)
        abandoned      = int(row["abandoned"] or 0)
 
    abandon_rate = round(abandoned / total_billing, 4) if total_billing else 0.0
 
    # ── Zone dwell stats ──────────────────────────────────────────────────────
    async with conn.execute(
        """SELECT zone_id,
                  AVG(dwell_ms) as avg_dwell,
                  COUNT(*) as visits
           FROM events
           WHERE store_id=? AND event_type IN ('ZONE_DWELL','ZONE_EXIT')
             AND zone_id IS NOT NULL AND is_staff=0
             AND ts BETWEEN ? AND ?
           GROUP BY zone_id
           ORDER BY visits DESC""",
        (store_id, start_ts, end_ts),
    ) as cur:
        zone_rows = await cur.fetchall()
 
    zone_dwell = [
        ZoneDwellStat(
            zone_id=r["zone_id"],
            avg_dwell_ms=round(float(r["avg_dwell"] or 0), 1),
            visit_count=int(r["visits"]),
        )
        for r in zone_rows
    ]
 
    return MetricsResponse(
        store_id=store_id,
        window_start=_iso(start_ts),
        window_end=_iso(end_ts),
        unique_visitors=unique_v,
        conversion_rate=conv_rate,
        avg_basket_inr=avg_basket,
        queue_depth_now=queue_depth,
        abandonment_rate=abandon_rate,
        zone_dwell=zone_dwell,
    )
 