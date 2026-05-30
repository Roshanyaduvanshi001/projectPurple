"""
funnel.py — Conversion funnel and heatmap computation.
 
Funnel stages (session-level, not raw events):
  Entry → Zone Visit → Billing Queue → Purchase
 
Re-entries do NOT double-count a visitor session.
"""
 
from __future__ import annotations
 
import logging
from datetime import datetime, timezone
 
from app.database import get_db
from app.models import FunnelResponse, FunnelStage, HeatmapResponse, HeatmapZone
 
log = logging.getLogger("funnel")
 
MIN_SESSIONS_FOR_CONFIDENCE = 20
 
 
def _today_window() -> tuple[float, float]:
    now   = datetime.now(tz=timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start.timestamp(), now.timestamp()
 
 
def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
 
 
async def get_funnel(store_id: str) -> FunnelResponse:
    conn             = get_db()
    start_ts, end_ts = _today_window()
 
    # Session-level funnel — each visitor counted once regardless of re-entries
    async with conn.execute(
        """SELECT
             COUNT(DISTINCT visitor_id)               AS entered,
             COUNT(DISTINCT CASE WHEN zones_visited != '[]'
                   THEN visitor_id END)               AS zone_visited,
             COUNT(DISTINCT CASE WHEN reached_billing=1
                   THEN visitor_id END)               AS billed,
             COUNT(DISTINCT CASE WHEN converted=1
                   THEN visitor_id END)               AS purchased
           FROM sessions
           WHERE store_id=? AND is_staff=0
             AND (entry_ts IS NULL OR entry_ts BETWEEN ? AND ?)""",
        (store_id, start_ts, end_ts),
    ) as cur:
        row = await cur.fetchone()
 
    entered      = int(row["entered"]      or 0)
    zone_visited = int(row["zone_visited"] or 0)
    billed       = int(row["billed"]       or 0)
    purchased    = int(row["purchased"]    or 0)
 
    def drop(prev: int, curr: int) -> float:
        if prev == 0:
            return 0.0
        return round((1 - curr / prev) * 100, 2)
 
    stages = [
        FunnelStage(stage="Entry",         count=entered,      drop_pct=0.0),
        FunnelStage(stage="Zone Visit",    count=zone_visited, drop_pct=drop(entered, zone_visited)),
        FunnelStage(stage="Billing Queue", count=billed,       drop_pct=drop(zone_visited, billed)),
        FunnelStage(stage="Purchase",      count=purchased,    drop_pct=drop(billed, purchased)),
    ]
 
    return FunnelResponse(
        store_id=store_id,
        window=f"{_iso(start_ts)}/{_iso(end_ts)}",
        stages=stages,
    )
 
 
async def get_heatmap(store_id: str) -> HeatmapResponse:
    conn             = get_db()
    start_ts, end_ts = _today_window()
 
    # Total sessions for confidence flag
    async with conn.execute(
        """SELECT COUNT(DISTINCT visitor_id) as sc
           FROM sessions
           WHERE store_id=? AND is_staff=0 AND entry_ts BETWEEN ? AND ?""",
        (store_id, start_ts, end_ts),
    ) as cur:
        row            = await cur.fetchone()
        session_count  = int(row["sc"] or 0)
 
    high_confidence = session_count >= MIN_SESSIONS_FOR_CONFIDENCE
 
    # Zone stats
    async with conn.execute(
        """SELECT zone_id,
                  COUNT(*) as visit_count,
                  AVG(dwell_ms) as avg_dwell
           FROM events
           WHERE store_id=? AND zone_id IS NOT NULL AND is_staff=0
             AND event_type IN ('ZONE_ENTER','ZONE_DWELL')
             AND ts BETWEEN ? AND ?
           GROUP BY zone_id""",
        (store_id, start_ts, end_ts),
    ) as cur:
        rows = await cur.fetchall()
 
    if not rows:
        return HeatmapResponse(
            store_id=store_id,
            window=f"{_iso(start_ts)}/{_iso(end_ts)}",
            zones=[],
        )
 
    # Normalise visit_count 0–100
    max_visits = max(int(r["visit_count"]) for r in rows) or 1
 
    zones = [
        HeatmapZone(
            zone_id=r["zone_id"],
            visit_count=int(r["visit_count"]),
            avg_dwell_ms=round(float(r["avg_dwell"] or 0), 1),
            normalised_score=round(int(r["visit_count"]) / max_visits * 100, 1),
            data_confidence=high_confidence,
        )
        for r in rows
    ]
    zones.sort(key=lambda z: z.normalised_score, reverse=True)
 
    return HeatmapResponse(
        store_id=store_id,
        window=f"{_iso(start_ts)}/{_iso(end_ts)}",
        zones=zones,
    )
 